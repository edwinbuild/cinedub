"""Immutable job inputs, reuse and estimated-budget reservations."""

import hashlib
import json
import shutil

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .adaptation_timing import freeze_timing_feedback
from .alignment import freeze_alignment_audio
from .config import get_settings
from .consent import (
    approved_consent,
    artifact_block_reason,
    profile_is_selected,
    validate_voice_use,
)
from .dialogue_prompt import GENERATION, PROMPT_VERSION
from .dialogue_review import freeze_dialogue_review
from .local_asr_profile import build_profile
from .mixes import freeze_background
from .models import (
    Artifact,
    Job,
    MediaAsset,
    Project,
    Speaker,
    StemSet,
    TimelineRevision,
    VoiceProfile,
)
from .providers import ProviderRegistry
from .providers.local_alignment import MODEL_NAME as ALIGNMENT_MODEL
from .providers.local_alignment import availability as alignment_availability
from .providers.local_alignment import read_manifest as alignment_manifest
from .providers.local_asr import MODEL_NAME, availability, read_manifest
from .providers.local_dialogue import MODEL_NAME as DIALOGUE_MODEL
from .providers.local_dialogue import availability as dialogue_availability
from .providers.local_dialogue import read_manifest as dialogue_manifest
from .providers.local_emotion import MODEL_NAME as EMOTION_MODEL
from .providers.local_emotion import PROFILE as EMOTION_PROFILE
from .providers.local_emotion import availability as emotion_availability
from .providers.local_emotion import read_manifest as emotion_manifest
from .providers.local_separation import MODEL_NAME as SEPARATOR_MODEL
from .providers.local_separation import availability as separator_availability
from .providers.local_separation import read_manifest as separator_manifest
from .providers.local_take_analysis import availability as take_analyzer_available
from .providers.local_target_alignment import MODEL_NAME as TARGET_ALIGNMENT_MODEL
from .providers.local_target_alignment import availability as target_aligner_available
from .providers.local_target_alignment import read_manifest as target_aligner_manifest
from .schemas import JobCreate, JobEstimate
from .speech_emotion import freeze_emotion
from .take_analysis import freeze_take_analysis
from .timeline import revision_segments
from .voices import candidate_signature

ACTIVE = ("queued", "running")


def write_lock(session: Session) -> None:
    if session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))


def budget_totals(session: Session, project_id: str) -> tuple[float, float]:
    jobs = session.scalars(select(Job).where(Job.project_id == project_id)).all()
    spent = sum(job.charged_estimate_inr for job in jobs)
    reserved = sum(
        max(0, job.estimated_cost_inr - job.charged_estimate_inr)
        for job in jobs
        if job.status in ACTIVE
    )
    return round(spent, 6), round(reserved, 6)


