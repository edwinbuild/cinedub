"""Transactional line replacement with preserved originals and reversible audit records."""

from fastapi import HTTPException
from sqlalchemy import select

from .jobs import ACTIVE
from .models import (
    Job,
    MediaAsset,
    Project,
    Segment,
    SegmentEdit,
    Speaker,
    TimelineRevision,
    TimelineStructureEdit,
)
from .schemas import SegmentRead, TimelineStructureEditRead
from .segment_history import content
from .timeline import revision_segments


def guard_revision(session, project_id, revision_id):
    project = session.get(Project, project_id)
    revision = session.get(TimelineRevision, revision_id)
    if not project or not revision or revision.project_id != project_id:
        raise HTTPException(404, "Timeline not found")
    if project.active_revision_id != revision_id:
        raise HTTPException(409, "Activate this timeline before changing dialogue structure")
    if session.scalar(select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Wait for active processing before changing dialogue structure")
    return project, revision


def snapshot(line):
    return SegmentRead.model_validate(line).model_dump(mode="json")


def source_limit(session, project, revision):
    source = session.get(MediaAsset, revision.source_asset_id) if revision.source_asset_id else None
    if revision.source_asset_id and (
        not source or source.project_id != project.id or not source.duration_ms
    ):
        raise HTTPException(422, "Source duration is unavailable")
    return source.duration_ms if source else project.duration_limit_seconds * 1000


def require_line(session, segment_id, revision_id, version):
    line = session.get(Segment, segment_id)
    if not line or line.revision_id != revision_id:
        raise HTTPException(422, "Line does not belong to this timeline")
    if line.retired or line.version != version:
        raise HTTPException(409, "Line was changed or replaced; refresh before changing structure")
    return line


def check_speaker(session, line):
    if line.speaker_id:
        speaker = session.get(Speaker, line.speaker_id)
        if (
            not speaker
            or speaker.project_id != line.project_id
            or speaker.revision_id != line.revision_id
        ):
            raise HTTPException(422, "Speaker does not belong to this timeline")


def change_activity(session, line, retired, operation):
    before = snapshot(line)
    line.retired = retired
    line.version += 1
    line.human_edited = True
    line.status = "needs_review"
    line.selected_candidate_id = None
    line.delivery_json = {
        key: value
        for key, value in line.delivery_json.items()
        if key
        not in {
            "applied_alignment_artifact_id",
            "applied_dialogue_adaptation_artifact_id",
            "applied_dialogue_adaptation_kind",
        }
    }
    session.add(
        SegmentEdit(
            segment_id=line.id,
            version=line.version,
            before_json=before,
            after_json={**snapshot(line), "structure_edit_id": operation.id},
        )
    )


def reindex(session, operation, new_ids):
    session.flush()
    for index, line in enumerate(
        revision_segments(session, operation.project_id, operation.revision_id)
    ):
        if line.index == index:
            continue
        before = snapshot(line)
        line.index = index
        if line.id not in new_ids:
            line.version += 1
            session.add(
                SegmentEdit(
                    segment_id=line.id,
                    version=line.version,
                    before_json=before,
                    after_json={**snapshot(line), "structure_edit_id": operation.id},
                )
            )
    session.flush()


def replacement(session, operation, original, start, end, text):
    line = Segment(
        project_id=original.project_id,
        revision_id=original.revision_id,
        speaker_id=original.speaker_id,
        index=original.index,
        start_ms=start,
        end_ms=end,
        source_text=text.source_text,
        translated_text=text.translated_text,
        status="needs_review",
        human_edited=True,
        warnings_json=["Manual structure edit; review wording, speaker and timing"]
        + (["Speaker unassigned; review this line"] if not original.speaker_id else []),
        delivery_json={"structure_edit_id": operation.id},
    )
    session.add(line)
    session.flush()
    return line


def perform_structure(session, line_id, payload, *, merge=False):
    original = session.get(Segment, line_id)
    if not original:
        raise HTTPException(404, "Line not found")
    project, revision = guard_revision(session, original.project_id, payload.revision_id)
    original = require_line(session, line_id, revision.id, payload.expected_version)
    check_speaker(session, original)
    if not payload.replacement_confirmed:
        raise HTTPException(
            422, "Confirm replacing saved lines and clearing their voice selections"
        )
    lines = revision_segments(session, project.id, revision.id)
    originals = [original]
    if merge:
        other = require_line(
            session, payload.next_segment_id, revision.id, payload.expected_next_version
        )
        position = next(index for index, line in enumerate(lines) if line.id == original.id)
        if position + 1 >= len(lines) or lines[position + 1].id != other.id:
            raise HTTPException(422, "Merge only with the next line in the current timeline")
        if original.speaker_id != other.speaker_id:
            raise HTTPException(422, "Correct both lines to the same speaker before merging")
        originals.append(other)
        parts = [
            (
                min(original.start_ms, other.start_ms),
                max(original.end_ms, other.end_ms),
                payload.text,
            )
        ]
    else:
        if len(lines) >= 500:
            raise HTTPException(422, "This short-scene editor supports at most 500 active lines")
        if not original.start_ms < payload.split_ms < original.end_ms:
            raise HTTPException(422, "Split time must be strictly inside the original window")
        parts = [
            (original.start_ms, payload.split_ms, payload.first),
            (payload.split_ms, original.end_ms, payload.second),
        ]
    limit = source_limit(session, project, revision)
    if any(not 0 <= start < end <= limit for start, end, _ in parts):
        raise HTTPException(422, "New line timing exceeds the current source scene")
    operation = TimelineStructureEdit(
        project_id=project.id,
        revision_id=revision.id,
        action="merge" if merge else "split",
        before_json=[snapshot(line) for line in originals],
        after_json=[],
    )
    session.add(operation)
    session.flush()
    for line in originals:
        change_activity(session, line, True, operation)
    created = [
        replacement(session, operation, original, start, end, text) for start, end, text in parts
    ]
    reindex(session, operation, {line.id for line in created})
    operation.after_json = [snapshot(line) for line in created]
    session.commit()
    return structure_read(session, operation)


def restore_reason(session, operation):
    project = session.get(Project, operation.project_id)
    if not project or project.active_revision_id != operation.revision_id:
        return "Activate this timeline before reversing this structural edit"
    for retired, snapshots in [(True, operation.before_json), (False, operation.after_json)]:
        for saved in snapshots:
            line = session.get(Segment, saved["id"])
            expected_version = saved["version"] + (1 if retired else 0)
            if (
                not line
                or line.retired != retired
                or line.version != expected_version
                or line.revision_id != operation.revision_id
                or content(snapshot(line)) != content(saved)
            ):
                return "Affected lines changed or were replaced; reversal will not overwrite them"
    if session.scalar(
        select(Job.id).where(
            Job.project_id == operation.project_id,
            Job.status.in_(ACTIVE),
        )
    ):
        return "Wait for active processing before reversing structure"
    return None


def structure_read(session, operation):
    reason = restore_reason(session, operation)
    return TimelineStructureEditRead(
        id=operation.id,
        revision_id=operation.revision_id,
        action=operation.action,
        parent_edit_id=operation.parent_edit_id,
        before=operation.before_json,
        after=operation.after_json,
        created_at=operation.created_at,
        restorable=reason is None,
        unavailable_reason=reason,
    )


def restore_structure(session, operation, payload):
    guard_revision(session, operation.project_id, payload.revision_id)
    if operation.revision_id != payload.revision_id:
        raise HTTPException(422, "Structural edit belongs to another timeline")
    if not payload.restoration_confirmed:
        raise HTTPException(422, "Confirm reversal requires review again and clears affected takes")
    reason = restore_reason(session, operation)
    if reason:
        raise HTTPException(409, reason)
    ids = {saved["id"] for saved in [*operation.before_json, *operation.after_json]}
    affected = {identifier: session.get(Segment, identifier) for identifier in ids}
    if payload.expected_versions != {key: line.version for key, line in affected.items()}:
        raise HTTPException(409, "Structural history changed; refresh before reversing")
    revived = [affected[saved["id"]] for saved in operation.before_json]
    remaining = len(revision_segments(session, operation.project_id, operation.revision_id))
    if remaining - len(operation.after_json) + len(revived) > 500:
        raise HTTPException(422, "Reversal would exceed the 500-line limit")
    project = session.get(Project, operation.project_id)
    revision = session.get(TimelineRevision, operation.revision_id)
    limit = source_limit(session, project, revision)
    for line in revived:
        check_speaker(session, line)
        if not 0 <= line.start_ms < line.end_ms <= limit:
            raise HTTPException(422, "Historical timing exceeds the current source scene")
    current = [affected[saved["id"]] for saved in operation.after_json]
    reverse = TimelineStructureEdit(
        project_id=operation.project_id,
        revision_id=operation.revision_id,
        action="restore",
        parent_edit_id=operation.id,
        before_json=[snapshot(line) for line in current],
        after_json=[],
    )
    session.add(reverse)
    session.flush()
    for line in current:
        change_activity(session, line, True, reverse)
    for line in revived:
        change_activity(session, line, False, reverse)
    reindex(session, reverse, {line.id for line in revived})
    reverse.after_json = [snapshot(line) for line in revived]
    session.commit()
    return structure_read(session, reverse)
