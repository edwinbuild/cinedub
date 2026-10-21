import subprocess
import sys
import wave

import pytest
from cinedub_api import core_processing, media, worker
from cinedub_api.database import SessionLocal
from cinedub_api.models import Job


def silent_wav(path):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000)


def test_cancellable_probe_preserves_actual_metadata(tmp_path):
    source = tmp_path / "synthetic.wav"
    silent_wav(source)
    assert media.probe_media(source, cancel=lambda: None) == media.probe_media(source)


def test_oversized_metadata_stops_its_child_and_excludes_credentials(monkeypatch):
    real_popen = subprocess.Popen
    children = []
    monkeypatch.setenv("SARVAM_API_KEY", "synthetic-private-key")

    def launch(*args, **kwargs):
        assert "synthetic-private-key" not in repr(kwargs["env"])
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(media.subprocess, "Popen", launch)
    with pytest.raises(media.MediaError, match="metadata exceeds"):
        media._capture_cancellable(
            [sys.executable, "-c", "import os,time;os.write(1,b'x'*2048);time.sleep(60)"],
            5,
            lambda: None,
            stdout_limit=1024,
        )
    assert children and children[0].poll() is not None


@pytest.mark.parametrize("stage", ["probe", "extraction", "waveform", "recognition", "proxy"])
@pytest.mark.anyio
async def test_ingest_cancellation_reaches_every_boundary_without_publishing(
    client, session, monkeypatch, stage
):
    from test_api import create_project

    project = await create_project(client)
    import io

    audio = io.BytesIO()
    with wave.open(audio, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000)
    response = await client.post(
        f"/projects/{project['id']}/assets",
        files={"file": ("synthetic.wav", audio.getvalue(), "audio/wav")},
    )
    assert response.status_code == 201
    from cinedub_api.models import MediaAsset

    asset = session.get(MediaAsset, response.json()["id"])
    asset.metadata_json = {**asset.metadata_json, "streams": [{"codec_type": "video"}]}
    session.commit()
    visited = []

    def boundary(name, cancel):
        visited.append(name)
        assert cancel is not None
        if name == stage:
            with SessionLocal() as other:
                active = other.query(Job).filter_by(project_id=project["id"]).one()
                active.cancel_requested = True
                other.commit()
        cancel()

    real_probe = media.probe_media

    def probe(source, *, cancel=None):
        boundary("probe", cancel)
        return real_probe(source)

    def ffmpeg(arguments, timeout=300, *, cancel=None):
        name = "extraction" if arguments[-1].endswith("source-48khz.wav") else "recognition"
        boundary(name, cancel)
        if name == "extraction":
            from pathlib import Path

            destination = Path(arguments[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            silent_wav(destination)

    monkeypatch.setattr(media, "probe_media", probe)
    monkeypatch.setattr(media, "run_ffmpeg", ffmpeg)
    monkeypatch.setattr(core_processing, "run_ffmpeg", ffmpeg)
    monkeypatch.setattr(
        core_processing, "write_waveform", lambda *args, cancel: boundary("waveform", cancel)
    )
    monkeypatch.setattr(core_processing, "file_digest", lambda path: "synthetic-hash")
    monkeypatch.setattr(
        core_processing, "create_preview_proxy", lambda *args, cancel: boundary("proxy", cancel)
    )
    assert worker.process_once(session)
    assert visited[-1] == stage
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["jobs"][0]["status"] == "cancelled"
    assert detail["artifacts"] == []


def test_cancel_waveform_before_publication(tmp_path):
    source = tmp_path / "synthetic.wav"
    silent_wav(source)
    destination = tmp_path / "waveform.json"
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls > 2:
            raise InterruptedError("Synthetic cancellation")

    with pytest.raises(InterruptedError):
        media.write_waveform(source, destination, cancel=cancel)
    assert not destination.exists()


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_real_ffmpeg_child_stops_on_cancel_or_deadline(monkeypatch, stop):
    real_popen = subprocess.Popen
    children = []

    def launch(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(media.subprocess, "Popen", launch)

    def cancel():
        if children and stop == "cancel":
            raise InterruptedError("Synthetic cancellation")

    with pytest.raises(InterruptedError if stop == "cancel" else TimeoutError):
        media.run_ffmpeg(
            ["-re", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "60", "-f", "null", "-"],
            timeout=-1 if stop == "deadline" else 10,
            cancel=cancel,
        )
    assert children and children[0].poll() is not None
