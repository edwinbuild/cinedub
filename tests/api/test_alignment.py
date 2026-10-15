import copy
import subprocess
import sys
from pathlib import Path

import pytest
from cinedub_api.alignment_processing import process_align
from cinedub_api.config import get_settings
from cinedub_api.local_process import run_inference
from cinedub_api.models import Artifact, Job, MediaAsset, ProviderRun, Segment, SegmentEdit, StemSet
from cinedub_api.providers.local_alignment import MODEL_NAME as ALIGNMENT_MODEL
from cinedub_api.providers.local_alignment import LocalAligner
from cinedub_api.worker import process_once, recover_jobs
from test_timeline import prepare_scene, transcribe


@pytest.fixture
def aligner(monkeypatch):
    manifest = {"revision": "recorded-test-model-not-real-inference"}
    monkeypatch.setattr("cinedub_api.jobs.alignment_availability", lambda _: (True, "test"))
    monkeypatch.setattr("cinedub_api.jobs.alignment_manifest", lambda _: manifest)
    monkeypatch.setattr("cinedub_api.alignment_processing.read_manifest", lambda _: manifest)
    calls = []

    def align(self, audio, directory, *, lines, duration_ms, language, cancel, progress):
        cancel()
        assert audio.is_file() and duration_ms == 2000 and language == "en-IN"
        calls.append(copy.deepcopy(lines))
        evidence = []
        for line in lines:
            evidence.append(
                {
                    "segment_id": line["id"],
                    "segment_version": line["version"],
                    "source_text": line["source_text"],
                    "original_start_ms": line["start_ms"],
                    "original_end_ms": line["end_ms"],
                    "status": "aligned",
                    "warnings": [],
                    "words": [
                        {
                            "text": "FIXTURE",
                            "start_ms": line["start_ms"] + 40,
                            "end_ms": line["end_ms"] - 40,
                            "acoustic_score": 0.9,
                        }
                    ],
                    "acoustic_score": 0.9,
                    "greedy_text": "FIXTURE",
                    "text_error_ratio": 0.1,
                    "performance": {
                        "rms_dbfs": -30,
                        "peak_dbfs": -24,
                        "pitch_median_hz": None,
                        "pitch_p10_hz": None,
                        "pitch_p90_hz": None,
                        "energy_active_ratio": 1,
                        "activity_threshold_dbfs": -50,
                        "words_per_minute": 120,
                        "pauses": [],
                        "frames": [],
                        "warnings": ["Recorded fixture, not measurements"],
                    },
                }
            )
        progress(len(lines), len(lines))
        return {"model": ALIGNMENT_MODEL, "lines": evidence, "metadata": {"latency_ms": 10}}

    monkeypatch.setattr(LocalAligner, "align", align)
    return calls


