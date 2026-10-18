"""Durable provider-neutral adaptation. Generating alternatives never edits the timeline."""

from sqlalchemy import select

from .adaptation_timing import validate_timing_feedback
from .config import get_settings
from .dialogue_adaptation import make_report, read_adaptation_report, validate_results
from .dialogue_prompt import GENERATION, PROMPT_VERSION, adaptation_requests
from .dialogue_review import stale_reason
from .job_errors import StaleInput
from .media import file_digest
from .models import Artifact, ProviderRun
from .processing import check_cancel, checkpoint
from .providers import ProviderRegistry


def process_adapt_dialogue(session, job):
    existing = session.scalar(
        select(Artifact).where(
            Artifact.job_id == job.id, Artifact.kind == "dialogue_adaptation_report"
        )
    )
    if existing:
        read_adaptation_report(session, existing)
        return {"adaptation_artifact_id": existing.id}
    inputs = job.input_json
    if (
        inputs.get("prompt_version") != PROMPT_VERSION
        or inputs.get("generation_parameters") != GENERATION
    ):
        raise StaleInput("Dialogue prompt profile changed; schedule a new adaptation")
    checkpoint(session, job, "preparing_dialogue_adaptation")
    reason = stale_reason(session, job.project_id, inputs)
    if reason:
        raise StaleInput(reason)
    validate_timing_feedback(session, job.project_id, inputs)
    directory = get_settings().storage_root / job.project_id / "dialogue-adaptation" / job.id
    completed = validate_results(
        inputs, job.project_id, job.checkpoint_json.get("adaptation_completed_lines", [])
    )
    reused_count = len(completed)

    def progress(values):
        nonlocal completed
        values = validate_results(inputs, job.project_id, values)
        if values[: len(completed)] != completed:
            raise ValueError("Adapter changed previously committed dialogue results")
        reason = stale_reason(session, job.project_id, inputs)
        if reason:
            raise StaleInput(reason)
        validate_timing_feedback(session, job.project_id, inputs)
        check_cancel(session, job)
        job.progress = len(values) / len(inputs["review_ids"]) * 0.95
        job.phase = "adapting_dialogue"
        job.checkpoint_json = {**job.checkpoint_json, "adaptation_completed_lines": values}
        session.commit()
        completed = values

    payload = (
        ProviderRegistry(get_settings())
        .dialogue_adapter(job.provider, inputs)
        .adapt(
            {
                "prompt_version": PROMPT_VERSION,
                "parameters": GENERATION,
                "lines": adaptation_requests(inputs, job.project_id),
                "completed_lines": completed,
            },
            directory,
            cancel=lambda: check_cancel(session, job),
            progress=progress,
        )
    )
    if any(
        payload.get(key) != wanted
        for key, wanted in {
            "provider": job.provider,
            "model": inputs["model"],
            "prompt_version": PROMPT_VERSION,
            "parameters": GENERATION,
        }.items()
    ):
        raise ValueError("Dialogue adapter returned mismatched model/prompt provenance")
    values = validate_results(inputs, job.project_id, payload["lines"], complete=True)
    progress(values)
    runtime = {
        **{key: payload["runtime"][key] for key in ("elapsed_ms", "peak_rss_mib", "threads")},
        "engine_tag": inputs["model_manifest"]["engine_tag"],
        "engine_commit": inputs["model_manifest"]["engine_commit"],
        "reused_lines": reused_count,
    }
    checkpoint(session, job, "saving_dialogue_alternatives", adaptation_runtime=runtime)
    report = make_report(inputs, job.project_id, values, runtime)
    reason = stale_reason(session, job.project_id, inputs)
    if reason:
        raise StaleInput(reason)
    validate_timing_feedback(session, job.project_id, inputs)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "dialogue-alternatives.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="dialogue_adaptation_report",
        path=str(path.resolve()),
        filename=path.name,
        media_type="application/json",
        metadata_json={
            "revision_id": report.revision_id,
            "brief_version": report.brief.version,
            "provider": job.provider,
            "model": report.model,
            "sha256": file_digest(path),
            "prompt_version": PROMPT_VERSION,
            "context_supplied_to_model": True,
            "candidates": {
                key: value["candidate_id"]
                for key, value in inputs.get("timing_feedback", {}).items()
            },
        },
    )
    session.add(artifact)
    for line in values:
        session.add(
            ProviderRun(
                project_id=job.project_id,
                job_id=job.id,
                capability="dialogue_adapter",
                provider=job.provider,
                model=inputs["model"],
                status="completed",
                latency_ms=line["latency_ms"],
                estimated_cost_inr=0,
                parameters_json={
                    "segment_id": line["segment_id"],
                    "prompt_version": PROMPT_VERSION,
                    "prompt_sha256": line["prompt_sha256"],
                    "request_sha256": line["request_sha256"],
                    "prompt_tokens": line["prompt_tokens"],
                    **report.generation_parameters,
                },
            )
        )
    session.commit()
    return {"adaptation_artifact_id": artifact.id, "adapted_lines": len(values)}
