"""Frozen job input and recorded output contracts, one pair per stage.

Inputs mirror exactly what preparation freezes into `Job.input_json` (and therefore its
fingerprint). New writes are validated strictly; stored rows are re-validated leniently so
fields added by later milestones never block resuming an older job.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ..schemas import LanguageCode, MixSettings

Snapshot = dict[str, Any]


class StageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str | None = None
    source_asset_id: str | None = None
    revision_id: str | None = None
    num_speakers: int | None = None
    segment_ids: list[str] | None = None
    regenerate: bool = False
    allow_incomplete: bool = False
    voice_profile_id: str | None = None
    registration_allowance_inr: float | None = None
    reference_reviewed: bool = False
    transcription_input: Literal["original", "dialogue_stem"] = "original"
    mix_settings: MixSettings | Snapshot | None = None
    source_language: LanguageCode | None = None
    target_language: LanguageCode | None = None
    fingerprint: str | None = None


class StageOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrozenSource(StageInput):
    source_asset_id: str
    source_sha256: str | None = None
    unit_rate_inr: float = 0


class FrozenAudio(StageInput):
    """Source/recognition audio snapshot shared by alignment, take and emotion analysis."""

    project_id: str
    source_asset_id: str
    source_sha256: str
    duration_ms: int
    revision_id: str
    recognition_artifact_id: str
    recognition_sha256: str
    stem_set_id: str | None = None
    stem_set_version: int | None = None
    model: str
    threads: int
    timeout_seconds: int


class FrozenTimeline(StageInput):
    revision_id: str
    source_asset_id: str | None = None
    segments: list[Snapshot]


class IngestInput(StageInput):
    source_asset_id: str
    source_sha256: str | None = None
    model: str | None = None
    unit_rate_inr: float = 0


class DemoPipelineInput(StageInput):
    pass


class TranscribeInput(FrozenSource):
    model: str
    recognition_artifact_id: str | None = None
    stem_set_id: str | None = None
    stem_set_version: int | None = None
    local_model_dir: str | None = None
    local_model_manifest: Snapshot | None = None
    asr_profile: Snapshot | None = None
    threads: int | None = None
    timeout_seconds: int | None = None


class SeparateInput(FrozenSource):
    model: str
    model_dir: str | None
    model_manifest: Snapshot
    threads: int
    timeout_seconds: int


class TranslateInput(FrozenTimeline):
    model: str
    style: str
    unit_rate_inr: float


class SynthesizeInput(FrozenTimeline):
    model: str
    models: list[str]
    voices: dict[str, Snapshot]
    unit_rate_inr: float
    max_timing_speedup: float


class ExportInput(FrozenTimeline):
    pass


class RenderPreviewInput(FrozenTimeline):
    candidates: dict[str, str]


class RenderMixInput(FrozenTimeline):
    candidates: dict[str, str]
    candidate_hashes: dict[str, str | None]
    stem_set_id: str
    stem_set_version: int
    background: dict[str, Snapshot]
    source_sha256: str | None
    duration_ms: int
    stem_model: str
    stem_provider: str


class PackageMixInput(StageInput):
    mix_id: str
    review_record_id: str
    candidates: dict[str, str]


class VoiceProfileInput(StageInput):
    voice_profile_id: str
    profile_version: int


class PrepareReferenceInput(VoiceProfileInput):
    consent_record_id: str
    source_asset_id: str
    start_ms: int
    end_ms: int


class RegisterVoiceInput(VoiceProfileInput):
    consent_record_id: str
    reference_artifact_id: str
    reference_sha256: str
    reference_language: str
    display_name: str


class DeleteVoiceInput(VoiceProfileInput):
    voice_id: str


class AlignInput(FrozenAudio):
    performance_provider: str
    performance_model: str
    model_dir: str | None
    model_manifest: Snapshot
    segments: list[Snapshot]


class AnalyzeTakesInput(FrozenAudio):
    candidate_ids: list[str] | None = None
    include_target_alignment: bool = False
    takes: list[Snapshot]
    voices: dict[str, Snapshot]
    candidates: dict[str, str]
    target_alignment_model: str | None = None
    target_model_dir: str | None = None
    target_model_manifest: Snapshot | None = None


class AnalyzeEmotionInput(FrozenAudio):
    profile: Snapshot
    model_manifest: Snapshot
    model_dir: str | None
    segments: list[Snapshot]


class ReviewTranslationInput(StageInput):
    model: str
    revision_id: str
    source_asset_id: str | None
    brief: Snapshot
    context_lines: list[Snapshot]
    review_ids: list[str]
    observed_versions: dict[str, int]


class AdaptDialogueInput(ReviewTranslationInput):
    candidate_ids: list[str] | None = None
    timing_feedback: dict[str, Snapshot] | None = None
    voices: dict[str, Snapshot] | None = None
    model_manifest: Snapshot
    model_dir: str | None
    threads: int
    timeout_seconds: int
    adaptation_provider: str
    prompt_version: str
    generation_parameters: Snapshot


class ArtifactsOutput(StageOutput):
    artifact_ids: list[str]


class IngestOutput(ArtifactsOutput):
    pass


class DemoPipelineOutput(StageOutput):
    segments: int | None = None
    speakers: int | None = None
    preserved_existing_segments: bool | None = None


class TranscribeOutput(StageOutput):
    revision_id: str
    segments: int
    warnings: list[str]


class TranslateOutput(StageOutput):
    translated_segments: int
    preserved_newer_edits: int
    candidate_results: dict[str, str]


class SynthesizeOutput(ArtifactsOutput):
    skipped_changed_lines: list[str]


class ExportOutput(ArtifactsOutput):
    validated: bool | None = None
    dubbed_mix: bool


class RenderPreviewOutput(ArtifactsOutput):
    dialogue_only: bool


class RenderMixOutput(ArtifactsOutput):
    mix_id: str
    review_required: bool


class PackageMixOutput(ArtifactsOutput):
    mix_id: str


class PrepareReferenceOutput(ArtifactsOutput):
    voice_profile_id: str | None = None


class RegisterVoiceOutput(StageOutput):
    voice_profile_id: str
    voice_id: str
    warning: str | None = None


class DeleteVoiceOutput(StageOutput):
    voice_profile_id: str
    provider_copy_deleted: bool
    local_history_retained: bool


class SeparateOutput(StageOutput):
    stem_set_id: str
    review_required: bool = True


class AlignOutput(StageOutput):
    alignment_artifact_id: str


class AnalyzeTakesOutput(StageOutput):
    performance_artifact_id: str


class ReviewTranslationOutput(StageOutput):
    dialogue_review_artifact_id: str
    checked_lines: int | None = None


class AdaptDialogueOutput(StageOutput):
    adaptation_artifact_id: str
    adapted_lines: int | None = None


class AnalyzeEmotionOutput(StageOutput):
    emotion_artifact_id: str
    classified_windows: int | None = None


def stored(model: type[BaseModel]) -> type[BaseModel]:
    """Lenient variant for re-validating persisted rows written by earlier milestones."""
    return type(
        f"Stored{model.__name__}",
        (model,),
        {"model_config": ConfigDict(**{**model.model_config, "extra": "ignore"})},
    )
