import array
import base64
import io
import subprocess
import wave
from pathlib import Path

import httpx
import pytest
from cinedub_api.audio import fit_dialogue
from cinedub_api.models import Artifact, Segment
from cinedub_api.providers.fake import FakeProvider
from cinedub_api.providers.sarvam import SarvamProvider
from cinedub_api.worker import process_once


def wav(seconds=8):
    data = io.BytesIO()
    with wave.open(data, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * int(16000 * seconds))
    return data.getvalue()


async def prepare_reviewed_scene(client, session, media=None):
    project = (await client.post("/projects", json={"name": "Voice workflow"})).json()
    asset = (
        await client.post(
            f"/projects/{project['id']}/assets",
            files={"file": media or ("scene.wav", wav(), "audio/wav")},
        )
    ).json()
    assert process_once(session)
    for payload in [
        {"stage": "transcribe", "source_asset_id": asset["id"]},
        {"stage": "translate"},
    ]:
        response = await client.post(f"/projects/{project['id']}/jobs", json=payload)
        assert response.status_code == 202, response.text
        assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    for line in detail["segments"]:
        response = await client.patch(
            f"/segments/{line['id']}",
            json={"status": "approved", "expected_version": line["version"]},
        )
        assert response.status_code == 200
    for index, speaker in enumerate(detail["speakers"]):
        response = await client.post(
            f"/speakers/{speaker['id']}/stock-voice",
            json={"provider": "fake", "voice_id": "speaker-a" if index == 0 else "speaker-b"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["consent_status"] == "not_required"
    response = await client.post(f"/projects/{project['id']}/jobs", json={"stage": "synthesize"})
    assert response.status_code == 202, response.text
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["jobs"][0]["status"] == "completed", detail["jobs"][0]
    for line in detail["segments"]:
        candidate = next(
            item
            for item in detail["artifacts"]
            if item["kind"] == "dialogue_candidate"
            and item["metadata_json"]["segment_id"] == line["id"]
        )
        assert candidate["metadata_json"]["fit_status"] == "ready"
        response = await client.post(
            f"/segments/{line['id']}/candidate",
            json={"artifact_id": candidate["id"], "expected_version": line["version"]},
        )
        assert response.status_code == 200, response.text
    return (await client.get(f"/projects/{project['id']}")).json()


@pytest.mark.anyio
async def test_voice_generation_selection_render_and_invalidation(client, session):
    detail = await prepare_reviewed_scene(client, session)
    assert all(
        line["status"] == "approved" and line["selected_candidate_id"]
        for line in detail["segments"]
    )
    response = await client.post(f"/projects/{detail['id']}/jobs", json={"stage": "render_preview"})
    assert response.status_code == 202, response.text
    assert process_once(session)
    detail = (await client.get(f"/projects/{detail['id']}")).json()
    assert detail["jobs"][0]["status"] == "completed", detail["jobs"][0]
    artifact = next(item for item in detail["artifacts"] if item["kind"] == "dialogue_mix")
    data = (await client.get(artifact["download_url"])).content
    with wave.open(io.BytesIO(data)) as audio:
        assert audio.getframerate() == 48000 and audio.getnchannels() == 2
        assert audio.getnframes() == 8 * 48000
    first = detail["segments"][0]
    profile = next(
        item for item in detail["voice_profiles"] if item["speaker_id"] == first["speaker_id"]
    )
    changed = await client.post(
        f"/speakers/{first['speaker_id']}/stock-voice",
        json={"provider": "fake", "voice_id": profile["provider_voice_id"], "pace": 1.05},
    )
    assert changed.status_code == 200
    session.expire_all()
    assert session.get(Segment, first["id"]).selected_candidate_id is None
    assert (
        await client.post(f"/projects/{detail['id']}/jobs", json={"stage": "render_preview"})
    ).status_code == 422
    line = (await client.get(f"/projects/{detail['id']}")).json()["segments"][0]
    assert (
        await client.post(
            f"/segments/{line['id']}/candidate",
            json={
                "artifact_id": first["selected_candidate_id"],
                "expected_version": line["version"],
            },
        )
    ).status_code == 409


@pytest.mark.anyio
async def test_video_preview_has_replaced_not_retained_source_audio(client, session):
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000",
            "-t",
            "12",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "frag_keyframe+empty_moov",
            "-f",
            "mp4",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    detail = await prepare_reviewed_scene(
        client, session, ("scene.mp4", result.stdout, "video/mp4")
    )
    await client.post(f"/projects/{detail['id']}/jobs", json={"stage": "render_preview"})
    assert process_once(session)
    detail = (await client.get(f"/projects/{detail['id']}")).json()
    assert detail["jobs"][0]["status"] == "completed", detail["jobs"][0]
    video = next(item for item in detail["artifacts"] if item["kind"] == "dub_preview")
    stored = session.get(Artifact, video["id"])
    from cinedub_api.media import probe_media

    metadata = probe_media(Path(stored.path))
    assert {stream["codec_type"] for stream in metadata["streams"]} == {"video", "audio"}
    assert abs(metadata["duration_ms"] - detail["assets"][0]["duration_ms"]) < 100
    mix = next(item for item in detail["artifacts"] if item["kind"] == "dialogue_mix")
    content = (await client.get(mix["download_url"])).content
    with wave.open(io.BytesIO(content)) as audio:
        audio.setpos(3 * 48000)
        # The source has a continuous 440 Hz tone here, but the first fitted take is silent.
        samples = array.array("h", audio.readframes(48000))
        assert max(abs(value) for value in samples) == 0
    assert video["metadata_json"]["dialogue_only"] and video["metadata_json"]["demo"]


def test_timing_fit_pads_short_audio_and_rejects_unsafe_speedup(tmp_path):
    raw = tmp_path / "raw.wav"
    FakeProvider().synthesize("short", "ml-IN", raw, voice_id="speaker-a")
    fitted = tmp_path / "fitted.wav"
    result = fit_dialogue(raw, fitted, 1500, 1.15)
    assert result["fit_status"] == "ready"
    with wave.open(str(fitted)) as audio:
        assert audio.getnframes() == 1500 * 48
    rejected = fit_dialogue(raw, tmp_path / "rejected.wav", 100, 1.15)
    assert rejected["fit_status"] == "too_long" and not (tmp_path / "rejected.wav").exists()


@pytest.mark.parametrize("variation", [None, 0.82])
def test_sarvam_stock_voice_payload_and_audio(monkeypatch, tmp_path, variation):
    payloads = []
    data = wav(1)

    def post(url, *, headers, json, timeout):
        payloads.append((url, json))
        return httpx.Response(
            200,
            json={"audios": [base64.b64encode(data).decode()], "request_id": "recorded"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", post)
    result = SarvamProvider("test-only", "https://api.invalid").synthesize(
        "മലയാളം",
        "ml-IN",
        tmp_path / "voice.wav",
        voice_id="ritu",
        voice_kind="preset",
        pace=1.1,
        variation=variation,
    )
    assert result.audio_path.read_bytes() == data
    assert payloads[0][0].endswith("/text-to-speech")
    assert payloads[0][1]["speaker"] == "ritu" and payloads[0][1]["model"] == "bulbul:v3"
    assert "pitch" not in payloads[0][1] and "loudness" not in payloads[0][1]
    assert payloads[0][1]["temperature"] == (variation if variation is not None else 0.6)
