import base64
import io
import math
import struct
import wave

import httpx
import pytest
from cinedub_api.config import get_settings
from cinedub_api.database import SessionLocal
from cinedub_api.models import Artifact, ConsentRecord, Job, VoiceProfile
from cinedub_api.providers.base import VoiceRegistrationResult
from cinedub_api.providers.fake import FakeProvider
from cinedub_api.providers.sarvam import SarvamProvider
from cinedub_api.worker import process_once, recover_jobs
from test_voice_workflow import prepare_reviewed_scene, wav


def reference_wav(seconds=12, silent=False):
    data = io.BytesIO()
    with wave.open(data, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(
            b"".join(
                struct.pack(
                    "<h", 0 if silent else round(2000 * math.sin(i * 2 * math.pi * 220 / 16000))
                )
                for i in range(seconds * 16000)
            )
        )
    return data.getvalue()


async def setup_clone(client, session, *, provider="fake", silent=False):
    scene = await prepare_reviewed_scene(client, session)
    asset = (
        await client.post(
            f"/projects/{scene['id']}/assets",
            files={"file": ("synthetic-reference.wav", reference_wav(silent=silent), "audio/wav")},
        )
    ).json()
    assert process_once(session)
    payload = {
        "speaker_id": scene["speakers"][0]["id"],
        "display_name": "Synthetic reference",
        "provider": provider,
        "reference_asset_id": asset["id"],
        "reference_start_ms": 0,
        "reference_end_ms": 10000,
        "consent": {
            "approved": True,
            "attested_by": "Synthetic test operator",
            "rights_holder": "Synthetic fixture",
            "note": "No actor voice in this test",
            "allows_provider_upload": True,
            "clean_single_speaker": True,
        },
    }
    return scene, asset, payload


async def stage(client, session, project_id, payload, *, success=True):
    response = await client.post(f"/projects/{project_id}/jobs", json=payload)
    assert response.status_code == 202, response.text
    assert process_once(session)
    detail = (await client.get(f"/projects/{project_id}")).json()
    assert detail["jobs"][0]["status"] == ("completed" if success else "failed"), detail["jobs"][0]
    return detail


@pytest.mark.anyio
async def test_consent_reference_enrollment_selection_and_revocation(client, session):
    scene, asset, payload = await setup_clone(client, session)
    endpoint = f"/projects/{scene['id']}/voice-profiles"
    for flag in ["approved", "allows_provider_upload", "clean_single_speaker"]:
        rejected = await client.post(
            endpoint, json={**payload, "consent": {**payload["consent"], flag: False}}
        )
        assert rejected.status_code == 422
    assert (
        await client.post(endpoint, json={**payload, "reference_end_ms": 16000})
    ).status_code == 422
    assert (
        await client.post(endpoint, json={**payload, "reference_end_ms": 9000})
    ).status_code == 422
    assert (
        await client.post(endpoint, json={**payload, "provider_voice_id": "bypass"})
    ).status_code == 422
    assert (
        await client.post(
            endpoint,
            json={
                **payload,
                "reference_asset_id": scene["assets"][0]["id"],
                "reference_end_ms": 10000,
            },
        )
    ).status_code == 422
    profile = (await client.post(endpoint, json=payload)).json()
    assert (
        profile["consent_status"] == "approved" and profile["registration_status"] == "unprepared"
    )
    register = {
        "stage": "register_voice",
        "provider": "fake",
        "voice_profile_id": profile["id"],
        "reference_reviewed": True,
    }
    assert (await client.post(f"/projects/{scene['id']}/jobs", json=register)).status_code == 422
    detail = await stage(
        client,
        session,
        scene["id"],
        {"stage": "prepare_reference", "voice_profile_id": profile["id"]},
    )
    profile = next(p for p in detail["voice_profiles"] if p["id"] == profile["id"])
    reference = next(a for a in detail["artifacts"] if a["id"] == profile["reference_artifact_id"])
    with wave.open(io.BytesIO((await client.get(reference["content_url"])).content)) as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getnframes()) == (
            24000,
            1,
            240000,
        )
    assert reference["metadata_json"]["source_asset_id"] == asset["id"]
    assert (
        await client.post(
            f"/projects/{scene['id']}/jobs", json={**register, "reference_reviewed": False}
        )
    ).status_code == 422
    detail = await stage(client, session, scene["id"], register)
    speaker = detail["speakers"][0]
    assert speaker["voice_profile_id"] != profile["id"]  # No automatic voice switch.
    select = {"profile_id": profile["id"], "expected_profile_id": speaker["voice_profile_id"]}
    assert (
        await client.post(
            f"/speakers/{speaker['id']}/voice-profile", json={**select, "expected_profile_id": None}
        )
    ).status_code == 409
    assert (
        await client.post(f"/speakers/{speaker['id']}/voice-profile", json=select)
    ).status_code == 200
    detail = await stage(client, session, scene["id"], {"stage": "synthesize", "force_new": True})
    line = next(line for line in detail["segments"] if line["speaker_id"] == speaker["id"])
    candidate = next(
        a
        for a in detail["artifacts"]
        if a["kind"] == "dialogue_candidate"
        and a["metadata_json"]["voice"]["profile_id"] == profile["id"]
    )
    assert (
        await client.post(
            f"/segments/{line['id']}/candidate",
            json={"artifact_id": candidate["id"], "expected_version": line["version"]},
        )
    ).status_code == 200
    detail = await stage(client, session, scene["id"], {"stage": "render_preview"})
    mix = next(a for a in detail["artifacts"] if a["kind"] == "dialogue_mix")
    assert (await client.get(mix["download_url"])).status_code == 200
    revoked = await client.post(
        f"/voice-profiles/{profile['id']}/revoke", json={"attested_by": "Rights holder"}
    )
    assert revoked.status_code == 200 and revoked.json()["consent_status"] == "revoked"
    detail = (await client.get(f"/projects/{scene['id']}")).json()
    assert (
        next(s for s in detail["speakers"] if s["id"] == speaker["id"])["voice_profile_id"] is None
    )
    for artifact in [reference, candidate, mix]:
        assert (await client.get(artifact["download_url"])).status_code == 403
        assert (
            await client.head(artifact["content_url"], headers={"Range": "bytes=0-3"})
        ).status_code == 403
        assert next(a for a in detail["artifacts"] if a["id"] == artifact["id"])[
            "access_blocked_reason"
        ]
    assert (
        await client.post(f"/projects/{scene['id']}/jobs", json={"stage": "synthesize"})
    ).status_code == 422
    history = (await client.get(f"/voice-profiles/{profile['id']}/consent")).json()
    assert [record["status"] for record in history] == ["approved", "revoked"]
    assert history[0]["scope_json"]["rights_holder"] == "Synthetic fixture"
    await stage(
        client,
        session,
        scene["id"],
        {"stage": "delete_voice", "provider": "fake", "voice_profile_id": profile["id"]},
    )
    # Explicit stock fallback is still available; no silent cloning fallback.
    assert (
        await client.post(
            f"/speakers/{speaker['id']}/stock-voice",
            json={"provider": "fake", "voice_id": "speaker-a"},
        )
    ).status_code == 200


