"""Preparation for source-bound stages: ingest, transcription and separation."""

import shutil

from fastapi import HTTPException
from sqlalchemy import select

from ..local_asr_profile import build_profile
from ..models import Artifact, MediaAsset, StemSet
from ..providers.fake_media import DEMO_MODEL
from ..providers.local_asr import MODEL_NAME
from ..providers.local_asr import read_manifest as asr_manifest
from ..providers.local_separation import MODEL_NAME as SEPARATOR_MODEL
from ..providers.local_separation import availability as separator_availability
from ..providers.local_separation import read_manifest as separator_manifest
from .preparation import Preparation


def separation_inputs(prep: Preparation) -> None:
    settings, provider = prep.settings, prep.provider
    if provider not in {"local", "fake"}:
        raise HTTPException(422, "This separator adapter is not installed")
    if provider == "local":
        ready, reason = separator_availability(settings.local_separator_model_dir)
        if not ready:
            raise HTTPException(422, reason)
    if shutil.disk_usage(settings.storage_root).free < 2 * 1024**3:
        raise HTTPException(422, "Keep at least 2 GiB free for local separation outputs")
    prep.inputs.update(
        {
            "model": DEMO_MODEL,
            "model_dir": None,
            "model_manifest": {"demo": True},
            "threads": 1,
            "timeout_seconds": 60,
        }
        if provider == "fake"
        else {
            "model": SEPARATOR_MODEL,
            "model_dir": str(settings.local_separator_model_dir.resolve()),
            "model_manifest": separator_manifest(settings.local_separator_model_dir),
            "threads": settings.local_separator_threads,
            "timeout_seconds": settings.local_separator_timeout_seconds,
        }
    )


def source_inputs(prep: Preparation) -> None:
    session, project, payload, settings = prep.session, prep.project, prep.payload, prep.settings
    stage, provider, inputs = prep.spec.stage, prep.provider, prep.inputs
    source = session.get(MediaAsset, payload.source_asset_id) if payload.source_asset_id else None
    if not source or source.project_id != project.id:
        raise HTTPException(422, "Select a source asset belonging to this project")
    if not source.duration_ms:
        raise HTTPException(422, "Source duration is unavailable")
    inputs["source_asset_id"] = source.id
    inputs["source_sha256"] = source.metadata_json.get("sha256")
    if stage != "separate":
        inputs["model"] = settings.transcription_model
    inputs["unit_rate_inr"] = settings.stt_diarization_inr_per_hour
    if provider == "local" and stage == "transcribe":
        inputs.update(
            {
                "model": MODEL_NAME,
                "local_model_dir": str(settings.local_asr_model_dir.resolve()),
                "local_model_manifest": asr_manifest(settings.local_asr_model_dir),
                "asr_profile": build_profile(settings.local_asr_threads),
                "threads": settings.local_asr_threads,
                "timeout_seconds": settings.local_asr_timeout_seconds,
                "unit_rate_inr": 0,
            }
        )
    if stage == "transcribe":
        if payload.transcription_input == "dialogue_stem":
            stems = (
                session.get(StemSet, source.active_stem_set_id)
                if source.active_stem_set_id
                else None
            )
            if not stems or stems.source_asset_id != source.id or stems.status != "approved":
                raise HTTPException(422, "Approve and select dialogue stems for this source first")
            inputs.update(
                {
                    "stem_set_id": stems.id,
                    "stem_set_version": stems.version,
                    "recognition_artifact_id": stems.artifacts_json["recognition_audio"],
                }
            )
        else:
            audio = next(
                (
                    item
                    for item in session.scalars(
                        select(Artifact)
                        .where(
                            Artifact.project_id == project.id,
                            Artifact.kind == "recognition_audio",
                        )
                        .order_by(Artifact.created_at.desc())
                    ).all()
                    if item.metadata_json.get("source_asset_id") == source.id
                ),
                None,
            )
            if not audio:
                raise HTTPException(422, "Prepare source media before starting transcription")
            inputs["recognition_artifact_id"] = audio.id
    if provider == "sarvam":
        prep.cost = source.duration_ms / 3_600_000 * settings.stt_diarization_inr_per_hour
