"""Pipeline orchestration: run the dubbing stages in order and pause at human review gates.

A pipeline never approves anything. Gates open only on an explicit `continue` and only once
their predicate is satisfied by saved human review state. Every job is submitted through the
same path as a manual request, so budgets, consent, staleness and the one-active-job rule apply.
"""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .jobs import ACTIVE, CostLimitExceeded, submit_job
from .models import Job, MediaAsset, MixRender, Pipeline, Project, Segment, Speaker, StemSet
from .observability import log_event
from .schemas import JobFields, PipelineCreate

ACTIVE_PIPELINE = ("running", "awaiting_review")
GATES = {
    "stems_approved": "Listen to the separated stems and approve them for this source",
    "speakers_assigned": "Review the transcript and assign a speaker to every line",
    "lines_approved": "Review, correct and approve every translated line",
    "voices_assigned": "Assign an approved voice to every speaker",
    "takes_selected": "Listen and select a timing-ready take for every line",
    "mix_accepted": "Listen to the mix, approve it and wait for the accepted export bundle",
}


def plan_steps(options: PipelineCreate) -> list[dict]:
    """The ordered steps for one pipeline. Optional stages are included only when requested."""
    steps = [{"key": "ingest", "kind": "job", "stage": "ingest"}]
    if options.separate_dialogue:
        steps += [
            {"key": "separate", "kind": "job", "stage": "separate"},
            {"key": "stems_approved", "kind": "gate"},
        ]
    steps += [
        {"key": "transcribe", "kind": "job", "stage": "transcribe"},
        {"key": "speakers_assigned", "kind": "gate"},
        {"key": "translate", "kind": "job", "stage": "translate"},
    ]
    if options.adapt_dialogue:
        steps += [
            {"key": "review_translation", "kind": "job", "stage": "review_translation"},
            {"key": "adapt_dialogue", "kind": "job", "stage": "adapt_dialogue"},
        ]
    steps += [
        {"key": "lines_approved", "kind": "gate"},
        {"key": "voices_assigned", "kind": "gate"},
        {"key": "synthesize", "kind": "job", "stage": "synthesize"},
        {"key": "takes_selected", "kind": "gate"},
    ]
    if options.analyze_performance:
        steps += [
            {"key": "align", "kind": "job", "stage": "align"},
            {"key": "analyze_takes", "kind": "job", "stage": "analyze_takes"},
            {"key": "analyze_emotion", "kind": "job", "stage": "analyze_emotion"},
        ]
    steps += [
        {"key": "render_mix", "kind": "job", "stage": "render_mix"},
        {"key": "mix_accepted", "kind": "gate"},
    ]
    for step in steps:
        step.update(status="pending", job_id=None)
    return steps


def _request(pipeline: Pipeline, stage: str) -> JobFields:
    options = pipeline.options_json
    audio = "dialogue_stem" if options.get("separate_dialogue") else "original"
    values = {"stage": stage}
    if stage in {"ingest", "separate"}:
        values["source_asset_id"] = pipeline.source_asset_id
    if stage == "transcribe":
        values.update(
            source_asset_id=pipeline.source_asset_id,
            transcription_input=audio,
            num_speakers=options.get("num_speakers"),
        )
    if stage in {"align", "analyze_takes", "analyze_emotion"}:
        values.update(source_asset_id=pipeline.source_asset_id, transcription_input=audio)
    return JobFields.model_validate(values)


def _lines(session: Session, project: Project) -> list[Segment]:
    if not project.active_revision_id:
        return []
    return session.scalars(
        select(Segment).where(
            Segment.project_id == project.id,
            Segment.revision_id == project.active_revision_id,
            Segment.retired.is_(False),
        )
    ).all()


def gate_blocker(session: Session, pipeline: Pipeline, gate: str) -> str | None:
    """None when the saved human review state satisfies the gate; otherwise what is missing."""
    project = session.get(Project, pipeline.project_id)
    lines = _lines(session, project)
    if gate == "stems_approved":
        source = session.get(MediaAsset, pipeline.source_asset_id)
        stems = (
            session.get(StemSet, source.active_stem_set_id) if source.active_stem_set_id else None
        )
        return None if stems and stems.status == "approved" else GATES[gate]
    if not lines:
        return "The active timeline has no dialogue lines"
    if gate == "speakers_assigned":
        missing = sum(1 for line in lines if not line.speaker_id)
        return f"{missing} lines have no speaker" if missing else None
    if gate == "lines_approved":
        pending = sum(
            1 for line in lines if line.status != "approved" or not line.translated_text.strip()
        )
        return f"{pending} lines are not approved" if pending else None
    if gate == "voices_assigned":
        speakers = {line.speaker_id for line in lines}
        missing = [
            speaker
            for speaker in speakers
            if not (record := session.get(Speaker, speaker)) or not record.voice_profile_id
        ]
        return f"{len(missing)} speakers have no voice" if missing else None
    if gate == "takes_selected":
        missing = sum(1 for line in lines if not line.selected_candidate_id)
        return f"{missing} lines have no selected take" if missing else None
    if gate == "mix_accepted":
        render = next(
            (step for step in pipeline.steps_json if step["key"] == "render_mix"), {}
        ).get("job_id")
        mix = (
            session.scalar(select(MixRender).where(MixRender.job_id == render)) if render else None
        )
        accepted = mix and any(
            review.status == "approved" and review.bundle_artifact_id for review in mix.reviews
        )
        return None if accepted else GATES[gate]
    raise ValueError(f"Unknown gate {gate}")