@pytest.mark.anyio
async def test_reference_failure_and_revocation_before_dispatch(client, session):
    scene, _, payload = await setup_clone(client, session, silent=True)
    profile = (await client.post(f"/projects/{scene['id']}/voice-profiles", json=payload)).json()
    detail = await stage(
        client,
        session,
        scene["id"],
        {"stage": "prepare_reference", "voice_profile_id": profile["id"]},
        success=False,
    )
    assert "silent" in detail["jobs"][0]["error_message"]
    assert not any(a["kind"] == "voice_reference" for a in detail["artifacts"])
    old_selection = {line["id"]: line["selected_candidate_id"] for line in detail["segments"]}
    await client.post(
        f"/voice-profiles/{profile['id']}/revoke", json={"attested_by": "Test operator"}
    )
    detail = (await client.get(f"/projects/{scene['id']}")).json()
    assert {
        line["id"]: line["selected_candidate_id"] for line in detail["segments"]
    } == old_selection


def test_recorded_sarvam_clone_contracts(monkeypatch, tmp_path):
    path = tmp_path / "reference.wav"
    path.write_bytes(reference_wav())
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/voices/create"):
            assert kwargs["files"]["file"][1].read() == path.read_bytes()
            return httpx.Response(
                201,
                json={
                    "status": "success",
                    "data": {
                        "voice_id": "svc-recorded-id",
                        "reference_text": "Original synthetic speech",
                    },
                },
                request=httpx.Request("POST", url),
            )
        assert kwargs["files"]["enable_qc"] == (None, "true")
        assert kwargs["files"]["pace"] == (None, "1.0")
        assert "ref_audio" not in kwargs["files"]
        return httpx.Response(
            200,
            json={"audio_b64": base64.b64encode(wav(1)).decode(), "request_id": "recorded"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(
        httpx,
        "delete",
        lambda url, **kwargs: httpx.Response(404, request=httpx.Request("DELETE", url)),
    )
    provider = SarvamProvider("test-only", "https://api.invalid")
    registered = provider.register_voice(path, "Reference", "en-IN")
    assert registered.voice_id == "svc-recorded-id" and registered.reference_text
    result = provider.synthesize(
        "മലയാളം",
        "ml-IN",
        tmp_path / "candidate.wav",
        voice_id=registered.voice_id,
        voice_kind="clone",
    )
    assert result.audio_path.read_bytes() == wav(1)
    provider.delete_voice(registered.voice_id)
    with pytest.raises(ValueError, match="1000"):
        provider.synthesize(
            "a" * 1001, "ml-IN", path, voice_id=registered.voice_id, voice_kind="clone"
        )
    assert len(calls) == 2


def test_uncertain_remote_registration_is_not_requeued(session):
    from cinedub_api.models import Project

    project = Project(name="Interrupted clone")
    session.add(project)
    session.flush()
    job = Job(
        project_id=project.id,
        stage="register_voice",
        provider="sarvam",
        status="running",
        checkpoint_json={"pending_registration": True},
    )
    session.add(job)
    session.commit()
    recover_jobs(session)
    assert job.status == "failed" and job.error_code == "uncertain_submission"


@pytest.mark.anyio
async def test_unknown_upload_charges_allowance_once_and_requires_explicit_retry(
    client, session, monkeypatch
):
    scene, _, payload = await setup_clone(client, session, provider="sarvam")
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "test-only")
    profile = (await client.post(f"/projects/{scene['id']}/voice-profiles", json=payload)).json()
    await stage(
        client,
        session,
        scene["id"],
        {"stage": "prepare_reference", "voice_profile_id": profile["id"]},
    )
    calls = []

    def uncertain(*args):
        calls.append(True)
        raise httpx.ReadTimeout("ambiguous", request=httpx.Request("POST", "https://api.invalid"))

    monkeypatch.setattr(SarvamProvider, "register_voice", uncertain)
    register = {
        "stage": "register_voice",
        "provider": "sarvam",
        "voice_profile_id": profile["id"],
        "reference_reviewed": True,
    }
    assert (await client.post(f"/projects/{scene['id']}/jobs", json=register)).status_code == 422
    detail = await stage(
        client, session, scene["id"], {**register, "registration_allowance_inr": 2}, success=False
    )
    assert len(calls) == 1 and detail["spent_estimate_inr"] == 2
    assert detail["jobs"][0]["error_code"] == "uncertain_registration"
    assert (
        await client.post(
            f"/projects/{scene['id']}/jobs", json={**register, "registration_allowance_inr": 2}
        )
    ).status_code == 409
    retry = await client.post(
        f"/projects/{scene['id']}/jobs",
        json={**register, "registration_allowance_inr": 2, "force_new": True},
    )
    assert retry.status_code == 202
    await client.post(
        f"/voice-profiles/{profile['id']}/revoke", json={"attested_by": "Test operator"}
    )
    assert not process_once(session)  # Revocation cancelled the queued external operation.
    assert len(calls) == 1
    detail = (await client.get(f"/projects/{scene['id']}")).json()
    assert detail["spent_estimate_inr"] == 2 and detail["reserved_inr"] == 0
    assert detail["status"] == "review"


@pytest.mark.anyio
async def test_revocation_during_upload_retains_remote_identity_for_cleanup(
    client, session, monkeypatch
):
    scene, _, payload = await setup_clone(client, session, provider="sarvam")
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "test-only")
    profile = (await client.post(f"/projects/{scene['id']}/voice-profiles", json=payload)).json()
    await stage(
        client,
        session,
        scene["id"],
        {"stage": "prepare_reference", "voice_profile_id": profile["id"]},
    )

    def revoke_during_call(*args):
        with SessionLocal() as other:
            current = other.get(VoiceProfile, profile["id"])
            current.consent_status = "revoked"
            current.version += 1
            other.add(
                ConsentRecord(
                    voice_profile_id=current.id, status="revoked", attested_by="Test operator"
                )
            )
            active = (
                other.query(Job).filter_by(stage="register_voice", project_id=scene["id"]).one()
            )
            active.cancel_requested = True
            other.commit()
        return VoiceRegistrationResult(
            "svc-recorded-cancelled", "sarvam", "sarvam-voice-cloning-beta", "Synthetic text"
        )

    monkeypatch.setattr(SarvamProvider, "register_voice", revoke_during_call)
    response = await client.post(
        f"/projects/{scene['id']}/jobs",
        json={
            "stage": "register_voice",
            "provider": "sarvam",
            "voice_profile_id": profile["id"],
            "reference_reviewed": True,
            "registration_allowance_inr": 1,
        },
    )
    assert response.status_code == 202
    assert process_once(session)
    detail = (await client.get(f"/projects/{scene['id']}")).json()
    assert detail["jobs"][0]["status"] == "cancelled", detail["jobs"][0]
    saved = next(p for p in detail["voice_profiles"] if p["id"] == profile["id"])
    assert saved["provider_voice_id"] == "svc-recorded-cancelled"
    assert saved["consent_status"] == "revoked" and saved["registration_status"] == "ready"
    selected = next(s for s in detail["speakers"] if s["id"] == saved["speaker_id"])
    assert selected["voice_profile_id"] != profile["id"]
    deleted = []
    monkeypatch.setattr(
        SarvamProvider, "delete_voice", lambda self, voice_id: deleted.append(voice_id)
    )
    await stage(
        client,
        session,
        scene["id"],
        {"stage": "delete_voice", "provider": "sarvam", "voice_profile_id": profile["id"]},
    )
    assert deleted == ["svc-recorded-cancelled"]


