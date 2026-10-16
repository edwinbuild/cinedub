import asyncio
import hashlib
import json
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .consent import artifact_block_reason
from .database import SessionLocal, create_database
from .dependencies import SessionDep, require_project
from .diagnostics import hardware_diagnostics
from .dialogue_review import latest_brief
from .dialogue_review import stale_reason as dialogue_context_stale_reason
from .jobs import ACTIVE, budget_totals, estimate_job, prepare_job, write_lock
from .line_editing import apply_line_edit
from .media import MediaError, probe_media, safe_filename
from .mixes import mix_read
from .models import (
    Artifact,
    Job,
    MediaAsset,
    MixRender,
    Project,
    ProviderRun,
    Segment,
    Speaker,
    StemSet,
    TimelineRevision,
    VoiceProfile,
    new_id,
)
from .providers import ProviderRegistry
from .routes.adaptation import router as adaptation_router
from .routes.alignment import router as alignment_router
from .routes.dialogue import router as dialogue_router
from .routes.emotion import router as emotion_router
from .routes.history import router as history_router
from .routes.mixes import router as mixes_router
from .routes.stems import router as stems_router
from .routes.structure import router as structure_router
from .routes.take_analysis import router as take_analysis_router
from .routes.voices import router as voices_router
from .schemas import (
    ArtifactRead,
    BudgetUpdate,
    CapabilityRead,
    HardwareRead,
    JobCreate,
    JobEstimate,
    JobRead,
    MediaAssetRead,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    RevisionActivate,
    RevisionRead,
    SegmentRead,
    SegmentUpdate,
    SpeakerCreate,
    SpeakerRead,
    SpeakerUpdate,
    StemSetRead,
    VoiceProfileRead,
)
from .streaming import media_response
from .timeline import revision_segments

settings = get_settings()
UploadDep = Annotated[UploadFile, File()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_database()
    yield


app = FastAPI(title="CineDub API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Range"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


app.include_router(voices_router)
app.include_router(stems_router)
app.include_router(mixes_router)
app.include_router(alignment_router)
app.include_router(take_analysis_router)
app.include_router(dialogue_router)
app.include_router(adaptation_router)
app.include_router(emotion_router)
app.include_router(history_router)
app.include_router(structure_router)


def artifact_read(artifact: Artifact, session: Session | None = None) -> ArtifactRead:
    return ArtifactRead(
        id=artifact.id,
        project_id=artifact.project_id,
        job_id=artifact.job_id,
        kind=artifact.kind,
        filename=artifact.filename,
        media_type=artifact.media_type,
        created_at=artifact.created_at,
        download_url=f"/artifacts/{artifact.id}/download",
        content_url=f"/artifacts/{artifact.id}/content",
        metadata_json=artifact.metadata_json,
        access_blocked_reason=artifact_block_reason(session, artifact) if session else None,
    )


def project_detail(session: Session, project: Project) -> ProjectDetail:
    assets = session.scalars(
        select(MediaAsset)
        .where(MediaAsset.project_id == project.id)
        .order_by(MediaAsset.created_at)
    ).all()
    speakers = session.scalars(
        select(Speaker)
        .where(Speaker.project_id == project.id, Speaker.revision_id == project.active_revision_id)
        .order_by(Speaker.label)
    ).all()
    segments = revision_segments(session, project.id, project.active_revision_id)
    jobs = session.scalars(
        select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc())
    ).all()
    artifacts = session.scalars(
        select(Artifact)
        .where(Artifact.project_id == project.id)
        .order_by(Artifact.created_at.desc())
    ).all()
    return ProjectDetail(
        **ProjectRead.model_validate(project).model_dump(),
        dialogue_brief=(
            latest_brief(session, project.id, project.active_revision_id)
            if project.active_revision_id
            else None
        ),
        assets=[MediaAssetRead.model_validate(item) for item in assets],
        speakers=[SpeakerRead.model_validate(item) for item in speakers],
        segments=[SegmentRead.model_validate(item) for item in segments],
        jobs=[JobRead.model_validate(item) for item in jobs],
        artifacts=[artifact_read(item, session) for item in artifacts],
        revisions=[
            RevisionRead.model_validate(item)
            for item in session.scalars(
                select(TimelineRevision)
                .where(TimelineRevision.project_id == project.id)
                .order_by(TimelineRevision.created_at.desc())
            ).all()
        ],
        spent_estimate_inr=budget_totals(session, project.id)[0],
        reserved_inr=budget_totals(session, project.id)[1],
        mixes=[
            mix_read(session, item)
            for item in session.scalars(
                select(MixRender)
                .where(MixRender.project_id == project.id)
                .order_by(MixRender.created_at.desc())
            ).all()
        ],
        stem_sets=[
            StemSetRead.model_validate(item)
            for item in session.scalars(
                select(StemSet)
                .where(StemSet.project_id == project.id)
                .order_by(StemSet.created_at.desc())
            ).all()
        ],
        voice_profiles=[
            VoiceProfileRead.model_validate(item)
            for item in session.scalars(
                select(VoiceProfile)
                .where(VoiceProfile.project_id == project.id)
                .order_by(VoiceProfile.updated_at.desc())
            ).all()
        ],
    )


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "environment": settings.env,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "local_only": settings.api_host in {"127.0.0.1", "localhost"},
    }


