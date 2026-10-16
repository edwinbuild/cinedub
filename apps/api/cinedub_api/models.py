from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    source_language: Mapped[str] = mapped_column(String(16), default="en-IN")
    target_language: Mapped[str] = mapped_column(String(16), default="ml-IN")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    duration_limit_seconds: Mapped[int] = mapped_column(Integer, default=120)
    active_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    budget_inr: Mapped[float] = mapped_column(Float, default=50.0)


class TimelineRevision(Base, TimestampMixin):
    __tablename__ = "timeline_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"))
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str] = mapped_column(String(48))
    model: Mapped[str] = mapped_column(String(120))
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)


class DialogueBrief(Base):
    """Append-only editorial context, scoped to one source-bound timeline revision."""

    __tablename__ = "dialogue_briefs"
    __table_args__ = (UniqueConstraint("revision_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("timeline_revisions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpeechEmotionReviewRecord(Base):
    __tablename__ = "speech_emotion_reviews"
    __table_args__ = (UniqueConstraint("artifact_id", "segment_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    direction: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(48))
    path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    active_stem_set_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class StemSet(Base, TimestampMixin):
    __tablename__ = "stem_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    provider: Mapped[str] = mapped_column(String(48))
    model: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), default="needs_review")
    version: Mapped[int] = mapped_column(Integer, default=1)
    artifacts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    reviews: Mapped[list["StemReviewRecord"]] = relationship(
        order_by="StemReviewRecord.created_at", lazy="selectin"
    )


class StemReviewRecord(Base):
    __tablename__ = "stem_review_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    stem_set_id: Mapped[str] = mapped_column(ForeignKey("stem_sets.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    reviewed_by: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MixRender(Base, TimestampMixin):
    __tablename__ = "mix_renders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("timeline_revisions.id"))
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"))
    stem_set_id: Mapped[str] = mapped_column(ForeignKey("stem_sets.id"))
    status: Mapped[str] = mapped_column(String(32), default="needs_review")
    version: Mapped[int] = mapped_column(Integer, default=1)
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifacts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_json: Mapped[dict] = mapped_column(JSON, default=dict)
    reviews: Mapped[list["MixReviewRecord"]] = relationship(
        order_by="MixReviewRecord.created_at", lazy="selectin"
    )


class MixReviewRecord(Base):
    __tablename__ = "mix_review_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mix_id: Mapped[str] = mapped_column(ForeignKey("mix_renders.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    reviewed_by: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text)
    certificate_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bundle_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Speaker(Base, TimestampMixin):
    __tablename__ = "speakers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(120))
    revision_id: Mapped[str | None] = mapped_column(ForeignKey("timeline_revisions.id"))
    voice_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Segment(Base, TimestampMixin):
    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    speaker_id: Mapped[str | None] = mapped_column(ForeignKey("speakers.id"), nullable=True)
    index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text, default="")
    translated_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    emotion_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    emotion_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy: Mapped[float | None] = mapped_column(Float, nullable=True)
    pace: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_json: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    revision_id: Mapped[str | None] = mapped_column(ForeignKey("timeline_revisions.id"))
    human_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    selected_candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class SegmentEdit(Base):
    __tablename__ = "segment_edits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    before_json: Mapped[dict] = mapped_column(JSON)
    after_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceProfile(Base, TimestampMixin):
    __tablename__ = "voice_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    speaker_id: Mapped[str] = mapped_column(ForeignKey("speakers.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(48))
    provider_voice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_assets.id"), nullable=True
    )
    consent_status: Mapped[str] = mapped_column(String(32), default="pending")
    voice_kind: Mapped[str] = mapped_column(String(16), default="clone")
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    reference_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    registration_status: Mapped[str] = mapped_column(String(32), default="unprepared")


class ConsentRecord(Base, TimestampMixin):
    __tablename__ = "consent_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    voice_profile_id: Mapped[str] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    attested_by: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    attested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    scope_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    provider: Mapped[str] = mapped_column(String(48), default="fake")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phase: Mapped[str] = mapped_column(String(48), default="queued")
    remote_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checkpoint_json: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    charged_estimate_inr: Mapped[float] = mapped_column(Float, default=0.0)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)

    @property
    def voice_profile_id(self) -> str | None:
        return self.input_json.get("voice_profile_id")


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ProviderRun(Base, TimestampMixin):
    __tablename__ = "provider_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    capability: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(48))
    model: Mapped[str] = mapped_column(String(120))
    parameters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
