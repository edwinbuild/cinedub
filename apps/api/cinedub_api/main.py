import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from .config import get_settings
from .config_checks import startup_warnings, validate_settings
from .database import create_database
from .idempotency import HEADER as IDEMPOTENCY_HEADER
from .observability import HEADER, CorrelationMiddleware, configure_logging, log_event
from .routes.adaptation import router as adaptation_router
from .routes.alignment import router as alignment_router
from .routes.artifacts import router as artifacts_router
from .routes.batch_editing import router as batch_editing_router
from .routes.diagnostics import router as diagnostics_router
from .routes.dialogue import router as dialogue_router
from .routes.emotion import router as emotion_router
from .routes.events import router as events_router
from .routes.group_history import router as group_history_router
from .routes.history import router as history_router
from .routes.jobs import router as jobs_router
from .routes.mixes import router as mixes_router
from .routes.pipelines import router as pipelines_router
from .routes.projects import router as projects_router
from .routes.speaker_reuse import router as speaker_reuse_router
from .routes.stems import router as stems_router
from .routes.structure import router as structure_router
from .routes.take_analysis import router as take_analysis_router
from .routes.timeline import router as timeline_router
from .routes.uploads import router as uploads_router
from .routes.voices import router as voices_router
from .storage_capacity import STORAGE_MESSAGE, is_storage_capacity_error
from .workspace_lock import workspace_lease

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging("api")
    startup_warnings[:] = validate_settings(settings)
    for warning in startup_warnings:
        log_event("configuration_warning", logging.WARNING, detail=warning)
    with workspace_lease(settings.database_url, settings.storage_root):
        create_database()
        configure_logging("api")  # Alembic's logging config replaces handlers during upgrade.
        log_event("api_started")
        yield


app = FastAPI(title="CineDub API", version="0.2.0", lifespan=lifespan)


@app.exception_handler(DBAPIError)
@app.exception_handler(OSError)
async def storage_capacity_failure(_: Request, error: Exception):
    if not is_storage_capacity_error(error):
        raise error
    logging.getLogger(__name__).error("storage_capacity_exhausted")
    return JSONResponse(status_code=507, content={"detail": STORAGE_MESSAGE})


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Range", HEADER, IDEMPOTENCY_HEADER],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", HEADER],
)
# Outermost: every request, including CORS preflight and errors, carries a correlation ID.
app.add_middleware(CorrelationMiddleware)


app.include_router(diagnostics_router)
app.include_router(projects_router)
app.include_router(uploads_router)
app.include_router(timeline_router)
app.include_router(jobs_router)
app.include_router(events_router)
app.include_router(artifacts_router)
app.include_router(voices_router)
app.include_router(pipelines_router)
app.include_router(stems_router)
app.include_router(mixes_router)
app.include_router(alignment_router)
app.include_router(take_analysis_router)
app.include_router(dialogue_router)
app.include_router(adaptation_router)
app.include_router(emotion_router)
app.include_router(history_router)
app.include_router(structure_router)
app.include_router(speaker_reuse_router)
app.include_router(batch_editing_router)
app.include_router(group_history_router)