@app.get("/capabilities", response_model=list[CapabilityRead])
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


@app.get("/diagnostics", response_model=HardwareRead)
async def diagnostics() -> dict:
    return hardware_diagnostics(settings.storage_root)


@app.get("/projects", response_model=list[ProjectRead])
async def list_projects(session: SessionDep) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.updated_at.desc())).all())


@app.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, session: SessionDep) -> Project:
    project = Project(
        **payload.model_dump(),
        duration_limit_seconds=settings.max_duration_seconds,
        budget_inr=settings.project_budget_inr,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@app.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: str, session: SessionDep) -> ProjectDetail:
    return project_detail(session, require_project(session, project_id))


@app.patch("/projects/{project_id}/budget", response_model=ProjectDetail)
async def change_budget(project_id: str, payload: BudgetUpdate, session: SessionDep):
    write_lock(session)
    project = require_project(session, project_id)
    spent, reserved = budget_totals(session, project_id)
    if payload.budget_inr < spent + reserved:
        raise HTTPException(422, "Budget cannot be lower than spent and reserved estimates")
    project.budget_inr = payload.budget_inr
    session.commit()
    return project_detail(session, project)


@app.post(
    "/projects/{project_id}/assets",
    response_model=MediaAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    project_id: str,
    file: UploadDep,
    session: SessionDep,
) -> MediaAsset:
    write_lock(session)
    project = require_project(session, project_id)
    if session.scalar(select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Wait for active processing before importing another source")
    original_name = safe_filename(file.filename or "upload.bin")
    extension = Path(original_name).suffix.lower()
    if extension not in {".mp4", ".mov", ".mkv", ".webm", ".wav", ".mp3", ".flac", ".m4a"}:
        raise HTTPException(status_code=415, detail="Unsupported media type")

    asset = MediaAsset(
        project_id=project.id,
        kind="source",
        path="",
        filename=original_name,
        media_type=file.content_type or "application/octet-stream",
    )
    target_dir = settings.storage_root / project.id / "source"
    target_dir.mkdir(parents=True, exist_ok=True)
    asset.id = new_id()
    target = target_dir / f"{asset.id}{extension}"
    received = 0
    digest = hashlib.sha256()
    try:
        with target.open("xb") as destination:
            while chunk := file.file.read(1024 * 1024):
                received += len(chunk)
                if received > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413, detail="Upload exceeds configured size limit"
                    )
                destination.write(chunk)
                digest.update(chunk)
        metadata = probe_media(target)
        duration_ms = metadata.get("duration_ms")
        if not duration_ms or duration_ms <= 0:
            raise HTTPException(422, "Media must have a readable positive duration")
        if not any(item.get("codec_type") == "audio" for item in metadata.get("streams", [])):
            raise HTTPException(422, "Scene must contain an audio stream")
        if duration_ms and duration_ms > project.duration_limit_seconds * 1000:
            detail = f"The first release supports at most {project.duration_limit_seconds} seconds"
            raise HTTPException(
                status_code=422,
                detail=detail,
            )
    except MediaError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()

    asset.path = str(target.resolve())
    asset.duration_ms = metadata.get("duration_ms")
    asset.metadata_json = {**metadata, "sha256": digest.hexdigest()}
    session.add(asset)
    session.flush()
    session.add(
        Job(
            project_id=project.id,
            stage="ingest",
            provider="local",
            input_json={"source_asset_id": asset.id},
        )
    )
    project.status = "processing"
    session.commit()
    session.refresh(asset)
    return asset


@app.patch("/segments/{segment_id}", response_model=SegmentRead)
async def update_segment(
    segment_id: str,
    payload: SegmentUpdate,
    session: SessionDep,
) -> Segment:
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    return apply_line_edit(session, segment, payload)


@app.post("/projects/{project_id}/speakers", response_model=SpeakerRead, status_code=201)
async def create_speaker(project_id: str, payload: SpeakerCreate, session: SessionDep):
    write_lock(session)
    require_project(session, project_id)
    revision = session.get(TimelineRevision, payload.revision_id)
    if not revision or revision.project_id != project_id:
        raise HTTPException(422, "Select a revision belonging to this project")
    name = payload.display_name.strip()
    if not name:
        raise HTTPException(422, "Speaker name cannot be blank")
    speaker = Speaker(
        project_id=project_id,
        revision_id=revision.id,
        label=f"MANUAL_{new_id()}",
        display_name=name,
    )
    session.add(speaker)
    session.commit()
    return speaker


@app.patch("/speakers/{speaker_id}", response_model=SpeakerRead)
async def rename_speaker(speaker_id: str, payload: SpeakerUpdate, session: SessionDep):
    speaker = session.get(Speaker, speaker_id)
    if not speaker:
        raise HTTPException(404, "Speaker not found")
    if not payload.display_name.strip():
        raise HTTPException(422, "Speaker name must not be blank")
    speaker.display_name = payload.display_name.strip()
    session.commit()
    return speaker


