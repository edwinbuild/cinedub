import json
import subprocess
import sys
from pathlib import Path

import pytest
from cinedub_api.local_process import run_inference
from cinedub_api.media import probe_media, run_ffmpeg
from cinedub_api.models import Artifact, Job, MediaAsset, ProviderRun, StemReviewRecord
from cinedub_api.providers.local_separation import MODEL_NAME, LocalSeparator
from cinedub_api.worker import process_once, recover_jobs
from test_timeline import prepare_scene, transcribe


@pytest.fixture
def separator(monkeypatch):
    manifest = {"revision": "recorded-test-model"}
    monkeypatch.setattr("cinedub_api.jobs.separator_availability", lambda _: (True, "test"))
    monkeypatch.setattr("cinedub_api.jobs.separator_manifest", lambda _: manifest)
    monkeypatch.setattr("cinedub_api.separation_processing.read_manifest", lambda _: manifest)
    calls = []

    def separate(self, audio, directory, *, duration_ms, gain_db, cancel, progress):
        cancel()
        assert audio.stat().st_size == round(duration_ms * 44.1) * 2 * 4
        calls.append(audio)
        for name in ("dialogue", "music", "effects"):
            run_ffmpeg(
                [
                    "-f",
                    "f32le",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-i",
                    str(audio),
                    "-ar",
                    "48000",
                    "-c:a",
                    "pcm_f32le",
                    str(directory / f"{name}.wav"),
                ]
            )
        progress(2, 2)
        metadata = {
            "model": MODEL_NAME,
            "latency_ms": 10,
            "peak_rss_mib": 100,
            "warning": "Recorded adapter response, not real isolation",
            "device": "cpu",
            "stems": {name: {"peak": 0.01} for name in ("dialogue", "music", "effects")},
        }
        (directory / "separation-result.json").write_text(json.dumps(metadata))
        return metadata

    monkeypatch.setattr(LocalSeparator, "separate", separate)
    return calls


