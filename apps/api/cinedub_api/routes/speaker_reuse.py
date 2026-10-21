"""Explicit character reuse, never automatic cross-run speaker identification."""

import hashlib
import json
from datetime import UTC

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..dependencies import SessionDep, require_project
from ..jobs import ACTIVE, write_lock
from ..models import Job, SegmentEdit, Speaker, SpeakerReuse, TimelineRevision, VoiceProfile
from ..schemas import (
    SegmentRead,
    SpeakerRead,
    SpeakerReuseApply,
    SpeakerReusePreview,
    SpeakerReuseRead,
    StockVoiceAssignment,
)
from ..timeline import revision_segments
from ..voices import stock_catalog

router = APIRouter(tags=["speaker reuse"])


def scope(session, target_id, source_id):
    target, source = session.get(Speaker, target_id), session.get(Speaker, source_id)
    if not target or not source or target.project_id != source.project_id:
        raise HTTPException(422, "Select speakers belonging to the same project")
    project = require_project(session, target.project_id)
    target_revision = (
        session.get(TimelineRevision, target.revision_id) if target.revision_id else None
    )
    source_revision = (
        session.get(TimelineRevision, source.revision_id) if source.revision_id else None
    )
    if (
        not target_revision
        or project.active_revision_id != target.revision_id
        or not source_revision
        or source_revision.id == target_revision.id
        or source_revision.project_id != project.id
        or target_revision.project_id != project.id
        or source_revision.created_at.replace(tzinfo=UTC)
        >= target_revision.created_at.replace(tzinfo=UTC)
    ):
        raise HTTPException(409, "Select an active speaker and a speaker from an earlier revision")
    return project, target, source


def snapshot(session, speaker):
    profile = (
        session.get(VoiceProfile, speaker.voice_profile_id) if speaker.voice_profile_id else None
    )
    if speaker.voice_profile_id and (
        not profile or profile.project_id != speaker.project_id or profile.speaker_id != speaker.id
    ):
        raise HTTPException(
            409, "Selected voice provenance belongs to another speaker or is unavailable"
        )
    return {
        **SpeakerRead.model_validate(speaker).model_dump(mode="json"),
        "updated_at": speaker.updated_at.isoformat(),
        "voice": {
            "id": profile.id,
            "kind": profile.voice_kind,
            "provider": profile.provider,
            "voice_id": profile.provider_voice_id,
            "version": profile.version,
            "settings": profile.settings_json,
            "consent_status": profile.consent_status,
            "registration_status": profile.registration_status,
        }
        if profile
        else {},
    }


def preview(session, target_id, source_id, copy_stock_voice):
    project, target, source = scope(session, target_id, source_id)
    source_state, target_state = snapshot(session, source), snapshot(session, target)
    voice = source_state["voice"]
    if copy_stock_voice:
        if voice.get("kind") != "preset" or voice.get("provider") not in {"fake", "sarvam"}:
            raise HTTPException(
                422, "Only an explicit stock voice may be copied; clones need fresh scoped consent"
            )
        try:
            assignment = StockVoiceAssignment(
                provider=voice["provider"],
                voice_id=voice["voice_id"],
                pace=voice["settings"].get("pace", 1),
                variation=voice["settings"].get("variation"),
            )
        except ValueError:
            raise HTTPException(422, "Historical stock voice settings are invalid") from None
        if assignment.voice_id not in {item.id for item in stock_catalog(assignment.provider)}:
            raise HTTPException(422, "Historical stock voice is not in the supported catalog")
    lines = [
        line
        for line in revision_segments(session, project.id, target.revision_id)
        if line.speaker_id == target.id
    ]
    material = {
        "project_id": project.id,
        "revision_id": project.active_revision_id,
        "source": source_state,
        "target": target_state,
        "copy_stock_voice": copy_stock_voice,
        "lines": [SegmentRead.model_validate(line).model_dump(mode="json") for line in lines],
    }
    fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    result = SpeakerReusePreview(
        source=SpeakerRead.model_validate(source),
        target=SpeakerRead.model_validate(target),
        copy_stock_voice=copy_stock_voice,
        voice=voice if copy_stock_voice else {},
        affected_line_ids=[line.id for line in lines],
        fingerprint=fingerprint,
        warnings=[
            "Manual identity decision, not biometric recognition. Audition both speakers first.",
            "Affected lines keep their text/timing but lose approval and selected takes.",
            "Briefs, cloned voices and consent are never copied.",
        ],
    )
    return result, material, target, source, lines