@app.get("/projects/{project_id}/revisions", response_model=list[RevisionRead])
async def list_revisions(project_id: str, session: SessionDep):
    require_project(session, project_id)
    return session.scalars(
        select(TimelineRevision)
        .where(TimelineRevision.project_id == project_id)
        .order_by(TimelineRevision.created_at.desc())
    ).all()


@app.post("/projects/{project_id}/revisions/{revision_id}/activate", response_model=ProjectDetail)
async def activate_revision(
    project_id: str, revision_id: str, payload: RevisionActivate, session: SessionDep
):
    write_lock(session)
    project = require_project(session, project_id)
    revision = session.get(TimelineRevision, revision_id)
    if not revision or revision.project_id != project.id:
        raise HTTPException(404, "Timeline revision not found")
    if project.active_revision_id != payload.expected_active_revision_id:
        raise HTTPException(409, "Active timeline changed; refresh first")
    if session.scalar(select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Wait for active processing before switching timelines")
    project.active_revision_id = revision.id
    project.status = "review"
    session.commit()
    return project_detail(session, project)


@app.post("/projects/{project_id}/jobs/estimate", response_model=JobEstimate)
async def job_estimate(project_id: str, payload: JobCreate, session: SessionDep):
    return estimate_job(session, require_project(session, project_id), payload)


@app.post(
    "/projects/{project_id}/jobs", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED
)
async def create_job(
    project_id: str,
    payload: JobCreate,
    session: SessionDep,
) -> Job:
    write_lock(session)
    project = require_project(session, project_id)
    provider, inputs, cost = prepare_job(session, project, payload)
    estimate = estimate_job(session, project, payload)
    if estimate.cached_job_id:
        return session.get(Job, estimate.cached_job_id)
    if session.scalar(select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Another job is active; wait or cancel it first")
    if cost > estimate.remaining_inr:
        raise HTTPException(
            402, "Estimated project budget exceeded; adjust local budget configuration"
        )
    job = Job(
        project_id=project_id,
        stage=payload.stage,
        provider=provider,
        input_json=inputs,
        estimated_cost_inr=cost,
    )
    project.status = "processing"
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@app.post("/jobs/{job_id}/resume", response_model=JobRead)
async def resume_job(job_id: str, session: SessionDep):
    write_lock(session)
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    local_dialogue = job.stage == "adapt_dialogue" and job.provider == "local"
    if (
        job.status != "failed"
        or not job.retryable
        or (not job.remote_job_id and not local_dialogue)
    ):
        raise HTTPException(422, "This job cannot safely resume; create a new request explicitly")
    if session.scalar(
        select(Job.id).where(Job.project_id == job.project_id, Job.status.in_(ACTIVE))
    ):
        raise HTTPException(409, "Another job is active")
    if local_dialogue:
        reason = dialogue_context_stale_reason(session, job.project_id, job.input_json)
        if reason:
            raise HTTPException(409, reason)
        job.retryable = False
    job.status = "queued"
    job.cancel_requested = False
    job.error_code = None
    job.error_message = None
    job.finished_at = None
    if job.remote_job_id:
        job.checkpoint_json = {**job.checkpoint_json, "poll_started_at": None}
    session.get(Project, job.project_id).status = "processing"
    session.commit()
    return job


@app.post("/jobs/{job_id}/cancel", response_model=JobRead)
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
        session.get(Project, job.project_id).status = "review"
    session.commit()
    session.refresh(job)
    return job


@app.get("/projects/{project_id}/events")
async def project_events(project_id: str, request: Request) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        last_payload = ""
        while not await request.is_disconnected():
            with SessionLocal() as session:
                project = session.get(Project, project_id)
                if not project:
                    yield 'event: error\ndata: {"detail":"Project not found"}\n\n'
                    return
                jobs = session.scalars(
                    select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())
                ).all()
                data = {
                    "project_status": project.status,
                    "jobs": [JobRead.model_validate(job).model_dump(mode="json") for job in jobs],
                }
                payload = json.dumps(data, separators=(",", ":"))
                if payload != last_payload:
                    yield f"event: update\ndata: {payload}\n\n"
                    last_payload = payload
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.api_route("/artifacts/{artifact_id}/content", methods=["GET", "HEAD"])
@app.api_route("/artifacts/{artifact_id}/download", methods=["GET", "HEAD"])
async def download_artifact(artifact_id: str, request: Request, session: SessionDep):
    artifact = session.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    blocked = artifact_block_reason(session, artifact)
    if blocked:
        raise HTTPException(403, blocked)
    path = Path(artifact.path).resolve()
    storage_root = settings.storage_root.resolve()
    if not path.is_relative_to(storage_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file is unavailable")

    return media_response(
        path,
        artifact.media_type,
        request,
        artifact.filename,
        download=request.url.path.endswith("/download"),
    )
