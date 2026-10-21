"""Validated source media upload; queues media preparation."""

import hashlib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select

from ..config import get_settings
from ..dependencies import SessionDep, require_project
from ..idempotency import Idempotency, request_hash
from ..jobs import ACTIVE, write_lock
from ..media import MediaError, probe_media, safe_filename
from ..models import (
    Job,
    MediaAsset,
    new_id,
)
from ..project_status import sync_project_status
from ..schemas import (
    MediaAssetRead,
)
from ..storage import storage

router = APIRouter()
settings = get_settings()
UploadDep = Annotated[UploadFile, File()]


@router.post(
    "/projects/{project_id}/assets",
    response_model=MediaAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    project_id: str,
    file: UploadDep,
    session: SessionDep,
    request: Request,
):
    write_lock(session)
    project = require_project(session, project_id)
    original_name = safe_filename(file.filename or "upload.bin")
    once = Idempotency(session, request)
    if earlier := once.stored():
        # A retried upload: verify it is the same file without storing it again.
        digest = hashlib.sha256()
        while chunk := file.file.read(1024 * 1024):
            digest.update(chunk)
        file.file.close()
        once.digest = request_hash(project_id, original_name, digest.hexdigest())
        return once.respond(earlier)
    if session.scalar(select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Wait for active processing before importing another source")
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
    target_dir = storage().upload_dir(project.id)
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
        once.digest = request_hash(project_id, original_name, digest.hexdigest())
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
    sync_project_status(session, project)
    session.commit()
    session.flush()
    once.remember(201, MediaAssetRead.model_validate(asset).model_dump(mode="json"))
    session.commit()
    session.refresh(asset)
    return asset
