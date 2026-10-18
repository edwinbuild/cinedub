"""Pipeline API: create (or preview), inspect, continue past a reviewed gate, cancel."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..dependencies import SessionDep, require_project
from ..jobs import ACTIVE, write_lock
from ..models import Job, MediaAsset, Pipeline
from ..pipeline import ACTIVE_PIPELINE, GATES, advance, continue_pipeline, plan_steps
from ..project_status import sync_project_status
from ..schemas import PipelineContinue, PipelineCreate, PipelinePlan, PipelineRead

router = APIRouter()


def require_pipeline(session, pipeline_id: str) -> Pipeline:
    pipeline = session.get(Pipeline, pipeline_id)
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    return pipeline


@router.post(
    "/projects/{project_id}/pipelines",
    response_model=PipelineRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_pipeline(project_id: str, payload: PipelineCreate, session: SessionDep):
    write_lock(session)
    project = require_project(session, project_id)
    source = session.get(MediaAsset, payload.source_asset_id)
    if not source or source.project_id != project.id:
        raise HTTPException(422, "Select a source asset belonging to this project")
    pipeline = Pipeline(
        project_id=project.id,
        source_asset_id=source.id,
        status="running",
        current_step=0,
        steps_json=plan_steps(payload),
        options_json=payload.model_dump(mode="json"),
        budget_confirmed_inr=payload.confirmed_budget_inr,
    )
    if session.scalar(
        select(Pipeline.id).where(
            Pipeline.project_id == project.id, Pipeline.status.in_(ACTIVE_PIPELINE)
        )
    ):
        raise HTTPException(409, "Another pipeline is active for this project")
    if session.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Another job is active; wait or cancel it first")
    session.add(pipeline)
    session.flush()
    advance(session, pipeline)
    sync_project_status(session, project)
    session.commit()
    session.refresh(pipeline)
    return pipeline


@router.post("/projects/{project_id}/pipelines/plan", response_model=PipelinePlan)
async def plan_pipeline(project_id: str, payload: PipelineCreate, session: SessionDep):
    """Preview the ordered steps and gates without queueing anything."""
    require_project(session, project_id)
    return PipelinePlan(steps=plan_steps(payload), gates=GATES)


@router.get("/projects/{project_id}/pipelines", response_model=list[PipelineRead])
async def list_pipelines(project_id: str, session: SessionDep):
    require_project(session, project_id)
    return session.scalars(
        select(Pipeline)
        .where(Pipeline.project_id == project_id)
        .order_by(Pipeline.created_at.desc())
    ).all()


@router.get("/pipelines/{pipeline_id}", response_model=PipelineRead)
async def get_pipeline(pipeline_id: str, session: SessionDep):
    return require_pipeline(session, pipeline_id)


@router.post("/pipelines/{pipeline_id}/continue", response_model=PipelineRead)
async def continue_after_review(pipeline_id: str, payload: PipelineContinue, session: SessionDep):
    write_lock(session)
    pipeline = require_pipeline(session, pipeline_id)
    try:
        continue_pipeline(session, pipeline, payload.confirmed_budget_inr)
    except HTTPException:
        session.commit()  # Keep the refreshed gate explanation.
        raise
    sync_project_status(session, pipeline.project_id)
    session.commit()
    session.refresh(pipeline)
    return pipeline


@router.post("/pipelines/{pipeline_id}/cancel", response_model=PipelineRead)
async def cancel_pipeline(pipeline_id: str, session: SessionDep):
    write_lock(session)
    pipeline = require_pipeline(session, pipeline_id)
    if pipeline.status not in ACTIVE_PIPELINE:
        return pipeline
    for step in pipeline.steps_json:
        job = session.get(Job, step["job_id"]) if step.get("job_id") else None
        if job and job.status in ACTIVE:
            job.cancel_requested = True
            if job.status == "queued":
                job.status = job.phase = "cancelled"
    pipeline.status = "cancelled"
    pipeline.gate_reason = "Cancelled by the editor; completed work is kept"
    sync_project_status(session, pipeline.project_id)
    session.commit()
    session.refresh(pipeline)
    return pipeline
