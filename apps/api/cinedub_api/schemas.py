from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class SpeakerReusePreview(BaseModel):
    source: SpeakerRead
    target: SpeakerRead
    copy_stock_voice: bool
    voice: dict
    affected_line_ids: list[str]
    fingerprint: str
    warnings: list[str]


class SpeakerReuseApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_speaker_id: str
    copy_stock_voice: bool = False
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity_confirmed: bool


class SpeakerReuseRead(ORMModel):
    id: str
    source_speaker_id: str
    target_speaker_id: str
    fingerprint: str
    before_json: dict
    after_json: dict
    created_at: datetime


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
    retired: bool = False


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


class SegmentContent(BaseModel):
    source_text: str = Field(min_length=1, max_length=4000)
    translated_text: str = Field(max_length=4000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    speaker_id: str | None


class SegmentBatchItem(SegmentUpdate):
    model_config = ConfigDict(extra="forbid")
    segment_id: str = Field(min_length=1, max_length=100)


class SegmentBatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str = Field(min_length=1, max_length=100)
    lines: list[SegmentBatchItem] = Field(min_length=1, max_length=100)


class SegmentBatchResult(BaseModel):
    group_id: str
    lines: list[SegmentRead]


class EditGroupSummary(BaseModel):
    group_id: str
    created_at: datetime
    line_count: int


class EditGroupLine(BaseModel):
    segment_id: str
    expected_version: int
    expected_edit_id: str
    index: int
    before: SegmentContent
    after: SegmentContent


class EditGroupHistory(BaseModel):
    group_id: str
    revision_id: str
    lines: list[EditGroupLine]
    excluded_nonmaterial_count: int
    can_undo: bool
    can_redo: bool
    unavailable_reason: str | None


class EditGroupVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)
    expected_edit_id: str = Field(min_length=1, max_length=100)


class EditGroupRestore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str = Field(min_length=1, max_length=100)
    action: Literal["undo", "redo"]
    lines: list[EditGroupVersion] = Field(min_length=1, max_length=100)
    restoration_confirmed: bool = False


class SegmentHistoryEntry(BaseModel):
    id: str
    version: int
    action: Literal["edit", "undo", "redo"]
    target_edit_id: str | None
    before: SegmentContent | None
    after: SegmentContent | None
    created_at: datetime


class SegmentHistory(BaseModel):
    segment_id: str
    version: int
    undo_edit_id: str | None
    redo_edit_id: str | None
    unavailable_reason: str | None
    entries: list[SegmentHistoryEntry]
    total_entries: int


class SegmentHistoryAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    expected_edit_id: str = Field(min_length=1, max_length=36)
    action: Literal["undo", "redo"]
    restoration_confirmed: bool = False


class SplitLinePart(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_text: str = Field(min_length=1, max_length=4000)
    translated_text: str = Field(default="", max_length=4000)


class SegmentSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str
    expected_version: int = Field(ge=1)
    split_ms: int = Field(gt=0)
    first: SplitLinePart
    second: SplitLinePart
    replacement_confirmed: bool = False


class SegmentMerge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str
    next_segment_id: str
    expected_version: int = Field(ge=1)
    expected_next_version: int = Field(ge=1)
    text: SplitLinePart
    replacement_confirmed: bool = False


class TimelineStructureEditRead(BaseModel):
    id: str
    revision_id: str
    action: Literal["split", "merge", "restore"]
    parent_edit_id: str | None
    before: list[SegmentRead]
    after: list[SegmentRead]
    created_at: datetime
    restorable: bool
    unavailable_reason: str | None


class TimelineStructureRestore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: str
    expected_versions: dict[str, int]
    restoration_confirmed: bool = False


class GlossaryTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: str = Field(min_length=1, max_length=120)
    preferred_target: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=500)


class CharacterDirection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    speaker_id: str = Field(min_length=1, max_length=36)
    intent: str = Field(default="", max_length=1000)
    delivery_notes: str = Field(default="", max_length=1000)


class DialogueBriefContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scene_summary: str = Field(default="", max_length=4000)
    adaptation_notes: str = Field(default="", max_length=4000)
    glossary: list[GlossaryTerm] = Field(default_factory=list, max_length=80)
    characters: list[CharacterDirection] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_entries(self):
        import unicodedata

        terms = [unicodedata.normalize("NFC", term.source).casefold() for term in self.glossary]
        speakers = [item.speaker_id for item in self.characters]
        if len(terms) != len(set(terms)) or len(speakers) != len(set(speakers)):
            raise ValueError("Use one glossary entry per source term and one direction per speaker")
        return self

    @field_validator("scene_summary", "adaptation_notes")
    @classmethod
    def no_null_bytes(cls, value):
        if "\x00" in value:
            raise ValueError("Notes cannot contain null bytes")
        return value


class DialogueBriefUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    content: DialogueBriefContent


class DialogueBriefRead(BaseModel):
    id: str | None
    project_id: str
    revision_id: str
    version: int
    content: DialogueBriefContent


class DialogueContextLine(BaseModel):
    segment_id: str
    source_text: str
    translated_text: str
    speaker_id: str | None
    speaker_name: str | None
    start_ms: int
    end_ms: int


class DialogueFinding(BaseModel):
    code: Literal["missing_translation", "missing_preferred_term", "unassigned_speaker"]
    message: str
    source_term: str | None = None
    preferred_target: str | None = None


class DialogueReviewLine(DialogueContextLine):
    segment_version: int
    slot_duration_ms: int
    target_character_count: int
    previous_line: DialogueContextLine | None
    next_line: DialogueContextLine | None
    character_direction: CharacterDirection | None
    matched_glossary: list[GlossaryTerm]
    findings: list[DialogueFinding]


class DialogueReviewReport(BaseModel):
    schema_version: Literal[1] = 1
    method: Literal["dialogue-review-v1"] = "dialogue-review-v1"
    project_id: str
    revision_id: str
    source_language: LanguageCode
    target_language: LanguageCode
    brief: DialogueBriefRead
    context_lines: list[DialogueContextLine]
    context_applied_by_model: Literal[False] = False
    lines: list[DialogueReviewLine]
    warnings: list[str]
    stale_reason: str | None = None


class DialogueModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    faithful: str = Field(min_length=1, max_length=1200)
    concise: str = Field(min_length=1, max_length=1200)
    notes: str = Field(default="", max_length=600)


class DialogueAlternative(BaseModel):
    kind: Literal["faithful", "concise"]
    text: str = Field(min_length=1, max_length=1200)
    findings: list[DialogueFinding]
    warnings: list[str]
    eligible_for_application: bool


class DialogueNativeLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    output: DialogueModelOutput
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_tokens: int = Field(ge=1, le=3312)
    latency_ms: int = Field(ge=0)


class DialogueTimingFeedback(BaseModel):
    candidate_id: str
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_sample_count: int = Field(gt=0)
    raw_sample_rate: Literal[48000] = 48000
    raw_duration_ms: int = Field(gt=0)
    target_duration_ms: int = Field(gt=0)
    required_speed_ratio: float = Field(gt=0, allow_inf_nan=False)
    max_safe_speedup: float = Field(ge=1, allow_inf_nan=False)
    safe_speedup_exceeded: bool
    signature: str
    voice: dict
    demo: bool = False
    evaluation_fixture: bool = False


class DialogueAdaptationLine(DialogueReviewLine):
    timing_feedback: DialogueTimingFeedback | None = None
    alternatives: list[DialogueAlternative]
    model_notes: str
    prompt_sha256: str
    request_sha256: str
    prompt_tokens: int = Field(ge=1)
    latency_ms: int = Field(ge=0)


class DialogueAdaptationReport(BaseModel):
    schema_version: Literal[1] = 1
    project_id: str
    revision_id: str
    source_language: LanguageCode
    target_language: LanguageCode
    brief: DialogueBriefRead
    context_lines: list[DialogueContextLine]
    context_supplied_to_model: Literal[True] = True
    provider: str
    model: str
    prompt_version: str
    generation_parameters: dict
    runtime: dict
    lines: list[DialogueAdaptationLine]
    warnings: list[str]
    stale_reason: str | None = None
    applied_line_ids: list[str] = Field(default_factory=list)
    applied_translations: dict[str, str] = Field(default_factory=dict)


class DialogueAdaptationApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    kind: Literal["faithful", "concise"]
    expected_version: int = Field(ge=1)
    language_reviewed: bool = False
    replace_reviewed_text: bool = False
    issues_reviewed: bool = False


SpeechEmotionLabel = Literal["neutral", "happy", "angry", "sad"]
PerformanceDirectionLabel = Literal[
    "neutral", "happy", "angry", "sad", "fearful", "surprised", "disgusted", "other"
]


