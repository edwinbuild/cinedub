"""Voice selection, reference consent and candidate review HTTP boundary."""

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from ..consent import (
    TERMS_VERSION,
    artifact_block_reason,
    invalidate_takes,
    profile_is_selected,
    validate_voice_use,
)
from ..dependencies import SessionDep, require_project
from ..jobs import ACTIVE, write_lock
from ..models import (
    Artifact,
    ConsentRecord,
    Job,
    MediaAsset,
    Segment,
    Speaker,
    TimelineRevision,
    VoiceProfile,
)
from ..schemas import (
    CandidateSelection,
    ConsentRecordRead,
    ConsentRevocation,
    SegmentRead,
    SpeakerRead,
    StockVoiceAssignment,
    VoiceChoice,
    VoiceProfileCreate,
    VoiceProfileRead,
    VoiceProfileSelection,
)
from ..voices import candidate_signature, stock_catalog, stock_variation

router = APIRouter(tags=["voices"])


@router.get("/voices/stock", response_model=list[VoiceChoice])
async def stock_voices(provider: Literal["sarvam", "fake"] = "sarvam"):
    return stock_catalog(provider)


@router.post("/speakers/{speaker_id}/stock-voice", response_model=VoiceProfileRead)
async def assign_stock_voice(speaker_id: str, payload: StockVoiceAssignment, session: SessionDep):
    write_lock(session)
    speaker = session.get(Speaker, speaker_id)
    if not speaker:
        raise HTTPException(404, "Speaker not found")
    if payload.voice_id not in {voice.id for voice in stock_catalog(payload.provider)}:
        raise HTTPException(422, "Voice does not belong to this provider/model catalog")
    if "expected_profile_id" in payload.model_fields_set:
        selected = (
            session.get(VoiceProfile, speaker.voice_profile_id)
            if speaker.voice_profile_id
            else None
        )
        if speaker.voice_profile_id != payload.expected_profile_id or (
            payload.expected_profile_version is not None
            and (not selected or selected.version != payload.expected_profile_version)
        ):
            raise HTTPException(409, "Selected voice changed; refresh before saving voice settings")
    profile = session.scalar(
        select(VoiceProfile)
        .where(
            VoiceProfile.speaker_id == speaker.id,
            VoiceProfile.voice_kind == "preset",
            VoiceProfile.provider == payload.provider,
        )
        .order_by(VoiceProfile.updated_at.desc())
    )
    voice_settings = {"pace": payload.pace}
    if payload.provider == "sarvam":
        try:
            voice_settings["variation"] = stock_variation(
                payload.variation
                if payload.variation is not None
                else profile.settings_json.get("variation", 0.6)
                if profile
                else 0.6
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    previous = dict(profile.settings_json) if profile else {}
    if profile and payload.provider == "sarvam":
        previous.setdefault("variation", 0.6)
    if profile:
        if (
            profile.provider_voice_id == payload.voice_id
            and previous == voice_settings
            and speaker.voice_profile_id == profile.id
        ):
            return profile
        profile.version += 1
        profile.provider_voice_id = payload.voice_id
        profile.settings_json = voice_settings
    else:
        profile = VoiceProfile(
            project_id=speaker.project_id,
            speaker_id=speaker.id,
            display_name=payload.voice_id.title(),
            provider=payload.provider,
            provider_voice_id=payload.voice_id,
            consent_status="not_required",
            voice_kind="preset",
            settings_json=voice_settings,
            registration_status="ready",
        )
        session.add(profile)
    session.flush()
    speaker.voice_profile_id = profile.id
    invalidate_takes(session, speaker_id)
    session.commit()
    session.refresh(profile)
    return profile


@router.post("/segments/{segment_id}/candidate", response_model=SegmentRead)
async def select_candidate(segment_id: str, payload: CandidateSelection, session: SessionDep):
    write_lock(session)
    line = session.get(Segment, segment_id)
    artifact = session.get(Artifact, payload.artifact_id)
    if (
        not line
        or line.retired
        or not artifact
        or artifact.project_id != line.project_id
        or artifact.kind != "dialogue_candidate"
        or artifact.metadata_json.get("segment_id") != line.id
    ):
        raise HTTPException(422, "Candidate does not belong to this dialogue line")
    voice = artifact.metadata_json.get("voice", {})
    profile = session.get(VoiceProfile, voice.get("profile_id"))
    current = SegmentRead.model_validate(line).model_dump()
    if (
        not profile
        or profile.version != voice.get("profile_version")
        or not profile_is_selected(session, profile)
        or artifact.metadata_json.get("signature") != candidate_signature(current, voice)
    ):
        raise HTTPException(
            409, "Candidate is stale; generate audio for the current text/timing/voice"
        )
    if artifact_block_reason(session, artifact):
        raise HTTPException(422, "Cloning consent is revoked; this candidate is quarantined")
    if artifact.metadata_json.get("fit_status") != "ready":
        raise HTTPException(
            422, "Candidate exceeds safe timing fit; shorten the translation or adjust timing"
        )
    result = session.execute(
        update(Segment)
        .where(Segment.id == line.id, Segment.version == payload.expected_version)
        .values(selected_candidate_id=artifact.id, version=Segment.version + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Line changed; refresh before selecting audio")
    session.commit()
    session.refresh(line)
    return line


@router.post(
    "/projects/{project_id}/voice-profiles",
    response_model=VoiceProfileRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_voice_profile(
    project_id: str,
    payload: VoiceProfileCreate,
    session: SessionDep,
) -> VoiceProfile:
    write_lock(session)
    require_project(session, project_id)
    speaker = session.get(Speaker, payload.speaker_id)
    if not speaker or speaker.project_id != project_id:
        raise HTTPException(status_code=422, detail="Speaker does not belong to this project")
    reference = session.get(MediaAsset, payload.reference_asset_id)
    if not reference or reference.project_id != project_id:
        raise HTTPException(422, "Reference asset does not belong to this project")
    if not reference.duration_ms or payload.reference_end_ms > reference.duration_ms:
        raise HTTPException(422, "Reference range exceeds source duration")
    if not 10000 <= payload.reference_end_ms - payload.reference_start_ms <= 15000:
        raise HTTPException(422, "Choose a clean 10–15 second single-speaker reference")
    consent = payload.consent
    if (
        not consent.approved
        or not consent.allows_provider_upload
        or not consent.clean_single_speaker
        or not consent.attested_by.strip()
        or not consent.rights_holder.strip()
        or not payload.display_name.strip()
    ):
        raise HTTPException(
            422,
            "Rights-holder consent, upload permission and single-speaker review are required",
        )
    revision = session.get(TimelineRevision, speaker.revision_id) if speaker.revision_id else None
    if (
        revision
        and revision.source_asset_id == reference.id
        and session.scalar(
            select(Segment.id).where(
                Segment.revision_id == revision.id,
                Segment.speaker_id.is_not(None),
                Segment.speaker_id != speaker.id,
                Segment.start_ms < payload.reference_end_ms,
                Segment.end_ms > payload.reference_start_ms,
            )
        )
    ):
        raise HTTPException(
            422, "Reference range includes another assigned speaker; choose a clean recording"
        )
    profile = VoiceProfile(
        project_id=project_id,
        speaker_id=payload.speaker_id,
        display_name=payload.display_name.strip(),
        provider=payload.provider,
        reference_asset_id=payload.reference_asset_id,
        consent_status="approved",
        voice_kind="clone",
        settings_json={
            "reference_start_ms": payload.reference_start_ms,
            "reference_end_ms": payload.reference_end_ms,
            "reference_language": "en-IN",
            "pace": 1.0,
            "enable_qc": True,
        },
    )
    session.add(profile)
    session.flush()
    session.add(
        ConsentRecord(
            voice_profile_id=profile.id,
            status=profile.consent_status,
            attested_by=consent.attested_by.strip(),
            note=consent.note,
            scope_json={
                "terms_version": TERMS_VERSION,
                "project_id": project_id,
                "provider": payload.provider,
                "speaker_id": speaker.id,
                "reference_asset_id": reference.id,
                "reference_start_ms": payload.reference_start_ms,
                "reference_end_ms": payload.reference_end_ms,
                "rights_holder": consent.rights_holder.strip(),
                "allows_provider_upload": True,
                "clean_single_speaker": True,
            },
        )
    )
    session.commit()
    session.refresh(profile)
    return profile


@router.post("/speakers/{speaker_id}/voice-profile", response_model=SpeakerRead)
async def select_voice_profile(
    speaker_id: str, payload: VoiceProfileSelection, session: SessionDep
):
    write_lock(session)
    speaker = session.get(Speaker, speaker_id)
    profile = session.get(VoiceProfile, payload.profile_id)
    if (
        not speaker
        or not profile
        or profile.speaker_id != speaker_id
        or profile.project_id != speaker.project_id
    ):
        raise HTTPException(422, "Voice profile does not belong to this speaker")
    if speaker.voice_profile_id != payload.expected_profile_id:
        raise HTTPException(409, "Voice selection changed; refresh first")
    try:
        validate_voice_use(session, profile)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    speaker.voice_profile_id = profile.id
    invalidate_takes(session, speaker.id)
    session.commit()
    return speaker


@router.get("/voice-profiles/{profile_id}/consent", response_model=list[ConsentRecordRead])
async def voice_consent_history(profile_id: str, session: SessionDep):
    if not session.get(VoiceProfile, profile_id):
        raise HTTPException(404, "Voice profile not found")
    return session.scalars(
        select(ConsentRecord)
        .where(ConsentRecord.voice_profile_id == profile_id)
        .order_by(ConsentRecord.attested_at)
    ).all()


@router.post("/voice-profiles/{profile_id}/revoke", response_model=VoiceProfileRead)
async def revoke_voice_consent(profile_id: str, payload: ConsentRevocation, session: SessionDep):
    write_lock(session)
    profile = session.get(VoiceProfile, profile_id)
    if not profile or profile.voice_kind != "clone":
        raise HTTPException(422, "Select a cloned-voice profile")
    if not payload.attested_by.strip():
        raise HTTPException(422, "Enter who is recording revocation")
    if profile.consent_status == "revoked":
        return profile
    profile.consent_status = "revoked"
    profile.version += 1
    speaker = session.get(Speaker, profile.speaker_id)
    if speaker.voice_profile_id == profile.id:
        speaker.voice_profile_id = None
    invalidate_takes(session, profile.speaker_id, profile.id)
    session.add(
        ConsentRecord(
            voice_profile_id=profile.id,
            status="revoked",
            attested_by=payload.attested_by.strip(),
            note=payload.note,
            scope_json={
                "terms_version": TERMS_VERSION,
                "project_id": profile.project_id,
                "provider": profile.provider,
            },
        )
    )
    for job in session.scalars(
        select(Job).where(Job.project_id == profile.project_id, Job.status.in_(ACTIVE))
    ).all():
        if (
            job.input_json.get("voice_profile_id") == profile.id
            or any(
                voice.get("profile_id") == profile.id
                for voice in job.input_json.get("voices", {}).values()
            )
            or (
                job.stage in {"render_preview", "render_mix", "package_mix"}
                and any(
                    not candidate or artifact_block_reason(session, candidate)
                    for candidate_id in job.input_json.get("candidates", {}).values()
                    for candidate in [session.get(Artifact, candidate_id)]
                )
            )
        ):
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.phase = "cancelled"
    session.flush()
    if not session.scalar(
        select(Job.id).where(Job.project_id == profile.project_id, Job.status.in_(ACTIVE))
    ):
        require_project(session, profile.project_id).status = "review"
    session.commit()
    return profile
