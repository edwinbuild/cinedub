"""Permanent project deletion with consent and provider-cleanup guards.

Deletion removes every database row and stored file for one project. It is refused while
work is active, and while a cloned voice may still exist at a provider: the editor must
revoke consent and run the provider deletion job first, so no remote voice is orphaned.
"""

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .jobs import ACTIVE
from .models import (
    Artifact,
    ArtifactInput,
    ConsentRecord,
    DialogueBrief,
    Job,
    MediaAsset,
    MixRender,
    MixReviewRecord,
    Pipeline,
    Project,
    ProviderRun,
    Segment,
    SegmentEdit,
    Speaker,
    SpeakerReuse,
    SpeechEmotionReviewRecord,
    StemReviewRecord,
    StemSet,
    TimelineRevision,
    TimelineStructureEdit,
    VoiceProfile,
)
from .observability import log_event
from .pipeline import ACTIVE_PIPELINE
from .storage import storage

# Children before parents; tables without project_id are removed through their parent.
OWNED = [
    SpeakerReuse,
    TimelineStructureEdit,
    DialogueBrief,
    Pipeline,
    MixRender,
    StemSet,
    Segment,
    Speaker,
    VoiceProfile,
    Artifact,
    ProviderRun,
    Job,
    TimelineRevision,
    MediaAsset,
]
INDIRECT = [
    (SegmentEdit, SegmentEdit.segment_id, Segment),
    (SpeechEmotionReviewRecord, SpeechEmotionReviewRecord.artifact_id, Artifact),
    (StemReviewRecord, StemReviewRecord.stem_set_id, StemSet),
    (MixReviewRecord, MixReviewRecord.mix_id, MixRender),
    (ConsentRecord, ConsentRecord.voice_profile_id, VoiceProfile),
    (ArtifactInput, ArtifactInput.artifact_id, Artifact),
]


def deletion_blocker(session: Session, project: Project) -> str | None:
    if session.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(ACTIVE))):
        return "Wait for or cancel active processing before deleting this project"
    if session.scalar(
        select(Pipeline.id).where(
            Pipeline.project_id == project.id, Pipeline.status.in_(ACTIVE_PIPELINE)
        )
    ):
        return "Cancel the active pipeline before deleting this project"
    remote = session.scalar(
        select(VoiceProfile.id).where(
            VoiceProfile.project_id == project.id,
            VoiceProfile.voice_kind == "clone",
            VoiceProfile.provider_voice_id.is_not(None),
            VoiceProfile.provider != "fake",
        )
    )
    if remote:
        return (
            "A cloned voice may still exist at its provider. Revoke consent and run provider "
            "deletion for every cloned voice first"
        )
    return None


def delete_project(session: Session, project: Project) -> dict:
    blocker = deletion_blocker(session, project)
    if blocker:
        raise HTTPException(409, blocker)
    counts = {}
    for model, foreign_key, parent in INDIRECT:
        result = session.execute(
            delete(model).where(
                foreign_key.in_(select(parent.id).where(parent.project_id == project.id))
            )
        )
        counts[model.__tablename__] = result.rowcount
    for model in OWNED:
        result = session.execute(delete(model).where(model.project_id == project.id))
        counts[model.__tablename__] = result.rowcount
    project_id = project.id
    session.delete(project)
    session.flush()
    # Files go last: a database failure above leaves the project fully intact.
    session.commit()
    storage().delete_project(project_id)
    log_event("project_deleted", project_id=project_id, rows=sum(counts.values()))
    return counts
