import copy

import pytest
from cinedub_api.config import get_settings
from cinedub_api.models import Artifact, Job, ProviderRun, Segment, VoiceProfile
from cinedub_api.providers import ProviderRegistry
from cinedub_api.providers.base import SynthesisResult
from cinedub_api.providers.fake import FakeProvider
from cinedub_api.providers.sarvam import SarvamProvider
from cinedub_api.schemas import StockVoiceAssignment
from cinedub_api.worker import process_once
from pydantic import ValidationError
from test_dialogue_review import scene


@pytest.mark.parametrize("value", [0, -0.1, 1.01, float("nan"), float("inf"), True, "0.6"])
def test_variation_requires_a_finite_supported_number(value):
    with pytest.raises(ValidationError):
        StockVoiceAssignment(provider="sarvam", voice_id="ritu", variation=value)


def test_demo_tones_and_clone_adapter_do_not_silently_accept_variation(tmp_path):
    with pytest.raises(ValidationError):
        StockVoiceAssignment(provider="fake", voice_id="speaker-a", variation=0.6)
    with pytest.raises(ValueError):
        FakeProvider().synthesize(
            "x", "ml-IN", tmp_path / "out.wav", voice_id="speaker-a", variation=0.6
        )
    with pytest.raises(ValueError):
        SarvamProvider("synthetic", "https://api.invalid").synthesize(
            "x", "ml-IN", tmp_path / "out.wav", voice_id="clone", voice_kind="clone", variation=0.6
        )
    assert not (tmp_path / "out.wav").exists()


@pytest.mark.anyio
async def test_variation_versioning_noop_legacy_defaults_and_conflicts(client, session):
    project, revision, speaker = scene(session)
    saved = session.query(Segment).filter_by(speaker_id=speaker.id).first()
    saved.selected_candidate_id = "synthetic-historical-take"
    version = saved.version
    session.commit()
    url = f"/speakers/{speaker.id}/stock-voice"
    assigned = await client.post(
        url, json={"provider": "sarvam", "voice_id": "ritu", "variation": 0.82}
    )
    assert assigned.status_code == 200
    first = assigned.json()
    assert first["settings_json"] == {"pace": 1, "variation": 0.82}
    session.expire_all()
    assert saved.status == "approved" and saved.translated_text == "ആൻ രവിയെ കണ്ടു."
    assert saved.selected_candidate_id is None and saved.version == version + 1
    same = await client.post(url, json={"provider": "sarvam", "voice_id": "ritu"})
    assert same.json()["version"] == first["version"]
    assert same.json()["settings_json"]["variation"] == 0.82
    updated = await client.post(
        url,
        json={
            "provider": "sarvam",
            "voice_id": "ritu",
            "variation": 0.43,
            "expected_profile_id": first["id"],
            "expected_profile_version": first["version"],
        },
    )
    assert updated.status_code == 200 and updated.json()["version"] == first["version"] + 1
    stale = await client.post(
        url,
        json={
            "provider": "sarvam",
            "voice_id": "ritu",
            "variation": 0.99,
            "expected_profile_id": first["id"],
            "expected_profile_version": first["version"],
        },
    )
    assert stale.status_code == 409
    wrong = await client.post(
        url, json={"provider": "sarvam", "voice_id": "ritu", "expected_profile_id": None}
    )
    assert wrong.status_code == 409
    session.expire_all()
    profile = session.get(VoiceProfile, first["id"])
    assert profile.settings_json["variation"] == 0.43
    profile.settings_json = {"pace": 1}
    session.commit()
    version = profile.version
    legacy = await client.post(
        url, json={"provider": "sarvam", "voice_id": "ritu", "variation": 0.6}
    )
    assert legacy.json()["version"] == version
    assert legacy.json()["settings_json"] == {"pace": 1}  # No invented historical backfill.
    profile.settings_json = {"pace": 1, "variation": 2}
    session.commit()
    invalid = await client.post(url, json={"provider": "sarvam", "voice_id": "ritu"})
    assert invalid.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["normal", "missing", "invalid"])
async def test_synthesis_freezes_and_executes_variation_or_holds_unfrozen_legacy(
    client, session, monkeypatch, mode
):
    project, revision, speaker = scene(session)
    assigned = await client.post(
        f"/speakers/{speaker.id}/stock-voice",
        json={
            "provider": "sarvam",
            "voice_id": "ritu",
            "variation": 0.82,
        },
    )
    assert assigned.status_code == 200
    session.expire_all()
    line = session.query(Segment).filter_by(speaker_id=speaker.id).first()
    line.status = "approved"
    session.commit()
    settings = get_settings().model_copy(update={"sarvam_api_key": "synthetic-test-only"})
    monkeypatch.setattr("cinedub_api.jobs.get_settings", lambda: settings)
    calls = []

    class Recorded:
        def synthesize(self, text, language, output, **options):
            calls.append(options)
            FakeProvider().synthesize(text, language, output, voice_id="speaker-a")
            return SynthesisResult(output, "sarvam", "bulbul:v3", "recorded")

    monkeypatch.setattr(ProviderRegistry, "voice_synthesizer", lambda *args: Recorded())
    response = await client.post(
        f"/projects/{project.id}/jobs",
        json={
            "stage": "synthesize",
            "provider": "sarvam",
            "segment_ids": [line.id],
        },
    )
    assert response.status_code == 202, response.text
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.input_json["voices"][line.id]["variation"] == 0.82
    if mode != "normal":
        payload = copy.deepcopy(job.input_json)
        if mode == "missing":
            payload["voices"][line.id].pop("variation")
        else:
            payload["voices"][line.id]["variation"] = 2
        job.input_json = payload
        session.commit()
    assert process_once(session)
    if mode != "normal":
        assert job.status == "failed" and "variation" in job.error_message
        assert calls == [] and job.charged_estimate_inr == 0
        return
    assert job.status == "completed", job.error_message
    assert calls[0]["variation"] == 0.82
    candidate = session.query(Artifact).filter_by(job_id=job.id, kind="dialogue_candidate").one()
    assert candidate.metadata_json["voice"]["variation"] == 0.82
    run = session.query(ProviderRun).filter_by(job_id=job.id).one()
    assert run.parameters_json["voice"]["variation"] == 0.82
    changed = await client.post(
        f"/speakers/{speaker.id}/stock-voice",
        json={
            "provider": "sarvam",
            "voice_id": "ritu",
            "variation": 0.43,
        },
    )
    assert changed.status_code == 200
    fresh = await client.post(
        f"/projects/{project.id}/jobs",
        json={
            "stage": "synthesize",
            "provider": "sarvam",
            "segment_ids": [line.id],
        },
    )
    assert fresh.status_code == 202 and fresh.json()["id"] != job.id
    assert session.get(Job, fresh.json()["id"]).input_json["voices"][line.id]["variation"] == 0.43
