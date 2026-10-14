"""Voice candidates preserve approval and never overwrite selected takes."""

import time
from pathlib import Path

from sqlalchemy import select

from .audio import combine_audio, fit_dialogue, mux_dialogue_preview, render_dialogue_mix
from .config import get_settings
from .consent import artifact_block_reason, profile_is_selected, validate_voice_use
from .media import file_digest, probe_media
from .models import Artifact, MediaAsset, ProviderRun, Segment, VoiceProfile
from .processing import charge, check_cancel, checkpoint, split_translation
from .providers import ProviderRegistry
from .providers.retry import retry_safe
from .voices import candidate_signature


def process_synthesize(session, job):
    settings = get_settings()
    provider = ProviderRegistry(settings).voice_synthesizer(job.provider)
    created, skipped = [], []
    for snapshot in job.input_json["segments"]:
        check_cancel(session, job)
        existing = next(
            (
                item
                for item in session.scalars(
                    select(Artifact).where(
                        Artifact.job_id == job.id, Artifact.kind == "dialogue_candidate"
                    )
                ).all()
                if item.metadata_json.get("segment_id") == snapshot["id"]
            ),
            None,
        )
        if existing:
            created.append(existing.id)
            continue
        line = session.get(Segment, snapshot["id"])
        voice = job.input_json["voices"][snapshot["id"]]
        profile = session.get(VoiceProfile, voice["profile_id"])
        if (
            not line
            or line.version != snapshot["version"]
            or not profile
            or profile.version != voice["profile_version"]
            or not profile_is_selected(session, profile)
        ):
            skipped.append(snapshot["id"])
            continue
        validate_voice_use(session, profile)
        output_dir = settings.storage_root / job.project_id / "voice" / job.id / line.id
        output_dir.mkdir(parents=True, exist_ok=True)
        parts = split_translation(
            snapshot["translated_text"], 1000 if voice["voice_kind"] == "clone" else 2500
        )
        completed = dict(job.checkpoint_json.get("voice_chunks", {}))
        paths = [Path(value) for value in completed.get(line.id, [])]
        for index, text in enumerate(parts):
            if index < len(paths):
                continue
            path = output_dir / f"part-{index}.wav"
            checkpoint(session, job, "generating_voice", pending_voice=f"{line.id}:{index}")

            def before_attempt(text=text, profile=profile, snapshot=snapshot, voice=voice):
                session.expire_all()
                current = session.get(Segment, snapshot["id"])
                if (
                    not current
                    or current.version != snapshot["version"]
                    or profile.version != voice["profile_version"]
                    or not profile_is_selected(session, profile)
                ):
                    raise ValueError(
                        "Dialogue or selected voice changed; remaining provider calls stopped"
                    )
                validate_voice_use(session, profile)
                if job.provider == "sarvam":
                    charge(session, job, len(text) / 10_000 * job.input_json["unit_rate_inr"])

            started = time.monotonic()
            result = retry_safe(
                lambda text=text, path=path, voice=voice: provider.synthesize(
                    text,
                    job.input_json["target_language"],
                    path,
                    voice_id=voice["voice_id"],
                    voice_kind=voice["voice_kind"],
                    pace=voice["pace"],
                ),
                lambda: check_cancel(session, job),
                before_attempt,
            )
            probe_media(result.audio_path)
            paths.append(result.audio_path)
            session.add(
                ProviderRun(
                    project_id=job.project_id,
                    job_id=job.id,
                    capability="voice_synthesizer",
                    provider=result.provider,
                    model=result.model,
                    status="completed",
                    latency_ms=round((time.monotonic() - started) * 1000),
                    estimated_cost_inr=(
                        len(text) / 10_000 * job.input_json["unit_rate_inr"]
                        if job.provider == "sarvam"
                        else 0
                    ),
                    parameters_json={
                        "segment_id": line.id,
                        "source_version": snapshot["version"],
                        "voice": voice,
                        "request_id": result.request_id,
                    },
                )
            )
            completed[line.id] = [str(item) for item in paths]
            checkpoint(session, job, "generating_voice", pending_voice=None, voice_chunks=completed)
        raw = output_dir / "raw.wav"
        combine_audio(paths, raw)
        fitted = output_dir / "fitted.wav"
        checkpoint(session, job, "fitting_timing")
        fit = fit_dialogue(
            raw,
            fitted,
            snapshot["end_ms"] - snapshot["start_ms"],
            job.input_json["max_timing_speedup"],
        )
        artifact = Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="dialogue_candidate",
            path=str((fitted if fit["fit_status"] == "ready" else raw).resolve()),
            filename=f"line-{line.index + 1}-candidate.wav",
            media_type="audio/wav",
            metadata_json={
                **fit,
                "segment_id": line.id,
                "revision_id": job.input_json["revision_id"],
                "source_version": snapshot["version"],
                "provider": job.provider,
                "model": voice["model"],
                "voice": voice,
                "signature": candidate_signature(snapshot, voice),
                "demo": job.provider == "fake",
                "sha256": file_digest(fitted if fit["fit_status"] == "ready" else raw),
            },
        )
        session.add(artifact)
        session.flush()
        created.append(artifact.id)
        session.commit()
    if skipped:
        job.warnings_json = [
            "Newer dialogue or voice edits were preserved; regenerate skipped lines"
        ]
    session.commit()
    return {"artifact_ids": created, "skipped_changed_lines": skipped}


