"""Shared timeline edit validation and immutable before/after evidence."""

from fastapi import HTTPException
from sqlalchemy import update

from .models import MediaAsset, Segment, SegmentEdit, Speaker, TimelineRevision
from .schemas import SegmentRead, SegmentUpdate


def apply_line_edit(
    session, segment, payload: SegmentUpdate, *, history_metadata=None, commit=True
):
    if segment.retired:
        raise HTTPException(
            409, "This line was replaced by a structural edit; use current dialogue"
        )
    if segment.version != payload.expected_version:
        raise HTTPException(409, "Segment changed; refresh before saving")
    values = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    for field in ("source_text", "translated_text", "start_ms", "end_ms", "status"):
        if field in values and values[field] is None:
            raise HTTPException(422, f"{field} cannot be null")
    if "source_text" in values and not values["source_text"].strip():
        raise HTTPException(422, "English dialogue must not be blank")
    if values.get("speaker_id"):
        speaker = session.get(Speaker, values["speaker_id"])
        if (
            not speaker
            or speaker.project_id != segment.project_id
            or speaker.revision_id != segment.revision_id
        ):
            raise HTTPException(422, "Speaker does not belong to this project")
    start = values.get("start_ms", segment.start_ms)
    end = values.get("end_ms", segment.end_ms)
    revision = session.get(TimelineRevision, segment.revision_id) if segment.revision_id else None
    source = (
        session.get(MediaAsset, revision.source_asset_id)
        if revision and revision.source_asset_id
        else None
    )
    if end <= start or (source and end > source.duration_ms):
        raise HTTPException(422, "Line timing must satisfy 0 ≤ start < end ≤ scene duration")
    changed = any(
        values.get(field, getattr(segment, field)) != getattr(segment, field)
        for field in ("source_text", "translated_text", "speaker_id", "start_ms", "end_ms")
    )
    if changed:
        values.update(human_edited=True, status="needs_review", selected_candidate_id=None)
        # Restoring content is a new manual decision, not reapplying earlier AI evidence.
        if history_metadata:
            values["delivery_json"] = {
                key: value
                for key, value in segment.delivery_json.items()
                if key
                not in {
                    "applied_alignment_artifact_id",
                    "applied_dialogue_adaptation_artifact_id",
                    "applied_dialogue_adaptation_kind",
                }
            }
    if "speaker_id" in values:
        values["warnings_json"] = [
            warning
            for warning in segment.warnings_json
            if warning != "Speaker unassigned; review this line"
        ]
        if values["speaker_id"] is None:
            values["warnings_json"].append("Speaker unassigned; review this line")
    if (
        values.get("status") == "approved"
        and not values.get("translated_text", segment.translated_text).strip()
    ):
        raise HTTPException(422, "Add a Malayalam translation before approving this line")
    before = SegmentRead.model_validate(segment).model_dump(mode="json")
    result = session.execute(
        update(Segment)
        .where(Segment.id == segment.id, Segment.version == payload.expected_version)
        .values(**values, version=payload.expected_version + 1)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "Segment changed; refresh before saving")
    session.refresh(segment)
    session.add(
        SegmentEdit(
            segment_id=segment.id,
            version=segment.version,
            before_json=before,
            after_json={
                **SegmentRead.model_validate(segment).model_dump(mode="json"),
                **(history_metadata or {}),
            },
        )
    )
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(segment)
    return segment
