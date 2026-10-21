from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_language: Literal["en-IN"] = "en-IN"
    target_language: Literal["ml-IN"] = "ml-IN"


class ProjectRead(ORMModel):
    id: str
    name: str
    source_language: str
    target_language: str
    status: str
    created_at: datetime
    updated_at: datetime


class MediaAssetRead(ORMModel):
    id: str
    project_id: str
    kind: str
    filename: str
    media_type: str
    duration_ms: int | None
    created_at: datetime


class SpeakerRead(ORMModel):
    id: str
    project_id: str
    label: str
    display_name: str


class SegmentRead(ORMModel):
    id: str
    project_id: str
    speaker_id: str | None
    index: int
    start_ms: int
    end_ms: int
    source_text: str
    translated_text: str
    status: str
    emotion_label: str | None
    emotion_confidence: float | None
    energy: float | None
    pace: float | None
    version: int
    updated_at: datetime


class SegmentUpdate(BaseModel):
    translated_text: str | None = Field(default=None, max_length=4000)
    speaker_id: str | None = None
    emotion_label: str | None = Field(default=None, max_length=32)
    energy: float | None = Field(default=None, ge=0, le=1)
    pace: float | None = Field(default=None, ge=0.5, le=2)
    status: Literal["draft", "translated", "voiced", "approved", "needs_review"] | None = None
    expected_version: int


class JobCreate(BaseModel):
    stage: Literal["ingest", "demo_pipeline", "translate", "synthesize", "export"]
    provider: Literal["fake", "sarvam", "local"] | None = None


class JobRead(ORMModel):
    id: str
    project_id: str
    stage: str
    status: str
    progress: float
    provider: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ArtifactRead(ORMModel):
    id: str
    project_id: str
    job_id: str | None
    kind: str
    filename: str
    media_type: str
    created_at: datetime
    download_url: str


class ProjectDetail(ProjectRead):
    assets: list[MediaAssetRead]
    speakers: list[SpeakerRead]
    segments: list[SegmentRead]
    jobs: list[JobRead]
    artifacts: list[ArtifactRead]


class ConsentInput(BaseModel):
    approved: bool
    attested_by: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)


class VoiceProfileCreate(BaseModel):
    speaker_id: str
    display_name: str = Field(min_length=1, max_length=120)
    provider: Literal["sarvam", "local", "fake"] = "sarvam"
    provider_voice_id: str | None = Field(default=None, max_length=255)
    reference_asset_id: str | None = None
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


class CapabilityRead(BaseModel):
    capability: str
    selected_provider: str
    available: bool
    reason: str | None = None
