"""Find (and optionally remove) storage no database row references.

Three kinds of leftovers are reported:

* orphaned uploads: files in a project's `source/` area with no media asset row;
* orphaned project directories: UUID-named directories whose project no longer exists
  (for example a deletion interrupted after its database commit);
* stale job directories: work areas of cancelled jobs, or failed jobs that cannot resume,
  older than a grace period.

Completed job directories are always kept whole (they hold provenance such as raw takes).
Directories of queued, running or resumable jobs are never touched, nor are files directly
under the storage root (workspace locks, backups), nor any path outside the root.
"""

import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Artifact, Job, MediaAsset, Project
from .storage import LocalStorage

AREAS = {
    "ingest",
    "transcript",
    "translation",
    "voice",
    "preview",
    "exports",
    "separation",
    "mixes",
    "alignment",
    "take-analysis",
    "dialogue-review",
    "dialogue-adaptation",
    "speech-emotion",
    "references",
}


@dataclass
class CleanupReport:
    orphaned_files: list[Path] = field(default_factory=list)
    orphaned_project_directories: list[Path] = field(default_factory=list)
    stale_job_directories: list[Path] = field(default_factory=list)
    reclaimable_bytes: int = 0
    removed: bool = False


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(
        (Path(folder) / name).stat().st_size
        for folder, _, names in os.walk(path)
        for name in names
        if not (Path(folder) / name).is_symlink()
    )


def _is_uuid(name: str) -> bool:
    try:
        return str(UUID(name)) == name
    except ValueError:
        return False


def plan_cleanup(session: Session, store: LocalStorage, *, grace_days: int = 7) -> CleanupReport:
    referenced = {
        Path(path).resolve()
        for (path,) in session.execute(select(Artifact.path)).all()
        + session.execute(select(MediaAsset.path)).all()
        if path
    }
    jobs = {job.id: job for job in session.scalars(select(Job)).all()}
    projects = {project_id for (project_id,) in session.execute(select(Project.id)).all()}
    cutoff = datetime.now(UTC) - timedelta(days=grace_days)
    report = CleanupReport()
    for project_dir in sorted(path for path in store.root.iterdir() if path.is_dir()):
        if project_dir.name not in projects:
            if _is_uuid(project_dir.name) and not project_dir.is_symlink():
                report.orphaned_project_directories.append(project_dir)
            continue
        uploads = project_dir / "source"
        if uploads.is_dir():
            report.orphaned_files.extend(
                path.resolve()
                for path in sorted(uploads.iterdir())
                if path.is_file()
                and not path.is_symlink()
                and path.resolve() not in referenced
                # Never race an upload in progress: only files older than the grace period.
                and datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff
            )
        for area in sorted(path for path in project_dir.iterdir() if path.is_dir()):
            if area.name not in AREAS:
                continue
            for job_dir in sorted(path for path in area.iterdir() if path.is_dir()):
                job = jobs.get(job_dir.name)
                finished = job.finished_at if job else None
                if finished and finished.tzinfo is None:
                    finished = finished.replace(tzinfo=UTC)
                if (
                    job
                    and (
                        job.status == "cancelled" or (job.status == "failed" and not job.retryable)
                    )
                    and finished
                    and finished < cutoff
                    and not any(path.is_relative_to(job_dir) for path in referenced)
                ):
                    report.stale_job_directories.append(job_dir)
    report.reclaimable_bytes = sum(
        _size(path)
        for path in [
            *report.orphaned_files,
            *report.orphaned_project_directories,
            *report.stale_job_directories,
        ]
    )
    return report


def apply_cleanup(store: LocalStorage, report: CleanupReport) -> CleanupReport:
    for path in report.orphaned_files:
        if store.contains(path) and path.parent != store.root:
            path.unlink(missing_ok=True)
    for path in report.stale_job_directories:
        if store.contains(path) and len(path.relative_to(store.root).parts) == 3:
            shutil.rmtree(path, ignore_errors=True)
    for path in report.orphaned_project_directories:
        if store.contains(path) and path.parent == store.root and _is_uuid(path.name):
            shutil.rmtree(path, ignore_errors=True)
    report.removed = True
    return report
