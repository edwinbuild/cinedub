"""Durable local briefing checks. Never writes translated text or approval state."""

import time

from sqlalchemy import select

from .dialogue_review import METHOD, build_review, read_dialogue_review, stale_reason
from .job_errors import StaleInput
from .media import file_digest
from .models import Artifact, ProviderRun
from .processing import checkpoint
from .storage import storage


def process_review_translation(session, job):
    existing = session.scalar(
        select(Artifact).where(Artifact.job_id == job.id, Artifact.kind == "dialogue_review_report")
    )
    if existing:
        read_dialogue_review(session, existing)
        return {"dialogue_review_artifact_id": existing.id}
    checkpoint(session, job, "checking_saved_dialogue")
    reason = stale_reason(session, job.project_id, job.input_json)
    if reason:
        raise StaleInput(reason)
    started = time.monotonic()
    report = build_review(job.input_json, job.project_id)
    checkpoint(session, job, "saving_editorial_review")
    reason = stale_reason(session, job.project_id, job.input_json)
    if reason:
        raise StaleInput(reason)
    directory = storage().job_dir(job.project_id, "dialogue-review", job.id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "dialogue-review.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="dialogue_review_report",
        path=str(path.resolve()),
        filename=path.name,
        media_type="application/json",
        metadata_json={
            "revision_id": report.revision_id,
            "brief_version": report.brief.version,
            "provider": "local",
            "model": METHOD,
            "sha256": file_digest(path),
            "context_applied_by_model": False,
        },
    )
    session.add(artifact)
    session.add(
        ProviderRun(
            project_id=job.project_id,
            job_id=job.id,
            capability="translation_reviewer",
            provider="local",
            model=METHOD,
            status="completed",
            latency_ms=round((time.monotonic() - started) * 1000),
            estimated_cost_inr=0,
            parameters_json={
                "brief_version": report.brief.version,
                "context_applied_by_model": False,
            },
        )
    )
    session.commit()
    return {"dialogue_review_artifact_id": artifact.id, "checked_lines": len(report.lines)}
