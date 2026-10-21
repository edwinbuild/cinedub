"""Reference preparation, explicit remote enrollment and retained consent lineage."""

import array
import hashlib
import math
import time
import wave
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select

from .config import get_settings
from .consent import approved_consent
from .media import run_ffmpeg
from .models import Artifact, MediaAsset, ProviderRun, VoiceProfile
from .processing import charge, check_cancel, checkpoint
from .providers import ProviderRegistry
from .providers.retry import retry_safe


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def reference_metrics(path):
    with wave.open(str(path), "rb") as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (24000, 1, 2):
            raise ValueError("Reference preparation did not produce canonical audio")
        frames = audio.getnframes()
        samples = array.array("h", audio.readframes(frames))
    if not samples:
        raise ValueError("Reference clip is empty")
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
    rms_dbfs = 20 * math.log10(max(rms, 1e-10))
    if rms_dbfs < -50:
        raise ValueError("Reference is silent or too quiet; choose a clear spoken clip")
    clipping = sum(abs(value) >= 32760 for value in samples) / len(samples)
    warnings = []
    if rms_dbfs < -35:
        warnings.append("Reference is quiet; review audibility before upload")
    if clipping > 0.001:
        warnings.append("Reference contains clipping; choose a cleaner recording")
    return {
        "frames": frames,
        "rms_dbfs": round(rms_dbfs, 2),
        "clipped_fraction": round(clipping, 6),
        "warnings": warnings,
    }


def current_profile(session, job, *, consent=True):
    session.expire_all()
    profile = session.get(VoiceProfile, job.input_json["voice_profile_id"])
    if not profile or profile.version != job.input_json["profile_version"]:
        raise ValueError("Voice profile changed since scheduling; no provider call was made")
    if consent:
        record = approved_consent(session, profile)
        if record.id != job.input_json["consent_record_id"]:
            raise ValueError("Voice consent changed since scheduling")
    check_cancel(session, job)
    return profile


def process_prepare_reference(session, job):
    existing = session.scalar(
        select(Artifact).where(Artifact.job_id == job.id, Artifact.kind == "voice_reference")
    )
    if existing:
        approved_consent(session, session.get(VoiceProfile, job.input_json["voice_profile_id"]))
        return {"artifact_ids": [existing.id]}
    profile = current_profile(session, job)
    if profile.reference_artifact_id:
        return {"artifact_ids": [profile.reference_artifact_id]}
    source = session.get(MediaAsset, job.input_json["source_asset_id"])
    path = get_settings().storage_root / job.project_id / "references" / job.id / "reference.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    duration_ms = job.input_json["end_ms"] - job.input_json["start_ms"]
    checkpoint(session, job, "preparing_reference")
    run_ffmpeg(
        [
            "-i",
            source.path,
            "-ss",
            str(job.input_json["start_ms"] / 1000),
            "-t",
            str(duration_ms / 1000),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        timeout=60,
    )
    metrics = reference_metrics(path)
    if abs(metrics["frames"] - duration_ms * 24) > 24:
        raise ValueError("Reference clip duration does not match the selected source range")
    profile = current_profile(session, job)
    artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="voice_reference",
        path=str(path.resolve()),
        filename="voice-reference.wav",
        media_type="audio/wav",
        metadata_json={
            "voice_profile_id": profile.id,
            "source_asset_id": source.id,
            "start_ms": job.input_json["start_ms"],
            "end_ms": job.input_json["end_ms"],
            "consent_record_id": job.input_json["consent_record_id"],
            "sha256": file_hash(path),
            "sample_rate": 24000,
            "channels": 1,
            "quality": metrics,
            "warning": "Single-speaker identity/cleanliness attested by user, not inferred",
        },
    )
    session.add(artifact)
    session.flush()
    profile.reference_artifact_id = artifact.id
    profile.registration_status = "prepared"
    profile.version += 1
    job.warnings_json = metrics["warnings"]
    session.commit()
    return {"artifact_ids": [artifact.id], "voice_profile_id": profile.id}


def process_register_voice(session, job):
    values = job.checkpoint_json.get("registration_result")
    if not values:
        profile = current_profile(session, job)
        reference = session.get(Artifact, job.input_json["reference_artifact_id"])
        if not reference or file_hash(reference.path) != job.input_json["reference_sha256"]:
            raise ValueError("Reference audio changed or is unavailable")
        provider = ProviderRegistry(get_settings()).voice_cloner(job.provider)
        checkpoint(session, job, "registering_voice", pending_registration=True)
        if job.provider == "sarvam":
            charge(session, job, job.estimated_cost_inr)
        started = time.monotonic()
        # Registration creates an external identity. Do not blindly retry even a 5xx.
        result = provider.register_voice(
            Path(reference.path),
            job.input_json["display_name"],
            job.input_json["reference_language"],
        )
        values = asdict(result)
        # Preserve the returned remote identity even if revocation/cancellation happened
        # during the HTTP call. This makes provider-side cleanup possible.
        session.refresh(job)
        job.checkpoint_json = {
            **job.checkpoint_json,
            "registration_result": values,
            "pending_registration": False,
        }
        session.add(
            ProviderRun(
                project_id=job.project_id,
                job_id=job.id,
                capability="voice_cloner",
                provider=result.provider,
                model=result.model,
                status="completed",
                latency_ms=round((time.monotonic() - started) * 1000),
                estimated_cost_inr=job.charged_estimate_inr,
                parameters_json={
                    "voice_profile_id": profile.id,
                    "voice_id": result.voice_id,
                    "reference_artifact_id": reference.id,
                    "consent_record_id": job.input_json["consent_record_id"],
                },
            )
        )
        session.commit()
    session.expire_all()
    profile = session.get(VoiceProfile, job.input_json["voice_profile_id"])
    if profile.registration_status != "ready" or profile.provider_voice_id != values["voice_id"]:
        profile.provider_voice_id = values["voice_id"]
        profile.registration_status = "ready"
        profile.settings_json = {
            **profile.settings_json,
            "reference_text": values["reference_text"],
        }
        profile.version += 1
        session.commit()
    check_cancel(session, job)
    approved_consent(session, profile)
    return {
        "voice_profile_id": profile.id,
        "voice_id": profile.provider_voice_id,
        "warning": "Select this clone explicitly; no automatic switch from stock voices",
    }


def process_delete_voice(session, job):
    profile = session.get(VoiceProfile, job.input_json["voice_profile_id"])
    if profile and profile.registration_status == "deleted":
        return {
            "voice_profile_id": profile.id,
            "provider_copy_deleted": True,
            "local_history_retained": True,
        }
    profile = current_profile(session, job, consent=False)
    if profile.consent_status != "revoked":
        raise ValueError("Revoke local consent before deleting the provider copy")
    provider = ProviderRegistry(get_settings()).voice_cloner(job.provider)
    checkpoint(session, job, "deleting_provider_voice")
    retry_safe(
        lambda: provider.delete_voice(job.input_json["voice_id"]),
        lambda: check_cancel(session, job),
    )
    profile.registration_status = "deleted"
    profile.version += 1
    session.add(
        ProviderRun(
            project_id=job.project_id,
            job_id=job.id,
            capability="voice_deletion",
            provider=job.provider,
            model="saved-voice-delete",
            status="completed",
            estimated_cost_inr=0,
            parameters_json={"voice_profile_id": profile.id},
        )
    )
    session.commit()
    return {
        "voice_profile_id": profile.id,
        "provider_copy_deleted": True,
        "local_history_retained": True,
    }
