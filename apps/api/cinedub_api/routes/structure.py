"""Split, merge and guarded reversal; originals are retained for provenance."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..dependencies import SessionDep
from ..jobs import write_lock
from ..models import TimelineRevision, TimelineStructureEdit
from ..schemas import (
    SegmentMerge,
    SegmentSplit,
    TimelineStructureEditRead,
    TimelineStructureRestore,
)
from ..timeline_structure import perform_structure, restore_structure, structure_read

router = APIRouter(tags=["timeline-structure"])


@router.post("/segments/{segment_id}/split", response_model=TimelineStructureEditRead)
def split_line(segment_id: str, payload: SegmentSplit, session: SessionDep):
    write_lock(session)
    return perform_structure(session, segment_id, payload)


@router.post("/segments/{segment_id}/merge", response_model=TimelineStructureEditRead)
def merge_line(segment_id: str, payload: SegmentMerge, session: SessionDep):
    write_lock(session)
    return perform_structure(session, segment_id, payload, merge=True)


@router.get(
    "/projects/{project_id}/revisions/{revision_id}/structure-edits",
    response_model=list[TimelineStructureEditRead],
)
def structure_history(project_id: str, revision_id: str, session: SessionDep):
    revision = session.get(TimelineRevision, revision_id)
    if not revision or revision.project_id != project_id:
        raise HTTPException(404, "Timeline not found")
    operations = session.scalars(
        select(TimelineStructureEdit)
        .where(
            TimelineStructureEdit.project_id == project_id,
            TimelineStructureEdit.revision_id == revision_id,
        )
        .order_by(TimelineStructureEdit.created_at.desc(), TimelineStructureEdit.id.desc())
        .limit(20)
    )
    return [structure_read(session, operation) for operation in operations]


@router.post(
    "/timeline-structure-edits/{operation_id}/restore", response_model=TimelineStructureEditRead
)
def reverse_edit(operation_id: str, payload: TimelineStructureRestore, session: SessionDep):
    write_lock(session)
    operation = session.get(TimelineStructureEdit, operation_id)
    if not operation:
        raise HTTPException(404, "Structural edit not found")
    return restore_structure(session, operation, payload)
