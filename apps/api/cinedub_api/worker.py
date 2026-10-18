import fcntl
import logging
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import case, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal, create_database
from .job_errors import InvalidJobInput, InvalidJobOutput, JobErrorCode, classify
from .lineage import record_job_lineage
from .models import Artifact, Job, Project
from .processing import check_cancel
from .project_status import sync_project_status
from .stages import STAGES, validated_inputs, validated_output
from .storage_capacity import STORAGE_MESSAGE, StorageCapacityError, is_storage_capacity_error
from .workspace_lock import inherit_lease, workspace_lease

logger = logging.getLogger("cinedub.worker")
settings = get_settings()


# Dispatch table derived from the stage registry (tests may substitute a processor).
PROCESSORS = {stage: spec.process for stage, spec in STAGES.items()}


def _finish_cancelled(session: Session, job: Job, message: str) -> None:
    job.status = "cancelled"
    job.phase = "cancelled"
    job.error_code = JobErrorCode.CANCELLED
    job.error_message = message
    job.retryable = False
    job.finished_at = datetime.now(UTC)
    sync_project_status(session, job.project_id)


def label_demo_artifacts(session: Session, job: Job) -> None:
    """Every artifact from a DEMO provider stays visibly labelled, whatever its stage."""
    for artifact in session.scalars(select(Artifact).where(Artifact.job_id == job.id)).all():
        if artifact.metadata_json.get("demo") is not True:
            artifact.metadata_json = {**artifact.metadata_json, "demo": True}


def claim_job(session: Session) -> Job | None:
    job = session.scalar(
        select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1)
    )
    if not job:
        return None
    result = session.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == "queued")
        .values(
            status="running",
            started_at=datetime.now(UTC),
            attempts=Job.attempts + 1,
            phase=case((Job.phase == "queued", "preparing"), else_=Job.phase),
        )
    )
    if result.rowcount != 1:
        session.rollback()
        return None
    session.commit()
    session.refresh(job)
    return job


def process_once(session: Session) -> bool:
    try:
        return _process_once(session)
    except (DBAPIError, OSError, sqlite3.Error) as exc:
        if not is_storage_capacity_error(exc):
            raise
        session.rollback()
        # Capacity may prevent even recording an error. Retain durable running
        # state/checkpoints and stop; restart recovery guards ambiguous paid calls.
        raise StorageCapacityError(STORAGE_MESSAGE) from None


def _process_once(session: Session) -> bool:
    job = claim_job(session)
    if not job:
        return False
    project = session.get(Project, job.project_id)
    try:
        # Cancellation may have been committed while claiming or before a restart.
        # Do not enter a processor (which may publish artifacts or call a provider).
        check_cancel(session, job)
        try:
            validated_inputs(job)
        except ValidationError as exc:
            raise InvalidJobInput(
                "Saved job inputs do not match this stage contract; submit a new request"
            ) from exc
        processor = PROCESSORS[job.stage]
        output = processor(session, job)
        session.refresh(job)
        if job.cancel_requested:
            raise InterruptedError("Job cancelled")
        try:
            output = validated_output(job.stage, output)
        except ValidationError as exc:
            raise InvalidJobOutput("Stage result failed its contract and was not recorded") from exc
        if job.provider == "fake":
            label_demo_artifacts(session, job)
        record_job_lineage(session, job)
        job.output_json = output
        job.progress = 1.0
        job.status = "completed"
        job.phase = "completed"
        sync_project_status(session, project)
    except InterruptedError as exc:
        session.rollback()
        job = session.get(Job, job.id)
        _finish_cancelled(session, job, str(exc))
    except Exception as exc:  # worker boundary records structured failures
        if is_storage_capacity_error(exc):
            raise
        logger.error("job_id=%s stage=%s error_type=%s", job.id, job.stage, type(exc).__name__)
        session.rollback()
        job = session.get(Job, job.id)
        job.status = "failed"
        code, message = classify(exc, job)
        job.error_code, job.error_message = code, message
        job.retryable = STAGES[job.stage].retry.retryable_after(job, code)
        job.finished_at = datetime.now(UTC)
        sync_project_status(session, job.project_id)
        session.commit()
        return True
    job.finished_at = datetime.now(UTC)
    session.commit()
    return True


def recover_jobs(session: Session) -> None:
    for job in session.scalars(select(Job).where(Job.status == "running")).all():
        submission = STAGES[job.stage].retry.submission_phase
        uncertain = job.provider != "fake" and (
            (submission and not job.remote_job_id and job.phase == submission)
            or bool(job.checkpoint_json.get("pending_chunk"))
            or bool(job.checkpoint_json.get("pending_voice"))
            or bool(job.checkpoint_json.get("pending_registration"))
        )
        if uncertain:
            job.status = "failed"
            job.error_code = JobErrorCode.UNCERTAIN_SUBMISSION
            job.error_message = (
                "Interrupted provider submission; inspect usage before explicitly retrying"
            )
            job.finished_at = datetime.now(UTC)
            sync_project_status(session, job.project_id)
        elif job.cancel_requested:
            _finish_cancelled(
                session,
                job,
                "Cancellation retained after restart; "
                "any submitted provider work may still be billed",
            )
        else:
            job.status = "queued"
            if submission and job.remote_job_id and job.phase == submission:
                job.phase = "created"
    session.commit()


def worker_lock_path() -> Path:
    if settings.database_url.startswith("sqlite:///"):
        database = Path(settings.database_url.removeprefix("sqlite:///")).resolve()
        return database.with_name(f"{database.name}.worker.lock")
    return settings.storage_root / ".worker.lock"


def run_worker(poll_interval: float = 1.0) -> None:
    try:
        _run_worker(poll_interval)
    except (DBAPIError, OSError, sqlite3.Error, StorageCapacityError) as exc:
        if not is_storage_capacity_error(exc):
            raise
        logger.error("storage_capacity_exhausted: %s", STORAGE_MESSAGE)
        raise SystemExit(1) from None


def _run_worker(poll_interval: float) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    lock_path = worker_lock_path()
    with workspace_lease(settings.database_url, settings.storage_root), lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("A CineDub worker is already running for this database") from exc
        with inherit_lease(lock.fileno()):
            create_database()
            # Alembic sets the root threshold to WARN; retain worker lifecycle evidence.
            logger.setLevel(logging.INFO)
            with SessionLocal() as session:
                recover_jobs(session)
            _worker_loop(poll_interval)


def _worker_loop(poll_interval: float) -> None:
    logger.info("CineDub worker started")
    while True:
        with SessionLocal() as session:
            worked = process_once(session)
        if not worked:
            time.sleep(poll_interval)
