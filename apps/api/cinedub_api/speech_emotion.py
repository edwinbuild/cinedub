"""Immutable audio-bound emotion evidence and independent human performance review."""

from pathlib import Path

from sqlalchemy import select

from .alignment import freeze_alignment_audio, validate_alignment_source
from .config import get_settings
from .media import file_digest
from .models import Job, Segment, SpeechEmotionReviewRecord
from .schemas import SpeechEmotionInference, SpeechEmotionReport, SpeechEmotionReviewRead
from .timeline import revision_segments


def overlapping(line, others):
    return any(
        other.id != line.id and line.start_ms < other.end_ms and line.end_ms > other.start_ms
        for other in others
    )


def freeze_emotion(session, project, payload):
    if project.source_language != "en-IN":
        raise ValueError("The installed emotion model supports English source speech only")
    values = freeze_alignment_audio(
        session,
        project,
        payload.revision_id or project.active_revision_id,
        payload.transcription_input,
    )
    if payload.source_asset_id and payload.source_asset_id != values["source_asset_id"]:
        raise ValueError("Selected source does not match the active timeline")
    all_lines = revision_segments(session, project.id, values["revision_id"])
    lines = all_lines
    if payload.segment_ids is not None:
        ids = payload.segment_ids
        if (
            not ids
            or len(ids) != len(set(ids))
            or not set(ids).issubset({line.id for line in lines})
        ):
            raise ValueError("Select distinct dialogue lines from this revision")
        lines = [line for line in lines if line.id in ids]
    if not 0 < len(lines) <= 500 or payload.regenerate:
        raise ValueError(
            "Speech-emotion review requires 1 to 500 saved lines; it never regenerates text"
        )
    return {
        **values,
        "project_id": project.id,
        "segments": [
            {
                "id": line.id,
                "version": line.version,
                "source_text": line.source_text,
                "speaker_id": line.speaker_id,
                "start_ms": line.start_ms,
                "end_ms": line.end_ms,
                "overlap": overlapping(line, all_lines),
            }
            for line in lines
        ],
    }


def line_changed(session, project_id, revision_id, snapshot, all_lines):
    line = session.get(Segment, snapshot["id"])
    return (
        not line
        or line.retired
        or line.project_id != project_id
        or line.revision_id != revision_id
        or any(getattr(line, key) != snapshot[key] for key in ("start_ms", "end_ms", "speaker_id"))
        or overlapping(line, all_lines) != snapshot["overlap"]
    )


def validate_emotion_inputs(session, inputs, *, files=False):
    session.expire_all()
    validate_alignment_source(session, inputs, verify_files=files)
    lines = revision_segments(session, inputs["project_id"], inputs["revision_id"])
    if any(
        line_changed(session, inputs["project_id"], inputs["revision_id"], snapshot, lines)
        for snapshot in inputs["segments"]
    ):
        raise ValueError("Source timing, speaker or overlap changed; analyze current windows again")


