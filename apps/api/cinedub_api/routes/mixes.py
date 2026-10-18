"""Listening acceptance is separate from technical render checks and durable packaging."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from ..dependencies import SessionDep
from ..jobs import ACTIVE, write_lock
from ..mixes import mix_read, validate_mix_snapshot
from ..models import Job, MixRender, MixReviewRecord
from ..project_status import sync_project_status
from ..schemas import MixRenderRead, MixReview

router = APIRouter(tags=["mixes"])


@router.post("/mixes/{mix_id}/review", response_model=MixRenderRead)
async def review_mix(mix_id: str, payload: MixReview, session: SessionDep):
    write_lock(session)
    mix = session.get(MixRender, mix_id)
    if not mix:
        raise HTTPException(404, "Mix not found")
    if not payload.reviewed_by.strip():
        raise HTTPException(422, "Record who reviewed the mix")
    if session.scalar(
        select(Job.id).where(Job.project_id == mix.project_id, Job.status.in_(ACTIVE))
    ):
        raise HTTPException(409, "Wait for active processing before accepting or rejecting a mix")
    job = session.get(Job, mix.job_id)
    if not job:
        raise HTTPException(409, "Render provenance is unavailable")
    if payload.status == "approved":
        if not payload.listening_confirmed:
            raise HTTPException(
                422, "Confirm listening and synchronization review before export acceptance"
            )
        if mix.quality_json.get("technical_status") != "passed":
            raise HTTPException(422, "Technical validation must pass before acceptance")
        try:
            validate_mix_snapshot(session, job.input_json)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    result = session.execute(
        update(MixRender)
        .where(MixRender.id == mix.id, MixRender.version == payload.expected_version)
        .values(status=payload.status, version=MixRender.version + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Mix review changed; refresh first")
    review = MixReviewRecord(
        mix_id=mix.id,
        version=payload.expected_version + 1,
        status=payload.status,
        reviewed_by=payload.reviewed_by.strip(),
        note=payload.note,
    )
    session.add(review)
    session.flush()
    if payload.status == "approved":
        session.add(
            Job(
                project_id=mix.project_id,
                stage="package_mix",
                provider="local",
                input_json={
                    "mix_id": mix.id,
                    "review_record_id": review.id,
                    "candidates": job.input_json["candidates"],
                },
            )
        )
    sync_project_status(session, mix.project_id)
    session.commit()
    session.refresh(mix)
    return mix_read(session, mix)
