"""Artifact lineage and byte-range media delivery."""

from fastapi import APIRouter, HTTPException, Request

from ..config import get_settings
from ..consent import artifact_block_reason
from ..dependencies import SessionDep
from ..lineage import ancestry
from ..models import (
    Artifact,
)
from ..schemas import (
    ArtifactLineage,
)
from ..storage import storage
from ..streaming import media_response

router = APIRouter()
settings = get_settings()


@router.get("/artifacts/{artifact_id}/lineage", response_model=ArtifactLineage)
async def artifact_lineage(artifact_id: str, session: SessionDep):
    artifact = session.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ancestry(session, artifact)


@router.api_route("/artifacts/{artifact_id}/content", methods=["GET", "HEAD"])
@router.api_route("/artifacts/{artifact_id}/download", methods=["GET", "HEAD"])
async def download_artifact(artifact_id: str, request: Request, session: SessionDep):
    artifact = session.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    blocked = artifact_block_reason(session, artifact)
    if blocked:
        raise HTTPException(403, blocked)
    path = storage().readable(artifact.path)
    if not path:
        raise HTTPException(status_code=404, detail="Artifact file is unavailable")

    return media_response(
        path,
        artifact.media_type,
        request,
        artifact.filename,
        download=request.url.path.endswith("/download"),
    )
