"""Response builders shared by project and artifact routes."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .consent import artifact_block_reason
from .dialogue_review import latest_brief
from .jobs import budget_totals
from .mixes import mix_read
from .models import (
    Artifact,
    Job,
    MediaAsset,
    MixRender,
    Pipeline,
    Project,
    Speaker,
    StemSet,
    TimelineRevision,
    VoiceProfile,
)
from .schemas import (
    ArtifactRead,
    JobRead,
    MediaAssetRead,
    PipelineRead,
    ProjectDetail,
    ProjectRead,
    RevisionRead,
    SegmentRead,
    SpeakerRead,
    StemSetRead,
    VoiceProfileRead,
)
from .timeline import revision_segments

settings = get_settings()


def artifact_read(artifact: Artifact, session: Session | None = None) -> ArtifactRead:
    return ArtifactRead(
        id=artifact.id,
        project_id=artifact.project_id,
        job_id=artifact.job_id,
        kind=artifact.kind,
        filename=artifact.filename,
        media_type=artifact.media_type,
        created_at=artifact.created_at,
        download_url=f"/artifacts/{artifact.id}/download",
        content_url=f"/artifacts/{artifact.id}/content",
        metadata_json=artifact.metadata_json,
        access_blocked_reason=artifact_block_reason(session, artifact) if session else None,
        sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
    )


def project_detail(session: Session, project: Project) -> ProjectDetail:
    assets = session.scalars(
        select(MediaAsset)
        .where(MediaAsset.project_id == project.id)
        .order_by(MediaAsset.created_at)
    ).all()
    speakers = session.scalars(
        select(Speaker)
        .where(Speaker.project_id == project.id, Speaker.revision_id == project.active_revision_id)
        .order_by(Speaker.label)
    ).all()
    segments = revision_segments(session, project.id, project.active_revision_id)
    jobs = session.scalars(
        select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc())
    ).all()
    artifacts = session.scalars(
        select(Artifact)
        .where(Artifact.project_id == project.id)
        .order_by(Artifact.created_at.desc())
    ).all()
    pipeline = session.scalar(
        select(Pipeline)
        .where(Pipeline.project_id == project.id)
        .order_by(Pipeline.created_at.desc())
    )
    return ProjectDetail(
        **ProjectRead.model_validate(project).model_dump(),
        latest_pipeline=PipelineRead.model_validate(pipeline) if pipeline else None,
        dialogue_brief=(
            latest_brief(session, project.id, project.active_revision_id)
            if project.active_revision_id
            else None
        ),
        assets=[MediaAssetRead.model_validate(item) for item in assets],
        speakers=[SpeakerRead.model_validate(item) for item in speakers],
        segments=[SegmentRead.model_validate(item) for item in segments],
        jobs=[JobRead.model_validate(item) for item in jobs],
        artifacts=[artifact_read(item, session) for item in artifacts],
        revisions=[
            RevisionRead.model_validate(item)
            for item in session.scalars(
                select(TimelineRevision)
                .where(TimelineRevision.project_id == project.id)
                .order_by(TimelineRevision.created_at.desc())
            ).all()
        ],
        spent_estimate_inr=budget_totals(session, project.id)[0],
        reserved_inr=budget_totals(session, project.id)[1],
        mixes=[
            mix_read(session, item)
            for item in session.scalars(
                select(MixRender)
                .where(MixRender.project_id == project.id)
                .order_by(MixRender.created_at.desc())
            ).all()
        ],
        stem_sets=[
            StemSetRead.model_validate(item)
            for item in session.scalars(
                select(StemSet)
                .where(StemSet.project_id == project.id)
                .order_by(StemSet.created_at.desc())
            ).all()
        ],
        voice_profiles=[
            VoiceProfileRead.model_validate(item)
            for item in session.scalars(
                select(VoiceProfile)
                .where(VoiceProfile.project_id == project.id)
                .order_by(VoiceProfile.updated_at.desc())
            ).all()
        ],
    )
