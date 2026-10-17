"""Bounded, all-or-nothing dialogue edits with shared history and version checks."""

from fastapi import APIRouter, HTTPException

from ..dependencies import SessionDep, require_project
from ..jobs import write_lock
from ..line_editing import apply_line_edit
from ..models import Segment, new_id
from ..schemas import SegmentBatchResult, SegmentBatchUpdate, SegmentUpdate

router = APIRouter()


@router.patch("/projects/{project_id}/segments", response_model=SegmentBatchResult)
async def update_segments(project_id: str, payload: SegmentBatchUpdate, session: SessionDep):
    try:
        write_lock(session)
        project = require_project(session, project_id)
        if project.active_revision_id != payload.revision_id:
            raise HTTPException(409, "Active timeline changed; no grouped edits were saved")
        ids = [line.segment_id for line in payload.lines]
        if len(set(ids)) != len(ids):
            raise HTTPException(422, "Each dialogue line may appear only once in a grouped save")
        group_id, saved = new_id(), []
        for item in payload.lines:
            segment = session.get(Segment, item.segment_id)
            if (
                not segment
                or segment.project_id != project_id
                or segment.revision_id != payload.revision_id
            ):
                raise HTTPException(
                    422, "Every line must belong to the selected project and timeline"
                )
            changes = item.model_dump(exclude={"segment_id"}, exclude_unset=True)
            if set(changes) <= {"expected_version"}:
                raise HTTPException(422, "Each grouped line must contain an explicit change")
            saved.append(
                apply_line_edit(
                    session,
                    segment,
                    SegmentUpdate(**changes),
                    history_metadata={"group_id": group_id},
                    commit=False,
                )
            )
        result = SegmentBatchResult(group_id=group_id, lines=saved)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
