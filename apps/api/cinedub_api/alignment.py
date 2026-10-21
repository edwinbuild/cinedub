"""Source-bound alignment evidence and explicit, revision-safe timing suggestions."""

from pathlib import Path

from sqlalchemy import select

from .media import audio_offset_ms, file_digest
from .models import Artifact, MediaAsset, Project, Segment, StemSet, TimelineRevision
from .schemas import AlignmentReport


def freeze_alignment_audio(session, project, revision_id, transcription_input):
    revision = session.get(TimelineRevision, revision_id) if revision_id else None
    if not revision or revision.project_id != project.id or not revision.source_asset_id:
        raise ValueError("Select a source-bound transcript revision first")
    if revision.id != project.active_revision_id:
        raise ValueError("Activate this timeline before alignment")
    source = session.get(MediaAsset, revision.source_asset_id)
    if not source or not source.duration_ms or not source.metadata_json.get("sha256"):
        raise ValueError("Source duration/checksum is unavailable")
    if source.duration_ms > 120000:
        raise ValueError("Local alignment supports scenes up to two minutes")
    values = {
        "source_asset_id": source.id,
        "source_sha256": source.metadata_json["sha256"],
        "duration_ms": source.duration_ms,
        "revision_id": revision.id,
    }
    if transcription_input == "dialogue_stem":
        stems = (
            session.get(StemSet, source.active_stem_set_id) if source.active_stem_set_id else None
        )
        if not stems or stems.source_asset_id != source.id or stems.status != "approved":
            raise ValueError("Approve and select dialogue stems for this source first")
        values.update(stem_set_id=stems.id, stem_set_version=stems.version)
        audio = session.get(Artifact, stems.artifacts_json.get("recognition_audio"))
        mapping_version = stems.metadata_json.get("timeline_mapping_version")
    else:
        audio = next(
            (
                item
                for item in session.scalars(
                    select(Artifact)
                    .where(Artifact.project_id == project.id, Artifact.kind == "recognition_audio")
                    .order_by(Artifact.created_at.desc())
                ).all()
                if item.metadata_json.get("source_asset_id") == source.id
            ),
            None,
        )
        mapping_version = audio.metadata_json.get("timeline_mapping_version") if audio else None
    if not audio or audio.project_id != project.id or not Path(audio.path).is_file():
        raise ValueError("Prepare the source audio before alignment")
    if transcription_input == "dialogue_stem":
        if (
            audio.kind != "stem_recognition_audio"
            or audio.metadata_json.get("stem_set_id") != stems.id
        ):
            raise ValueError("Dialogue analysis audio provenance does not match the approved stems")
    elif audio.kind != "recognition_audio":
        raise ValueError("Original analysis audio provenance is invalid")
    if audio_offset_ms(source.metadata_json) and mapping_version != 2:
        raise ValueError("Prepare this offset source again with current timeline mapping")
    values.update(recognition_artifact_id=audio.id, recognition_sha256=file_digest(audio.path))
    return values


def validate_alignment_source(session, inputs, *, verify_files=False):
    project = session.get(Project, inputs["project_id"])
    source = session.get(MediaAsset, inputs["source_asset_id"])
    audio = session.get(Artifact, inputs["recognition_artifact_id"])
    revision = session.get(TimelineRevision, inputs["revision_id"])
    if not project or project.active_revision_id != inputs["revision_id"]:
        raise ValueError("Active timeline changed; this alignment is historical")
    if (
        not source
        or source.project_id != project.id
        or source.metadata_json.get("sha256") != inputs["source_sha256"]
        or not audio
        or audio.project_id != project.id
        or audio.metadata_json.get("source_asset_id") != source.id
        or not revision
        or revision.source_asset_id != source.id
        or revision.project_id != project.id
    ):
        raise ValueError("Alignment source provenance changed or is unavailable")
    if inputs.get("stem_set_id"):
        stems = session.get(StemSet, inputs["stem_set_id"])
        if (
            not stems
            or stems.status != "approved"
            or source.active_stem_set_id != stems.id
            or stems.source_asset_id != source.id
            or stems.version != inputs["stem_set_version"]
            or stems.artifacts_json.get("recognition_audio") != audio.id
        ):
            raise ValueError("Reviewed dialogue stem changed; align again")
    if verify_files:
        if file_digest(source.path) != inputs["source_sha256"]:
            raise ValueError("Source media bytes changed; align again")
        if file_digest(audio.path) != inputs["recognition_sha256"]:
            raise ValueError("Analysis audio bytes changed; align again")


def validate_alignment_lines(session, project_id, revision_id, snapshots):
    for snapshot in snapshots:
        line = session.get(Segment, snapshot["id"])
        if (
            not line
            or line.retired
            or line.project_id != project_id
            or line.revision_id != revision_id
            or line.version != snapshot["version"]
            or any(
                getattr(line, field) != snapshot[field]
                for field in ("source_text", "start_ms", "end_ms", "speaker_id")
            )
        ):
            raise ValueError("Dialogue changed during alignment; align the saved lines again")


def read_alignment_report(session, artifact):
    if file_digest(artifact.path) != artifact.metadata_json.get("sha256"):
        raise ValueError("Alignment report checksum changed; align again")
    report = AlignmentReport.model_validate_json(Path(artifact.path).read_text())
    if report.project_id != artifact.project_id or report.revision_id != artifact.metadata_json.get(
        "revision_id"
    ):
        raise ValueError("Alignment report provenance is inconsistent")
    try:
        validate_alignment_source(session, report.model_dump())
    except ValueError as exc:
        report.stale_reason = str(exc)
    for evidence in report.lines:
        line = session.get(Segment, evidence.segment_id)
        if (
            not line
            or line.retired
            or line.project_id != report.project_id
            or line.revision_id != report.revision_id
            or line.version != evidence.segment_version
        ):
            evidence.stale_reason = "Saved line changed; align this line again"
    return report
