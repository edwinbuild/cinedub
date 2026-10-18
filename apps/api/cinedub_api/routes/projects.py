"""Projects: list, create, inspect and budget."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..config import get_settings
from ..dependencies import SessionDep, require_project
from ..jobs import budget_totals, write_lock
from ..models import (
    Project,
)
from ..project_deletion import delete_project
from ..schemas import (
    BudgetUpdate,
    ProjectCreate,
    ProjectDeletion,
    ProjectDetail,
    ProjectRead,
)
from ..views import project_detail

router = APIRouter()
settings = get_settings()


@router.get("/projects", response_model=list[ProjectRead])
async def list_projects(session: SessionDep) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.updated_at.desc())).all())


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, session: SessionDep) -> Project:
    project = Project(
        **payload.model_dump(),
        duration_limit_seconds=settings.max_duration_seconds,
        budget_inr=settings.project_budget_inr,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: str, session: SessionDep) -> ProjectDetail:
    return project_detail(session, require_project(session, project_id))


@router.patch("/projects/{project_id}/budget", response_model=ProjectDetail)
async def change_budget(project_id: str, payload: BudgetUpdate, session: SessionDep):
    write_lock(session)
    project = require_project(session, project_id)
    spent, reserved = budget_totals(session, project_id)
    if payload.budget_inr < spent + reserved:
        raise HTTPException(422, "Budget cannot be lower than spent and reserved estimates")
    project.budget_inr = payload.budget_inr
    session.commit()
    return project_detail(session, project)


@router.delete("/projects/{project_id}", response_model=ProjectDeletion)
async def remove_project(project_id: str, confirm: str, session: SessionDep):
    """Permanently delete a project. `confirm` must repeat the exact project name."""
    write_lock(session)
    project = require_project(session, project_id)
    if confirm != project.name:
        raise HTTPException(422, "Type the exact project name to confirm deletion")
    return ProjectDeletion(project_id=project_id, deleted_rows=delete_project(session, project))
