"""Shared job preparation: provider routing, common frozen inputs and fingerprinting."""

import hashlib
import json
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Project
from ..providers import ProviderRegistry
from ..providers.local_asr import availability as asr_availability
from ..schemas import JobFields
from .spec import StageSpec

# Stages whose provider is chosen from a registry capability rather than fixed by the stage.
ROUTED = {"transcribe", "translate", "synthesize", "register_voice", "delete_voice"}


@dataclass
class Preparation:
    session: Session
    project: Project
    payload: JobFields
    settings: Settings
    spec: StageSpec
    provider: str = ""
    inputs: dict = field(default_factory=dict)
    cost: float = 0.0


def resolve_provider(prep: Preparation) -> None:
    settings, payload, stage = prep.settings, prep.payload, prep.spec.stage
    default = prep.spec.default_provider(settings)
    provider = payload.provider or default
    if provider == "fake" and not settings.demo_providers_allowed():
        raise HTTPException(422, "DEMO providers are disabled in this environment")
    if stage in ROUTED:
        capability = (
            next(
                item
                for item in ProviderRegistry(settings).capabilities()
                if item.capability == prep.spec.capability and item.selected_provider == provider
            )
            if provider == default
            else None
        )
        allowed = {"fake", "sarvam", "local"} if stage == "transcribe" else {"fake", "sarvam"}
        if provider not in allowed:
            raise HTTPException(422, "This provider adapter is not implemented")
        if provider == "sarvam" and not settings.sarvam_api_key:
            raise HTTPException(422, "Configure SARVAM_API_KEY locally before using Sarvam")
        if capability and not capability.available:
            raise HTTPException(422, capability.reason)
        if provider == "local":
            ready, reason = asr_availability(settings.local_asr_model_dir)
            if not ready:
                raise HTTPException(422, reason)
            if prep.project.source_language != "en-IN":
                raise HTTPException(422, "The installed small.en model supports English input only")
            if payload.num_speakers is not None:
                raise HTTPException(422, "Local ASR has no diarization; assign speakers manually")
    elif provider != default:
        raise HTTPException(422, "Provider is incompatible with this stage")
    prep.provider = provider


def common_inputs(prep: Preparation) -> None:
    payload, stage = prep.payload, prep.spec.stage
    inputs = payload.model_dump(exclude={"provider", "force_new"})
    if stage != "analyze_takes":
        if (
            payload.candidate_ids is not None and stage != "adapt_dialogue"
        ) or payload.include_target_alignment:
            raise HTTPException(422, "Take-analysis options require the analyze_takes stage")
        # Preserve existing paid-job fingerprints when adding independent review options.
        inputs.pop("candidate_ids")
        inputs.pop("include_target_alignment")
    inputs.update(
        {
            "source_language": prep.project.source_language,
            "target_language": prep.project.target_language,
        }
    )
    prep.inputs = inputs


def fingerprint(stage: str, provider: str, inputs: dict) -> str:
    identity = {"stage": stage, "provider": provider, "input": inputs}
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
