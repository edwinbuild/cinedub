"""Project status is derived from jobs and timeline state in exactly one place."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Job, Project, Segment

ACTIVE = ("queued", "running")


def _naive(value):
    # SQLite returns naive UTC; freshly flushed values are aware. Compare consistently.
    return value.replace(tzinfo=None) if value and value.tzinfo else value


DELIVERY_STAGES = {"export", "render_preview", "package_mix"}


def derive_status(session: Session, project: Project) -> str:
    """processing > failed > ready > review > draft, from the latest finished job."""
    jobs = session.scalars(select(Job).where(Job.project_id == project.id)).all()
    if any(job.status in ACTIVE for job in jobs):
        return "processing"
    latest = max(
        jobs, key=lambda job: (_naive(job.updated_at), _naive(job.created_at)), default=None
    )
    if latest and latest.status == "failed":
        return "failed"
    if latest and latest.status == "completed" and latest.stage in DELIVERY_STAGES:
        return "ready"
    has_lines = project.active_revision_id and session.scalar(
        select(Segment.id).where(
            Segment.project_id == project.id,
            Segment.revision_id == project.active_revision_id,
            Segment.retired.is_(False),
        )
    )
    return "review" if has_lines else "draft"


def sync_project_status(session: Session, project: Project | str) -> str:
    """Recompute the stored (display/backup) status after any job or timeline transition."""
    if isinstance(project, str):
        project = session.get(Project, project)
    session.flush()  # Sessions do not autoflush; derive from the pending job transitions too.
    project.status = derive_status(session, project)
    return project.status