@pytest.mark.anyio
async def test_prepared_reference_recovery_reuses_committed_artifact(client, session):
    scene, _, payload = await setup_clone(client, session)
    profile = (await client.post(f"/projects/{scene['id']}/voice-profiles", json=payload)).json()
    detail = await stage(
        client,
        session,
        scene["id"],
        {"stage": "prepare_reference", "voice_profile_id": profile["id"]},
    )
    job = session.get(Job, detail["jobs"][0]["id"])
    job.status = "running"
    session.commit()
    recover_jobs(session)
    assert process_once(session)
    assert session.query(Artifact).filter_by(job_id=job.id, kind="voice_reference").count() == 1


@pytest.mark.anyio
async def test_voice_switch_stops_remaining_synthesis_chunks(client, session, monkeypatch):
    from cinedub_api.models import Speaker

    scene, _, payload = await setup_clone(client, session)
    profile = (await client.post(f"/projects/{scene['id']}/voice-profiles", json=payload)).json()
    await stage(
        client,
        session,
        scene["id"],
        {"stage": "prepare_reference", "voice_profile_id": profile["id"]},
    )
    detail = await stage(
        client,
        session,
        scene["id"],
        {
            "stage": "register_voice",
            "provider": "fake",
            "voice_profile_id": profile["id"],
            "reference_reviewed": True,
        },
    )
    speaker = next(s for s in detail["speakers"] if s["id"] == profile["speaker_id"])
    stock_id = speaker["voice_profile_id"]
    await client.post(
        f"/speakers/{speaker['id']}/voice-profile",
        json={"profile_id": profile["id"], "expected_profile_id": stock_id},
    )
    detail = (await client.get(f"/projects/{scene['id']}")).json()
    line = next(line for line in detail["segments"] if line["speaker_id"] == speaker["id"])
    line = (
        await client.patch(
            f"/segments/{line['id']}",
            json={"translated_text": "വാക്ക് " * 210, "expected_version": line["version"]},
        )
    ).json()
    assert "version" in line, line
    await client.patch(
        f"/segments/{line['id']}", json={"status": "approved", "expected_version": line["version"]}
    )
    original = FakeProvider.synthesize
    calls = []

    def switching(self, *args, **kwargs):
        calls.append(True)
        result = original(self, *args, **kwargs)
        with SessionLocal() as other:
            other.get(Speaker, speaker["id"]).voice_profile_id = stock_id
            other.commit()
        return result

    monkeypatch.setattr(FakeProvider, "synthesize", switching)
    detail = await stage(
        client,
        session,
        scene["id"],
        {"stage": "synthesize", "segment_ids": [line["id"]]},
        success=False,
    )
    assert len(calls) == 1
    assert "remaining provider calls stopped" in detail["jobs"][0]["error_message"]