def _save(pipeline: Pipeline, steps: list[dict], **values) -> None:
    pipeline.steps_json = steps  # Reassign: JSON columns track replacement, not mutation.
    for key, value in values.items():
        setattr(pipeline, key, value)


def _spent(session: Session, pipeline: Pipeline) -> float:
    ids = [step["job_id"] for step in pipeline.steps_json if step.get("job_id")]
    if not ids:
        return 0.0
    jobs = session.scalars(select(Job).where(Job.id.in_(ids))).all()
    return round(sum(job.estimated_cost_inr for job in jobs), 6)


def advance(session: Session, pipeline: Pipeline) -> None:
    """Run forward from the current step until a job is running, a gate waits, or it ends."""
    project = session.get(Project, pipeline.project_id)
    while pipeline.current_step < len(pipeline.steps_json):
        steps = [dict(step) for step in pipeline.steps_json]
        step = steps[pipeline.current_step]
        if step["kind"] == "gate":
            if step["status"] != "completed":
                step["status"] = "awaiting"
                _save(
                    pipeline,
                    steps,
                    status="awaiting_review",
                    gate_reason=gate_blocker(session, pipeline, step["key"])
                    or "Ready: continue when you have reviewed this step",
                )
                log_event("pipeline_waiting", pipeline_id=pipeline.id, gate=step["key"])
                return
            _save(pipeline, steps, current_step=pipeline.current_step + 1)
            continue
        if step["job_id"]:
            job = session.get(Job, step["job_id"])
            if job.status in ACTIVE:
                _save(pipeline, steps, status="running", gate_reason=None)
                return
            if job.status != "completed":
                step["status"] = job.status
                _save(
                    pipeline,
                    steps,
                    status="failed" if job.status == "failed" else "cancelled",
                    gate_reason=job.error_message,
                    finished_at=datetime.now(UTC),
                )
                log_event("pipeline_stopped", pipeline_id=pipeline.id, step=step["key"])
                return
            step["status"] = "completed"
            _save(pipeline, steps, current_step=pipeline.current_step + 1)
            continue
        remaining = pipeline.budget_confirmed_inr - _spent(session, pipeline)
        try:
            job = submit_job(
                session, project, _request(pipeline, step["stage"]), cost_limit=remaining
            )
        except CostLimitExceeded as exc:
            step["status"] = "awaiting"
            _save(
                pipeline,
                steps,
                status="awaiting_review",
                gate_reason=f"Confirm a pipeline budget of at least ₹{exc.required:.2f} "
                f"to continue ({step['stage']} estimate ₹{exc.cost:.2f})",
            )
            return
        except HTTPException as exc:
            step["status"] = "failed"
            _save(
                pipeline,
                steps,
                status="failed",
                gate_reason=str(exc.detail),
                finished_at=datetime.now(UTC),
            )
            log_event("pipeline_stopped", pipeline_id=pipeline.id, step=step["key"])
            return
        session.flush()
        step.update(job_id=job.id, status="running")
        _save(pipeline, steps, status="running", gate_reason=None)
        log_event("pipeline_advanced", pipeline_id=pipeline.id, step=step["key"], job_id=job.id)
        if job.status in ACTIVE:
            return
    _save(
        pipeline,
        pipeline.steps_json,
        status="completed",
        gate_reason=None,
        finished_at=datetime.now(UTC),
    )
    log_event("pipeline_completed", pipeline_id=pipeline.id)


def pipeline_for_job(session: Session, job: Job) -> Pipeline | None:
    pipeline = session.scalar(
        select(Pipeline).where(
            Pipeline.project_id == job.project_id, Pipeline.status.in_([*ACTIVE_PIPELINE, "failed"])
        )
    )
    if not pipeline or pipeline.current_step >= len(pipeline.steps_json):
        return None
    return pipeline if pipeline.steps_json[pipeline.current_step].get("job_id") == job.id else None


def after_job(session: Session, job: Job) -> None:
    """Called once a pipeline job finishes (completed, failed or cancelled), or is resumed."""
    pipeline = pipeline_for_job(session, job)
    if not pipeline:
        return
    if job.status in ACTIVE:
        pipeline.status = "running"
        pipeline.gate_reason = None
        pipeline.finished_at = None
        return
    advance(session, pipeline)


def continue_pipeline(session: Session, pipeline: Pipeline, budget: float | None) -> None:
    if pipeline.status != "awaiting_review":
        raise HTTPException(409, "This pipeline is not waiting for review")
    if budget is not None:
        if budget < pipeline.budget_confirmed_inr:
            raise HTTPException(422, "A pipeline budget can only be raised")
        pipeline.budget_confirmed_inr = budget
    steps = [dict(step) for step in pipeline.steps_json]
    step = steps[pipeline.current_step]
    if step["kind"] == "gate":
        blocker = gate_blocker(session, pipeline, step["key"])
        if blocker:
            pipeline.gate_reason = blocker
            raise HTTPException(409, blocker)
        step["status"] = "completed"
        _save(pipeline, steps)
    else:
        step["status"] = "pending"  # Budget pause: retry the submission.
        _save(pipeline, steps)
    advance(session, pipeline)


def recover_pipelines(session: Session) -> None:
    """After a worker restart, settle active pipelines whose current job already stopped."""
    for pipeline in session.scalars(
        select(Pipeline).where(Pipeline.status.in_(ACTIVE_PIPELINE))
    ).all():
        if pipeline.current_step >= len(pipeline.steps_json):
            continue
        job_id = pipeline.steps_json[pipeline.current_step].get("job_id")
        job = session.get(Job, job_id) if job_id else None
        if job and job.status not in ACTIVE:
            advance(session, pipeline)