async def create_stems(client, session, project, asset, **extra):
    response = await client.post(
        f"/projects/{project['id']}/jobs",
        json={
            "stage": "separate",
            "source_asset_id": asset["id"],
            **extra,
        },
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["estimated_cost_inr"] == 0
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["jobs"][0]["status"] == "completed", detail["jobs"][0]
    return detail, job


@pytest.mark.anyio
async def test_stems_review_and_frozen_transcription_input(client, session, separator):
    project, asset = await prepare_scene(client, session)
    original = await transcribe(client, session, project, asset)
    line = original["segments"][0]
    await client.patch(
        f"/segments/{line['id']}",
        json={
            "expected_version": line["version"],
            "translated_text": "Preserved human translation",
        },
    )
    detail, job = await create_stems(client, session, project, asset)
    stems = detail["stem_sets"][0]
    assert stems["status"] == "needs_review" and detail["assets"][0]["active_stem_set_id"] is None
    assert len(separator) == 1
    for artifact in detail["artifacts"]:
        if artifact["kind"] in {"stem_master", "stem_preview", "stem_recognition_audio"}:
            assert artifact["metadata_json"]["sha256"]
            content = await client.get(artifact["content_url"], headers={"Range": "bytes=0-3"})
            assert content.status_code == 206 and content.content == b"RIFF"
    masters = session.query(Artifact).filter_by(job_id=job["id"], kind="stem_master").all()
    assert len(masters) == 3
    for master in masters:
        info = probe_media(Path(master.path))
        assert info["duration_ms"] == 2000
        assert info["streams"][0]["sample_rate"] == "48000" and info["streams"][0]["channels"] == 2
    request = {
        "stage": "transcribe",
        "source_asset_id": asset["id"],
        "transcription_input": "dialogue_stem",
        "force_new": True,
    }
    assert (await client.post(f"/projects/{project['id']}/jobs", json=request)).status_code == 422
    review = {
        "status": "approved",
        "expected_version": 1,
        "expected_active_stem_set_id": None,
        "reviewed_by": "Test reviewer",
        "note": "Fixture workflow only, no listening-quality assertion",
    }
    blank = await client.post(
        f"/stem-sets/{stems['id']}/review", json={**review, "reviewed_by": " "}
    )
    assert blank.status_code == 422
    approved = await client.post(f"/stem-sets/{stems['id']}/review", json=review)
    assert approved.status_code == 200 and approved.json()["version"] == 2
    assert approved.json()["reviews"][0]["reviewed_by"] == "Test reviewer"
    assert (await client.post(f"/stem-sets/{stems['id']}/review", json=review)).status_code == 409
    submitted = (await client.post(f"/projects/{project['id']}/jobs", json=request)).json()
    frozen = session.get(Job, submitted["id"]).input_json
    assert frozen["stem_set_id"] == stems["id"] and frozen["stem_set_version"] == 2
    assert frozen["recognition_artifact_id"] == stems["artifacts_json"]["recognition_audio"]
    assert (
        await client.post(
            f"/stem-sets/{stems['id']}/review",
            json={**review, "expected_version": 2, "expected_active_stem_set_id": stems["id"]},
        )
    ).status_code == 409
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    raw = next(
        item
        for item in detail["artifacts"]
        if item["kind"] == "raw_transcript" and item["job_id"] == submitted["id"]
    )
    assert raw["metadata_json"]["stem_set_id"] == stems["id"]
    assert detail["active_revision_id"] == original["active_revision_id"]
    assert detail["segments"][0]["translated_text"] == "Preserved human translation"
    again, _ = await create_stems(client, session, project, asset, force_new=True)
    assert len(again["stem_sets"]) == 2 and again["assets"][0]["active_stem_set_id"] == stems["id"]
    rejected = await client.post(
        f"/stem-sets/{stems['id']}/review",
        json={
            **review,
            "status": "rejected",
            "expected_version": 2,
            "expected_active_stem_set_id": stems["id"],
        },
    )
    assert rejected.status_code == 200
    assert [record["status"] for record in rejected.json()["reviews"]] == ["approved", "rejected"]
    session.expire_all()
    assert session.get(MediaAsset, asset["id"]).active_stem_set_id is None
    assert session.query(StemReviewRecord).filter_by(stem_set_id=stems["id"]).count() == 2
    assert session.query(ProviderRun).filter_by(job_id=job["id"]).one().estimated_cost_inr == 0


@pytest.mark.anyio
async def test_separation_checkpoint_recovery_and_changed_source(
    client, session, separator, monkeypatch
):
    project, asset = await prepare_scene(client, session)
    native_probe = probe_media
    monkeypatch.setattr(
        "cinedub_api.separation_processing.probe_media",
        lambda _: (_ for _ in ()).throw(ValueError("crash before persistence")),
    )
    submitted = (
        await client.post(
            f"/projects/{project['id']}/jobs",
            json={"stage": "separate", "source_asset_id": asset["id"]},
        )
    ).json()
    assert process_once(session)
    job = session.get(Job, submitted["id"])
    assert job.status == "failed" and len(separator) == 1
    job.status = "running"
    session.commit()
    recover_jobs(session)
    assert job.status == "queued"
    monkeypatch.setattr("cinedub_api.separation_processing.probe_media", native_probe)
    assert process_once(session) and job.status == "completed"
    assert len(separator) == 1  # Reuse completed local inference, no new expensive work.
    second = (
        await client.post(
            f"/projects/{project['id']}/jobs",
            json={"stage": "separate", "source_asset_id": asset["id"], "force_new": True},
        )
    ).json()
    source = session.get(MediaAsset, asset["id"])
    with Path(source.path).open("ab") as handle:
        handle.write(b"changed after scheduling")
    assert process_once(session)
    assert "changed since scheduling" in session.get(Job, second["id"]).error_message
    assert len(separator) == 1


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_separator_native_process_stops_and_has_no_keys(tmp_path, monkeypatch, stop):
    native_popen = subprocess.Popen
    children = []

    def start(command, **kwargs):
        assert "SARVAM_API_KEY" not in kwargs["env"]
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        child = native_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr("cinedub_api.local_process.subprocess.Popen", start)
    monkeypatch.setenv("SARVAM_API_KEY", "not-a-real-key")

    def cancel():
        if stop == "cancel":
            raise InterruptedError("requested")

    with pytest.raises(InterruptedError if stop == "cancel" else TimeoutError):
        run_inference(
            "unused",
            [],
            tmp_path,
            threads=4,
            timeout_seconds=-1,
            cancel=cancel,
            progress=lambda *_: None,
        )
    assert children[0].poll() is not None


def test_stft_inverse_and_stereo_chunk_crossfades():
    np = pytest.importorskip("numpy")
    from cinedub_api.separation_dsp import WINDOWS, istft, separate_channels, stft

    rng = np.random.default_rng(42)
    samples = rng.normal(0, 0.1, size=(45000, 2)).astype(np.float32)
    for size in WINDOWS:
        np.testing.assert_allclose(
            istft(stft(samples[:, 0], size), size, len(samples)), samples[:, 0], atol=1e-6
        )

    class IdentityMasks:
        def run(self, names, inputs):
            return [
                np.broadcast_to(
                    np.full((1, 3, 1, 1), 1 / 9, dtype=np.float32),
                    (1, 3, size // 2 + 1, inputs[f"mag_{size}"].shape[2]),
                )
                for size in WINDOWS
            ]

    progress = []
    # Small test-only sample rate exercises overlapping windows, not the actual model.
    stems = separate_channels(
        samples, IdentityMasks(), sample_rate=1000, progress=lambda *pair: progress.append(pair)
    )
    np.testing.assert_allclose(stems.sum(axis=0), samples, atol=1e-6)
    assert progress[-1] == (6, 6)
    assert not np.allclose(stems[0, :, 0], stems[0, :, 1])


def test_missing_separator_installation_is_unavailable(tmp_path):
    from cinedub_api.providers.local_separation import availability, read_manifest

    assert availability(tmp_path)[0] is False
    with pytest.raises(OSError):
        read_manifest(tmp_path)


def test_separator_manifest_pin_checksum_and_malformed_data(tmp_path):
    from cinedub_api.providers.local_separation import (
        MODEL_FILE,
        MODEL_ID,
        MODEL_REVISION,
        MODEL_SHA256,
        availability,
        read_manifest,
    )

    path = tmp_path / "cinedub-manifest.json"
    path.write_text("[]")
    assert availability(tmp_path)[0] is False
    manifest = {"model_id": MODEL_ID, "revision": MODEL_REVISION, "sha256": MODEL_SHA256}
    path.write_text(json.dumps(manifest))
    with (tmp_path / MODEL_FILE).open("wb") as handle:
        handle.truncate(31_287_081)
    assert read_manifest(tmp_path) == manifest
    with pytest.raises(ValueError, match="checksum"):
        read_manifest(tmp_path, verify=True)
    path.write_text(json.dumps({**manifest, "revision": "other"}))
    with pytest.raises(ValueError, match="pinned"):
        read_manifest(tmp_path)


def test_invalid_separator_masks_fail_closed():
    np = pytest.importorskip("numpy")
    from cinedub_api.separation_dsp import separate_chunk

    class InvalidMasks:
        def run(self, *_):
            return [np.full((1, 3, 513, 1), np.nan, dtype=np.float32)] * 3

    with pytest.raises(ValueError, match="invalid masks"):
        separate_chunk(np.ones(10000, dtype=np.float32), InvalidMasks())
