"""Saved editorial direction uses append-only versions and optimistic concurrency."""

from fastapi import APIRouter, HTTPException

from ..dependencies import SessionDep, require_project
from ..dialogue_review import latest_brief, read_dialogue_review
from ..jobs import write_lock
from ..models import Artifact, DialogueBrief, Speaker, TimelineRevision
from ..schemas import DialogueBriefRead, DialogueBriefUpdate, DialogueReviewReport

router = APIRouter(tags=["dialogue-brief"])


def require_revision(session, project_id, revision_id):
    require_project(session, project_id)
    revision = session.get(TimelineRevision, revision_id)
    if not revision or revision.project_id != project_id:
        raise HTTPException(404, "Timeline revision not found")


@router.get(
    "/projects/{project_id}/revisions/{revision_id}/dialogue-brief",
    response_model=DialogueBriefRead,
)
async def get_brief(project_id: str, revision_id: str, session: SessionDep):
    require_revision(session, project_id, revision_id)
    return latest_brief(session, project_id, revision_id)


@router.post(
    "/projects/{project_id}/revisions/{revision_id}/dialogue-brief",
    response_model=DialogueBriefRead,
)
async def save_brief(
    project_id: str, revision_id: str, payload: DialogueBriefUpdate, session: SessionDep
):
    write_lock(session)
    require_revision(session, project_id, revision_id)
    current = latest_brief(session, project_id, revision_id)
    if current.version != payload.expected_version:
        raise HTTPException(409, "Saved brief changed; load the latest brief before saving")
    for direction in payload.content.characters:
        speaker = session.get(Speaker, direction.speaker_id)
        if not speaker or speaker.project_id != project_id or speaker.revision_id != revision_id:
            raise HTTPException(422, "Character direction must use a speaker from this revision")
    if current.content == payload.content:
        return current
    session.add(
        DialogueBrief(
            project_id=project_id,
            revision_id=revision_id,
            version=current.version + 1,
            content_json=payload.content.model_dump(mode="json"),
        )
    )
    session.commit()
    return latest_brief(session, project_id, revision_id)


@router.get("/dialogue-review-reports/{artifact_id}", response_model=DialogueReviewReport)
def review_report(artifact_id: str, session: SessionDep):
    artifact = session.get(Artifact, artifact_id)
    if not artifact or artifact.kind != "dialogue_review_report":
        raise HTTPException(404, "Editorial review report not found")
    try:
        return read_dialogue_review(session, artifact)
    except (ValueError, OSError) as exc:
        raise HTTPException(
            409, "Editorial report is unavailable or changed; review again"
        ) from exc
