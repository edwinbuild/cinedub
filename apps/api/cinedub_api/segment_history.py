"""Replay append-only material edits; never restore approval, consent or voice selection."""

from sqlalchemy import select

from .models import SegmentEdit
from .schemas import SegmentContent, SegmentHistory, SegmentHistoryEntry

FIELDS = tuple(SegmentContent.model_fields)


def content(snapshot):
    try:
        value = SegmentContent.model_validate({key: snapshot[key] for key in FIELDS})
        if value.end_ms <= value.start_ms or not value.source_text.strip():
            return None
        return value
    except (ValueError, KeyError, TypeError):
        return None


def history_state(session, segment):
    records = session.scalars(
        select(SegmentEdit)
        .where(SegmentEdit.segment_id == segment.id)
        .order_by(SegmentEdit.version, SegmentEdit.created_at, SegmentEdit.id)
    ).all()
    undo, redo, previous = [], [], None
    entries = []
    for record in records:
        before, after = content(record.before_json), content(record.after_json)
        metadata = record.after_json if isinstance(record.after_json, dict) else {}
        action = metadata.get("history_action", "edit")
        target = metadata.get("history_target_edit_id")
        if action not in {"edit", "undo", "redo"}:
            action = "edit"
        entries.append(
            SegmentHistoryEntry(
                id=record.id,
                version=record.version,
                action=action,
                target_edit_id=target,
                before=before,
                after=after,
                created_at=record.created_at,
            )
        )
        if before is None or after is None:
            undo, redo, previous = [], [], None
            continue
        if previous is not None and previous != before:
            # A provider or another operation changed material outside this edit chain.
            undo, redo = [], []
        if action in {"undo", "redo"}:
            source, destination = (undo, redo) if action == "undo" else (redo, undo)
            expected = (
                content(source[-1].before_json if action == "undo" else source[-1].after_json)
                if source
                else None
            )
            if not source or source[-1].id != target or after != expected:
                undo, redo = [], []
            else:
                destination.append(source.pop())
        elif before != after:
            undo.append(record)
            redo = []
        previous = after
    reason = None
    current = content({key: getattr(segment, key) for key in FIELDS})
    if current is None or (records and previous != current):
        undo, redo = [], []
        reason = "Line content changed outside the saved edit chain; older history is read-only"
    if segment.retired:
        undo, redo = [], []
        reason = "This replaced line is read-only; use structural history"
    result = SegmentHistory(
        segment_id=segment.id,
        version=segment.version,
        undo_edit_id=undo[-1].id if undo else None,
        redo_edit_id=redo[-1].id if redo else None,
        unavailable_reason=reason,
        entries=list(reversed(entries[-20:])),
        total_entries=len(entries),
    )
    return result, undo, redo