async def create_alignment(client, session, project, **extra):
    response = await client.post(
        f"/projects/{project['id']}/jobs", json={"stage": "align", **extra}
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["estimated_cost_inr"] == 0
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["jobs"][0]["status"] == "completed", detail["jobs"][0]
    artifact = next(item for item in detail["artifacts"] if item["job_id"] == job["id"])
    report = (await client.get(f"/alignment-reports/{artifact['id']}")).json()
    return detail, job, artifact, report


@pytest.mark.anyio
async def test_alignment_is_free_revision_bound_evidence_with_explicit_safe_application(
    client, session, aligner
):
    project, asset = await prepare_scene(client, session)
    initial = await transcribe(client, session, project, asset)
    detail, job, artifact, report = await create_alignment(client, session, project)
    assert detail["segments"] == initial["segments"]  # Analysis never changes the timeline.
    assert len(aligner) == 1 and len(report["lines"]) == 2
    assert report["stale_reason"] is None and report["source_asset_id"] == asset["id"]
    assert report["recognition_sha256"] and report["source_sha256"]
    assert "not emotion" in report["warnings"][-1]
    assert (
        session.query(ProviderRun)
        .filter_by(job_id=job["id"], capability="timing_aligner")
        .one()
        .estimated_cost_inr
        == 0
    )
    assert (
        session.query(ProviderRun)
        .filter_by(job_id=job["id"], capability="performance_analyzer")
        .one()
        .model
        == "acoustic-dsp-v1"
    )
    assert process_align(session, session.get(Job, job["id"])) == {
        "alignment_artifact_id": artifact["id"]
    }
    # Same immutable inputs reuse the completed job rather than consuming local resources again.
    cached = (await client.post(f"/projects/{project['id']}/jobs", json={"stage": "align"})).json()
    assert cached["id"] == job["id"]
    line, evidence = detail["segments"][0], report["lines"][0]
    apply_url = f"/alignment-reports/{artifact['id']}/apply"
    payload = {
        "segment_id": line["id"],
        "expected_version": line["version"],
        "listening_confirmed": True,
    }
    assert (
        await client.post(apply_url, json={**payload, "listening_confirmed": False})
    ).status_code == 422
    assert (
        await client.post(apply_url, json={**payload, "expected_version": 999})
    ).status_code == 409
    changed = (await client.post(apply_url, json=payload)).json()
    assert changed["start_ms"] == evidence["words"][0]["start_ms"]
    assert changed["end_ms"] == evidence["words"][-1]["end_ms"]
    assert changed["version"] == line["version"] + 1 and changed["human_edited"]
    assert changed["status"] == "needs_review" and changed["selected_candidate_id"] is None
    session.expire_all()
    history = session.query(SegmentEdit).filter_by(segment_id=line["id"]).one()
    assert history.before_json["start_ms"] == line["start_ms"]
    assert history.after_json["alignment_artifact_id"] == artifact["id"]
    assert (await client.post(apply_url, json=payload)).status_code == 409
    refreshed = (await client.get(f"/alignment-reports/{artifact['id']}")).json()
    assert refreshed["lines"][0]["stale_reason"]
    assert (
        refreshed["lines"][1]["stale_reason"] is None
    )  # Other suggestions remain individually reviewable.
    assert refreshed["stale_reason"] is None


@pytest.mark.anyio
async def test_alignment_protects_reviewed_timing_and_detects_audio_changes(
    client, session, aligner
):
    project, asset = await prepare_scene(client, session)
    initial = await transcribe(client, session, project, asset)
    first = initial["segments"][0]
    edited = (
        await client.patch(
            f"/segments/{first['id']}",
            json={
                "expected_version": first["version"],
                "translated_text": "Human translation",
            },
        )
    ).json()
    detail, job, artifact, report = await create_alignment(client, session, project)
    url = f"/alignment-reports/{artifact['id']}/apply"
    payload = {
        "segment_id": first["id"],
        "expected_version": edited["version"],
        "listening_confirmed": True,
    }
    assert (await client.post(url, json=payload)).status_code == 422
    assert (
        await client.post(url, json={**payload, "replace_reviewed_timing": True})
    ).status_code == 200
    second = detail["segments"][1]
    audio = session.get(Artifact, report["recognition_artifact_id"])
    path = Path(audio.path)
    path.write_bytes(path.read_bytes() + b"changed bytes")
    assert (
        await client.post(
            url,
            json={
                "segment_id": second["id"],
                "expected_version": second["version"],
            },
        )
    ).status_code == 409
    # Report downloads and typed inspection detect report mutation independently of input audio.
    Path(session.get(Artifact, artifact["id"]).path).write_text("{}")
    assert (await client.get(f"/alignment-reports/{artifact['id']}")).status_code == 409


@pytest.mark.anyio
async def test_alignment_rejects_foreign_sources_and_late_edits(
    client, session, aligner, monkeypatch
):
    project, asset = await prepare_scene(client, session)
    initial = await transcribe(client, session, project, asset)
    other, other_asset = await prepare_scene(client, session)
    assert (
        await client.post(
            f"/projects/{project['id']}/jobs",
            json={
                "stage": "align",
                "source_asset_id": other_asset["id"],
            },
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/projects/{other['id']}/jobs",
            json={
                "stage": "align",
                "revision_id": initial["active_revision_id"],
            },
        )
    ).status_code == 422
    native = LocalAligner.align

    def late(self, *args, **kwargs):
        result = native(self, *args, **kwargs)
        line = session.get(Segment, initial["segments"][0]["id"])
        line.source_text, line.version = "New edit during native inference", line.version + 1
        session.commit()
        return result

    monkeypatch.setattr(LocalAligner, "align", late)
    response = await client.post(f"/projects/{project['id']}/jobs", json={"stage": "align"})
    assert response.status_code == 202
    assert process_once(session)
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.status == "failed" and job.charged_estimate_inr == 0
    assert not session.query(Artifact).filter_by(job_id=job.id).all()


@pytest.mark.anyio
async def test_weak_alignment_is_visible_but_cannot_be_applied(
    client, session, aligner, monkeypatch
):
    project, asset = await prepare_scene(client, session)
    await transcribe(client, session, project, asset)
    native = LocalAligner.align

    def weak(self, *args, **kwargs):
        result = native(self, *args, **kwargs)
        result["lines"][0]["status"] = "needs_review"
        result["lines"][0]["warnings"].append("Fixture weak acoustic agreement")
        return result

    monkeypatch.setattr(LocalAligner, "align", weak)
    _, _, artifact, report = await create_alignment(client, session, project)
    line = report["lines"][0]
    assert (
        await client.post(
            f"/alignment-reports/{artifact['id']}/apply",
            json={
                "segment_id": line["segment_id"],
                "expected_version": line["segment_version"],
            },
        )
    ).status_code == 422


def test_ctc_path_repeated_letters_and_missing_frames():
    np = pytest.importorskip("numpy")
    from cinedub_api.alignment_dsp import english_tokens, force_align

    vocab = {"<pad>": 0, "A": 1, "B": 2, "|": 3, "'": 4}
    normalized, tokens = english_tokens("aa, b!", vocab)
    assert normalized == "AA B" and tokens == [1, 1, 3, 2]
    logits = np.full((10, len(vocab)), -8.0)
    path = [0, 1, 1, 0, 1, 3, 0, 2, 2, 0]
    logits[np.arange(len(path)), path] = 8
    output = force_align(logits, tokens, normalized, vocab, offset_ms=1000, duration_ms=1200)
    assert output["words"] == [
        {"text": "AA", "start_ms": 1020, "end_ms": 1100, "acoustic_score": 1.0},
        {"text": "B", "start_ms": 1140, "end_ms": 1180, "acoustic_score": 1.0},
    ]
    assert output["text_error_ratio"] == 0 and output["greedy_text"] == "AA B"
    with pytest.raises(ValueError, match="cannot fit"):
        force_align(logits[:2], tokens, normalized, vocab, offset_ms=0, duration_ms=40)
    for unsupported in ("A 123", "A മലയാളം", "A café"):
        with pytest.raises(ValueError, match="Unsupported"):
            english_tokens(unsupported, vocab)


def test_acoustic_measurements_pitch_energy_and_pauses_not_emotion():
    np = pytest.importorskip("numpy")
    from cinedub_api.acoustics import measure_performance

    sine = np.sin(2 * np.pi * 200 * np.arange(16000) / 16000) * 0.1
    samples = np.r_[np.zeros(8000), sine, np.zeros(8000)]
    result = measure_performance(samples, offset_ms=1000, word_count=4)
    assert abs(result["pitch_median_hz"] - 200) < 2
    assert abs(result["peak_dbfs"] + 20) < 0.1
    assert abs(result["rms_dbfs"] + 26.02) < 0.1
    assert result["words_per_minute"] == 120
    assert len(result["pauses"]) == 2 and result["pauses"][0]["start_ms"] == 1000
    assert 0.45 < result["energy_active_ratio"] < 0.55
    assert "emotion" not in result
    silence = measure_performance(np.zeros(16000))
    assert silence["pitch_median_hz"] is None and silence["rms_dbfs"] is None
    assert silence["energy_active_ratio"] == 0
    assert silence["pauses"] == [{"start_ms": 0, "end_ms": 1000}]


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_alignment_native_child_cancellation_and_deadline(tmp_path, monkeypatch, stop):
    native = subprocess.Popen
    children = []

    def start(command, **kwargs):
        assert "SARVAM_API_KEY" not in kwargs["env"] and kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        process = native([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr("cinedub_api.local_process.subprocess.Popen", start)
    monkeypatch.setenv("SARVAM_API_KEY", "not-a-key")

    def cancel():
        if stop == "cancel":
            raise InterruptedError("requested")

    with pytest.raises(InterruptedError if stop == "cancel" else TimeoutError):
        run_inference(
            "cinedub_api.local_alignment_runner",
            [],
            tmp_path,
            threads=4,
            timeout_seconds=-1,
            cancel=cancel,
            progress=lambda *_: None,
        )
    assert children and children[0].poll() is not None


def test_alignment_job_recovers_without_remote_billing_uncertainty(session):
    from cinedub_api.models import Project

    project = Project(name="Recovered alignment")
    session.add(project)
    session.flush()
    job = Job(
        project_id=project.id,
        stage="align",
        provider="local",
        status="running",
        phase="aligning_words",
        input_json={},
    )
    session.add(job)
    session.commit()
    recover_jobs(session)
    assert job.status == "queued" and job.charged_estimate_inr == 0


@pytest.mark.anyio
async def test_alignment_invalidates_old_take_without_changing_translation(
    client, session, aligner
):
    project, asset = await prepare_scene(client, session)
    initial = await transcribe(client, session, project, asset)
    line = session.get(Segment, initial["segments"][0]["id"])
    candidate = Artifact(
        project_id=project["id"],
        kind="dialogue_candidate",
        path="fixture-only-no-audio",
        filename="fixture.wav",
        media_type="audio/wav",
        metadata_json={"demo": True},
    )
    session.add(candidate)
    session.flush()
    line.selected_candidate_id = candidate.id
    line.translated_text, line.status, line.human_edited = (
        "Preserved human translation",
        "approved",
        True,
    )
    line.delivery_json = {"translation_source": line.source_text}
    session.commit()
    detail, _, artifact, report = await create_alignment(client, session, project)
    response = await client.post(
        f"/alignment-reports/{artifact['id']}/apply",
        json={
            "segment_id": line.id,
            "expected_version": line.version,
            "replace_reviewed_timing": True,
            "listening_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["selected_candidate_id"] is None
    assert response.json()["translated_text"] == "Preserved human translation"
    assert response.json()["status"] == "needs_review"
    session.expire_all()
    current = session.get(Segment, line.id)
    assert current.delivery_json["translation_source"] == current.source_text
    assert current.delivery_json["applied_alignment_artifact_id"] == artifact["id"]
    assert session.get(Artifact, candidate.id)  # Old take remains as history.


@pytest.mark.anyio
async def test_alignment_stem_choice_is_explicit_and_revision_bound(client, session, aligner):
    project, asset = await prepare_scene(client, session)
    await transcribe(client, session, project, asset)
    url = f"/projects/{project['id']}/jobs"
    request = {"stage": "align", "transcription_input": "dialogue_stem"}
    assert (await client.post(url, json=request)).status_code == 422
    original = (
        session.query(Artifact).filter_by(project_id=project["id"], kind="recognition_audio").one()
    )
    job = Job(project_id=project["id"], stage="separate", provider="local", status="completed")
    session.add(job)
    session.flush()
    stems = StemSet(
        project_id=project["id"],
        source_asset_id=asset["id"],
        job_id=job.id,
        provider="recorded-fixture",
        model="not-real-separated-audio",
        status="approved",
        metadata_json={"timeline_mapping_version": 2},
    )
    session.add(stems)
    session.flush()
    audio = Artifact(
        project_id=project["id"],
        kind="stem_recognition_audio",
        path=original.path,
        filename="recorded-stem.wav",
        media_type="audio/wav",
        metadata_json={"source_asset_id": asset["id"], "stem_set_id": stems.id},
    )
    session.add(audio)
    session.flush()
    stems.artifacts_json = {"recognition_audio": audio.id}
    session.get(MediaAsset, asset["id"]).active_stem_set_id = stems.id
    session.commit()
    _, _, artifact, report = await create_alignment(
        client, session, project, transcription_input="dialogue_stem"
    )
    assert report["stem_set_id"] == stems.id and report["recognition_artifact_id"] == audio.id
    reject = await client.post(
        f"/stem-sets/{stems.id}/review",
        json={
            "status": "rejected",
            "expected_version": 1,
            "expected_active_stem_set_id": stems.id,
            "reviewed_by": "Fixture reviewer",
        },
    )
    assert reject.status_code == 200, reject.text
    stale = (await client.get(f"/alignment-reports/{artifact['id']}")).json()
    assert "stem changed" in stale["stale_reason"]
    evidence = stale["lines"][0]
    assert (
        await client.post(
            f"/alignment-reports/{artifact['id']}/apply",
            json={
                "segment_id": evidence["segment_id"],
                "expected_version": evidence["segment_version"],
                "listening_confirmed": True,
            },
        )
    ).status_code == 409


@pytest.mark.anyio
async def test_alignment_does_not_silently_ignore_acoustic_provider_routing(
    client, session, aligner, monkeypatch
):
    project, asset = await prepare_scene(client, session)
    await transcribe(client, session, project, asset)
    monkeypatch.setattr(get_settings(), "performance_analyzer", "not-installed")
    response = await client.post(f"/projects/{project['id']}/jobs", json={"stage": "align"})
    assert response.status_code == 422 and "local acoustic adapter" in response.text
    assert not session.query(Job).filter_by(project_id=project["id"], stage="align").all()
