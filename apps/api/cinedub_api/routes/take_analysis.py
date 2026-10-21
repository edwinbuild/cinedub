"""Typed source-versus-take evidence with the same consent quarantine as audio downloads."""

from fastapi import APIRouter, HTTPException

from ..dependencies import SessionDep
from ..models import Artifact
from ..schemas import TakePerformanceReport
from ..take_analysis import read_take_report

router = APIRouter(tags=["take-analysis"])


@router.get("/take-analysis-reports/{artifact_id}", response_model=TakePerformanceReport)
def take_analysis_report(artifact_id: str, session: SessionDep):
    artifact = session.get(Artifact, artifact_id)
    if not artifact or artifact.kind != "take_performance_report":
        raise HTTPException(404, "Take analysis report not found")
    try:
        return read_take_report(session, artifact)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(
            409, "Take analysis report is unavailable or changed; analyze again"
        ) from exc
