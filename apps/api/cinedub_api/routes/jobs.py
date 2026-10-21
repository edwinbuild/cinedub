"""Job estimate, submission, resume and cancellation."""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from ..config import get_settings
from ..dependencies import SessionDep, require_project
from ..dialogue_review import stale_reason as dialogue_context_stale_reason
from ..idempotency import Idempotency, request_hash
from ..jobs import ACTIVE, estimate_job, submit_job, write_lock
from ..models import (
    Job,
)
from ..pipeline import after_job
from ..project_status import sync_project_status
from ..schemas import (
    JobCreate,
    JobEstimate,
    JobRead,
)
from ..stages import STAGES

router = APIRouter()
settings = get_settings()


@router.post("/projects/{project_id}/jobs/estimate", response_model=JobEstimate)
async def job_estimate(project_id: str, payload: JobCreate, session: SessionDep):
    return estimate_job(session, require_project(session, project_id), payload)


@router.post(
    "/projects/{project_id}/jobs", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED
)
async def create_job(
    project_id: str,
    payload: JobCreate,
    session: SessionDep,
    request: Request,
):
    write_lock(session)
    once = Idempotency(session, request, request_hash(project_id, payload.model_dump(mode="json")))
    if replay := once.replay():
        return replay
    job = submit_job(session, require_project(session, project_id), payload)
    session.flush()
    once.remember(202, JobRead.model_validate(job).model_dump(mode="json"))
    session.commit()
    session.refresh(job)
    return job


@router.post("/jobs/{job_id}/resume", response_model=JobRead)
async def resume_job(job_id: str, session: SessionDep):
    write_lock(session)
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    spec = STAGES.get(job.stage)
    if not spec or not spec.retry.can_resume(job):
        raise HTTPException(422, "This job cannot safely resume; create a new request explicitly")
    local_resume = not job.remote_job_id
    if session.scalar(
        select(Job.id).where(Job.project_id == job.project_id, Job.status.in_(ACTIVE))
    ):
        raise HTTPException(409, "Another job is active")
    if job.stage == "adapt_dialogue":
        reason = dialogue_context_stale_reason(session, job.project_id, job.input_json)
        if reason:
            raise HTTPException(409, reason)
    if local_resume:
        job.retryable = False
    job.status = "queued"
    job.cancel_requested = False
    job.error_code = None
    job.error_message = None
    job.finished_at = None
    if job.remote_job_id:
        job.checkpoint_json = {**job.checkpoint_json, "poll_started_at": None}
    after_job(session, job)  # A failed pipeline resumes with its job.
    sync_project_status(session, job.project_id)
    session.commit()
    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
async def cancel_job(job_id: str, session: SessionDep) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"completed", "failed", "cancelled"}:
        return job
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.phase = "cancelled"
        after_job(session, job)
        sync_project_status(session, job.project_id)
    session.commit()
    session.refresh(job)
    return job
