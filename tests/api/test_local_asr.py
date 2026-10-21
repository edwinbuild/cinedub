import copy
import hashlib
import json
import subprocess
import sys

import pytest
from cinedub_api.config import get_settings
from cinedub_api.models import Job, ProviderRun
from cinedub_api.providers.local_asr import (
    MODEL_FILES,
    MODEL_ID,
    MODEL_NAME,
    MODEL_REVISION,
    LocalTranscriber,
    read_manifest,
)
from cinedub_api.worker import process_once, recover_jobs
from test_timeline import prepare_scene


@pytest.fixture
def model_directory(tmp_path, monkeypatch):
    directory = tmp_path / "model"
    directory.mkdir()
    hashes = {}
    for name in MODEL_FILES:
        (directory / name).write_bytes(b"fixture model bytes, not actual weights")
        hashes[name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    (directory / "cinedub-manifest.json").write_text(
        json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION, "sha256": hashes})
    )
    monkeypatch.setattr(get_settings(), "local_asr_model_dir", directory)
    # Runtime is optional: no real inference/download belongs in the unit suite.
    monkeypatch.setattr(
        "cinedub_api.stages.preparation.asr_availability", lambda _: (True, "test adapter")
    )
    monkeypatch.setattr("cinedub_api.providers.registry.availability", lambda _: (True, "test"))
    monkeypatch.setattr(
        "cinedub_api.local_asr_profile.runtime_versions",
        lambda: {
            name: "fixture-version"
            for name in ("faster-whisper", "ctranslate2", "onnxruntime", "numpy")
        },
    )
    return directory


