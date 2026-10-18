"""Immutable reviewed-input render, technical validation and verifiable export manifest."""

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from . import __version__
from .media import file_digest, probe_media, run_ffmpeg, write_srt
from .mix_media import mux_source_video, normalize_mix, render_mix_sum, verify_audio
from .mixes import validate_mix_snapshot
from .models import Artifact, MediaAsset, MixRender, ProviderRun
from .processing import add_warnings, check_cancel, checkpoint
from .storage import storage


def checked_file(path, expected=None):
    path = Path(path)
    if not path.is_file():
        raise ValueError("A render input or output file is unavailable")
    actual = file_digest(path)
    if expected and actual != expected:
        raise ValueError(
            "Media checksum changed; restore the input or create a fresh reviewed render"
        )
    return {"sha256": actual, "bytes": path.stat().st_size}


def render_artifacts(session, mix):
    artifacts = [session.get(Artifact, identifier) for identifier in mix.artifacts_json.values()]
    if any(not item for item in artifacts):
        raise ValueError("Rendered artifact lineage is unavailable")
    for item in artifacts:
        checked_file(item.path, item.metadata_json["sha256"])
    return artifacts


def process_render_mix(session, job):
    started = time.monotonic()
    existing = session.scalar(select(MixRender).where(MixRender.job_id == job.id))
    if existing:
        artifacts = render_artifacts(session, existing)
        return {
            "mix_id": existing.id,
            "artifact_ids": [item.id for item in artifacts],
            "review_required": existing.status != "approved",
        }
    inputs = job.input_json
    validate_mix_snapshot(session, inputs)
    source = session.get(MediaAsset, inputs["source_asset_id"])
    directory = storage().job_dir(job.project_id, "mixes", job.id)
    directory.mkdir(parents=True, exist_ok=True)
    settings = inputs["mix_settings"]

    def cancel():
        check_cancel(session, job)

    def phase(name):
        checkpoint(session, job, name)
        session.expire_all()
        validate_mix_snapshot(session, inputs)

    phase("verifying_mix_inputs")
    source_file = checked_file(
        source.path,
        inputs.get("source_sha256") or job.checkpoint_json.get("render_source", {}).get("sha256"),
    )
    files, background, lines, voices = {}, {}, [], set()
    recorded_hashes = job.checkpoint_json.get("render_input_hashes", {})
    for name, spec in inputs["background"].items():
        artifact = session.get(Artifact, spec["artifact_id"])
        files[artifact.id] = checked_file(artifact.path, spec["sha256"])
        background[name] = Path(artifact.path)
    demo = False
    candidate_provenance = {}
    for snapshot in inputs["segments"]:
        artifact = session.get(Artifact, inputs["candidates"][snapshot["id"]])
        expected = inputs["candidate_hashes"].get(snapshot["id"]) or recorded_hashes.get(
            artifact.id, {}
        ).get("sha256")
        files[artifact.id] = checked_file(artifact.path, expected)
        audio = next(
            stream
            for stream in probe_media(Path(artifact.path))["streams"]
            if stream["codec_type"] == "audio"
        )
        if (
            int(audio["sample_rate"]) != 48000
            or audio["channels"] != 2
            or abs(float(audio["duration"]) * 1000 - (snapshot["end_ms"] - snapshot["start_ms"]))
            > 1
        ):
            raise ValueError("Selected take no longer satisfies its timing/format contract")
        lines.append({"path": artifact.path, "start_ms": snapshot["start_ms"]})
        voices.add(artifact.metadata_json["voice"]["profile_id"])
        demo = demo or artifact.metadata_json.get("demo", False)
        candidate_provenance[artifact.id] = artifact.metadata_json
    checkpoint(
        session, job, "mixing_reviewed_tracks", render_input_hashes=files, render_source=source_file
    )
    raw = render_mix_sum(lines, background, settings, inputs["duration_ms"], directory, cancel)
    phase("normalizing_mix_loudness")
    master = directory / "stereo-master.wav"
    normalization = normalize_mix(raw, master, inputs["duration_ms"], settings, cancel)
    phase("validating_audio_master")
    master_quality = verify_audio(
        master, inputs["duration_ms"], settings, cancel, codec="pcm_s24le"
    )
    preview = directory / "listening-copy.wav"
    run_ffmpeg(["-i", str(master), "-c:a", "pcm_s16le", str(preview)], cancel=cancel)
    preview_quality = verify_audio(
        preview, inputs["duration_ms"], settings, cancel, codec="pcm_s16le"
    )
    subtitles = directory / "malayalam.srt"
    write_srt([SimpleNamespace(**line) for line in inputs["segments"]], subtitles)
    video = directory / "dubbed-review.mp4"
    phase("muxing_original_resolution_video")
    video_quality = mux_source_video(
        Path(source.path), master, video, inputs["duration_ms"], cancel
    )
    if video_quality:
        video_quality["audio"] = verify_audio(
            video, inputs["duration_ms"], settings, cancel, codec="aac", encoded=True
        )
    phase("validating_render_lineage")
    # Reject file changes during rendering, not just before it.
    checked_file(source.path, source_file["sha256"])
    for identifier, expected in files.items():
        checked_file(session.get(Artifact, identifier).path, expected["sha256"])
    warnings = [
        "Listen for retained dialogue leakage, missing effects, voice naturalness and timing. "
        "Technical validation is not listening acceptance."
    ]
    if demo:
        warnings.append("DEMO: selected dialogue takes are test tones, not dubbed speech")
    if normalization["second_pass"]["normalization_type"] != "linear":
        warnings.append(
            "Explicitly allowed dynamic normalization changed the mix dynamics; listen carefully"
        )
    quality = {
        "technical_status": "passed",
        "human_listening": "pending",
        "audio_master": master_quality,
        "listening_copy": preview_quality,
        "video": video_quality,
        "normalization": normalization,
        "warnings": warnings,
    }
    mix = MixRender(
        project_id=job.project_id,
        job_id=job.id,
        revision_id=inputs["revision_id"],
        source_asset_id=source.id,
        stem_set_id=inputs["stem_set_id"],
        settings_json=settings,
        quality_json=quality,
    )
    session.add(mix)
    session.flush()
    common = {
        "mix_id": mix.id,
        "revision_id": mix.revision_id,
        "source_asset_id": source.id,
        "stem_set_id": mix.stem_set_id,
        "candidates": inputs["candidates"],
        "voice_profile_ids": sorted(voices),
        "segment_versions": {line["id"]: line["version"] for line in inputs["segments"]},
        "demo": demo,
        "dialogue_only": False,
        "review_required": True,
    }
    outputs = [
        ("master", "mix_master", master, "audio/wav"),
        ("preview", "mix_listening_copy", preview, "audio/wav"),
        ("subtitles", "mix_subtitles", subtitles, "application/x-subrip"),
    ]
    if video_quality:
        outputs.append(("video", "mix_video", video, "video/mp4"))
    manifest_files = []
    for key, kind, path, media_type in outputs:
        evidence = checked_file(path)
        filename = f"demo-{path.name}" if demo else path.name
        artifact = Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind=kind,
            path=str(path.resolve()),
            filename=filename,
            media_type=media_type,
            metadata_json={**common, **evidence},
        )
        session.add(artifact)
        session.flush()
        mix.artifacts_json = {**mix.artifacts_json, key: artifact.id}
        manifest_files.append(
            {"artifact_id": artifact.id, "filename": filename, "kind": kind, **evidence}
        )
    ffmpeg_version = subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, text=True, check=True, timeout=5
    ).stdout.splitlines()[0]
    manifest = directory / "render-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "cinedub-render-v1",
                "mix_id": mix.id,
                "job_id": job.id,
                "project_id": job.project_id,
                "revision_id": mix.revision_id,
                "source_asset_id": source.id,
                "source_file": source_file,
                "duration_ms": inputs["duration_ms"],
                "cinedub_version": __version__,
                "ffmpeg_version": ffmpeg_version,
                "settings": settings,
                "quality": quality,
                "demo": demo,
                "stem_set": {
                    "id": mix.stem_set_id,
                    "version": inputs["stem_set_version"],
                    "provider": inputs["stem_provider"],
                    "model": inputs["stem_model"],
                },
                "segments": inputs["segments"],
                "candidates": inputs["candidates"],
                "input_files": files,
                "renderer_version": "cinedub-stereo-mix-v1",
                "background": inputs["background"],
                "candidate_provenance": candidate_provenance,
                "original_dialogue_track_mapped": False,
                "separation_may_retain_dialogue_leakage": True,
                "source_audio_mapped_to_video": False,
                "files": manifest_files,
                "review_status_at_render": "needs_review",
                "acceptance": "Approved bundles require a separate versioned listening certificate",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="mix_manifest",
        path=str(manifest.resolve()),
        filename=manifest.name,
        media_type="application/json",
        metadata_json={**common, **checked_file(manifest)},
    )
    session.add(artifact)
    session.flush()
    mix.artifacts_json = {**mix.artifacts_json, "manifest": artifact.id}
    session.flush()
    session.expire_all()
    cancel()
    validate_mix_snapshot(session, inputs)
    add_warnings(job, warnings)
    session.add(
        ProviderRun(
            project_id=job.project_id,
            job_id=job.id,
            capability="media_exporter",
            provider="local",
            model="cinedub-stereo-mix-v1",
            status="completed",
            estimated_cost_inr=0,
            latency_ms=round((time.monotonic() - started) * 1000),
            parameters_json={
                "mix_id": mix.id,
                "settings": settings,
                "stem_set_id": mix.stem_set_id,
                "ffmpeg_version": ffmpeg_version,
            },
        )
    )
    session.commit()
    return {
        "mix_id": mix.id,
        "artifact_ids": list(mix.artifacts_json.values()),
        "review_required": True,
    }
