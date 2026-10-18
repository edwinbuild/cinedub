"""Job requests, reuse and estimated-budget reservations. Stage logic lives in `stages`."""

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import Job, Project
from .schemas import JobEstimate, JobFields
from .stages import prepare_stage
from .stages.preparation import Preparation

ACTIVE = ("queued", "running")


def write_lock(session: Session) -> None:
    if session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))


def budget_totals(session: Session, project_id: str) -> tuple[float, float]:
    jobs = session.scalars(select(Job).where(Job.project_id == project_id)).all()
    spent = sum(job.charged_estimate_inr for job in jobs)
    reserved = sum(
        max(0, job.estimated_cost_inr - job.charged_estimate_inr)
        for job in jobs
        if job.status in ACTIVE
    )
    return round(spent, 6), round(reserved, 6)


def request_fields(payload) -> JobFields:
    """Normalize a typed per-stage request to the flat fields frozen into every job.

    Keeping the frozen shape identical preserves fingerprints of earlier (possibly paid) jobs.
    """
    if isinstance(payload, JobFields):
        return payload
    return JobFields.model_validate(payload.model_dump())


def prepare_job(session: Session, project: Project, payload) -> tuple[str, dict, float]:
    prep = prepare_stage(session, project, request_fields(payload))
    return prep.provider, prep.inputs, prep.cost


def cached_job(session: Session, project: Project, prep: Preparation, force_new: bool):
    return next(
        (
            job
            for job in session.scalars(
                select(Job)
                .where(
                    Job.project_id == project.id,
                    Job.stage == prep.spec.stage,
                    Job.provider == prep.provider,
                    Job.status.in_([*ACTIVE, "completed"]),
                )
                .order_by(Job.created_at.desc())
            ).all()
            if job.input_json.get("fingerprint") == prep.inputs["fingerprint"]
            and (job.status in ACTIVE or not force_new)
        ),
        None,
    )


def estimate_prepared(
    session: Session, project: Project, prep: Preparation, force_new: bool
) -> JobEstimate:
    spent, reserved = budget_totals(session, project.id)
    cached = cached_job(session, project, prep, force_new)
    return JobEstimate(
        estimated_cost_inr=0 if cached else prep.cost,
        spent_estimate_inr=spent,
        reserved_inr=reserved,
        remaining_inr=max(0, project.budget_inr - spent - reserved),
        budget_inr=project.budget_inr,
        cached_job_id=cached.id if cached else None,
    )


def estimate_job(session: Session, project: Project, payload) -> JobEstimate:
    fields = request_fields(payload)
    return estimate_prepared(
        session, project, prepare_stage(session, project, fields), fields.force_new
    )