def test_manifest_requires_pinned_revision_and_hashes(model_directory):
    manifest = read_manifest(model_directory, verify=True)
    assert manifest["revision"] == MODEL_REVISION
    (model_directory / "model.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        read_manifest(model_directory, verify=True)
    manifest["revision"] = "untrusted-revision"
    (model_directory / "cinedub-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="pinned"):
        read_manifest(model_directory)


@pytest.mark.anyio
async def test_local_revision_manual_speakers_and_free_routing(
    client, session, model_directory, monkeypatch
):
    project, asset = await prepare_scene(client, session)

    def transcribe(self, audio, output, cancel):
        cancel()
        assert audio.is_file() and self.threads == 4
        return {
            "diarized_transcript": {
                "entries": [
                    {
                        "transcript": "Actual recorded response",
                        "start_time_seconds": 0,
                        "end_time_seconds": 1.5,
                        "speaker_id": None,
                    }
                ]
            },
            "words": [{"word": "Actual", "start": 0, "end": 0.4, "probability": 0.9}],
            "local_metadata": {
                "model": MODEL_NAME,
                "latency_ms": 120,
                "peak_rss_mib": 1000,
                "asr_profile": self.profile,
                "model_sha256": read_manifest(self.directory)["sha256"],
                "sampling_segments": 1,
                "decoder_segments": [
                    {
                        "index": 0,
                        "start": 0,
                        "end": 1.5,
                        "temperature": 0.2,
                        "avg_logprob": -0.3,
                        "compression_ratio": 1.2,
                        "no_speech_prob": 0.1,
                    }
                ],
            },
        }

    monkeypatch.setattr(LocalTranscriber, "transcribe", transcribe)
    request = {"stage": "transcribe", "provider": "local", "source_asset_id": asset["id"]}
    rejected = await client.post(
        f"/projects/{project['id']}/jobs", json={**request, "num_speakers": 2}
    )
    assert rejected.status_code == 422 and "no diarization" in rejected.text
    job = (await client.post(f"/projects/{project['id']}/jobs", json=request)).json()
    assert job["estimated_cost_inr"] == 0
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["jobs"][0]["status"] == "completed", detail["jobs"][0]
    assert detail["revisions"][0]["model"] == MODEL_NAME
    assert not detail["speakers"]
    line = detail["segments"][0]
    assert line["speaker_id"] is None and line["emotion_label"] is None
    assert "Speaker unassigned; review this line" in line["warnings_json"]
    raw = next(item for item in detail["artifacts"] if item["kind"] == "raw_transcript")
    assert (await client.get(raw["content_url"])).json()["words"][0]["word"] == "Actual"
    run = session.query(ProviderRun).filter_by(job_id=job["id"]).one()
    assert run.latency_ms == 120 and run.estimated_cost_inr == 0
    assert (
        run.parameters_json["asr_profile"] == session.get(Job, job["id"]).input_json["asr_profile"]
    )
    assert any(
        "sampling fallback" in warning for warning in detail["revisions"][0]["warnings_json"]
    )
    speaker_payload = {"revision_id": detail["active_revision_id"], "display_name": "Actor A"}
    other = (await client.post("/projects", json={"name": "Other"})).json()
    assert (
        await client.post(f"/projects/{other['id']}/speakers", json=speaker_payload)
    ).status_code == 422
    assert (
        await client.post(
            f"/projects/{project['id']}/speakers", json={**speaker_payload, "display_name": " "}
        )
    ).status_code == 422
    speaker = (
        await client.post(f"/projects/{project['id']}/speakers", json=speaker_payload)
    ).json()
    changed = (
        await client.patch(
            f"/segments/{line['id']}",
            json={"speaker_id": speaker["id"], "expected_version": line["version"]},
        )
    ).json()
    assert changed["speaker_id"] == speaker["id"] and not changed["warnings_json"]
    # Manual speaker assignment must not prevent filling an empty translation.
    assert (
        await client.post(f"/projects/{project['id']}/jobs", json={"stage": "translate"})
    ).status_code == 202
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["segments"][0]["translated_text"]
    assert detail["segments"][0]["speaker_id"] == speaker["id"]


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_local_native_process_is_stopped(model_directory, tmp_path, monkeypatch, stop):
    native_popen = subprocess.Popen
    children = []

    def start(command, **kwargs):
        assert "SARVAM_API_KEY" not in kwargs["env"]
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        process = native_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr("cinedub_api.providers.local_asr.subprocess.Popen", start)
    monkeypatch.setenv("SARVAM_API_KEY", "not-a-real-key")

    def cancel():
        if stop == "cancel":
            raise InterruptedError("requested")

    exception = InterruptedError if stop == "cancel" else TimeoutError
    with pytest.raises(exception):
        LocalTranscriber(model_directory, timeout_seconds=-1).transcribe(
            tmp_path / "source.wav", tmp_path / "out", cancel
        )
    assert children and children[0].poll() is not None


def test_local_work_recovers_without_paid_submission_uncertainty(session):
    from cinedub_api.models import Project

    project = Project(name="Restarted local scene")
    session.add(project)
    session.flush()
    job = Job(
        project_id=project.id,
        stage="transcribe",
        provider="local",
        status="running",
        phase="local_inference",
        input_json={},
    )
    session.add(job)
    session.commit()
    recover_jobs(session)
    assert job.status == "queued" and job.charged_estimate_inr == 0


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["legacy", "settings", "runtime"])
async def test_pending_local_job_cannot_silently_change_decoder(
    client, session, model_directory, monkeypatch, change
):
    project, asset = await prepare_scene(client, session)
    response = await client.post(
        f"/projects/{project['id']}/jobs",
        json={"stage": "transcribe", "provider": "local", "source_asset_id": asset["id"]},
    )
    job = session.get(Job, response.json()["id"])
    values = copy.deepcopy(job.input_json)
    if change == "legacy":
        values.pop("asr_profile")
    elif change == "settings":
        values["asr_profile"]["transcribe_options"]["beam_size"] = 1
    else:
        values["asr_profile"]["runtime_versions"]["faster-whisper"] = "changed"
    job.input_json = values
    session.commit()
    monkeypatch.setattr(
        LocalTranscriber,
        "transcribe",
        lambda *args: pytest.fail("Changed profile must not invoke native inference"),
    )
    assert process_once(session)
    session.expire_all()
    saved = session.get(Job, job.id)
    assert saved.status == "failed" and saved.charged_estimate_inr == 0
    assert "decoding" in saved.error_message or "profile changed" in saved.error_message
    assert not (await client.get(f"/projects/{project['id']}")).json()["revisions"]


@pytest.mark.anyio
async def test_legacy_raw_result_is_preserved_without_new_profile_claim(
    client, session, model_directory, monkeypatch
):
    project, asset = await prepare_scene(client, session)
    response = await client.post(
        f"/projects/{project['id']}/jobs",
        json={"stage": "transcribe", "provider": "local", "source_asset_id": asset["id"]},
    )
    job = session.get(Job, response.json()["id"])
    values = copy.deepcopy(job.input_json)
    values.pop("asr_profile")
    job.input_json = values
    session.commit()
    path = (
        get_settings().storage_root / project["id"] / "transcript" / job.id / "raw-transcript.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "diarized_transcript": {
                    "entries": [
                        {
                            "transcript": "Historical recorded response",
                            "start_time_seconds": 0,
                            "end_time_seconds": 1.5,
                            "speaker_id": None,
                        }
                    ]
                },
                "local_metadata": {"model": MODEL_NAME},
            }
        )
    )
    monkeypatch.setattr(
        LocalTranscriber,
        "transcribe",
        lambda *args: pytest.fail("Existing raw result must not be regenerated"),
    )
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["jobs"][0]["status"] == "completed"
    assert any(
        "no frozen decoding" in warning for warning in detail["revisions"][0]["warnings_json"]
    )
    run = session.query(ProviderRun).filter_by(job_id=job.id).one()
    assert "asr_profile" not in run.parameters_json