class SpeechEmotionScore(BaseModel):
    label: SpeechEmotionLabel
    score: float = Field(ge=0, le=1, allow_inf_nan=False)


class SpeechEmotionReviewRead(ORMModel):
    id: str
    version: int
    status: Literal["accepted", "corrected", "rejected"]
    label: PerformanceDirectionLabel | None
    direction: str
    reviewed_by: str
    note: str
    created_at: datetime


class SpeechEmotionReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    segment_id: str
    expected_review_version: int = Field(ge=0)
    status: Literal["accepted", "corrected", "rejected"]
    label: PerformanceDirectionLabel | None = None
    direction: str = Field(default="", max_length=1000)
    reviewed_by: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)
    listening_confirmed: bool = False


class SpeechEmotionInference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    status: Literal[
        "needs_review", "ambiguous", "no_speech", "too_short", "too_long", "overlap", "not_analyzed"
    ]
    suggested_label: SpeechEmotionLabel | None
    scores: list[SpeechEmotionScore]
    score_margin: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    speech_ms: int = Field(ge=0)
    speech_fraction: float = Field(ge=0, le=1, allow_inf_nan=False)
    rms_dbfs: float | None = Field(allow_inf_nan=False)
    warnings: list[str]


class SpeechEmotionLine(SpeechEmotionInference):
    segment_version: int
    source_text: str
    speaker_id: str | None
    stale_reason: str | None = None
    review_history: list[SpeechEmotionReviewRead] = Field(default_factory=list)


class SpeechEmotionReport(BaseModel):
    schema_version: Literal[1] = 1
    project_id: str
    revision_id: str
    source_asset_id: str
    source_sha256: str
    recognition_artifact_id: str
    recognition_sha256: str
    stem_set_id: str | None = None
    stem_set_version: int | None = None
    language: Literal["en-IN"]
    provider: str
    model: str
    profile: dict
    metadata: dict
    lines: list[SpeechEmotionLine]
    warnings: list[str]
    stale_reason: str | None = None


class AlignedWord(BaseModel):
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    acoustic_score: float = Field(ge=0, le=1, allow_inf_nan=False)


class AcousticFrame(BaseModel):
    time_ms: int = Field(ge=0)
    rms_dbfs: float | None = Field(allow_inf_nan=False)
    pitch_hz: float | None = Field(allow_inf_nan=False)


