"""Review-export input contracts and current-versus-historical lineage checks."""

from pathlib import Path

from sqlalchemy import select

from .consent import artifact_block_reason, profile_is_selected
from .media import audio_offset_ms
from .models import Artifact, Job, MediaAsset, Project, Segment, StemSet, VoiceProfile
from .schemas import MixRenderRead
from .voices import candidate_signature


def freeze_background(session, project, revision, settings):
    if revision.id != project.active_revision_id:
        raise ValueError("Activate this timeline before rendering a retained-background mix")
    source = session.get(MediaAsset, revision.source_asset_id)
    stems = (
        session.get(StemSet, source.active_stem_set_id)
        if source and source.active_stem_set_id
        else None
    )
    if not stems or stems.status != "approved" or stems.source_asset_id != source.id:
        raise ValueError("Approve and select music/effects stems for this timeline source first")
    if (
        audio_offset_ms(source.metadata_json)
        and stems.metadata_json.get("timeline_mapping_version") != 2
    ):
        raise ValueError("Separate this offset audio track again with current timeline mapping")
    background = {}
    for name in ("music", "effects"):
        artifact = session.get(Artifact, stems.artifacts_json.get(name, {}).get("master"))
        if not artifact or artifact.kind != "stem_master" or not Path(artifact.path).is_file():
            raise ValueError("Reviewed background master is unavailable")
        if (
            artifact.project_id != project.id
            or artifact.metadata_json.get("stem_set_id") != stems.id
        ):
            raise ValueError("Background provenance does not match the reviewed source")
        if not artifact.metadata_json.get("sha256"):
            raise ValueError("Background checksum is unavailable; separate the source again")
        background[name] = {"artifact_id": artifact.id, "sha256": artifact.metadata_json["sha256"]}
    return {
        "mix_settings": settings.model_dump(),
        "stem_set_id": stems.id,
        "stem_set_version": stems.version,
        "background": background,
        "source_sha256": source.metadata_json.get("sha256"),
        "duration_ms": source.duration_ms,
        "stem_model": stems.model,
        "stem_provider": stems.provider,
    }


def validate_mix_snapshot(session, inputs):
    """No filesystem hashing here: safe for polling. Worker/acceptance verify media bytes."""
    source = session.get(MediaAsset, inputs["source_asset_id"])
    project = session.get(Project, source.project_id) if source else None
    stems = session.get(StemSet, inputs["stem_set_id"])
    if not project or project.active_revision_id != inputs["revision_id"]:
        raise ValueError("Active timeline changed; this render is historical")
    current_ids = set(
        session.scalars(
            select(Segment.id).where(
                Segment.project_id == project.id, Segment.revision_id == inputs["revision_id"]
            )
        )
    )
    if current_ids != {line["id"] for line in inputs["segments"]}:
        raise ValueError("Timeline lines changed; render the complete current timeline again")
    if (
        not stems
        or stems.status != "approved"
        or stems.version != inputs["stem_set_version"]
        or source.active_stem_set_id != stems.id
        or stems.source_asset_id != source.id
    ):
        raise ValueError("Reviewed background choice changed; render again")
    for snapshot in inputs["segments"]:
        line = session.get(Segment, snapshot["id"])
        if (
            not line
            or line.version != snapshot["version"]
            or line.status != "approved"
            or line.selected_candidate_id != inputs["candidates"][line.id]
        ):
            raise ValueError("Dialogue, timing, approval or selected takes changed; render again")
        candidate = session.get(Artifact, line.selected_candidate_id)
        if not candidate or artifact_block_reason(session, candidate):
            raise ValueError("Selected voice provenance/consent is unavailable or revoked")
        voice = candidate.metadata_json["voice"]
        profile = session.get(VoiceProfile, voice["profile_id"])
        if (
            not profile
            or profile.version != voice["profile_version"]
            or not profile_is_selected(session, profile)
            or candidate.metadata_json["signature"] != candidate_signature(snapshot, voice)
        ):
            raise ValueError("Selected voice changed; regenerate affected takes and render again")


def mix_read(session, mix):
    value = MixRenderRead.model_validate(mix)
    job = session.get(Job, mix.job_id)
    try:
        if not job:
            raise ValueError("Render lineage is unavailable")
        validate_mix_snapshot(session, job.input_json)
    except ValueError as exc:
        value.stale_reason = str(exc)
    return value
