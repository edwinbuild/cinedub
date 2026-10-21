"""Preparation for read-only source/take analysis: alignment, take comparison and emotion."""

from fastapi import HTTPException

from ..alignment import freeze_alignment_audio
from ..providers.fake_analysis import EMOTION_MANIFEST
from ..providers.fake_analysis import EMOTION_PROFILE as DEMO_EMOTION_PROFILE
from ..providers.fake_media import DEMO_MODEL
from ..providers.local_alignment import MODEL_NAME as ALIGNMENT_MODEL
from ..providers.local_alignment import availability as alignment_availability
from ..providers.local_alignment import read_manifest as alignment_manifest
from ..providers.local_emotion import MODEL_NAME as EMOTION_MODEL
from ..providers.local_emotion import PROFILE as EMOTION_PROFILE
from ..providers.local_emotion import availability as emotion_availability
from ..providers.local_emotion import read_manifest as emotion_manifest
from ..providers.local_take_analysis import availability as take_analyzer_available
from ..providers.local_target_alignment import MODEL_NAME as TARGET_ALIGNMENT_MODEL
from ..providers.local_target_alignment import availability as target_aligner_available
from ..providers.local_target_alignment import read_manifest as target_aligner_manifest
from ..speech_emotion import freeze_emotion
from ..take_analysis import freeze_take_analysis
from ..timeline import revision_segments
from .preparation import Preparation


def emotion_inputs(prep: Preparation) -> None:
    settings, provider = prep.settings, prep.provider
    if provider not in {"local", "fake"}:
        raise HTTPException(422, "This speech-emotion adapter is not implemented")
    if provider == "local":
        ready, reason = emotion_availability(settings.local_emotion_model_dir)
        if not ready:
            raise HTTPException(422, reason)
    try:
        prep.inputs.update(freeze_emotion(prep.session, prep.project, prep.payload))
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    prep.inputs.update(
        {
            "model": DEMO_MODEL,
            "profile": DEMO_EMOTION_PROFILE,
            "model_manifest": EMOTION_MANIFEST,
            "model_dir": None,
            "threads": 1,
            "timeout_seconds": 60,
        }
        if provider == "fake"
        else {
            "model": EMOTION_MODEL,
            "profile": EMOTION_PROFILE,
            "model_manifest": emotion_manifest(settings.local_emotion_model_dir),
            "model_dir": str(settings.local_emotion_model_dir.resolve()),
            "threads": settings.local_emotion_threads,
            "timeout_seconds": settings.local_emotion_timeout_seconds,
        }
    )


def take_inputs(prep: Preparation) -> None:
    settings, provider, payload, inputs = prep.settings, prep.provider, prep.payload, prep.inputs
    if provider not in {"local", "fake"} or (provider == "local" and not take_analyzer_available()):
        raise HTTPException(422, "Install the optional local acoustic analysis adapter")
    try:
        inputs.update(freeze_take_analysis(prep.session, prep.project, payload))
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    inputs.update(
        {
            "model": DEMO_MODEL if provider == "fake" else "acoustic-dsp-v1",
            "threads": 1 if provider == "fake" else settings.local_aligner_threads,
            "timeout_seconds": settings.local_take_analyzer_timeout_seconds,
        }
    )
    if payload.include_target_alignment and provider == "fake":
        if settings.target_timing_aligner != "fake":
            raise HTTPException(422, "DEMO take analysis requires the DEMO target-language aligner")
        inputs["target_alignment_model"] = DEMO_MODEL
    elif payload.include_target_alignment:
        if settings.target_timing_aligner != "local" or prep.project.target_language != "ml-IN":
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


def alignment_inputs(prep: Preparation) -> None:
    session, project, payload, settings = prep.session, prep.project, prep.payload, prep.settings
    provider, inputs = prep.provider, prep.inputs
    if provider not in {"local", "fake"}:
        raise HTTPException(422, "This alignment adapter is not installed")
    if settings.performance_analyzer != provider:
        raise HTTPException(
            422,
            f"This combined source-analysis job requires the matching {provider} acoustic adapter",
        )
    if provider == "local":
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
            **(
                {
                    "performance_model": DEMO_MODEL,
                    "model": DEMO_MODEL,
                    "model_dir": None,
                    "model_manifest": {"demo": True},
                    "threads": 1,
                }
                if provider == "fake"
                else {
                    "performance_model": "acoustic-dsp-v1",
                    "model": ALIGNMENT_MODEL,
                    "model_dir": str(settings.local_aligner_model_dir.resolve()),
                    "model_manifest": alignment_manifest(settings.local_aligner_model_dir),
                    "threads": settings.local_aligner_threads,
                }
            ),
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
