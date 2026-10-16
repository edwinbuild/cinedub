from datetime import UTC, datetime, timedelta

import pytest
from cinedub_api.models import (
    Job,
    Segment,
    SegmentEdit,
    Speaker,
    SpeakerReuse,
    TimelineRevision,
    VoiceProfile,
)
from test_dialogue_review import scene


@pytest.fixture
def actors(session):
    project, old, source = scene(session)
    old.created_at = datetime.now(UTC) - timedelta(minutes=1)
    source.display_name = "Captain Ravi"
    voice = VoiceProfile(
        project_id=project.id,
        speaker_id=source.id,
        display_name="Fixture voice",
        provider="fake",
        provider_voice_id="speaker-a",
        voice_kind="preset",
        consent_status="not_required",
        settings_json={"pace": 1.1},
        registration_status="ready",
    )
    session.add(voice)
    session.flush()
    source.voice_profile_id = voice.id
    current = TimelineRevision(
        project_id=project.id, provider="fake", model="rerun", created_at=datetime.now(UTC)
    )
    session.add(current)
    session.flush()
    target = Speaker(
        project_id=project.id, revision_id=current.id, label="run-2-A", display_name="Speaker A"
    )
    session.add(target)
    session.flush()
    line = Segment(
        project_id=project.id,
        revision_id=current.id,
        speaker_id=target.id,
        index=0,
        start_ms=0,
        end_ms=1000,
        source_text="Original unchanged text",
        translated_text="മലയാളം",
        status="approved",
        selected_candidate_id="historical-candidate",
        version=1,
    )
    session.add(line)
    project.active_revision_id = current.id
    session.commit()
    return project, source, target, voice, line


async def preview(client, source, target, copy=True):
    return await client.get(
        f"/speakers/{target.id}/reuse/{source.id}", params={"copy_stock_voice": copy}
    )


async def apply(client, source, target, fingerprint, **extra):
    return await client.post(
        f"/speakers/{target.id}/reuse",
        json={
            "source_speaker_id": source.id,
            "copy_stock_voice": True,
            "expected_fingerprint": fingerprint,
            "identity_confirmed": True,
            **extra,
        },
    )


@pytest.mark.anyio
async def test_reviewed_reuse_preserves_history_and_voice_identity_is_never_shared(
    client, session, actors
):
    project, source, target, voice, line = actors
    result = (await preview(client, source, target)).json()
    assert result["affected_line_ids"] == [line.id]
    assert (await client.get(f"/projects/{project.id}/earlier-speakers")).json()[0][
        "id"
    ] == source.id
    response = await apply(client, source, target, result["fingerprint"])
    assert response.status_code == 200, response.text
    session.expire_all()
    assert target.display_name == source.display_name == "Captain Ravi"
    assert target.voice_profile_id != voice.id
    copied = session.get(VoiceProfile, target.voice_profile_id)
    assert copied.speaker_id == target.id and copied.settings_json == {"pace": 1.1}
    assert voice.speaker_id == source.id and source.voice_profile_id == voice.id
    assert (
        line.status == "needs_review" and line.version == 2 and line.selected_candidate_id is None
    )
    assert line.source_text == "Original unchanged text" and line.translated_text == "മലയാളം"
    assert (
        session.query(SegmentEdit)
        .filter_by(segment_id=line.id)
        .one()
        .after_json["speaker_reuse_id"]
        == response.json()["id"]
    )
    target.display_name = "Later correction"
    session.commit()
    repeated = await apply(client, source, target, result["fingerprint"])
    assert repeated.json()["id"] == response.json()["id"]
    session.expire_all()
    assert target.display_name == "Later correction" and session.query(SpeakerReuse).count() == 1
    assert len((await client.get(f"/speakers/{target.id}/reuse-history")).json()) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change",
    ["source_name", "target_name", "profile", "line", "confirmation", "job", "active_revision"],
)
async def test_stale_or_unconfirmed_reuse_changes_nothing(client, session, actors, change):
    project, source, target, voice, line = actors
    fingerprint = (await preview(client, source, target)).json()["fingerprint"]
    extra = {}
    if change == "source_name":
        source.display_name = "Changed source"
    if change == "target_name":
        target.display_name = "Changed target"
    if change == "profile":
        voice.settings_json = {"pace": 1.2}
    if change == "line":
        line.version += 1
    if change == "confirmation":
        extra["identity_confirmed"] = False
    if change == "job":
        session.add(Job(project_id=project.id, stage="translate", provider="fake", status="queued"))
    if change == "active_revision":
        project.active_revision_id = source.revision_id
    session.commit()
    response = await apply(client, source, target, fingerprint, **extra)
    assert response.status_code in {409, 422}, response.text
    session.expire_all()
    assert not target.voice_profile_id and line.status == "approved"
    assert session.query(SpeakerReuse).count() == 0


@pytest.mark.anyio
async def test_clone_consent_is_never_transferred_but_names_can_be_reused(client, session, actors):
    _, source, target, voice, _ = actors
    voice.voice_kind = "clone"
    voice.consent_status = "revoked"
    session.commit()
    assert (await preview(client, source, target)).status_code == 422
    result = (await preview(client, source, target, copy=False)).json()
    response = await apply(client, source, target, result["fingerprint"], copy_stock_voice=False)
    assert response.status_code == 200
    session.expire_all()
    assert target.display_name == source.display_name and target.voice_profile_id is None
    assert voice.consent_status == "revoked" and voice.speaker_id == source.id


@pytest.mark.anyio
async def test_foreign_speakers_and_unknown_stock_settings_are_refused(client, session, actors):
    project, source, target, voice, _ = actors
    other, _, foreign = scene(session)
    assert (await preview(client, foreign, target)).status_code == 422
    assert (await client.get(f"/projects/{project.id}/earlier-speakers")).json()[0][
        "project_id"
    ] != other.id
    voice.provider_voice_id = "not-in-catalog"
    session.commit()
    assert (await preview(client, source, target)).status_code == 422
    voice.provider_voice_id = "speaker-a"
    voice.settings_json = {"pace": "invalid"}
    session.commit()
    assert (await preview(client, source, target)).status_code == 422