def validated_inferences(inputs, values):
    if not isinstance(values, list) or len(values) != len(inputs["segments"]):
        raise ValueError("Emotion adapter did not return every requested window")
    results = []
    for raw, snapshot in zip(values, inputs["segments"], strict=True):
        result = SpeechEmotionInference.model_validate(raw)
        if (
            result.segment_id != snapshot["id"]
            or result.start_ms != snapshot["start_ms"]
            or result.end_ms != snapshot["end_ms"]
        ):
            raise ValueError("Emotion adapter returned mismatched source-window provenance")
        duration = result.end_ms - result.start_ms
        if duration <= 0 or result.speech_ms > duration:
            raise ValueError("Speech evidence exceeds its audio window")
        if abs(result.speech_ms - result.speech_fraction * duration) > 1:
            raise ValueError("Speech evidence duration and fraction disagree")
        inferred = result.status in {"needs_review", "ambiguous"}
        if inferred:
            scores = {item.label: item.score for item in result.scores}
            if (
                len(result.scores) != 4
                or set(scores) != {"neutral", "happy", "angry", "sad"}
                or abs(sum(scores.values()) - 1) > 0.0001
            ):
                raise ValueError("Emotion model scores are incomplete or not normalized")
            ranked = sorted(scores, key=scores.get, reverse=True)
            margin = scores[ranked[0]] - scores[ranked[1]]
            suggested = (
                ranked[0]
                if scores[ranked[0]] >= inputs["profile"]["suggestion_score"]
                and margin >= inputs["profile"]["suggestion_margin"]
                else None
            )
            if (
                result.suggested_label != suggested
                or result.score_margin is None
                or abs(result.score_margin - margin) > 0.0001
                or (result.status == "needs_review") != bool(suggested)
            ):
                raise ValueError("Emotion suggestion does not match its uncalibrated model scores")
            if (
                snapshot["overlap"]
                or not inputs["profile"]["min_window_ms"]
                <= result.end_ms - result.start_ms
                <= inputs["profile"]["max_window_ms"]
            ):
                raise ValueError("Emotion was inferred outside the supported window profile")
            if (
                result.speech_ms < inputs["profile"]["min_speech_ms"]
                or result.speech_fraction < inputs["profile"]["min_speech_fraction"]
            ):
                raise ValueError("Emotion label lacks the required speech-presence evidence")
        elif result.scores or result.suggested_label is not None or result.score_margin is not None:
            raise ValueError("Skipped windows cannot have invented emotion scores or labels")
        results.append(result)
    return results


def read_emotion_report(session, artifact):
    path = Path(artifact.path).resolve()
    if (
        not path.is_relative_to(get_settings().storage_root.resolve())
        or not path.is_file()
        or file_digest(path) != artifact.metadata_json.get("sha256")
    ):
        raise ValueError("Speech-emotion report bytes changed or are unavailable")
    report = SpeechEmotionReport.model_validate_json(path.read_text(encoding="utf-8"))
    job = session.get(Job, artifact.job_id)
    if (
        not job
        or job.stage != "analyze_emotion"
        or report.project_id != artifact.project_id
        or job.project_id != artifact.project_id
    ):
        raise ValueError("Speech-emotion report lineage is inconsistent")
    inputs = job.input_json
    for key in (
        "revision_id",
        "source_asset_id",
        "source_sha256",
        "recognition_artifact_id",
        "recognition_sha256",
        "stem_set_id",
        "stem_set_version",
        "model",
        "profile",
    ):
        if getattr(report, key) != inputs.get(key):
            raise ValueError("Speech-emotion report differs from the scheduled source/model")
    if report.provider != job.provider or report.language != inputs["source_language"]:
        raise ValueError("Speech-emotion provider or language provenance changed")
    validated_inferences(
        inputs,
        [
            line.model_dump(
                exclude={
                    "segment_version",
                    "source_text",
                    "speaker_id",
                    "stale_reason",
                    "review_history",
                }
            )
            for line in report.lines
        ],
    )
    current = revision_segments(session, report.project_id, report.revision_id)
    try:
        validate_alignment_source(session, inputs, verify_files=True)
    except (OSError, ValueError) as exc:
        report.stale_reason = str(exc)
    history = {}
    for record in session.scalars(
        select(SpeechEmotionReviewRecord)
        .where(SpeechEmotionReviewRecord.artifact_id == artifact.id)
        .order_by(SpeechEmotionReviewRecord.version)
    ):
        history.setdefault(record.segment_id, []).append(
            SpeechEmotionReviewRead.model_validate(record)
        )
    for line, snapshot in zip(report.lines, inputs["segments"], strict=True):
        if (
            line.source_text != snapshot["source_text"]
            or line.speaker_id != snapshot["speaker_id"]
            or line.segment_version != snapshot["version"]
            or line.review_history
            or line.stale_reason
        ):
            raise ValueError("Speech-emotion line provenance changed")
        if line_changed(session, report.project_id, report.revision_id, snapshot, current):
            line.stale_reason = (
                "Source timing, speaker or overlap changed; analyze this window again"
            )
        line.review_history = history.get(line.segment_id, [])
    return report
