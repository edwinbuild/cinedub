from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LanguageCode = Literal["en-IN", "ml-IN"]
ProjectStatus = Literal["draft", "processing", "review", "ready", "failed"]
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
SegmentStatus = Literal["draft", "translated", "voiced", "approved", "needs_review"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_language: Literal["en-IN"] = "en-IN"
    target_language: Literal["ml-IN"] = "ml-IN"


class BudgetUpdate(BaseModel):
    budget_inr: float = Field(gt=0, le=100_000, allow_inf_nan=False)


class ProjectRead(ORMModel):
    id: str
    name: str
    source_language: LanguageCode
    target_language: LanguageCode
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    active_revision_id: str | None
    budget_inr: float


class MediaAssetRead(ORMModel):
    id: str
    project_id: str
    kind: str
    filename: str
    media_type: str
    duration_ms: int | None
    created_at: datetime
    active_stem_set_id: str | None


class StemReviewRecordRead(ORMModel):
    id: str
    version: int
    status: Literal["approved", "rejected"]
    reviewed_by: str
    note: str
    created_at: datetime


class StemSetRead(ORMModel):
    id: str
    source_asset_id: str
    job_id: str
    provider: str
    model: str
    status: Literal["needs_review", "approved", "rejected"]
    version: int
    artifacts_json: dict
    metadata_json: dict
    created_at: datetime
    reviews: list[StemReviewRecordRead]


class StemReview(BaseModel):
    status: Literal["approved", "rejected"]
    expected_version: int = Field(ge=1)
    expected_active_stem_set_id: str | None
    reviewed_by: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)


class MixSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["stereo-review-v1"] = "stereo-review-v1"
    dialogue_gain_db: float = Field(default=0, ge=-24, le=12, allow_inf_nan=False)
    music_gain_db: float = Field(default=0, ge=-60, le=12, allow_inf_nan=False)
    effects_gain_db: float = Field(default=0, ge=-60, le=12, allow_inf_nan=False)
    music_muted: bool = False
    effects_muted: bool = False
    target_lufs: float = Field(default=-23, ge=-30, le=-14, allow_inf_nan=False)
    true_peak_dbfs: float = Field(default=-2, ge=-6, le=-2, allow_inf_nan=False)
    allow_dynamic_normalization: bool = False


class MixReview(BaseModel):
    status: Literal["approved", "rejected"]
    expected_version: int = Field(ge=1)
    reviewed_by: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)
    listening_confirmed: bool = False


class MixReviewRecordRead(StemReviewRecordRead):
    certificate_artifact_id: str | None
    bundle_artifact_id: str | None


class MixRenderRead(ORMModel):
    id: str
    job_id: str
    revision_id: str
    source_asset_id: str
    stem_set_id: str
    status: Literal["needs_review", "approved", "rejected"]
    version: int
    settings_json: dict
    artifacts_json: dict
    quality_json: dict
    created_at: datetime
    reviews: list[MixReviewRecordRead]
    stale_reason: str | None = None


class SpeakerRead(ORMModel):
    id: str
    project_id: str
    label: str
    display_name: str
    revision_id: str | None
    voice_profile_id: str | None


class SpeakerUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class SpeakerCreate(SpeakerUpdate):
    revision_id: str


class RevisionRead(ORMModel):
    id: str
    source_asset_id: str | None
    provider: str
    model: str
    warnings_json: list[str]
    created_at: datetime


class RevisionActivate(BaseModel):
    expected_active_revision_id: str | None


class SegmentRead(ORMModel):
    id: str
    project_id: str
    speaker_id: str | None
    index: int
    start_ms: int
    end_ms: int
    source_text: str
    translated_text: str
    status: SegmentStatus
    emotion_label: str | None
    emotion_confidence: float | None
    energy: float | None
    pace: float | None
    version: int
    updated_at: datetime
    revision_id: str | None
    human_edited: bool
    warnings_json: list[str]
    selected_candidate_id: str | None


class SegmentUpdate(BaseModel):
    source_text: str | None = Field(default=None, min_length=1, max_length=4000)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)
    translated_text: str | None = Field(default=None, max_length=4000)
    speaker_id: str | None = None
    emotion_label: str | None = Field(default=None, max_length=32)
    energy: float | None = Field(default=None, ge=0, le=1)
    pace: float | None = Field(default=None, ge=0.5, le=2)
    status: SegmentStatus | None = None
    expected_version: int = Field(ge=1)


