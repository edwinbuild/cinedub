"""Fail-closed clone consent and artifact access, independent of voice vendor."""

from sqlalchemy import select, update

from .models import Artifact, ConsentRecord, Segment, Speaker, VoiceProfile

TERMS_VERSION = "cinedub-project-clone-v1"


def approved_consent(session, profile):
    if not profile or profile.voice_kind != "clone" or profile.consent_status != "approved":
        raise ValueError("Cloning consent is not approved or has been revoked")
    record = session.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.voice_profile_id == profile.id)
        .order_by(
            ConsentRecord.attested_at.desc(),
            ConsentRecord.created_at.desc(),
            ConsentRecord.id.desc(),
        )
    )
    scope = record.scope_json if record else {}
    if (
        not record
        or record.status != "approved"
        or scope.get("terms_version") != TERMS_VERSION
        or scope.get("project_id") != profile.project_id
        or scope.get("provider") != profile.provider
        or scope.get("speaker_id") != profile.speaker_id
        or scope.get("reference_asset_id") != profile.reference_asset_id
        or scope.get("reference_start_ms") != profile.settings_json.get("reference_start_ms")
        or scope.get("reference_end_ms") != profile.settings_json.get("reference_end_ms")
        or not scope.get("allows_provider_upload")
        or not scope.get("clean_single_speaker")
        or not scope.get("rights_holder")
    ):
        raise ValueError("Scoped consent is missing; create a new consented reference profile")
    return record


def validate_voice_use(session, profile):
    if not profile:
        raise ValueError("Assign a voice to every selected speaker first")
    if profile.voice_kind == "preset":
        return
    approved_consent(session, profile)
    if profile.registration_status != "ready" or not profile.provider_voice_id:
        raise ValueError("Prepare and register the consented reference before using this clone")


def invalidate_takes(session, speaker_id, profile_id=None):
    query = update(Segment).where(
        Segment.speaker_id == speaker_id, Segment.selected_candidate_id.is_not(None)
    )
    if profile_id:
        ids = []
        for line in session.scalars(select(Segment).where(Segment.speaker_id == speaker_id)).all():
            artifact = (
                session.get(Artifact, line.selected_candidate_id)
                if line.selected_candidate_id
                else None
            )
            if artifact and artifact.metadata_json.get("voice", {}).get("profile_id") == profile_id:
                ids.append(line.id)
        query = query.where(Segment.id.in_(ids))
    session.execute(query.values(selected_candidate_id=None, version=Segment.version + 1))


def artifact_block_reason(session, artifact, seen=None):
    seen = seen or set()
    if artifact.id in seen:
        return "Invalid artifact lineage"
    seen.add(artifact.id)
    metadata = artifact.metadata_json
    ids = set(metadata.get("voice_profile_ids", []))
    if metadata.get("voice_profile_id"):
        ids.add(metadata["voice_profile_id"])
    if metadata.get("voice", {}).get("profile_id"):
        ids.add(metadata["voice"]["profile_id"])
    for profile_id in ids:
        profile = session.get(VoiceProfile, profile_id)
        if not profile:
            return "Voice profile provenance is unavailable"
        if profile.voice_kind == "clone":
            try:
                approved_consent(session, profile)
            except ValueError:
                return "Cloning consent revoked or unavailable; this audio is quarantined"
    for candidate_id in metadata.get("candidates", {}).values():
        candidate = session.get(Artifact, candidate_id)
        if not candidate:
            return "Candidate provenance is unavailable"
        reason = artifact_block_reason(session, candidate, seen.copy())
        if reason:
            return reason
    return None


def profile_is_selected(session, profile):
    speaker = session.get(Speaker, profile.speaker_id)
    return bool(speaker and speaker.voice_profile_id == profile.id)
