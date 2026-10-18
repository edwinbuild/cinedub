"""Timeline lines, speakers and revisions."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..config import get_settings
from ..dependencies import SessionDep, require_project
from ..jobs import ACTIVE, write_lock
from ..line_editing import apply_line_edit
from ..models import (
    Job,
    Segment,
    Speaker,
    TimelineRevision,
    new_id,
)
from ..project_status import sync_project_status
from ..schemas import (
    ProjectDetail,
    RevisionActivate,
    RevisionRead,
    SegmentRead,
    SegmentUpdate,
    SpeakerCreate,
    SpeakerRead,
    SpeakerUpdate,
)
from ..views import project_detail

router = APIRouter()
settings = get_settings()


@router.patch("/segments/{segment_id}", response_model=SegmentRead)
async def update_segment(
    segment_id: str,
    payload: SegmentUpdate,
    session: SessionDep,
) -> Segment:
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    return apply_line_edit(session, segment, payload)


@router.post("/projects/{project_id}/speakers", response_model=SpeakerRead, status_code=201)
async def create_speaker(project_id: str, payload: SpeakerCreate, session: SessionDep):
    write_lock(session)
    require_project(session, project_id)
    revision = session.get(TimelineRevision, payload.revision_id)
    if not revision or revision.project_id != project_id:
        raise HTTPException(422, "Select a revision belonging to this project")
    name = payload.display_name.strip()
    if not name:
        raise HTTPException(422, "Speaker name cannot be blank")
    speaker = Speaker(
        project_id=project_id,
        revision_id=revision.id,
        label=f"MANUAL_{new_id()}",
        display_name=name,
    )
    session.add(speaker)
    session.commit()
    return speaker


@router.patch("/speakers/{speaker_id}", response_model=SpeakerRead)
async def rename_speaker(speaker_id: str, payload: SpeakerUpdate, session: SessionDep):
    speaker = session.get(Speaker, speaker_id)
    if not speaker:
        raise HTTPException(404, "Speaker not found")
    if not payload.display_name.strip():
        raise HTTPException(422, "Speaker name must not be blank")
    speaker.display_name = payload.display_name.strip()
    session.commit()
    return speaker


@router.get("/projects/{project_id}/revisions", response_model=list[RevisionRead])
async def list_revisions(project_id: str, session: SessionDep):
    require_project(session, project_id)
    return session.scalars(
        select(TimelineRevision)
        .where(TimelineRevision.project_id == project_id)
        .order_by(TimelineRevision.created_at.desc())
    ).all()


@router.post(
    "/projects/{project_id}/revisions/{revision_id}/activate", response_model=ProjectDetail
)
async def activate_revision(
    project_id: str, revision_id: str, payload: RevisionActivate, session: SessionDep
):
    write_lock(session)
    project = require_project(session, project_id)
    revision = session.get(TimelineRevision, revision_id)
    if not revision or revision.project_id != project.id:
        raise HTTPException(404, "Timeline revision not found")
    if project.active_revision_id != payload.expected_active_revision_id:
        raise HTTPException(409, "Active timeline changed; refresh first")
    if session.scalar(select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Wait for active processing before switching timelines")
    project.active_revision_id = revision.id
    sync_project_status(session, project)
    session.commit()
    return project_detail(session, project)