@pytest.mark.anyio
async def test_profile_changes_cache_identity_and_old_jobs_are_not_reused(
    client, session, model_directory, monkeypatch
):
    from cinedub_api.jobs import prepare_job
    from cinedub_api.models import Project
    from cinedub_api.schemas import JobFields

    project, asset = await prepare_scene(client, session)
    request = {"stage": "transcribe", "provider": "local", "source_asset_id": asset["id"]}
    provider, inputs, _ = prepare_job(
        session, session.get(Project, project["id"]), JobFields(**request)
    )
    current_fingerprint = inputs["fingerprint"]
    legacy_input = {
        key: value for key, value in inputs.items() if key not in {"fingerprint", "asr_profile"}
    }
    legacy_input["fingerprint"] = hashlib.sha256(
        json.dumps(
            {"stage": "transcribe", "provider": provider, "input": legacy_input},
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    legacy = Job(
        project_id=project["id"],
        stage="transcribe",
        provider="local",
        status="completed",
        input_json=legacy_input,
    )
    session.add(legacy)
    session.commit()
    estimate = (await client.post(f"/projects/{project['id']}/jobs/estimate", json=request)).json()
    assert estimate["cached_job_id"] is None
    fresh = (await client.post(f"/projects/{project['id']}/jobs", json=request)).json()
    assert fresh["id"] != legacy.id
    assert session.get(Job, fresh["id"]).input_json["fingerprint"] == current_fingerprint
    monkeypatch.setattr(
        "cinedub_api.local_asr_profile.runtime_versions", lambda: {"faster-whisper": "next-version"}
    )
    next_estimate = (
        await client.post(f"/projects/{project['id']}/jobs/estimate", json=request)
    ).json()
    assert next_estimate["cached_job_id"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["profile", "hashes", "evidence"])
async def test_unverified_native_result_is_not_published(
    client, session, model_directory, monkeypatch, fault
):
    project, asset = await prepare_scene(client, session)

    def invalid(self, *args):
        metadata = {
            "model": MODEL_NAME,
            "asr_profile": copy.deepcopy(self.profile),
            "model_sha256": read_manifest(self.directory)["sha256"],
            "sampling_segments": 0,
            "decoder_segments": [
                {
                    "index": 0,
                    "start": 0,
                    "end": 1,
                    "temperature": 0.0,
                    "avg_logprob": -0.2,
                    "compression_ratio": 1.0,
                    "no_speech_prob": 0.01,
                }
            ],
        }
        if fault == "profile":
            metadata["asr_profile"]["version"] = "foreign"
        elif fault == "hashes":
            metadata["model_sha256"] = {"model.bin": "foreign"}
        else:
            metadata["decoder_segments"] = []
        return {
            "diarized_transcript": {
                "entries": [
                    {
                        "transcript": "Unverified result",
                        "start_time_seconds": 0,
                        "end_time_seconds": 1,
                        "speaker_id": None,
                    }
                ]
            },
            "local_metadata": metadata,
        }

    monkeypatch.setattr(LocalTranscriber, "transcribe", invalid)
    response = await client.post(
        f"/projects/{project['id']}/jobs",
        json={"stage": "transcribe", "provider": "local", "source_asset_id": asset["id"]},
    )
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["jobs"][0]["status"] == "failed"
    assert not detail["revisions"]
    assert not any(artifact["kind"] == "raw_transcript" for artifact in detail["artifacts"])
    assert not (
        get_settings().storage_root
        / project["id"]
        / "transcript"
        / response.json()["id"]
        / "raw-transcript.json"
    ).exists()
