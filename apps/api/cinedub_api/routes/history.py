"""Explicit, version-safe undo/redo of saved dialogue content and timing."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..dependencies import SessionDep
from ..jobs import ACTIVE, write_lock
from ..line_editing import apply_line_edit
from ..models import Job, Project, Segment
from ..schemas import SegmentHistory, SegmentHistoryAction, SegmentRead, SegmentUpdate
from ..segment_history import content, history_state

router = APIRouter(tags=["edit-history"])


def require_segment(session, segment_id):
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(404, "Segment not found")
    return segment


@router.get("/segments/{segment_id}/history", response_model=SegmentHistory)
def inspect_history(segment_id: str, session: SessionDep):
    return history_state(session, require_segment(session, segment_id))[0]


@router.post("/segments/{segment_id}/history", response_model=SegmentRead)
def restore_history(segment_id: str, payload: SegmentHistoryAction, session: SessionDep):
    write_lock(session)
    segment = require_segment(session, segment_id)
    if segment.retired:
        raise HTTPException(409, "This replaced line is read-only; use structural history")
    project = session.get(Project, segment.project_id)
    if project.active_revision_id != segment.revision_id:
        raise HTTPException(409, "Activate this timeline before restoring saved edits")
    if segment.version != payload.expected_version:
        raise HTTPException(409, "Line changed; refresh history before restoring")
    if session.scalar(
        select(Job.id).where(
            Job.project_id == segment.project_id,
            Job.status.in_(ACTIVE),
        )
    ):
        raise HTTPException(409, "Wait for active processing before restoring saved edits")
    if not payload.restoration_confirmed:
        raise HTTPException(
            422, "Confirm restoration clears selected audio and requires review again"
        )
    history, undo, redo = history_state(session, segment)
    stack = undo if payload.action == "undo" else redo
    if not stack or stack[-1].id != payload.expected_edit_id:
        raise HTTPException(
            409, history.unavailable_reason or "History changed; refresh before restoring"
        )
    target = stack[-1]
    saved = content(target.before_json if payload.action == "undo" else target.after_json)
    if saved is None:
        raise HTTPException(409, "This historical snapshot is unavailable")
    return apply_line_edit(
        session,
        segment,
        SegmentUpdate(**saved.model_dump(), expected_version=payload.expected_version),
        history_metadata={"history_action": payload.action, "history_target_edit_id": target.id},
    )
