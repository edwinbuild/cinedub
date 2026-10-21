"""Durable source-bound cinematic stems. Originals and earlier runs are never overwritten."""

import json
import math
from pathlib import Path

from sqlalchemy import select

from .config import get_settings
from .media import canonical_audio_filter, file_digest, probe_media, run_ffmpeg
from .media_quality import measure_loudness
from .models import Artifact, MediaAsset, ProviderRun, StemSet
from .processing import check_cancel, checkpoint
from .providers import ProviderRegistry
from .providers.local_separation import read_manifest


def process_separate(session, job):
    existing = session.scalar(select(StemSet).where(StemSet.job_id == job.id))
    if existing:
        return {"stem_set_id": existing.id}
    settings = get_settings()
    source = session.get(MediaAsset, job.input_json["source_asset_id"])
    if not source or source.project_id != job.project_id or not Path(source.path).is_file():
        raise ValueError("Selected source is unavailable")
    source_hash = file_digest(source.path)
    expected_hash = job.input_json.get("source_sha256") or job.checkpoint_json.get("source_sha256")
    if expected_hash and source_hash != expected_hash:
        raise ValueError("Source media changed since scheduling")
    model_dir = Path(job.input_json["model_dir"])
    if read_manifest(model_dir) != job.input_json["model_manifest"]:
        raise ValueError("Separator model changed since scheduling; submit a new request")
    directory = settings.storage_root / job.project_id / "separation" / job.id
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / "input.f32"
    checkpoint(session, job, "preparing_separation_audio", source_sha256=source_hash)
    run_ffmpeg(
        [
            "-i",
            source.path,
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-af",
            canonical_audio_filter(source.metadata_json, 44100),
            "-f",
            "f32le",
            str(raw_path),
        ],
        timeout=60,
    )
    result_path = directory / "separation-result.json"
    if result_path.is_file():
        metadata = json.loads(result_path.read_text())
    else:
        checkpoint(session, job, "measuring_source_loudness")
        levels = measure_loudness(raw_path, ("-f", "f32le", "-ar", "44100", "-ac", "2"))
        gain = (
            max(-60, min(60, -27 - levels["integrated_lufs"]))
            if levels["integrated_lufs"] is not None
            else 0
        )
        checkpoint(session, job, "separating", source_levels=levels, gain_db=gain)

        def cancel():
            check_cancel(session, job)

        def progress(completed, total):
            check_cancel(session, job)
            job.progress = completed / max(1, total) * 0.85
            job.checkpoint_json = {
                **job.checkpoint_json,
                "chunks_completed": completed,
                "chunks_total": total,
            }
            session.commit()

        metadata = (
            ProviderRegistry(settings)
            .stem_separator(job.provider, job.input_json)
            .separate(
                raw_path,
                directory,
                duration_ms=source.duration_ms,
                gain_db=gain,
                cancel=cancel,
                progress=progress,
            )
        )
    if metadata["model"] != job.input_json["model"]:
        raise ValueError("Separation output model does not match scheduled inputs")
    metadata = {**metadata, "source_sha256": source_hash, "timeline_mapping_version": 2}
    checkpoint(session, job, "validating_stems")
    stem_set = StemSet(
        project_id=job.project_id,
        source_asset_id=source.id,
        job_id=job.id,
        provider=job.provider,
        model=metadata["model"],
        metadata_json=metadata,
    )
    session.add(stem_set)
    session.flush()
    artifacts = {}
    for name in ("dialogue", "music", "effects"):
        master = directory / f"{name}.wav"
        probed = probe_media(master)
        stream = next(item for item in probed["streams"] if item["codec_type"] == "audio")
        if (
            abs(probed["duration_ms"] - source.duration_ms) > 1
            or int(stream["sample_rate"]) != 48000
            or stream["channels"] != 2
            or stream["codec_name"] != "pcm_f32le"
        ):
            raise ValueError("Separated stem failed duration/channel/sample-rate validation")
        common = {
            "stem_set_id": stem_set.id,
            "source_asset_id": source.id,
            "stem": name,
            "model": metadata["model"],
            "provider": job.provider,
            "sha256": file_digest(master),
            "sample_rate": 48000,
            "channels": 2,
            "review_required": True,
        }
        artifact = Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="stem_master",
            path=str(master.resolve()),
            filename=f"{name}-master.wav",
            media_type="audio/wav",
            metadata_json={**common, "codec": "pcm_f32le"},
        )
        session.add(artifact)
        session.flush()
        proxy = directory / f"{name}-preview.wav"
        levels = measure_loudness(master)
        true_peak = levels["true_peak_dbfs"]
        playback_gain = min(1.0, 10 ** ((-1 - true_peak) / 20)) if true_peak is not None else 1.0
        if not math.isfinite(playback_gain):
            raise ValueError("Invalid stem playback level")
        run_ffmpeg(
            [
                "-i",
                str(master),
                "-af",
                f"volume={playback_gain:.12f}",
                "-c:a",
                "pcm_s16le",
                str(proxy),
            ],
            timeout=60,
        )
        preview = Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="stem_preview",
            path=str(proxy.resolve()),
            filename=proxy.name,
            media_type="audio/wav",
            metadata_json={
                **common,
                "master_artifact_id": artifact.id,
                "codec": "pcm_s16le",
                "playback_gain": playback_gain,
                "sha256": file_digest(proxy),
                "master_levels": levels,
            },
        )
        session.add(preview)
        session.flush()
        artifacts[name] = {"master": artifact.id, "preview": preview.id}
    recognition = directory / "dialogue-recognition.wav"
    dialogue_gain = session.get(Artifact, artifacts["dialogue"]["preview"]).metadata_json[
        "playback_gain"
    ]
    run_ffmpeg(
        [
            "-i",
            str(directory / "dialogue.wav"),
            "-af",
            f"volume={dialogue_gain:.12f}",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(recognition),
        ],
        timeout=60,
    )
    audio = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="stem_recognition_audio",
        path=str(recognition.resolve()),
        filename=recognition.name,
        media_type="audio/wav",
        metadata_json={
            "stem_set_id": stem_set.id,
            "source_asset_id": source.id,
            "sha256": file_digest(recognition),
            "sample_rate": 16000,
            "channels": 1,
        },
    )
    session.add(audio)
    session.flush()
    artifacts["recognition_audio"] = audio.id
    stem_set.artifacts_json = artifacts
    session.add(
        ProviderRun(
            project_id=job.project_id,
            job_id=job.id,
            capability="stem_separator",
            provider=job.provider,
            model=metadata["model"],
            status="completed",
            latency_ms=metadata["latency_ms"],
            estimated_cost_inr=0,
            parameters_json={
                "stem_set_id": stem_set.id,
                "source_asset_id": source.id,
                "source_levels": job.checkpoint_json.get("source_levels"),
                "inference": metadata,
            },
        )
    )
    job.warnings_json = [metadata["warning"]]
    session.commit()
    return {"stem_set_id": stem_set.id, "review_required": True}
