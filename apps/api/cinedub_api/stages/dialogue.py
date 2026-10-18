"""Preparation for saved-dialogue editorial checks and contextual adaptation."""

from fastapi import HTTPException

from ..adaptation_timing import freeze_timing_feedback
from ..dialogue_prompt import GENERATION, PROMPT_VERSION
from ..dialogue_review import freeze_dialogue_review
from ..providers.fake_analysis import DIALOGUE_MANIFEST
from ..providers.fake_media import DEMO_MODEL
from ..providers.local_dialogue import MODEL_NAME as DIALOGUE_MODEL
from ..providers.local_dialogue import availability as dialogue_availability
from ..providers.local_dialogue import read_manifest as dialogue_manifest
from .preparation import Preparation


def review_inputs(prep: Preparation) -> None:
    try:
        prep.inputs.update(freeze_dialogue_review(prep.session, prep.project, prep.payload))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def adaptation_inputs(prep: Preparation) -> None:
    settings, provider, project, inputs = prep.settings, prep.provider, prep.project, prep.inputs
    if provider not in {"local", "fake"}:
        raise HTTPException(422, "This dialogue adapter is not implemented")
    if provider == "local":
        ready, reason = dialogue_availability(settings.local_dialogue_model_dir)
        if not ready:
            raise HTTPException(422, reason)
    if project.source_language != "en-IN" or project.target_language != "ml-IN":
        raise HTTPException(422, "This experimental profile supports English to Malayalam")
    try:
        feedback = freeze_timing_feedback(prep.session, project, inputs, prep.payload.candidate_ids)
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if feedback:
        inputs["timing_feedback"] = feedback
        inputs["voices"] = {key: value["voice"] for key, value in feedback.items()}
    inputs.update(
        {
            "model": DEMO_MODEL,
            "model_manifest": DIALOGUE_MANIFEST,
            "model_dir": None,
            "threads": 1,
            "timeout_seconds": 60,
        }
        if provider == "fake"
        else {
            "model": DIALOGUE_MODEL,
            "model_manifest": dialogue_manifest(settings.local_dialogue_model_dir),
            "model_dir": str(settings.local_dialogue_model_dir.resolve()),
            "threads": settings.local_dialogue_threads,
            "timeout_seconds": settings.local_dialogue_timeout_seconds,
        }
    )
    inputs.update(
        {
            "adaptation_provider": provider,
            "prompt_version": PROMPT_VERSION,
            "generation_parameters": GENERATION,
        }
    )