class AcousticPause(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class AcousticPerformance(BaseModel):
    method: Literal["acoustic-dsp-v1"] = "acoustic-dsp-v1"
    rms_dbfs: float | None = Field(allow_inf_nan=False)
    peak_dbfs: float | None = Field(allow_inf_nan=False)
    pitch_median_hz: float | None = Field(allow_inf_nan=False)
    pitch_p10_hz: float | None = Field(allow_inf_nan=False)
    pitch_p90_hz: float | None = Field(allow_inf_nan=False)
    energy_active_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    activity_threshold_dbfs: float = Field(allow_inf_nan=False)
    words_per_minute: float = Field(ge=0, allow_inf_nan=False)
    pauses: list[AcousticPause]
    frames: list[AcousticFrame]
    warnings: list[str]


class LineAlignment(BaseModel):
    segment_id: str
    segment_version: int
    source_text: str
    original_start_ms: int
    original_end_ms: int
    status: Literal["aligned", "needs_review", "unalignable"]
    words: list[AlignedWord]
    acoustic_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    greedy_text: str = ""
    text_error_ratio: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    performance: AcousticPerformance
    warnings: list[str]
    stale_reason: str | None = None


class AlignmentReport(BaseModel):
    schema_version: Literal[1] = 1
    project_id: str
    revision_id: str
    source_asset_id: str
    source_sha256: str
    recognition_artifact_id: str
    recognition_sha256: str
    stem_set_id: str | None = None
    stem_set_version: int | None = None
    provider: str
    model: str
    language: LanguageCode
    metadata: dict
    lines: list[LineAlignment]
    warnings: list[str]
    stale_reason: str | None = None


class AlignmentApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    expected_version: int = Field(ge=1)
    replace_reviewed_timing: bool = False
    listening_confirmed: bool = False


class TargetWordAlignment(BaseModel):
    status: Literal["not_requested", "aligned", "needs_review", "unalignable"]
    model: str | None = None
    words: list[AlignedWord] = Field(default_factory=list)
    acoustic_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    greedy_text: str = ""
    text_error_ratio: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    warnings: list[str] = Field(default_factory=list)


class PerformanceComparison(BaseModel):
    rms_delta_db: float | None = Field(allow_inf_nan=False)
    pitch_shift_semitones: float | None = Field(allow_inf_nan=False)
    source_active_span_ms: int = Field(ge=0)
    target_active_span_ms: int = Field(ge=0)
    source_internal_pause_ms: int = Field(ge=0)
    target_internal_pause_ms: int = Field(ge=0)
    active_span_delta_ms: int
    fitted_padding_ms: int = Field(ge=0)


class TakePerformanceLine(BaseModel):
    segment_id: str
    speaker_id: str | None
    segment_version: int
    candidate_id: str
    candidate_sha256: str
    source_text: str
    translated_text: str
    start_ms: int
    end_ms: int
    voice: dict
    signature: str
    demo: bool
    evaluation_fixture: bool = False
    source_performance: AcousticPerformance
    target_performance: AcousticPerformance
    comparison: PerformanceComparison
    target_alignment: TargetWordAlignment
    warnings: list[str]
    stale_reason: str | None = None


class TakePerformanceReport(BaseModel):
    schema_version: Literal[1] = 1
    project_id: str
    revision_id: str
    source_asset_id: str
    source_sha256: str
    recognition_artifact_id: str
    recognition_sha256: str
    stem_set_id: str | None = None
    stem_set_version: int | None = None
    provider: str
    model: str
    target_language: LanguageCode
    metadata: dict
    lines: list[TakePerformanceLine]
    warnings: list[str]
    stale_reason: str | None = None


RequestableStage = Literal[
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
    "align",
    "analyze_takes",
    "review_translation",
    "adapt_dialogue",
    "analyze_emotion",
]
ProviderName = Literal["fake", "sarvam", "local"]
TranscriptionInput = Literal["original", "dialogue_stem"]


class JobFields(BaseModel):
    """Flat request fields frozen into every job. Their shape is part of job fingerprints."""

    stage: RequestableStage
    provider: ProviderName | None = None
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
    transcription_input: TranscriptionInput = "original"
    mix_settings: MixSettings = Field(default_factory=MixSettings)
    candidate_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    include_target_alignment: bool = False


class StageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderName | None = None
    force_new: bool = False


class LineSelection(StageRequest):
    revision_id: str | None = None
    segment_ids: list[str] | None = None
    regenerate: bool = False


class AudioSelection(StageRequest):
    revision_id: str | None = None
    source_asset_id: str | None = None
    segment_ids: list[str] | None = None
    transcription_input: TranscriptionInput = "original"


class IngestJobRequest(StageRequest):
    stage: Literal["ingest"]
    source_asset_id: str | None = None


class DemoPipelineJobRequest(StageRequest):
    stage: Literal["demo_pipeline"]


class TranscribeJobRequest(StageRequest):
    stage: Literal["transcribe"]
    source_asset_id: str | None = None
    num_speakers: int | None = Field(default=None, ge=1, le=20)
    transcription_input: TranscriptionInput = "original"


class SeparateJobRequest(StageRequest):
    stage: Literal["separate"]
    source_asset_id: str | None = None


class TranslateJobRequest(LineSelection):
    stage: Literal["translate"]


class SynthesizeJobRequest(LineSelection):
    stage: Literal["synthesize"]


class ExportJobRequest(LineSelection):
    stage: Literal["export"]
    allow_incomplete: bool = False


class RenderPreviewJobRequest(LineSelection):
    stage: Literal["render_preview"]


class RenderMixJobRequest(LineSelection):
    stage: Literal["render_mix"]
    allow_incomplete: bool = False
    mix_settings: MixSettings = Field(default_factory=MixSettings)


class ReviewTranslationJobRequest(LineSelection):
    stage: Literal["review_translation"]


class AdaptDialogueJobRequest(LineSelection):
    stage: Literal["adapt_dialogue"]
    candidate_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)


class PrepareReferenceJobRequest(StageRequest):
    stage: Literal["prepare_reference"]
    voice_profile_id: str | None = None


class RegisterVoiceJobRequest(StageRequest):
    stage: Literal["register_voice"]
    voice_profile_id: str | None = None
    reference_reviewed: bool = False
    registration_allowance_inr: float | None = Field(
        default=None, gt=0, le=1000, allow_inf_nan=False
    )


