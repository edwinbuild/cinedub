"""Preparation for consented voice references, provider enrollment and deletion."""

from fastapi import HTTPException
from sqlalchemy import select

from ..consent import approved_consent
from ..models import Artifact, Job, VoiceProfile
from .preparation import Preparation


def voice_profile_inputs(prep: Preparation) -> None:
    session, project, payload, inputs = prep.session, prep.project, prep.payload, prep.inputs
    stage, provider = prep.spec.stage, prep.provider
    profile = (
        session.get(VoiceProfile, payload.voice_profile_id) if payload.voice_profile_id else None
    )
    if not profile or profile.project_id != project.id or profile.voice_kind != "clone":
        raise HTTPException(422, "Select a cloned-voice profile belonging to this project")
    inputs.update({"voice_profile_id": profile.id, "profile_version": profile.version})
    if stage != "delete_voice":
        try:
            consent = approved_consent(session, profile)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        inputs["consent_record_id"] = consent.id
    if stage == "prepare_reference":
        inputs.update(
            {
                "source_asset_id": profile.reference_asset_id,
                "start_ms": profile.settings_json["reference_start_ms"],
                "end_ms": profile.settings_json["reference_end_ms"],
            }
        )
        return
    if provider != profile.provider:
        raise HTTPException(422, "Use the provider recorded on this cloned-voice profile")
    if stage == "delete_voice":
        if profile.consent_status != "revoked" or not profile.provider_voice_id:
            raise HTTPException(422, "Revoke local consent first; a known saved voice is required")
        inputs["voice_id"] = profile.provider_voice_id
        return
    if not payload.reference_reviewed:
        raise HTTPException(
            422, "Listen to and explicitly review the prepared reference before upload"
        )
    if profile.registration_status == "ready" or profile.provider_voice_id:
        raise HTTPException(422, "This voice is already registered; select it instead")
    uncertain = any(
        prior.input_json.get("voice_profile_id") == profile.id
        and prior.checkpoint_json.get("pending_registration")
        and not prior.checkpoint_json.get("registration_result")
        for prior in session.scalars(
            select(Job).where(
                Job.project_id == project.id,
                Job.stage == "register_voice",
                Job.status == "failed",
            )
        ).all()
    )
    if uncertain and not payload.force_new:
        raise HTTPException(
            409,
            "Earlier upload outcome is unknown; inspect provider voices/usage "
            "before explicitly retrying",
        )
    reference = (
        session.get(Artifact, profile.reference_artifact_id)
        if profile.reference_artifact_id
        else None
    )
    if not reference:
        raise HTTPException(422, "Prepare and listen to the reference clip first")
    inputs.update(
        {
            "reference_artifact_id": reference.id,
            "reference_sha256": reference.metadata_json["sha256"],
            "reference_language": profile.settings_json["reference_language"],
            "display_name": profile.display_name,
        }
    )
    if provider == "sarvam":
        if payload.registration_allowance_inr is None:
            raise HTTPException(
                422, "Set a registration allowance; its exact provider tariff is unverified"
            )
        prep.cost = payload.registration_allowance_inr
