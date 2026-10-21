"""Durable alignment stage: immutable evidence, no automatic transcript mutation."""

from pathlib import Path

from sqlalchemy import select

from .alignment import validate_alignment_lines, validate_alignment_source
from .config import get_settings
from .media import file_digest
from .models import Artifact, ProviderRun, Segment
from .processing import check_cancel, checkpoint
from .providers import ProviderRegistry
from .providers.local_alignment import read_manifest
from .schemas import AlignmentReport


def process_align(session, job):
    existing = session.scalar(
        select(Artifact).where(Artifact.job_id == job.id, Artifact.kind == "alignment_report")
    )
    if existing:
        return {"alignment_artifact_id": existing.id}
    settings, inputs = get_settings(), job.input_json
    validate_alignment_source(session, inputs, verify_files=True)
    validate_alignment_lines(session, job.project_id, inputs["revision_id"], inputs["segments"])
    model_dir = Path(inputs["model_dir"])
    if read_manifest(model_dir) != inputs["model_manifest"]:
        raise ValueError("Alignment model changed since scheduling; submit a new request")
    directory = settings.storage_root / job.project_id / "alignment" / job.id
    directory.mkdir(parents=True, exist_ok=True)
    audio = session.get(Artifact, inputs["recognition_artifact_id"])
    checkpoint(session, job, "aligning_words")

    def cancel():
        check_cancel(session, job)

    def progress(completed, total):
        cancel()
        job.progress = min(0.9, completed / max(1, total) * 0.9)
        job.checkpoint_json = {
            **job.checkpoint_json,
            "lines_completed": completed,
            "lines_total": total,
        }
        session.commit()

    payload = (
        ProviderRegistry(settings)
        .aligner(job.provider, inputs)
        .align(
            Path(audio.path),
            directory,
            lines=inputs["segments"],
            duration_ms=inputs["duration_ms"],
            language=inputs["source_language"],
            cancel=cancel,
            progress=progress,
        )
    )
    if payload.get("model") != inputs["model"]:
        raise ValueError("Alignment model provenance does not match the scheduled request")
    report = AlignmentReport(
        project_id=job.project_id,
        revision_id=inputs["revision_id"],
        source_asset_id=inputs["source_asset_id"],
        source_sha256=inputs["source_sha256"],
        recognition_artifact_id=audio.id,
        recognition_sha256=inputs["recognition_sha256"],
        stem_set_id=inputs.get("stem_set_id"),
        stem_set_version=inputs.get("stem_set_version"),
        provider=job.provider,
        model=inputs["model"],
        language=inputs["source_language"],
        metadata={**payload["metadata"], "model_manifest": inputs["model_manifest"]},
        lines=payload["lines"],
        warnings=[
            "Timing suggestions need listening review; "
            "acoustic scores are not calibrated confidence",
            "English source alignment only; Malayalam candidate alignment remains unverified",
            "Pitch, level and energy pauses are signal measurements, not emotion labels",
        ],
    )
    if len(report.lines) != len(inputs["segments"]):
        raise ValueError("Alignment did not return every requested line")
    neighbors = session.scalars(
        select(Segment).where(
            Segment.project_id == job.project_id,
            Segment.revision_id == inputs["revision_id"],
            Segment.retired.is_(False),
        )
    ).all()
    for evidence, snapshot in zip(report.lines, inputs["segments"], strict=True):
        if (
            evidence.segment_id != snapshot["id"]
            or evidence.segment_version != snapshot["version"]
            or evidence.source_text != snapshot["source_text"]
            or evidence.original_start_ms != snapshot["start_ms"]
            or evidence.original_end_ms != snapshot["end_ms"]
        ):
            raise ValueError("Alignment line provenance is inconsistent")
        previous = max(0, snapshot["start_ms"] - 300)
        for word in evidence.words:
            if (
                not previous
                <= word.start_ms
                < word.end_ms
                <= min(inputs["duration_ms"], snapshot["end_ms"] + 300)
            ):
                raise ValueError("Alignment returned invalid/non-monotonic word timings")
            previous = word.end_ms
        if evidence.status == "aligned" and not evidence.words:
            raise ValueError("Aligned status requires acoustic word evidence")
        overlap_warning = "Suggested timing overlaps another dialogue line"
        if (
            evidence.words
            and any(
                other.id != evidence.segment_id
                and evidence.words[0].start_ms < other.end_ms
                and evidence.words[-1].end_ms > other.start_ms
                for other in neighbors
            )
            and overlap_warning not in evidence.warnings
        ):
            evidence.warnings.append(overlap_warning)
    checkpoint(session, job, "validating_alignment")
    # Progress commits release the transaction, so inspect fresh database state after inference.
    session.expire_all()
    validate_alignment_source(session, inputs, verify_files=True)
    validate_alignment_lines(session, job.project_id, inputs["revision_id"], inputs["segments"])
    path = directory / "alignment-report.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="alignment_report",
        path=str(path.resolve()),
        filename="source-alignment-and-performance.json",
        media_type="application/json",
        metadata_json={
            "revision_id": report.revision_id,
            "source_asset_id": report.source_asset_id,
            "model": report.model,
            "provider": report.provider,
            "sha256": file_digest(path),
            "schema_version": 1,
            "line_count": len(report.lines),
            "aligned_count": sum(line.status == "aligned" for line in report.lines),
            "review_required": True,
        },
    )
    session.add(artifact)
    session.add(
        ProviderRun(
            project_id=job.project_id,
            job_id=job.id,
            capability="timing_aligner",
            provider=job.provider,
            model=report.model,
            parameters_json=report.metadata,
            latency_ms=payload["metadata"]["latency_ms"],
            estimated_cost_inr=0,
            status="completed",
        )
    )
    session.add(
        ProviderRun(
            project_id=job.project_id,
            job_id=job.id,
            capability="performance_analyzer",
            provider=job.provider,
            model="acoustic-dsp-v1",
            parameters_json={
                "scope": "source line energy/pitch/pauses, not emotion",
                "alignment_model": report.model,
                "sample_rate": 16000,
            },
            latency_ms=payload["metadata"]["latency_ms"],
            estimated_cost_inr=0,
            status="completed",
        )
    )
    session.commit()
    return {"alignment_artifact_id": artifact.id}