@router.get("/projects/{project_id}/earlier-speakers", response_model=list[SpeakerRead])
async def earlier_speakers(project_id: str, session: SessionDep):
    project = require_project(session, project_id)
    revision = (
        session.get(TimelineRevision, project.active_revision_id)
        if project.active_revision_id
        else None
    )
    if not revision:
        return []
    return list(
        session.scalars(
            select(Speaker)
            .join(TimelineRevision, Speaker.revision_id == TimelineRevision.id)
            .where(
                Speaker.project_id == project_id, TimelineRevision.created_at < revision.created_at
            )
            .order_by(TimelineRevision.created_at.desc(), Speaker.label)
            .limit(500)
        )
    )


@router.get("/speakers/{target_id}/reuse/{source_id}", response_model=SpeakerReusePreview)
async def reuse_preview(
    target_id: str, source_id: str, session: SessionDep, copy_stock_voice: bool = False
):
    return preview(session, target_id, source_id, copy_stock_voice)[0]


@router.get("/speakers/{target_id}/reuse-history", response_model=list[SpeakerReuseRead])
async def reuse_history(target_id: str, session: SessionDep):
    if not session.get(Speaker, target_id):
        raise HTTPException(404, "Speaker not found")
    return list(
        session.scalars(
            select(SpeakerReuse)
            .where(SpeakerReuse.target_speaker_id == target_id)
            .order_by(SpeakerReuse.created_at.desc())
            .limit(20)
        )
    )


@router.post("/speakers/{target_id}/reuse", response_model=SpeakerReuseRead)
async def apply_reuse(target_id: str, payload: SpeakerReuseApply, session: SessionDep):
    write_lock(session)
    project, target, _ = scope(session, target_id, payload.source_speaker_id)
    if not payload.identity_confirmed:
        raise HTTPException(422, "Confirm the reviewed identity and replacement consequences")
    if session.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Wait for active processing before reusing a character")
    existing = session.scalar(
        select(SpeakerReuse).where(
            SpeakerReuse.target_speaker_id == target_id,
            SpeakerReuse.fingerprint == payload.expected_fingerprint,
        )
    )
    if existing:
        if (
            existing.source_speaker_id != payload.source_speaker_id
            or existing.before_json["copy_stock_voice"] != payload.copy_stock_voice
        ):
            raise HTTPException(409, "Reuse request does not match its recorded operation")
        return existing  # A replay returns historical evidence, never reapplies changes.
    result, material, target, source, lines = preview(
        session, target_id, payload.source_speaker_id, payload.copy_stock_voice
    )
    if result.fingerprint != payload.expected_fingerprint:
        raise HTTPException(409, "Speaker, voice or dialogue changed; preview again")
    target.display_name = source.display_name
    if payload.copy_stock_voice:
        voice = result.voice
        profile = VoiceProfile(
            project_id=project.id,
            speaker_id=target.id,
            display_name=voice["voice_id"].title(),
            provider=voice["provider"],
            provider_voice_id=voice["voice_id"],
            voice_kind="preset",
            consent_status="not_required",
            settings_json={
                "pace": voice["settings"].get("pace", 1),
                **(
                    {"variation": voice["settings"]["variation"]}
                    if "variation" in voice["settings"]
                    else {}
                ),
            },
            registration_status="ready",
        )
        session.add(profile)
        session.flush()
        target.voice_profile_id = profile.id
    operation = SpeakerReuse(
        project_id=project.id,
        source_speaker_id=source.id,
        target_speaker_id=target.id,
        fingerprint=result.fingerprint,
        before_json=material,
        after_json={},
    )
    session.add(operation)
    session.flush()
    for line in lines:
        before = SegmentRead.model_validate(line).model_dump(mode="json")
        line.status = "needs_review"
        line.selected_candidate_id = None
        line.human_edited = True
        line.version += 1
        session.add(
            SegmentEdit(
                segment_id=line.id,
                version=line.version,
                before_json=before,
                after_json={
                    **SegmentRead.model_validate(line).model_dump(mode="json"),
                    "speaker_reuse_id": operation.id,
                },
            )
        )
    session.flush()
    operation.after_json = {
        "target": snapshot(session, target),
        "line_versions": {line.id: line.version for line in lines},
    }
    session.commit()
    return operation
