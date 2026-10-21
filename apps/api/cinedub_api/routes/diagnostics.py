"""Service health, provider capabilities and hardware diagnostics."""

import shutil

from fastapi import APIRouter
from sqlalchemy import select

from ..config import get_settings
from ..config_checks import startup_warnings
from ..dependencies import SessionDep
from ..diagnostics import hardware_diagnostics
from ..models import (
    Project,
    ProviderRun,
)
from ..providers import ProviderRegistry
from ..schemas import (
    CapabilityRead,
    HardwareRead,
    StorageUsage,
)
from ..storage import storage
from ..storage_cleanup import plan_cleanup

router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "environment": settings.env,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "local_only": settings.api_host in {"127.0.0.1", "localhost"},
        "config_warnings": startup_warnings,
    }


@router.get("/capabilities", response_model=list[CapabilityRead])
async def capabilities(session: SessionDep) -> list[CapabilityRead]:
    registry = ProviderRegistry(settings)
    values = []
    for item in registry.capabilities():
        value = CapabilityRead.model_validate(item, from_attributes=True)
        value.verified = item.available and bool(
            session.scalar(
                select(ProviderRun.id).where(
                    ProviderRun.capability == item.capability,
                    ProviderRun.provider == item.selected_provider,
                    ProviderRun.status == "completed",
                )
            )
        )
        values.append(value)
    return values


@router.get("/diagnostics", response_model=HardwareRead)
async def diagnostics() -> dict:
    return hardware_diagnostics(settings.storage_root)


@router.get("/diagnostics/storage", response_model=StorageUsage)
async def storage_usage(session: SessionDep) -> StorageUsage:
    """Read-only usage report; removal is the explicit `scripts/storage-cleanup.py --apply`."""
    store = storage()
    plan = plan_cleanup(session, store)
    projects = [project_id for (project_id,) in session.execute(select(Project.id)).all()]
    orphaned = [*plan.orphaned_files, *plan.orphaned_project_directories]
    return StorageUsage(
        root_bytes=store.usage(),
        free_bytes=shutil.disk_usage(store.root).free,
        projects={project_id: store.usage(project_id) for project_id in projects},
        orphaned_files=len(orphaned),
        orphaned_bytes=plan.reclaimable_bytes,
        stale_job_directories=len(plan.stale_job_directories),
    )