def process_render_preview(session, job):
    settings = get_settings()
    existing = session.scalars(select(Artifact).where(Artifact.job_id == job.id)).all()
    if existing:
        return {"artifact_ids": [item.id for item in existing], "dialogue_only": True}
    source = session.get(MediaAsset, job.input_json["source_asset_id"])
    output_dir = settings.storage_root / job.project_id / "preview" / job.id
    mix = output_dir / "dialogue-only.wav"
    lines = []
    demo = False
    for snapshot in job.input_json["segments"]:
        candidate = session.get(Artifact, job.input_json["candidates"][snapshot["id"]])
        if not candidate or not Path(candidate.path).is_file():
            raise ValueError("A selected candidate file is unavailable")
        if artifact_block_reason(session, candidate):
            raise ValueError("Selected audio has revoked cloning consent")
        lines.append({"path": candidate.path, "start_ms": snapshot["start_ms"]})
        demo = demo or candidate.metadata_json.get("demo", False)
    checkpoint(session, job, "mixing_dialogue")
    render_dialogue_mix(lines, source.duration_ms, mix)
    metadata = {
        "revision_id": job.input_json["revision_id"],
        "source_asset_id": source.id,
        "dialogue_only": True,
        "demo": demo,
        "candidates": job.input_json["candidates"],
        "voice_profile_ids": list(
            {
                session.get(Artifact, candidate_id).metadata_json["voice"]["profile_id"]
                for candidate_id in job.input_json["candidates"].values()
            }
        ),
        "segment_versions": {line["id"]: line["version"] for line in job.input_json["segments"]},
        "warning": "Dialogue-only preview; original dialogue, music and effects are excluded",
    }
    artifacts = [
        Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="dialogue_mix",
            path=str(mix.resolve()),
            filename="demo-dialogue-only.wav" if demo else mix.name,
            media_type="audio/wav",
            metadata_json=metadata,
        )
    ]
    proxy = next(
        (
            item
            for item in session.scalars(
                select(Artifact).where(
                    Artifact.project_id == job.project_id, Artifact.kind == "preview_proxy"
                )
            ).all()
            if item.metadata_json.get("source_asset_id") == source.id
        ),
        None,
    )
    if proxy:
        checkpoint(session, job, "rendering_video_preview")
        video = output_dir / "dialogue-only.mp4"
        mux_dialogue_preview(Path(proxy.path), mix, video, source.duration_ms)
        artifacts.append(
            Artifact(
                project_id=job.project_id,
                job_id=job.id,
                kind="dub_preview",
                path=str(video.resolve()),
                filename="demo-dialogue-only.mp4" if demo else video.name,
                media_type="video/mp4",
                metadata_json=metadata,
            )
        )
    session.add_all(artifacts)
    session.commit()
    return {"artifact_ids": [item.id for item in artifacts], "dialogue_only": True}