class DeleteVoiceJobRequest(StageRequest):
    stage: Literal["delete_voice"]
    voice_profile_id: str | None = None


class AlignJobRequest(AudioSelection):
    stage: Literal["align"]


class AnalyzeTakesJobRequest(AudioSelection):
    stage: Literal["analyze_takes"]
    candidate_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    include_target_alignment: bool = False


class AnalyzeEmotionJobRequest(AudioSelection):
    stage: Literal["analyze_emotion"]
    regenerate: bool = False


JOB_REQUESTS = (
    IngestJobRequest,
    DemoPipelineJobRequest,
    TranscribeJobRequest,
    SeparateJobRequest,
    TranslateJobRequest,
    SynthesizeJobRequest,
    ExportJobRequest,
    RenderPreviewJobRequest,
    RenderMixJobRequest,
    ReviewTranslationJobRequest,
    AdaptDialogueJobRequest,
    PrepareReferenceJobRequest,
    RegisterVoiceJobRequest,
    DeleteVoiceJobRequest,
    AlignJobRequest,
    AnalyzeTakesJobRequest,
    AnalyzeEmotionJobRequest,
)
JobCreate = Annotated[Union[JOB_REQUESTS], Field(discriminator="stage")]  # noqa: UP007


class PipelineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_asset_id: str
    separate_dialogue: bool = False
    adapt_dialogue: bool = False
    analyze_performance: bool = False
    num_speakers: int | None = Field(default=None, ge=1, le=20)
    # Upper bound on estimated paid-provider spend; the pipeline pauses before exceeding it.
    confirmed_budget_inr: float = Field(default=0, ge=0, le=100000, allow_inf_nan=False)


class PipelineContinue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed_budget_inr: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)


class PipelineStep(BaseModel):
    key: str
    kind: Literal["job", "gate"]
    stage: str | None = None
    status: Literal["pending", "running", "awaiting", "completed", "failed", "cancelled"]
    job_id: str | None = None


PipelineStatus = Literal["running", "awaiting_review", "completed", "failed", "cancelled"]


class PipelinePlan(BaseModel):
    steps: list[PipelineStep]
    gates: dict[str, str]


class PipelineRead(ORMModel):
    id: str
    project_id: str
    source_asset_id: str
    status: PipelineStatus
    current_step: int
    steps_json: list[PipelineStep]
    options_json: dict
    gate_reason: str | None
    budget_confirmed_inr: float
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


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
    correlation_id: str | None = None


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
    sha256: str | None = None
    size_bytes: int | None = None


class LineageJob(BaseModel):
    id: str
    stage: str
    provider: str


class LineageProviderRun(BaseModel):
    capability: str
    provider: str
    model: str
    status: str
    latency_ms: int | None
    estimated_cost_inr: float | None


class LineageArtifact(BaseModel):
    id: str
    kind: str
    filename: str
    sha256: str | None
    size_bytes: int | None
    storage_key: str | None
    demo: bool
    job: LineageJob | None
    provider_runs: list[LineageProviderRun]


class LineageEdge(BaseModel):
    artifact_id: str
    role: str
    input_artifact_id: str | None
    input_asset_id: str | None


class LineageSource(BaseModel):
    id: str
    filename: str
    sha256: str | None
    duration_ms: int | None


class ArtifactLineage(BaseModel):
    artifact_id: str
    artifacts: list[LineageArtifact]
    edges: list[LineageEdge]
    sources: list[LineageSource]


class ProjectDetail(ProjectRead):
    dialogue_brief: DialogueBriefRead | None
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
    model_config = ConfigDict(extra="forbid")
    provider: Literal["fake", "sarvam"]
    voice_id: str = Field(min_length=1, max_length=120)
    pace: float = Field(default=1.0, ge=0.5, le=2.0)
    variation: float | None = Field(default=None, ge=0.01, le=1.0, allow_inf_nan=False, strict=True)
    expected_profile_id: str | None = None
    expected_profile_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def supported_variation(self):
        if self.variation is not None and self.provider != "sarvam":
            raise ValueError("Generation variation is supported only for Sarvam stock voices")
        if self.expected_profile_version is not None and self.expected_profile_id is None:
            raise ValueError("A profile version requires its profile ID")
        return self


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
