import io
import wave

import pytest
from cinedub_api.models import Job, Segment
from cinedub_api.worker import process_once


async def create_project(client):
    response = await client.post(
        "/projects",
        json={"name": "Golden scene", "source_language": "en-IN", "target_language": "ml-IN"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.anyio
async def test_project_demo_edit_and_export(client, session):
    project = await create_project(client)
    response = await client.post(
        f"/projects/{project['id']}/jobs",
        json={"stage": "demo_pipeline", "provider": "fake"},
    )
    assert response.status_code == 202
    assert process_once(session)

    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["status"] == "review"
    assert len(detail["segments"]) == 4
    assert len(detail["speakers"]) == 2

    segment = detail["segments"][0]
    response = await client.patch(
        f"/segments/{segment['id']}",
        json={
            "translated_text": "തിരുത്തിയ വരി.",
            "status": "approved",
            "expected_version": segment["version"],
        },
    )
    assert response.status_code == 200
    assert response.json()["translated_text"] == "തിരുത്തിയ വരി."

    stale = await client.patch(
        f"/segments/{segment['id']}",
        json={"status": "needs_review", "expected_version": segment["version"]},
    )
    assert stale.status_code == 409

    response = await client.post(f"/projects/{project['id']}/jobs", json={"stage": "export"})
    assert response.status_code == 202
    session.expire_all()
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["status"] == "ready"
    subtitle = next(item for item in detail["artifacts"] if item["kind"] == "subtitle")
    download = await client.get(subtitle["download_url"])
    assert download.status_code == 200
    assert "തിരുത്തിയ വരി." in download.text


@pytest.mark.anyio
async def test_upload_validates_and_ingests_real_media(client, session):
    project = await create_project(client)
    audio = io.BytesIO()
    with wave.open(audio, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 16_000)
    response = await client.post(
        f"/projects/{project['id']}/assets",
        files={"file": ("scene.wav", audio.getvalue(), "audio/wav")},
    )
    assert response.status_code == 201
    assert 900 <= response.json()["duration_ms"] <= 1100
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["status"] == "draft"
    assert {artifact["kind"] for artifact in detail["artifacts"]} == {
        "source_audio",
        "waveform",
    }


@pytest.mark.anyio
async def test_job_creation_is_idempotent(client, session):
    project = await create_project(client)
    first = (
        await client.post(f"/projects/{project['id']}/jobs", json={"stage": "demo_pipeline"})
    ).json()
    second = (
        await client.post(f"/projects/{project['id']}/jobs", json={"stage": "demo_pipeline"})
    ).json()
    assert first["id"] == second["id"]
    assert session.query(Job).count() == 1


@pytest.mark.anyio
async def test_approved_translation_is_preserved(client, session):
    project = await create_project(client)
    await client.post(f"/projects/{project['id']}/jobs", json={"stage": "demo_pipeline"})
    assert process_once(session)
    segment = session.query(Segment).order_by(Segment.index).first()
    segment.translated_text = "മനുഷ്യൻ അംഗീകരിച്ച വരി"
    segment.status = "approved"
    session.commit()

    await client.post(
        f"/projects/{project['id']}/jobs",
        json={"stage": "translate", "provider": "fake"},
    )
    assert process_once(session)
    session.refresh(segment)
    assert segment.translated_text == "മനുഷ്യൻ അംഗീകരിച്ച വരി"
