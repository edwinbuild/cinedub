"""Explicit source-bound approval of estimated cinematic stems."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from ..dependencies import SessionDep
from ..jobs import ACTIVE, write_lock
from ..models import Job, MediaAsset, StemReviewRecord, StemSet
from ..schemas import StemReview, StemSetRead

router = APIRouter(tags=["stems"])


@router.post("/stem-sets/{stem_set_id}/review", response_model=StemSetRead)
async def review_stems(stem_set_id: str, payload: StemReview, session: SessionDep):
    write_lock(session)
    stems = session.get(StemSet, stem_set_id)
    if not stems:
        raise HTTPException(404, "Stem set not found")
    source = session.get(MediaAsset, stems.source_asset_id)
    if not payload.reviewed_by.strip():
        raise HTTPException(422, "Record who reviewed the stems")
    if source.active_stem_set_id != payload.expected_active_stem_set_id:
        raise HTTPException(409, "Active stem choice changed; refresh first")
    if session.scalar(
        select(Job.id).where(Job.project_id == stems.project_id, Job.status.in_(ACTIVE))
    ):
        raise HTTPException(409, "Wait for active processing before changing stem approval")
    result = session.execute(
        update(StemSet)
        .where(StemSet.id == stems.id, StemSet.version == payload.expected_version)
        .values(status=payload.status, version=StemSet.version + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Stem review changed; refresh first")
    if payload.status == "approved":
        source.active_stem_set_id = stems.id
    elif source.active_stem_set_id == stems.id:
        source.active_stem_set_id = None
    session.add(
        StemReviewRecord(
            stem_set_id=stems.id,
            version=payload.expected_version + 1,
            status=payload.status,
            reviewed_by=payload.reviewed_by.strip(),
            note=payload.note,
        )
    )
    session.commit()
    session.refresh(stems)
    return stems
