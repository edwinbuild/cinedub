"""Explicit model-draft application keeps version/history and invalidates old voice takes."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from ..dependencies import SessionDep
from ..dialogue_adaptation import read_adaptation_report, script_warnings
from ..jobs import ACTIVE, write_lock
from ..models import Artifact, Job, Project, Segment, SegmentEdit
from ..schemas import DialogueAdaptationApply, DialogueAdaptationReport, SegmentRead

router = APIRouter(tags=["dialogue-adaptation"])


def require_report(session, artifact_id):
    artifact = session.get(Artifact, artifact_id)
    if not artifact or artifact.kind != "dialogue_adaptation_report":
        raise HTTPException(404, "Dialogue adaptation report not found")
    try:
        return read_adaptation_report(session, artifact)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(
            409, "Dialogue alternatives are unavailable or changed; adapt again"
        ) from exc


@router.get("/dialogue-adaptation-reports/{artifact_id}", response_model=DialogueAdaptationReport)
def inspect_adaptation(artifact_id: str, session: SessionDep):
    return require_report(session, artifact_id)


@router.post("/dialogue-adaptation-reports/{artifact_id}/apply", response_model=SegmentRead)
def apply_adaptation(artifact_id: str, payload: DialogueAdaptationApply, session: SessionDep):
    write_lock(session)
    report = require_report(session, artifact_id)
    if report.stale_reason:
        raise HTTPException(409, report.stale_reason)
    project = session.get(Project, report.project_id)
    if project.active_revision_id != report.revision_id:
        raise HTTPException(409, "Activate this timeline before applying alternatives")
    if session.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Wait for active processing before applying alternatives")
    evidence = next((line for line in report.lines if line.segment_id == payload.segment_id), None)
    if not evidence:
        raise HTTPException(422, "This line is not in the adaptation report")
    option = next(item for item in evidence.alternatives if item.kind == payload.kind)
    if not option.eligible_for_application or script_warnings(option.text):
        raise HTTPException(422, "Wrong-script or control-marker output must be corrected manually")
    line = session.get(Segment, payload.segment_id)
    if line.version != payload.expected_version:
        raise HTTPException(409, "Saved line changed; refresh before applying")
    if not payload.language_reviewed:
        raise HTTPException(422, "Verify Malayalam meaning and naturalness before applying")
    if (line.human_edited or line.status == "approved") and not payload.replace_reviewed_text:
        raise HTTPException(422, "Confirm replacing previously edited or approved text")
    if (option.findings or option.warnings) and not payload.issues_reviewed:
        raise HTTPException(422, "Review all terminology, number and script warnings first")
    if line.translated_text == option.text:
        return line
    before = SegmentRead.model_validate(line).model_dump(mode="json")
    changed = session.execute(
        update(Segment)
        .where(
            Segment.id == line.id,
            Segment.version == payload.expected_version,
        )
        .values(
            translated_text=option.text,
            status="needs_review",
            human_edited=True,
            selected_candidate_id=None,
            version=Segment.version + 1,
            delivery_json={
                **line.delivery_json,
                "applied_dialogue_adaptation_artifact_id": artifact_id,
                "applied_dialogue_adaptation_kind": payload.kind,
            },
        )
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "Saved line changed; refresh before applying")
    session.refresh(line)
    session.add(
        SegmentEdit(
            segment_id=line.id,
            version=line.version,
            before_json=before,
            after_json={
                **SegmentRead.model_validate(line).model_dump(mode="json"),
                "adaptation_artifact_id": artifact_id,
                "adaptation_kind": payload.kind,
            },
        )
    )
    session.commit()
    return line
