"""Read-only source speech emotion inference; no synthesis or content approval side effects."""

import math
from pathlib import Path

from sqlalchemy import select

from .config import get_settings
from .media import file_digest
from .models import Artifact, ProviderRun
from .processing import check_cancel, checkpoint
from .providers import ProviderRegistry
from .providers.local_emotion import QUALITY_WARNING, read_manifest
from .schemas import SpeechEmotionReport
from .speech_emotion import read_emotion_report, validate_emotion_inputs, validated_inferences


def process_analyze_emotion(session, job):
    existing = session.scalar(
        select(Artifact).where(Artifact.job_id == job.id, Artifact.kind == "speech_emotion_report")
    )
    if existing:
        read_emotion_report(session, existing)
        return {"emotion_artifact_id": existing.id}
    inputs = job.input_json
    validate_emotion_inputs(session, inputs, files=True)
    if read_manifest(Path(inputs["model_dir"])) != inputs["model_manifest"]:
        raise ValueError("Speech-emotion model installation changed; schedule a new analysis")
    directory = get_settings().storage_root / job.project_id / "speech-emotion" / job.id
    checkpoint(session, job, "analyzing_source_speech")
    audio = session.get(Artifact, inputs["recognition_artifact_id"])

    def progress(completed, total):
        check_cancel(session, job)
        job.progress = min(0.9, completed / max(1, total) * 0.9)
        job.checkpoint_json = {
            **job.checkpoint_json,
            "classified_windows": completed,
            "classification_total": total,
        }
        session.commit()

    payload = (
        ProviderRegistry(get_settings())
        .emotion_analyzer(job.provider, inputs)
        .analyze(
            Path(audio.path),
            directory,
            windows=[
                {key: value[key] for key in ("id", "start_ms", "end_ms", "overlap")}
                for value in inputs["segments"]
            ],
            duration_ms=inputs["duration_ms"],
            language=inputs["source_language"],
            cancel=lambda: check_cancel(session, job),
            progress=progress,
        )
    )
    if (
        payload.get("provider") != job.provider
        or payload.get("model") != inputs["model"]
        or payload.get("profile") != inputs["profile"]
    ):
        raise ValueError("Emotion model/profile provenance does not match the scheduled request")
    inferences = validated_inferences(inputs, payload["lines"])
    metadata = {
        key: payload["metadata"][key]
        for key in (
            "elapsed_ms",
            "peak_rss_mib",
            "threads",
            "emotion_inference_count",
            "vad_frame_count",
        )
    }
    for key in ("elapsed_ms", "emotion_inference_count", "vad_frame_count"):
        if type(metadata[key]) is not int or metadata[key] < 0:
            raise ValueError("Emotion runtime metadata must contain nonnegative counts")
    if (
        metadata["threads"] != inputs["threads"]
        or not isinstance(metadata["peak_rss_mib"], (int, float))
        or not math.isfinite(metadata["peak_rss_mib"])
        or not 0 <= metadata["peak_rss_mib"] <= 10 * 1024
    ):
        raise ValueError("Emotion runtime exceeded or misreported its bounded profile")
    if metadata["emotion_inference_count"] != sum(
        line.status in {"needs_review", "ambiguous"} for line in inferences
    ):
        raise ValueError("Emotion inference count is inconsistent")
    report = SpeechEmotionReport(
        **{
            key: inputs.get(key)
            for key in (
                "project_id",
                "revision_id",
                "source_asset_id",
                "source_sha256",
                "recognition_artifact_id",
                "recognition_sha256",
                "stem_set_id",
                "stem_set_version",
            )
        },
        language=inputs["source_language"],
        provider=job.provider,
        model=inputs["model"],
        profile=inputs["profile"],
        metadata={**metadata, "model_manifest": inputs["model_manifest"]},
        lines=[
            {
                **result.model_dump(),
                "segment_version": saved["version"],
                "source_text": saved["source_text"],
                "speaker_id": saved["speaker_id"],
            }
            for result, saved in zip(inferences, inputs["segments"], strict=True)
        ],
        warnings=[
            QUALITY_WARNING,
            "Audio-only model hints, not text sentiment or facts about an actor's mental state",
            "English, four training classes only; "
            "Malayalam and natural-film accuracy are not validated",
            "Human performance reviews do not change translation, timing, "
            "voice settings or approvals",
        ],
    )
    checkpoint(session, job, "validating_speech_emotion")
    validate_emotion_inputs(session, inputs, files=True)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "speech-emotion.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="speech_emotion_report",
        path=str(path.resolve()),
        filename=path.name,
        media_type="application/json",
        metadata_json={
            "revision_id": report.revision_id,
            "source_asset_id": report.source_asset_id,
            "model": report.model,
            "provider": job.provider,
            "sha256": file_digest(path),
        },
    )
    session.add(artifact)
    for capability, count, model in [
        ("emotion_analyzer", metadata["emotion_inference_count"], inputs["model"]),
        (
            "speech_presence_detector",
            metadata["vad_frame_count"],
            inputs["model_manifest"]["vad_id"] + "@" + inputs["model_manifest"]["vad_revision"],
        ),
    ]:
        if count:
            session.add(
                ProviderRun(
                    project_id=job.project_id,
                    job_id=job.id,
                    capability=capability,
                    provider=job.provider,
                    model=model,
                    status="completed",
                    latency_ms=metadata["elapsed_ms"],
                    estimated_cost_inr=0,
                    parameters_json={
                        "count": count,
                        "profile": inputs["profile"],
                        "calibrated_confidence": False,
                    },
                )
            )
    session.commit()
    return {
        "emotion_artifact_id": artifact.id,
        "classified_windows": metadata["emotion_inference_count"],
    }
