import asyncio
import json
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal, create_database, get_session
from .diagnostics import hardware_diagnostics
from .media import MediaError, probe_media, safe_filename
from .models import (
    Artifact,
    ConsentRecord,
    Job,
    MediaAsset,
    Project,
    Segment,
    Speaker,
    VoiceProfile,
)
from .providers import ProviderRegistry
from .schemas import (
    ArtifactRead,
    CapabilityRead,
    JobCreate,
    JobRead,
    MediaAssetRead,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    SegmentRead,
    SegmentUpdate,
    SpeakerRead,
    VoiceProfileCreate,
    VoiceProfileRead,
)

settings = get_settings()
SessionDep = Annotated[Session, Depends(get_session)]
UploadDep = Annotated[UploadFile, File()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_database()
    yield


app = FastAPI(title="CineDub API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def artifact_read(artifact: Artifact) -> ArtifactRead:
    return ArtifactRead(
        id=artifact.id,
        project_id=artifact.project_id,
        job_id=artifact.job_id,
        kind=artifact.kind,
        filename=artifact.filename,
        media_type=artifact.media_type,
        created_at=artifact.created_at,
        download_url=f"/artifacts/{artifact.id}/download",
    )


def project_detail(session: Session, project: Project) -> ProjectDetail:
    assets = session.scalars(
        select(MediaAsset)
        .where(MediaAsset.project_id == project.id)
        .order_by(MediaAsset.created_at)
    ).all()
    speakers = session.scalars(
        select(Speaker).where(Speaker.project_id == project.id).order_by(Speaker.label)
    ).all()
    segments = session.scalars(
        select(Segment).where(Segment.project_id == project.id).order_by(Segment.index)
    ).all()
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
        assets=[MediaAssetRead.model_validate(item) for item in assets],
        speakers=[SpeakerRead.model_validate(item) for item in speakers],
        segments=[SegmentRead.model_validate(item) for item in segments],
        jobs=[JobRead.model_validate(item) for item in jobs],
        artifacts=[artifact_read(item) for item in artifacts],
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
async def capabilities() -> list[CapabilityRead]:
    registry = ProviderRegistry(settings)
    return [
        CapabilityRead.model_validate(item, from_attributes=True)
        for item in registry.capabilities()
    ]


@app.get("/diagnostics")
async def diagnostics() -> dict:
    return hardware_diagnostics(settings.storage_root)


@app.get("/projects", response_model=list[ProjectRead])
async def list_projects(session: SessionDep) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.updated_at.desc())).all())


@app.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, session: SessionDep) -> Project:
    project = Project(**payload.model_dump(), duration_limit_seconds=settings.max_duration_seconds)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@app.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: str, session: SessionDep) -> ProjectDetail:
    return project_detail(session, require_project(session, project_id))


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
    project = require_project(session, project_id)
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
    target = target_dir / f"{asset.id}{extension}"
    received = 0
    try:
        with target.open("xb") as destination:
            while chunk := file.file.read(1024 * 1024):
                received += len(chunk)
                if received > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413, detail="Upload exceeds configured size limit"
                    )
                destination.write(chunk)
        metadata = probe_media(target)
        duration_ms = metadata.get("duration_ms")
        if duration_ms and duration_ms > project.duration_limit_seconds * 1000:
            detail = f"The first release supports at most {project.duration_limit_seconds} seconds"
            raise HTTPException(
                status_code=422,
                detail=detail,
            )
    except (HTTPException, MediaError):
        target.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()

    asset.path = str(target.resolve())
    asset.duration_ms = metadata.get("duration_ms")
    asset.metadata_json = metadata
    session.add(asset)
    session.flush()
    session.add(Job(project_id=project.id, stage="ingest", provider="local"))
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
    if segment.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Segment changed; refresh before saving")
    values = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    if values.get("speaker_id"):
        speaker = session.get(Speaker, values["speaker_id"])
        if not speaker or speaker.project_id != segment.project_id:
            raise HTTPException(status_code=422, detail="Speaker does not belong to this project")
    for field, value in values.items():
        setattr(segment, field, value)
    segment.version += 1
    session.commit()
    session.refresh(segment)
    return segment


@app.post(
    "/projects/{project_id}/voice-profiles",
    response_model=VoiceProfileRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_voice_profile(
    project_id: str,
    payload: VoiceProfileCreate,
    session: SessionDep,
) -> VoiceProfile:
    require_project(session, project_id)
    speaker = session.get(Speaker, payload.speaker_id)
    if not speaker or speaker.project_id != project_id:
        raise HTTPException(status_code=422, detail="Speaker does not belong to this project")
    if payload.reference_asset_id:
        reference = session.get(MediaAsset, payload.reference_asset_id)
        if not reference or reference.project_id != project_id:
            raise HTTPException(
                status_code=422, detail="Reference asset does not belong to this project"
            )
    profile = VoiceProfile(
        project_id=project_id,
        speaker_id=payload.speaker_id,
        display_name=payload.display_name,
        provider=payload.provider,
        provider_voice_id=payload.provider_voice_id,
        reference_asset_id=payload.reference_asset_id,
        consent_status="approved" if payload.consent.approved else "denied",
    )
    session.add(profile)
    session.flush()
    session.add(
        ConsentRecord(
            voice_profile_id=profile.id,
            status=profile.consent_status,
            attested_by=payload.consent.attested_by,
            note=payload.consent.note,
        )
    )
    session.commit()
    session.refresh(profile)
    return profile


@app.post(
    "/projects/{project_id}/jobs", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED
)
async def create_job(
    project_id: str,
    payload: JobCreate,
    session: SessionDep,
) -> Job:
    project = require_project(session, project_id)
    active = session.scalar(
        select(Job).where(
            Job.project_id == project_id,
            Job.stage == payload.stage,
            Job.status.in_(["queued", "running"]),
        )
    )
    if active:
        return active
    default_provider = {
        "ingest": "local",
        "demo_pipeline": "fake",
        "translate": settings.translator,
        "synthesize": settings.voice_synthesizer,
        "export": "local",
    }[payload.stage]
    job = Job(
        project_id=project_id, stage=payload.stage, provider=payload.provider or default_provider
    )
    project.status = "processing"
    session.add(job)
    session.commit()
    session.refresh(job)
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


@app.get("/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: str, session: SessionDep) -> StreamingResponse:
    artifact = session.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = Path(artifact.path).resolve()
    storage_root = settings.storage_root.resolve()
    if not path.is_relative_to(storage_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file is unavailable")

    async def chunks() -> AsyncIterator[bytes]:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                yield chunk

    headers = {"Content-Disposition": f'attachment; filename="{artifact.filename}"'}
    return StreamingResponse(chunks(), media_type=artifact.media_type, headers=headers)
