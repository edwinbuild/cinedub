"""Atomic restoration of the material members of an immutable saved-edit group."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from ..dependencies import SessionDep, require_project
from ..jobs import ACTIVE, write_lock
from ..line_editing import apply_line_edit
from ..models import Job, Segment, SegmentEdit
from ..schemas import (
    EditGroupHistory,
    EditGroupLine,
    EditGroupRestore,
    EditGroupSummary,
    SegmentBatchResult,
    SegmentUpdate,
)
from ..segment_history import content, history_state

router = APIRouter(tags=["edit-history"])


def inspect_group(session, project_id, group_id):
    project = require_project(session, project_id)
    records = session.scalars(
        select(SegmentEdit)
        .join(Segment, Segment.id == SegmentEdit.segment_id)
        .where(
            Segment.project_id == project_id,
            SegmentEdit.after_json["group_id"].as_string() == group_id,
        )
        .order_by(Segment.index, SegmentEdit.id)
        .limit(101)
    ).all()
    if not records:
        raise HTTPException(404, "Saved edit group not found in this project")
    first = session.get(Segment, records[0].segment_id)
    revision_id = first.revision_id
    if (
        not revision_id
        or len(records) > 100
        or len({r.segment_id for r in records}) != len(records)
    ):
        raise HTTPException(409, "Saved edit group membership is unavailable")
    lines, excluded, undo_ready, redo_ready, reason = [], 0, True, True, None
    for record in records:
        segment = session.get(Segment, record.segment_id)
        before, after = content(record.before_json), content(record.after_json)
        if segment.revision_id != revision_id or before is None or after is None:
            reason = "Group contains unavailable historical snapshots; no restoration is allowed"
            continue
        if before == after:
            excluded += 1
            continue
        history, undo, redo = history_state(session, segment)
        lines.append(
            EditGroupLine(
                segment_id=segment.id,
                expected_version=segment.version,
                expected_edit_id=record.id,
                index=segment.index,
                before=before,
                after=after,
            )
        )
        undo_ready &= bool(undo and undo[-1].id == record.id)
        redo_ready &= bool(redo and redo[-1].id == record.id)
        if segment.retired or history.unavailable_reason:
            reason = (
                history.unavailable_reason or "A grouped line was replaced; use structural history"
            )
    if project.active_revision_id != revision_id:
        reason = "Activate this timeline before restoring grouped content"
    elif not lines:
        reason = (
            reason or "No content-changing members; approval-only saves cannot be reversed here"
        )
    elif not undo_ready and not redo_ready:
        reason = (
            reason
            or "A grouped line has newer or independently restored content; no partial restoration"
        )
    return EditGroupHistory(
        group_id=group_id,
        revision_id=revision_id,
        lines=lines,
        excluded_nonmaterial_count=excluded,
        can_undo=bool(lines and undo_ready and not reason),
        can_redo=bool(lines and redo_ready and not reason),
        unavailable_reason=reason,
    )


@router.get("/projects/{project_id}/edit-groups", response_model=list[EditGroupSummary])
def list_groups(project_id: str, revision_id: str, session: SessionDep):
    require_project(session, project_id)
    identity = SegmentEdit.after_json["group_id"].as_string()
    return [
        EditGroupSummary(group_id=row[0], created_at=row[1], line_count=row[2])
        for row in session.execute(
            select(identity, func.max(SegmentEdit.created_at), func.count(SegmentEdit.id))
            .join(Segment, Segment.id == SegmentEdit.segment_id)
            .where(
                Segment.project_id == project_id,
                Segment.revision_id == revision_id,
                identity.is_not(None),
            )
            .group_by(identity)
            .order_by(func.max(SegmentEdit.created_at).desc(), identity)
            .limit(20)
        )
    ]


@router.get("/projects/{project_id}/edit-groups/{group_id}", response_model=EditGroupHistory)
def read_group(project_id: str, group_id: str, session: SessionDep):
    return inspect_group(session, project_id, group_id)


@router.post(
    "/projects/{project_id}/edit-groups/{group_id}/restore", response_model=SegmentBatchResult
)
def restore_group(project_id: str, group_id: str, payload: EditGroupRestore, session: SessionDep):
    try:
        write_lock(session)
        view = inspect_group(session, project_id, group_id)
        if not payload.restoration_confirmed:
            raise HTTPException(
                422,
                "Confirm grouped restoration clears selected takes and requires review again",
            )
        if view.revision_id != payload.revision_id or not getattr(view, f"can_{payload.action}"):
            raise HTTPException(
                409, view.unavailable_reason or "Grouped history changed; refresh before restoring"
            )
        expected = {
            line.segment_id: (line.expected_version, line.expected_edit_id) for line in view.lines
        }
        supplied = {
            line.segment_id: (line.expected_version, line.expected_edit_id)
            for line in payload.lines
        }
        if len(supplied) != len(payload.lines) or supplied != expected:
            raise HTTPException(
                409, "Every content-changing group member must match the inspected version and edit"
            )
        if session.scalar(
            select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE))
        ):
            raise HTTPException(409, "Wait for active processing before restoring grouped content")
        saved = []
        for line in view.lines:
            snapshot = line.before if payload.action == "undo" else line.after
            saved.append(
                apply_line_edit(
                    session,
                    session.get(Segment, line.segment_id),
                    SegmentUpdate(**snapshot.model_dump(), expected_version=line.expected_version),
                    history_metadata={
                        "history_action": payload.action,
                        "history_target_edit_id": line.expected_edit_id,
                        "history_group_id": group_id,
                    },
                    commit=False,
                )
            )
        result = SegmentBatchResult(group_id=group_id, lines=saved)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