def prepare_job(session: Session, project: Project, payload: JobCreate) -> tuple[str, dict, float]:
    settings = get_settings()
    defaults = {
        "ingest": "local",
        "demo_pipeline": "fake",
        "transcribe": settings.transcriber,
        "translate": settings.translator,
        "synthesize": settings.voice_synthesizer,
        "export": "local",
        "render_preview": "local",
        "render_mix": "local",
        "prepare_reference": "local",
        "register_voice": settings.voice_synthesizer,
        "delete_voice": settings.voice_synthesizer,
        "separate": settings.stem_separator,
        "align": settings.timing_aligner,
        "analyze_takes": settings.performance_analyzer,
        "review_translation": "local",
        "adapt_dialogue": settings.dialogue_adapter,
        "analyze_emotion": settings.emotion_analyzer,
    }
    provider = payload.provider or defaults[payload.stage]
    if payload.stage in {"transcribe", "translate", "synthesize", "register_voice", "delete_voice"}:
        name = {
            "transcribe": "transcriber",
            "translate": "translator",
            "synthesize": "voice_synthesizer",
            "register_voice": "voice_cloner",
            "delete_voice": "voice_cloner",
        }[payload.stage]
        capability = (
            next(
                item
                for item in ProviderRegistry(settings).capabilities()
                if item.capability == name and item.selected_provider == provider
            )
            if provider == defaults[payload.stage]
            else None
        )
        allowed = (
            {"fake", "sarvam", "local"} if payload.stage == "transcribe" else {"fake", "sarvam"}
        )
        if provider not in allowed:
            raise HTTPException(422, "This provider adapter is not implemented")
        if provider == "sarvam" and not settings.sarvam_api_key:
            raise HTTPException(422, "Configure SARVAM_API_KEY locally before using Sarvam")
        if capability and not capability.available:
            raise HTTPException(422, capability.reason)
        if provider == "local":
            ready, reason = availability(settings.local_asr_model_dir)
            if not ready:
                raise HTTPException(422, reason)
            if project.source_language != "en-IN":
                raise HTTPException(422, "The installed small.en model supports English input only")
            if payload.num_speakers is not None:
                raise HTTPException(422, "Local ASR has no diarization; assign speakers manually")
    elif provider != defaults[payload.stage]:
        raise HTTPException(422, "Provider is incompatible with this stage")
    inputs = payload.model_dump(exclude={"provider", "force_new"})
    if payload.stage != "analyze_takes":
        if (
            payload.candidate_ids is not None and payload.stage != "adapt_dialogue"
        ) or payload.include_target_alignment:
            raise HTTPException(422, "Take-analysis options require the analyze_takes stage")
        # Preserve existing paid-job fingerprints when adding independent review options.
        inputs.pop("candidate_ids")
        inputs.pop("include_target_alignment")
    inputs.update(
        {"source_language": project.source_language, "target_language": project.target_language}
    )
    cost = 0.0
    if payload.stage == "analyze_emotion":
        if provider != "local":
            raise HTTPException(422, "This speech-emotion adapter is not implemented")
        ready, reason = emotion_availability(settings.local_emotion_model_dir)
        if not ready:
            raise HTTPException(422, reason)
        try:
            inputs.update(freeze_emotion(session, project, payload))
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        inputs.update(
            {
                "model": EMOTION_MODEL,
                "profile": EMOTION_PROFILE,
                "model_manifest": emotion_manifest(settings.local_emotion_model_dir),
                "model_dir": str(settings.local_emotion_model_dir.resolve()),
                "threads": settings.local_emotion_threads,
                "timeout_seconds": settings.local_emotion_timeout_seconds,
            }
        )
    if payload.stage in {"review_translation", "adapt_dialogue"}:
        try:
            inputs.update(freeze_dialogue_review(session, project, payload))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if payload.stage == "adapt_dialogue":
            if provider != "local":
                raise HTTPException(422, "This dialogue adapter is not implemented")
            ready, reason = dialogue_availability(settings.local_dialogue_model_dir)
            if not ready:
                raise HTTPException(422, reason)
            if project.source_language != "en-IN" or project.target_language != "ml-IN":
                raise HTTPException(422, "This experimental profile supports English to Malayalam")
            try:
                feedback = freeze_timing_feedback(session, project, inputs, payload.candidate_ids)
            except (OSError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
            if feedback:
                inputs["timing_feedback"] = feedback
                inputs["voices"] = {key: value["voice"] for key, value in feedback.items()}
            inputs.update(
                {
                    "model": DIALOGUE_MODEL,
                    "model_manifest": dialogue_manifest(settings.local_dialogue_model_dir),
                    "model_dir": str(settings.local_dialogue_model_dir.resolve()),
                    "threads": settings.local_dialogue_threads,
                    "timeout_seconds": settings.local_dialogue_timeout_seconds,
                    "adaptation_provider": provider,
                    "prompt_version": PROMPT_VERSION,
                    "generation_parameters": GENERATION,
                }
            )
    if payload.stage == "analyze_takes":
        if provider != "local" or not take_analyzer_available():
            raise HTTPException(422, "Install the optional local acoustic analysis adapter")
        try:
            inputs.update(freeze_take_analysis(session, project, payload))
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        inputs.update(
            {
                "model": "acoustic-dsp-v1",
                "threads": settings.local_aligner_threads,
                "timeout_seconds": settings.local_take_analyzer_timeout_seconds,
            }
        )
        if payload.include_target_alignment:
            if settings.target_timing_aligner != "local" or project.target_language != "ml-IN":
                raise HTTPException(422, "This target-language alignment adapter is not installed")
            ready, reason = target_aligner_available(settings.local_target_aligner_model_dir)
            if not ready:
                raise HTTPException(422, reason)
            inputs.update(
                {
                    "target_alignment_model": TARGET_ALIGNMENT_MODEL,
                    "target_model_dir": str(settings.local_target_aligner_model_dir.resolve()),
                    "target_model_manifest": target_aligner_manifest(
                        settings.local_target_aligner_model_dir
                    ),
                }
            )
    if payload.stage == "align":
        if provider != "local":
            raise HTTPException(422, "This alignment adapter is not installed")
        if settings.performance_analyzer != "local":
            raise HTTPException(
                422, "This combined source-analysis job requires the local acoustic adapter"
            )
        ready, reason = alignment_availability(settings.local_aligner_model_dir)
        if not ready:
            raise HTTPException(422, reason)
        if project.source_language != "en-IN":
            raise HTTPException(422, "The installed aligner supports English source audio only")
        revision_id = payload.revision_id or project.active_revision_id
        try:
            inputs.update(
                freeze_alignment_audio(session, project, revision_id, payload.transcription_input)
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        if payload.source_asset_id and payload.source_asset_id != inputs["source_asset_id"]:
            raise HTTPException(422, "Selected source does not match the transcript revision")
        segments = revision_segments(session, project.id, revision_id)
        if payload.segment_ids is not None:
            ids = set(payload.segment_ids)
            if not ids or not ids.issubset({line.id for line in segments}):
                raise HTTPException(422, "Selected lines do not belong to this revision")
            segments = [line for line in segments if line.id in ids]
        if not segments or len(segments) > 500:
            raise HTTPException(422, "Alignment requires 1–500 saved dialogue lines")
        inputs.update(
            {
                "project_id": project.id,
                "performance_provider": settings.performance_analyzer,
                "performance_model": "acoustic-dsp-v1",
                "model": ALIGNMENT_MODEL,
                "model_dir": str(settings.local_aligner_model_dir.resolve()),
                "model_manifest": alignment_manifest(settings.local_aligner_model_dir),
                "threads": settings.local_aligner_threads,
                "timeout_seconds": settings.local_aligner_timeout_seconds,
                "segments": [
                    {
                        "id": line.id,
                        "version": line.version,
                        "source_text": line.source_text,
                        "start_ms": line.start_ms,
                        "end_ms": line.end_ms,
                        "speaker_id": line.speaker_id,
                    }
                    for line in segments
                ],
            }
        )
    if payload.stage == "separate":
        if provider != "local":
            raise HTTPException(422, "This separator adapter is not installed")
        ready, reason = separator_availability(settings.local_separator_model_dir)
        if not ready:
            raise HTTPException(422, reason)
        if shutil.disk_usage(settings.storage_root).free < 2 * 1024**3:
            raise HTTPException(422, "Keep at least 2 GiB free for local separation outputs")
        inputs.update(
            {
                "model": SEPARATOR_MODEL,
                "model_dir": str(settings.local_separator_model_dir.resolve()),
                "model_manifest": separator_manifest(settings.local_separator_model_dir),
                "threads": settings.local_separator_threads,
                "timeout_seconds": settings.local_separator_timeout_seconds,
            }
        )
    if (
        payload.stage == "render_mix"
        and shutil.disk_usage(settings.storage_root).free < 2 * 1024**3
    ):
        raise HTTPException(422, "Keep at least 2 GiB free for mix/export intermediates")
    if payload.stage in {"prepare_reference", "register_voice", "delete_voice"}:
        profile = (
            session.get(VoiceProfile, payload.voice_profile_id)
            if payload.voice_profile_id
            else None
        )
        if not profile or profile.project_id != project.id or profile.voice_kind != "clone":
            raise HTTPException(422, "Select a cloned-voice profile belonging to this project")
        inputs.update({"voice_profile_id": profile.id, "profile_version": profile.version})
        if payload.stage != "delete_voice":
            try:
                consent = approved_consent(session, profile)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            inputs["consent_record_id"] = consent.id
        if payload.stage == "prepare_reference":
            inputs.update(
                {
                    "source_asset_id": profile.reference_asset_id,
                    "start_ms": profile.settings_json["reference_start_ms"],
                    "end_ms": profile.settings_json["reference_end_ms"],
                }
            )
        else:
            if provider != profile.provider:
                raise HTTPException(422, "Use the provider recorded on this cloned-voice profile")
            if payload.stage == "register_voice":
                if not payload.reference_reviewed:
                    raise HTTPException(
                        422, "Listen to and explicitly review the prepared reference before upload"
                    )
                if profile.registration_status == "ready" or profile.provider_voice_id:
                    raise HTTPException(422, "This voice is already registered; select it instead")
                uncertain = any(
                    prior.input_json.get("voice_profile_id") == profile.id
                    and prior.checkpoint_json.get("pending_registration")
                    and not prior.checkpoint_json.get("registration_result")
                    for prior in session.scalars(
                        select(Job).where(
                            Job.project_id == project.id,
                            Job.stage == "register_voice",
                            Job.status == "failed",
                        )
                    ).all()
                )
                if uncertain and not payload.force_new:
                    raise HTTPException(
                        409,
                        "Earlier upload outcome is unknown; inspect provider voices/usage "
                        "before explicitly retrying",
                    )
                reference = (
                    session.get(Artifact, profile.reference_artifact_id)
                    if profile.reference_artifact_id
                    else None
                )
                if not reference:
                    raise HTTPException(422, "Prepare and listen to the reference clip first")
                inputs.update(
                    {
                        "reference_artifact_id": reference.id,
                        "reference_sha256": reference.metadata_json["sha256"],
                        "reference_language": profile.settings_json["reference_language"],
                        "display_name": profile.display_name,
                    }
                )
                if provider == "sarvam":
                    if payload.registration_allowance_inr is None:
                        raise HTTPException(
                            422,
                            "Set a registration allowance; its exact provider tariff is unverified",
                        )
                    cost = payload.registration_allowance_inr
            else:
                if profile.consent_status != "revoked" or not profile.provider_voice_id:
                    raise HTTPException(
                        422, "Revoke local consent first; a known saved voice is required"
                    )
                inputs["voice_id"] = profile.provider_voice_id
    if payload.stage in {"ingest", "transcribe", "separate"}:
        source = (
            session.get(MediaAsset, payload.source_asset_id) if payload.source_asset_id else None
        )
        if not source or source.project_id != project.id:
            raise HTTPException(422, "Select a source asset belonging to this project")
        if not source.duration_ms:
            raise HTTPException(422, "Source duration is unavailable")
        inputs["source_asset_id"] = source.id
        inputs["source_sha256"] = source.metadata_json.get("sha256")
        if payload.stage != "separate":
            inputs["model"] = settings.transcription_model
        inputs["unit_rate_inr"] = settings.stt_diarization_inr_per_hour
        if provider == "local" and payload.stage == "transcribe":
            inputs.update(
                {
                    "model": MODEL_NAME,
                    "local_model_dir": str(settings.local_asr_model_dir.resolve()),
                    "local_model_manifest": read_manifest(settings.local_asr_model_dir),
                    "asr_profile": build_profile(settings.local_asr_threads),
                    "threads": settings.local_asr_threads,
                    "timeout_seconds": settings.local_asr_timeout_seconds,
                    "unit_rate_inr": 0,
                }
            )
        if payload.stage == "transcribe":
            if payload.transcription_input == "dialogue_stem":
                stems = (
                    session.get(StemSet, source.active_stem_set_id)
                    if source.active_stem_set_id
                    else None
                )
                if not stems or stems.source_asset_id != source.id or stems.status != "approved":
                    raise HTTPException(
                        422, "Approve and select dialogue stems for this source first"
                    )
                inputs.update(
                    {
                        "stem_set_id": stems.id,
                        "stem_set_version": stems.version,
                        "recognition_artifact_id": stems.artifacts_json["recognition_audio"],
                    }
                )
            else:
                audio = next(
                    (
                        item
                        for item in session.scalars(
                            select(Artifact)
                            .where(
                                Artifact.project_id == project.id,
                                Artifact.kind == "recognition_audio",
                            )
                            .order_by(Artifact.created_at.desc())
                        ).all()
                        if item.metadata_json.get("source_asset_id") == source.id
                    ),
                    None,
                )
                if not audio:
                    raise HTTPException(422, "Prepare source media before starting transcription")
                inputs["recognition_artifact_id"] = audio.id
        if provider == "sarvam":
            cost = source.duration_ms / 3_600_000 * settings.stt_diarization_inr_per_hour
    if payload.stage in {"translate", "synthesize", "export", "render_preview", "render_mix"}:
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
            if payload.stage == "render_mix":
                raise HTTPException(
                    422, "Retained-background exports require the complete timeline"
                )
            ids = set(payload.segment_ids)
            if not ids or not ids.issubset({line.id for line in segments}):
                raise HTTPException(422, "Selected lines do not belong to this revision")
            segments = [line for line in segments if line.id in ids]
        if payload.regenerate and not payload.segment_ids:
            raise HTTPException(422, "Regeneration requires explicitly selected lines")
        if payload.stage == "translate":
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
                cost = (
                    sum(len(line.source_text) for line in segments)
                    / 10_000
                    * settings.translation_inr_per_10k_chars
                    * 3
                )
        voices = {}
        candidates = {}
        if payload.stage in {"synthesize", "render_preview", "render_mix"}:
            if any(
                line.status != "approved" or not line.translated_text.strip() for line in segments
            ):
                raise HTTPException(
                    422, "Approve translated dialogue before voice generation or rendering"
                )
            for line in segments:
                if payload.stage == "synthesize":
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
                            422,
                            "Selected voice belongs to another provider; choose a matching voice",
                        )
                    voices[line.id] = {
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
                else:
                    artifact = (
                        session.get(Artifact, line.selected_candidate_id)
                        if line.selected_candidate_id
                        else None
                    )
                    if (
                        not artifact
                        or artifact.kind != "dialogue_candidate"
                        or artifact.metadata_json.get("fit_status") != "ready"
                    ):
                        raise HTTPException(
                            422, "Select a timing-ready audio candidate for every line"
                        )
                    voice = artifact.metadata_json["voice"]
                    profile = session.get(VoiceProfile, voice["profile_id"])
                    material = {
                        field: getattr(line, field)
                        for field in (
                            "source_text",
                            "translated_text",
                            "start_ms",
                            "end_ms",
                            "speaker_id",
                        )
                    }
                    if (
                        not profile
                        or profile.version != voice["profile_version"]
                        or not profile_is_selected(session, profile)
                        or artifact.metadata_json["signature"]
                        != candidate_signature(material, voice)
                    ):
                        raise HTTPException(
                            409, "Selected audio is stale; regenerate it before rendering"
                        )
                    if artifact_block_reason(session, artifact):
                        raise HTTPException(422, "Selected audio has revoked cloning consent")
                    candidates[line.id] = artifact.id
            if payload.stage == "synthesize":
                inputs.update(
                    {
                        "model": next(iter({voice["model"] for voice in voices.values()}))
                        if len({voice["model"] for voice in voices.values()}) == 1
                        else "mixed-voice-models",
                        "models": sorted({voice["model"] for voice in voices.values()}),
                        "voices": voices,
                        "unit_rate_inr": settings.synthesis_inr_per_10k_chars,
                        "max_timing_speedup": settings.max_timing_speedup,
                    }
                )
                if provider == "sarvam":
                    cost = (
                        sum(len(line.translated_text) for line in segments)
                        / 10_000
                        * settings.synthesis_inr_per_10k_chars
                        * 3
                    )
            else:
                if not revision.source_asset_id:
                    raise HTTPException(422, "A source scene is required to render a preview")
                inputs["candidates"] = candidates
                if payload.stage == "render_mix":
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
            payload.stage == "export"
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
    identity = {"stage": payload.stage, "provider": provider, "input": inputs}
    inputs["fingerprint"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return provider, inputs, round(cost, 6)


def estimate_job(session: Session, project: Project, payload: JobCreate) -> JobEstimate:
    provider, inputs, cost = prepare_job(session, project, payload)
    spent, reserved = budget_totals(session, project.id)
    cached = next(
        (
            job
            for job in session.scalars(
                select(Job)
                .where(
                    Job.project_id == project.id,
                    Job.stage == payload.stage,
                    Job.provider == provider,
                    Job.status.in_([*ACTIVE, "completed"]),
                )
                .order_by(Job.created_at.desc())
            ).all()
            if job.input_json.get("fingerprint") == inputs["fingerprint"]
            and (job.status in ACTIVE or not payload.force_new)
        ),
        None,
    )
    return JobEstimate(
        estimated_cost_inr=0 if cached else cost,
        spent_estimate_inr=spent,
        reserved_inr=reserved,
        remaining_inr=max(0, project.budget_inr - spent - reserved),
        budget_inr=project.budget_inr,
        cached_job_id=cached.id if cached else None,
    )
