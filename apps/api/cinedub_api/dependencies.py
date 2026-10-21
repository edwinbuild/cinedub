"""Shared HTTP dependencies without importing the application object."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from .database import get_session
from .models import Project

SessionDep = Annotated[Session, Depends(get_session)]


def require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project
