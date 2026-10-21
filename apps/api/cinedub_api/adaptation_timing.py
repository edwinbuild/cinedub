"""Measured, explicitly chosen take timing; no text-based duration prediction."""

import wave
from pathlib import Path

from .config import get_settings
from .consent import artifact_block_reason, profile_is_selected, validate_voice_use
from .media import file_digest
from .models import Artifact, Job, Segment, VoiceProfile
from .schemas import DialogueTimingFeedback
from .voices import candidate_signature


def measure_feedback(session, project_id, revision_id, context, candidate_id):
    candidate = session.get(Artifact, candidate_id)
    line = session.get(Segment, context["segment_id"])
    if (
        not candidate
        or candidate.project_id != project_id
        or candidate.kind != "dialogue_candidate"
        or not line
        or line.retired
        or line.project_id != project_id
        or line.revision_id != revision_id
        or candidate.metadata_json.get("segment_id") != line.id
        or candidate.metadata_json.get("revision_id") != revision_id
    ):
        raise ValueError("Timing feedback requires a take from a chosen line in this revision")
    metadata = candidate.metadata_json
    voice = metadata.get("voice", {})
    profile = (
        session.get(VoiceProfile, voice.get("profile_id")) if voice.get("profile_id") else None
    )
    job = session.get(Job, candidate.job_id)
    snapshot = (
        next(
            (item for item in job.input_json.get("segments", []) if item.get("id") == line.id), None
        )
        if job
        else None
    )
    if (
        not profile
        or profile.project_id != project_id
        or profile.speaker_id != context["speaker_id"]
        or profile.version != voice.get("profile_version")
        or not profile_is_selected(session, profile)
        or not job
        or job.project_id != project_id
        or job.stage != "synthesize"
        or job.input_json.get("voices", {}).get(line.id) != voice
        or not snapshot
        or any(
            snapshot.get(key) != context[key]
            for key in ("source_text", "translated_text", "start_ms", "end_ms", "speaker_id")
        )
        or metadata.get("signature") != candidate_signature(context, voice)
    ):
        raise ValueError("Timing take dialogue or selected voice changed; synthesize again")
    validate_voice_use(session, profile)
    if artifact_block_reason(session, candidate):
        raise ValueError("Timing take consent is unavailable or revoked")
    root = get_settings().storage_root.resolve()
    directory = (root / project_id / "voice" / job.id / line.id).resolve()
    path = Path(candidate.path).resolve()
    if not directory.is_relative_to(root) or path.parent != directory:
        raise ValueError("Timing take audio provenance is unavailable")
    raw = directory / "raw.wav"
    if raw.resolve() != raw or not raw.is_file():
        raise ValueError("Canonical raw timing audio is unavailable; synthesize again")
    expected = metadata.get("raw_sha256")
    if metadata.get("fit_status") == "too_long" and path == raw:
        expected = expected or metadata.get("sha256")
    elif metadata.get("fit_status") != "ready" or path != directory / "fitted.wav":
        raise ValueError("Timing take fitting provenance is unavailable")
    if not expected:
        raise ValueError("This older fitted take has no verified raw checksum; synthesize again")
    if file_digest(path) != metadata.get("sha256") or file_digest(raw) != expected:
        raise ValueError("Timing take audio bytes changed; synthesize again")
    try:
        with wave.open(str(raw), "rb") as audio:
            if (
                audio.getframerate(),
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getcomptype(),
            ) != (48000, 2, 2, "NONE"):
                raise ValueError("Timing feedback requires the canonical raw PCM take")
            frames = audio.getnframes()
    except (wave.Error, EOFError) as exc:
        raise ValueError("Raw timing audio is unreadable; synthesize again") from exc
    duration = round(frames * 1000 / 48000)
    target = context["end_ms"] - context["start_ms"]
    if duration != metadata.get("raw_duration_ms") or target != metadata.get("target_duration_ms"):
        raise ValueError("Timing take duration or dialogue window changed; synthesize again")
    ratio = frames / (target * 48) if target > 0 else 0
    limit = job.input_json["max_timing_speedup"]
    return DialogueTimingFeedback(
        candidate_id=candidate.id,
        candidate_sha256=metadata["sha256"],
        raw_sha256=expected,
        raw_sample_count=frames,
        raw_duration_ms=duration,
        target_duration_ms=target,
        required_speed_ratio=ratio,
        max_safe_speedup=limit,
        safe_speedup_exceeded=ratio > limit,
        signature=metadata["signature"],
        voice=voice,
        demo=bool(metadata.get("demo")) or metadata.get("provider") == "fake",
        evaluation_fixture=bool(metadata.get("evaluation_fixture")),
    ).model_dump()


def freeze_timing_feedback(session, project, inputs, candidate_ids):
    if not candidate_ids:
        return {}
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Choose distinct timing-feedback takes")
    context = {line["segment_id"]: line for line in inputs["context_lines"]}
    result = {}
    for identifier in candidate_ids:
        artifact = session.get(Artifact, identifier)
        line_id = artifact.metadata_json.get("segment_id") if artifact else None
        if line_id not in inputs["review_ids"] or line_id in result:
            raise ValueError("Choose at most one timing-feedback take per adapted line")
        result[line_id] = measure_feedback(
            session, project.id, inputs["revision_id"], context[line_id], identifier
        )
    return result


def validate_timing_feedback(session, project_id, inputs):
    context = {line["segment_id"]: line for line in inputs["context_lines"]}
    for identifier, saved in inputs.get("timing_feedback", {}).items():
        actual = measure_feedback(
            session, project_id, inputs["revision_id"], context[identifier], saved["candidate_id"]
        )
        if actual != saved:
            raise ValueError("Measured timing feedback changed; generate alternatives again")
