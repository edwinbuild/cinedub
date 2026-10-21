"""Explicit timing application records normal timeline history and invalidates old voice takes."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from ..alignment import read_alignment_report, validate_alignment_source
from ..dependencies import SessionDep
from ..jobs import ACTIVE, write_lock
from ..models import Artifact, Job, Segment, SegmentEdit
from ..schemas import AlignmentApply, AlignmentReport, SegmentRead

router = APIRouter(tags=["alignment"])


def require_report(session, artifact_id):
    artifact = session.get(Artifact, artifact_id)
    if not artifact or artifact.kind != "alignment_report":
        raise HTTPException(404, "Alignment report not found")
    try:
        return read_alignment_report(session, artifact)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Alignment report is unavailable or changed; align again") from exc


@router.get("/alignment-reports/{artifact_id}", response_model=AlignmentReport)
async def get_alignment_report(artifact_id: str, session: SessionDep):
    return require_report(session, artifact_id)


@router.post("/alignment-reports/{artifact_id}/apply", response_model=SegmentRead)
async def apply_alignment(artifact_id: str, payload: AlignmentApply, session: SessionDep):
    write_lock(session)
    report = require_report(session, artifact_id)
    evidence = next((line for line in report.lines if line.segment_id == payload.segment_id), None)
    if not evidence:
        raise HTTPException(422, "This line is not in the alignment report")
    if report.stale_reason or evidence.stale_reason:
        raise HTTPException(409, report.stale_reason or evidence.stale_reason)
    if evidence.status != "aligned" or not evidence.words:
        raise HTTPException(422, "Weak or missing acoustic evidence; correct timing manually")
    if session.scalar(
        select(Job.id).where(Job.project_id == report.project_id, Job.status.in_(ACTIVE))
    ):
        raise HTTPException(409, "Wait for active processing before applying alignment")
    try:
        validate_alignment_source(session, report.model_dump(), verify_files=True)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Alignment audio changed or is unavailable; align again") from exc
    line = session.get(Segment, evidence.segment_id)
    if line.version != payload.expected_version or line.version != evidence.segment_version:
        raise HTTPException(409, "Saved line changed; align it again")
    if not payload.listening_confirmed:
        raise HTTPException(422, "Listen to and confirm the suggested source timing first")
    if (line.human_edited or line.status == "approved") and not payload.replace_reviewed_timing:
        raise HTTPException(422, "Confirm replacing previously edited or approved timing")
    start, end = evidence.words[0].start_ms, evidence.words[-1].end_ms
    if start == line.start_ms and end == line.end_ms:
        return line
    before = SegmentRead.model_validate(line).model_dump(mode="json")
    result = session.execute(
        update(Segment)
        .where(Segment.id == line.id, Segment.version == payload.expected_version)
        .values(
            start_ms=start,
            end_ms=end,
            version=Segment.version + 1,
            human_edited=True,
            status="needs_review",
            selected_candidate_id=None,
            delivery_json={**line.delivery_json, "applied_alignment_artifact_id": artifact_id},
        )
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Saved line changed; refresh and align again")
    session.refresh(line)
    session.add(
        SegmentEdit(
            segment_id=line.id,
            version=line.version,
            before_json=before,
            after_json={
                **SegmentRead.model_validate(line).model_dump(mode="json"),
                "alignment_artifact_id": artifact_id,
            },
        )
    )
    session.commit()
    return line
