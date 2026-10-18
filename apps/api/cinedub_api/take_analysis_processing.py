"""Durable read-only performance review. Never alters takes, voices or saved timings."""

from pathlib import Path

from sqlalchemy import select

from .config import get_settings
from .job_errors import StaleInput
from .media import file_digest, probe_media, run_ffmpeg
from .models import Artifact, ProviderRun
from .processing import check_cancel, checkpoint
from .providers import ProviderRegistry
from .providers.local_target_alignment import read_manifest
from .schemas import TakePerformanceReport
from .take_analysis import validate_take_analysis


def process_analyze_takes(session, job):
    existing = session.scalar(
        select(Artifact).where(
            Artifact.job_id == job.id, Artifact.kind == "take_performance_report"
        )
    )
    if existing:
        return {"performance_artifact_id": existing.id}
    settings, inputs = get_settings(), job.input_json
    validate_take_analysis(session, inputs, verify_files=True)
    if (
        inputs["include_target_alignment"]
        and job.provider != "fake"
        and read_manifest(Path(inputs["target_model_dir"]), verify=True)
        != inputs["target_model_manifest"]
    ):
        raise StaleInput("Target alignment model changed; schedule a new analysis")
    directory = settings.storage_root / job.project_id / "take-analysis" / job.id
    directory.mkdir(parents=True, exist_ok=True)
    source_audio = session.get(Artifact, inputs["recognition_artifact_id"])
    prepared = []
    for index, take in enumerate(inputs["takes"]):
        checkpoint(session, job, "preparing_take_analysis", takes_prepared=index)
        candidate = session.get(Artifact, take["candidate_id"])
        duration = take["end_ms"] - take["start_ms"]
        if abs(probe_media(Path(candidate.path))["duration_ms"] - duration) > 1:
            raise ValueError("Candidate duration does not match its saved timing")
        path = directory / f"take-{index}-16k.wav"
        run_ffmpeg(
            [
                "-i",
                candidate.path,
                "-af",
                f"aresample=16000,apad=whole_len={duration * 16},atrim=end_sample={duration * 16}",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(path),
            ],
            timeout=60,
            cancel=lambda: check_cancel(session, job),
        )
        prepared.append({**take, "prepared_audio_path": str(path.resolve())})
    checkpoint(session, job, "analyzing_take_delivery")

    def progress(completed, total):
        check_cancel(session, job)
        job.progress = min(0.9, completed / max(1, total) * 0.9)
        job.checkpoint_json = {
            **job.checkpoint_json,
            "takes_completed": completed,
            "takes_total": total,
        }
        session.commit()

    payload = (
        ProviderRegistry(settings)
        .take_analyzer(job.provider, inputs)
        .compare(
            {
                "source_audio_path": source_audio.path,
                "duration_ms": inputs["duration_ms"],
                "takes": prepared,
                "include_target_alignment": inputs["include_target_alignment"],
                "target_model_dir": inputs.get("target_model_dir"),
            },
            directory,
            cancel=lambda: check_cancel(session, job),
            progress=progress,
        )
    )
    if payload["metadata"].get("model") != inputs["model"] or payload["metadata"].get(
        "target_alignment_model"
    ) != inputs.get("target_alignment_model"):
        raise ValueError("Take analysis model provenance does not match the scheduled request")
    if len(payload["lines"]) != len(inputs["takes"]):
        raise ValueError("Take analysis did not return every requested take")
    lines = []
    for result, take in zip(payload["lines"], inputs["takes"], strict=True):
        if result["candidate_id"] != take["candidate_id"]:
            raise ValueError("Take analysis returned mismatched candidate provenance")
        lines.append(
            {
                **take,
                **{
                    field: result[field]
                    for field in (
                        "source_performance",
                        "target_performance",
                        "target_alignment",
                        "comparison",
                    )
                },
                "warnings": [
                    "Signals are not emotion, vocal identity or a quality score",
                    "Text pace differs across languages; "
                    "level/pitch changes may reflect voice or input gain",
                ],
            }
        )
    report = TakePerformanceReport(
        project_id=job.project_id,
        revision_id=inputs["revision_id"],
        source_asset_id=inputs["source_asset_id"],
        source_sha256=inputs["source_sha256"],
        recognition_artifact_id=source_audio.id,
        recognition_sha256=inputs["recognition_sha256"],
        stem_set_id=inputs.get("stem_set_id"),
        stem_set_version=inputs.get("stem_set_version"),
        provider=job.provider,
        model=inputs["model"],
        target_language=inputs["target_language"],
        metadata={
            **payload["metadata"],
            "target_model_manifest": inputs.get("target_model_manifest"),
        },
        lines=lines,
        warnings=[
            "Readonly comparison; no timing, voice, approval or take is changed automatically",
            "Malayalam word alignment is experimental and requires listening/language review",
        ],
    )
    for line in report.lines:
        if line.demo and line.target_alignment.words:
            raise ValueError("Demo tones cannot have spoken word alignment")
        if line.target_alignment.status == "aligned" and not line.target_alignment.words:
            raise ValueError("Aligned status requires acoustic word evidence")
        previous = line.start_ms
        for word in line.target_alignment.words:
            if not previous <= word.start_ms < word.end_ms <= line.end_ms:
                raise ValueError("Target words are not monotonic within the take envelope")
            previous = word.end_ms
    checkpoint(session, job, "validating_take_analysis")
    session.expire_all()
    validate_take_analysis(session, inputs, verify_files=True)
    path = directory / "take-performance-report.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="take_performance_report",
        path=str(path.resolve()),
        filename="source-versus-take-performance.json",
        media_type="application/json",
        metadata_json={
            "revision_id": report.revision_id,
            "source_asset_id": report.source_asset_id,
            "sha256": file_digest(path),
            "model": report.model,
            "schema_version": 1,
            "candidates": inputs["candidates"],
            "voice_profile_ids": sorted({take["voice"]["profile_id"] for take in inputs["takes"]}),
            "target_alignment_requested": inputs["include_target_alignment"],
            "demo": any(line.demo for line in report.lines),
        },
    )
    session.add(artifact)
    session.add(
        ProviderRun(
            project_id=job.project_id,
            job_id=job.id,
            capability="performance_analyzer",
            provider=job.provider,
            model=report.model,
            parameters_json=report.metadata,
            latency_ms=report.metadata["latency_ms"],
            estimated_cost_inr=0,
            status="completed",
        )
    )
    if inputs["include_target_alignment"] and report.metadata.get("target_inference_count", 0) > 0:
        session.add(
            ProviderRun(
                project_id=job.project_id,
                job_id=job.id,
                capability="target_timing_aligner",
                provider=job.provider,
                model=inputs["target_alignment_model"],
                parameters_json={"experimental": True},
                latency_ms=report.metadata["latency_ms"],
                estimated_cost_inr=0,
                status="completed",
            )
        )
    session.commit()
    return {"performance_artifact_id": artifact.id}
