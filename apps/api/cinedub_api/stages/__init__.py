"""The stage registry: every job stage's contracts, routing, preparation and processor."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..adaptation_processing import process_adapt_dialogue
from ..alignment_processing import process_align
from ..clone_processing import (
    process_delete_voice,
    process_prepare_reference,
    process_register_voice,
)
from ..config import get_settings
from ..core_processing import process_demo_pipeline, process_export, process_ingest
from ..dialogue_processing import process_review_translation
from ..emotion_processing import process_analyze_emotion
from ..mix_packaging import process_package_mix
from ..mix_processing import process_render_mix
from ..models import Project
from ..processing import process_transcribe, process_translate
from ..schemas import JobFields
from ..separation_processing import process_separate
from ..take_analysis_processing import process_analyze_takes
from ..voice_processing import process_render_preview, process_synthesize
from . import contracts as c
from .analysis import alignment_inputs, emotion_inputs, take_inputs
from .dialogue import adaptation_inputs, review_inputs
from .preparation import Preparation, common_inputs, fingerprint, resolve_provider
from .source import separation_inputs, source_inputs
from .spec import RetryPolicy, StageSpec
from .timeline import mix_disk_space, revision_inputs
from .voice import voice_profile_inputs


def local(_settings) -> str:
    return "local"


def fake(_settings) -> str:
    return "fake"


SPECS = [
    StageSpec("ingest", c.IngestInput, c.IngestOutput, process_ingest, local, (source_inputs,)),
    StageSpec(
        "demo_pipeline", c.DemoPipelineInput, c.DemoPipelineOutput, process_demo_pipeline, fake
    ),
    StageSpec(
        "transcribe",
        c.TranscribeInput,
        c.TranscribeOutput,
        process_transcribe,
        lambda settings: settings.transcriber,
        (source_inputs,),
        capability="transcriber",
        retry=RetryPolicy(
            retryable_errors=frozenset({"provider_timeout", "provider_transport"}),
            remote_resume_phases=frozenset({"starting", "polling", "downloading"}),
        ),
    ),
    StageSpec(
        "translate",
        c.TranslateInput,
        c.TranslateOutput,
        process_translate,
        lambda settings: settings.translator,
        (revision_inputs,),
        capability="translator",
    ),
    StageSpec(
        "synthesize",
        c.SynthesizeInput,
        c.SynthesizeOutput,
        process_synthesize,
        lambda settings: settings.voice_synthesizer,
        (revision_inputs,),
        capability="voice_synthesizer",
    ),
    StageSpec("export", c.ExportInput, c.ExportOutput, process_export, local, (revision_inputs,)),
    StageSpec(
        "render_preview",
        c.RenderPreviewInput,
        c.RenderPreviewOutput,
        process_render_preview,
        local,
        (revision_inputs,),
    ),
    StageSpec(
        "render_mix",
        c.RenderMixInput,
        c.RenderMixOutput,
        process_render_mix,
        local,
        (mix_disk_space, revision_inputs),
    ),
    StageSpec(
        "package_mix",
        c.PackageMixInput,
        c.PackageMixOutput,
        process_package_mix,
        local,
        internal=True,
    ),
    StageSpec(
        "prepare_reference",
        c.PrepareReferenceInput,
        c.PrepareReferenceOutput,
        process_prepare_reference,
        local,
        (voice_profile_inputs,),
    ),
    StageSpec(
        "register_voice",
        c.RegisterVoiceInput,
        c.RegisterVoiceOutput,
        process_register_voice,
        lambda settings: settings.voice_synthesizer,
        (voice_profile_inputs,),
        capability="voice_cloner",
    ),
    StageSpec(
        "delete_voice",
        c.DeleteVoiceInput,
        c.DeleteVoiceOutput,
        process_delete_voice,
        lambda settings: settings.voice_synthesizer,
        (voice_profile_inputs,),
        capability="voice_cloner",
    ),
    StageSpec(
        "separate",
        c.SeparateInput,
        c.SeparateOutput,
        process_separate,
        lambda settings: settings.stem_separator,
        (separation_inputs, source_inputs),
        capability="stem_separator",
    ),
    StageSpec(
        "align",
        c.AlignInput,
        c.AlignOutput,
        process_align,
        lambda settings: settings.timing_aligner,
        (alignment_inputs,),
        capability="timing_aligner",
    ),
    StageSpec(
        "analyze_takes",
        c.AnalyzeTakesInput,
        c.AnalyzeTakesOutput,
        process_analyze_takes,
        lambda settings: settings.performance_analyzer,
        (take_inputs,),
        capability="performance_analyzer",
    ),
    StageSpec(
        "review_translation",
        c.ReviewTranslationInput,
        c.ReviewTranslationOutput,
        process_review_translation,
        local,
        (review_inputs,),
    ),
    StageSpec(
        "adapt_dialogue",
        c.AdaptDialogueInput,
        c.AdaptDialogueOutput,
        process_adapt_dialogue,
        lambda settings: settings.dialogue_adapter,
        (review_inputs, adaptation_inputs),
        capability="dialogue_adapter",
        retry=RetryPolicy(retryable_errors=frozenset({"deadline_exceeded", "internal"})),
    ),
    StageSpec(
        "analyze_emotion",
        c.AnalyzeEmotionInput,
        c.AnalyzeEmotionOutput,
        process_analyze_emotion,
        lambda settings: settings.emotion_analyzer,
        (emotion_inputs,),
        capability="emotion_analyzer",
    ),
]
STAGES: dict[str, StageSpec] = {spec.stage: spec for spec in SPECS}
STORED_INPUTS = {stage: c.stored(spec.input_model) for stage, spec in STAGES.items()}


def prepare_stage(session: Session, project: Project, payload: JobFields) -> Preparation:
    """Freeze one request's inputs. Every caller (estimate, create, pipeline) shares this path."""
    spec = STAGES.get(payload.stage)
    if not spec or spec.internal:
        raise HTTPException(422, "This stage cannot be requested directly")
    prep = Preparation(session, project, payload, get_settings(), spec)
    resolve_provider(prep)
    common_inputs(prep)
    for step in spec.prepare:
        step(prep)
    prep.inputs["fingerprint"] = fingerprint(spec.stage, prep.provider, prep.inputs)
    # A preparation bug must never persist an unvalidated job.
    spec.input_model.model_validate(prep.inputs)
    prep.cost = round(prep.cost, 6)
    return prep


def validated_inputs(job) -> dict:
    """Re-validate a stored job before processing; raises pydantic.ValidationError."""
    STORED_INPUTS[job.stage].model_validate(job.input_json)
    return job.input_json


def validated_output(stage: str, output: dict) -> dict:
    return (
        STAGES[stage]
        .output_model.model_validate(output)
        .model_dump(mode="json", exclude_unset=True)
    )