class JobCreate(BaseModel):
    stage: Literal[
        "ingest",
        "demo_pipeline",
        "transcribe",
        "translate",
        "synthesize",
        "export",
        "render_preview",
        "prepare_reference",
        "register_voice",
        "delete_voice",
        "separate",
        "render_mix",
    ]
    provider: Literal["fake", "sarvam", "local"] | None = None
    source_asset_id: str | None = None
    revision_id: str | None = None
    num_speakers: int | None = Field(default=None, ge=1, le=20)
    segment_ids: list[str] | None = None
    regenerate: bool = False
    allow_incomplete: bool = False
    force_new: bool = False
    voice_profile_id: str | None = None
    registration_allowance_inr: float | None = Field(
        default=None, gt=0, le=1000, allow_inf_nan=False
    )
    reference_reviewed: bool = False
    transcription_input: Literal["original", "dialogue_stem"] = "original"
    mix_settings: MixSettings = Field(default_factory=MixSettings)


class JobEstimate(BaseModel):
    estimated_cost_inr: float
    spent_estimate_inr: float
    reserved_inr: float
    remaining_inr: float
    budget_inr: float
    cached_job_id: str | None = None


class JobRead(ORMModel):
    id: str
    project_id: str
    stage: str
    status: JobStatus
    progress: float
    provider: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    phase: str
    remote_job_id: str | None
    estimated_cost_inr: float
    charged_estimate_inr: float
    retryable: bool
    warnings_json: list[str]
    output_json: dict
    voice_profile_id: str | None


class ArtifactRead(ORMModel):
    id: str
    project_id: str
    job_id: str | None
    kind: str
    filename: str
    media_type: str
    created_at: datetime
    download_url: str
    content_url: str
    metadata_json: dict
    access_blocked_reason: str | None = None


class ProjectDetail(ProjectRead):
    assets: list[MediaAssetRead]
    speakers: list[SpeakerRead]
    segments: list[SegmentRead]
    jobs: list[JobRead]
    artifacts: list[ArtifactRead]
    revisions: list[RevisionRead]
    spent_estimate_inr: float
    reserved_inr: float
    voice_profiles: list["VoiceProfileRead"]
    stem_sets: list[StemSetRead]
    mixes: list[MixRenderRead]


class ConsentInput(BaseModel):
    approved: bool
    attested_by: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)
    rights_holder: str = Field(min_length=1, max_length=120)
    allows_provider_upload: bool
    clean_single_speaker: bool


class VoiceProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speaker_id: str
    display_name: str = Field(min_length=1, max_length=100)
    provider: Literal["sarvam", "fake"] = "sarvam"
    reference_asset_id: str
    reference_start_ms: int = Field(ge=0)
    reference_end_ms: int = Field(gt=0)
    consent: ConsentInput


class VoiceProfileRead(ORMModel):
    id: str
    project_id: str
    speaker_id: str
    display_name: str
    provider: str
    provider_voice_id: str | None
    reference_asset_id: str | None
    consent_status: str
    voice_kind: str
    settings_json: dict
    version: int
    reference_artifact_id: str | None
    registration_status: str


class VoiceProfileSelection(BaseModel):
    profile_id: str
    expected_profile_id: str | None


class ConsentRevocation(BaseModel):
    attested_by: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)


class ConsentRecordRead(ORMModel):
    id: str
    voice_profile_id: str
    status: str
    attested_by: str
    note: str
    attested_at: datetime
    scope_json: dict


class StockVoiceAssignment(BaseModel):
    provider: Literal["fake", "sarvam"]
    voice_id: str = Field(min_length=1, max_length=120)
    pace: float = Field(default=1.0, ge=0.5, le=2.0)


class VoiceChoice(BaseModel):
    id: str
    display_name: str
    provider: str
    model: str
    language: str


class CandidateSelection(BaseModel):
    artifact_id: str
    expected_version: int = Field(ge=1)


class CapabilityRead(BaseModel):
    capability: str
    selected_provider: str
    available: bool
    reason: str | None = None
    configured: bool = False
    implemented: bool = False
    verified: bool = False


class HardwareRead(BaseModel):
    gpu_detected: bool
    gpu_name: str | None
    cuda_ready: bool
    gpu_error: str | None
    memory_total_gib: float | None
    memory_available_gib: float | None
    storage_free_gib: float
    ffmpeg_ready: bool
