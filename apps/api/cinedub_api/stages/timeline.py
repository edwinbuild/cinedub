"""Preparation for revision-bound stages: translation, voices, subtitles and mixes."""

import shutil

from fastapi import HTTPException

from ..consent import (
    approved_consent,
    artifact_block_reason,
    profile_is_selected,
    validate_voice_use,
)
from ..mixes import freeze_background
from ..models import Artifact, Speaker, TimelineRevision, VoiceProfile
from ..timeline import revision_segments
from ..voices import candidate_signature, stock_variation
from .preparation import Preparation


def mix_disk_space(prep: Preparation) -> None:
    if shutil.disk_usage(prep.settings.storage_root).free < 2 * 1024**3:
        raise HTTPException(422, "Keep at least 2 GiB free for mix/export intermediates")


def _voice(prep: Preparation, line) -> dict:
    session, settings, provider = prep.session, prep.settings, prep.provider
    speaker = session.get(Speaker, line.speaker_id) if line.speaker_id else None
    profile = (
        session.get(VoiceProfile, speaker.voice_profile_id)
        if speaker and speaker.voice_profile_id
        else None
    )
    try:
        validate_voice_use(session, profile)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if profile.provider != provider:
        raise HTTPException(
            422, "Selected voice belongs to another provider; choose a matching voice"
        )
    voice = {
        "profile_id": profile.id,
        "profile_version": profile.version,
        "voice_id": profile.provider_voice_id,
        "voice_kind": profile.voice_kind,
        "pace": profile.settings_json.get("pace", 1.0),
        "provider": provider,
        "consent_record_id": approved_consent(session, profile).id
        if profile.voice_kind == "clone"
        else None,
        "model": "sarvam-voice-cloning-beta"
        if profile.voice_kind == "clone" and provider == "sarvam"
        else settings.synthesis_model
        if provider == "sarvam"
        else "deterministic-fixture-v1",
    }
    if provider == "sarvam" and profile.voice_kind == "preset":
        try:
            voice["variation"] = stock_variation(profile.settings_json.get("variation", 0.6))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return voice


def _selected_take(prep: Preparation, line) -> str:
    session = prep.session
    artifact = (
        session.get(Artifact, line.selected_candidate_id) if line.selected_candidate_id else None
    )
    if (
        not artifact
        or artifact.kind != "dialogue_candidate"
        or artifact.metadata_json.get("fit_status") != "ready"
    ):
        raise HTTPException(422, "Select a timing-ready audio candidate for every line")
    voice = artifact.metadata_json["voice"]
    profile = session.get(VoiceProfile, voice["profile_id"])
    material = {
        field: getattr(line, field)
        for field in ("source_text", "translated_text", "start_ms", "end_ms", "speaker_id")
    }
    if (
        not profile
        or profile.version != voice["profile_version"]
        or not profile_is_selected(session, profile)
        or artifact.metadata_json["signature"] != candidate_signature(material, voice)
    ):
        raise HTTPException(409, "Selected audio is stale; regenerate it before rendering")
    if artifact_block_reason(session, artifact):
        raise HTTPException(422, "Selected audio has revoked cloning consent")
    return artifact.id


def revision_inputs(prep: Preparation) -> None:
    session, project, payload, settings = prep.session, prep.project, prep.payload, prep.settings
    stage, provider, inputs = prep.spec.stage, prep.provider, prep.inputs
    revision_id = payload.revision_id or project.active_revision_id
    revision = session.get(TimelineRevision, revision_id) if revision_id else None
    if not revision or revision.project_id != project.id:
        raise HTTPException(422, "Select a timeline revision first")
    inputs["revision_id"] = revision.id
    inputs["source_asset_id"] = revision.source_asset_id
    segments = revision_segments(session, project.id, revision.id)
    if not segments:
        raise HTTPException(422, "This timeline has no speech to process")
    if payload.segment_ids is not None:
        if stage == "render_mix":
            raise HTTPException(422, "Retained-background exports require the complete timeline")
        ids = set(payload.segment_ids)
        if not ids or not ids.issubset({line.id for line in segments}):
            raise HTTPException(422, "Selected lines do not belong to this revision")
        segments = [line for line in segments if line.id in ids]
    if payload.regenerate and not payload.segment_ids:
        raise HTTPException(422, "Regeneration requires explicitly selected lines")
    if stage == "translate":
        segments = [
            line
            for line in segments
            if payload.regenerate
            or (
                line.status != "approved"
                and (not line.human_edited or not line.translated_text.strip())
                and line.delivery_json.get("translation_source") != line.source_text
            )
        ]
        inputs.update(
            {
                "model": settings.translation_model,
                "style": settings.translation_style,
                "unit_rate_inr": settings.translation_inr_per_10k_chars,
            }
        )
        if provider == "sarvam":
            # Up to three attempts are reserved. Only submitted attempts consume the estimate.
            prep.cost = (
                sum(len(line.source_text) for line in segments)
                / 10_000
                * settings.translation_inr_per_10k_chars
                * 3
            )
    if stage in {"synthesize", "render_preview", "render_mix"}:
        if any(line.status != "approved" or not line.translated_text.strip() for line in segments):
            raise HTTPException(
                422, "Approve translated dialogue before voice generation or rendering"
            )
        if stage == "synthesize":
            voices = {line.id: _voice(prep, line) for line in segments}
            models = {voice["model"] for voice in voices.values()}
            inputs.update(
                {
                    "model": next(iter(models)) if len(models) == 1 else "mixed-voice-models",
                    "models": sorted(models),
                    "voices": voices,
                    "unit_rate_inr": settings.synthesis_inr_per_10k_chars,
                    "max_timing_speedup": settings.max_timing_speedup,
                }
            )
            if provider == "sarvam":
                prep.cost = (
                    sum(len(line.translated_text) for line in segments)
                    / 10_000
                    * settings.synthesis_inr_per_10k_chars
                    * 3
                )
        else:
            candidates = {line.id: _selected_take(prep, line) for line in segments}
            if not revision.source_asset_id:
                raise HTTPException(422, "A source scene is required to render a preview")
            inputs["candidates"] = candidates
            if stage == "render_mix":
                inputs["candidate_hashes"] = {
                    key: session.get(Artifact, value).metadata_json.get("sha256")
                    for key, value in candidates.items()
                }
                if payload.allow_incomplete:
                    raise HTTPException(422, "Review and select every line before mix export")
                try:
                    inputs.update(
                        freeze_background(session, project, revision, payload.mix_settings)
                    )
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
    if (
        stage == "export"
        and any(not line.translated_text.strip() for line in segments)
        and not payload.allow_incomplete
    ):
        raise HTTPException(
            422, "Some lines have no Malayalam translation; confirm incomplete export"
        )
    inputs["segments"] = [
        {
            "id": line.id,
            "version": line.version,
            "source_text": line.source_text,
            "translated_text": line.translated_text,
            "start_ms": line.start_ms,
            "end_ms": line.end_ms,
            "speaker_id": line.speaker_id,
        }
        for line in segments
    ]
