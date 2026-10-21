import copy
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from cinedub_api.config import get_settings
from cinedub_api.models import Artifact, Job, ProviderRun, Segment
from cinedub_api.performance_comparison import compare_performance
from cinedub_api.providers.local_take_analysis import LocalTakeAnalyzer
from cinedub_api.take_analysis_processing import process_analyze_takes
from cinedub_api.worker import process_once, recover_jobs
from test_cloning import setup_clone, stage
from test_voice_workflow import prepare_reviewed_scene


@pytest.fixture
def analyzer(monkeypatch):
    monkeypatch.setattr("cinedub_api.stages.analysis.take_analyzer_available", lambda: True)
    calls = []

    def compare(self, request, output_dir, *, cancel, progress):
        cancel()
        calls.append(copy.deepcopy(request))
        lines = []
        for take in request["takes"]:
            assert Path(take["prepared_audio_path"]).is_file()
            start, end = take["start_ms"], take["end_ms"]
            source = {
                "rms_dbfs": -30,
                "peak_dbfs": -20,
                "pitch_median_hz": 200,
                "pitch_p10_hz": 190,
                "pitch_p90_hz": 210,
                "energy_active_ratio": 1,
                "activity_threshold_dbfs": -50,
                "words_per_minute": 120,
                "pauses": [],
                "frames": [
                    {"time_ms": start, "rms_dbfs": -30, "pitch_hz": 200},
                    {"time_ms": end - 20, "rms_dbfs": -30, "pitch_hz": 200},
                ],
                "warnings": ["Recorded adapter fixture, not a measured performance"],
            }
            target = {**source, "rms_dbfs": -20, "pitch_median_hz": 220}
            alignment = {
                "status": "unalignable" if request["include_target_alignment"] else "not_requested",
                "words": [],
                "warnings": ["Recorded fixture: demo tones have no words"],
            }
            lines.append(
                {
                    "candidate_id": take["candidate_id"],
                    "source_performance": source,
                    "target_performance": target,
                    "target_alignment": alignment,
                    "comparison": compare_performance(
                        source,
                        target,
                        start_ms=start,
                        end_ms=end,
                        fitted_padding_ms=take["fitted_padding_ms"],
                    ),
                }
            )
        progress(len(lines), len(lines))
        from cinedub_api.providers.local_target_alignment import MODEL_NAME

        return {
            "lines": lines,
            "metadata": {
                "model": "acoustic-dsp-v1",
                "latency_ms": 12,
                "peak_rss_mib": 100,
                "target_alignment_model": MODEL_NAME
                if request["include_target_alignment"]
                else None,
                "target_alignment_requested": request["include_target_alignment"],
                "target_inference_count": 0,
            },
        }

    monkeypatch.setattr(LocalTakeAnalyzer, "compare", compare)
    return calls


async def analyze(client, session, detail, **options):
    response = await client.post(
        f"/projects/{detail['id']}/jobs", json={"stage": "analyze_takes", **options}
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["estimated_cost_inr"] == 0
    assert process_once(session)
    after = (await client.get(f"/projects/{detail['id']}")).json()
    assert after["jobs"][0]["status"] == "completed", after["jobs"][0]
    artifact = next(item for item in after["artifacts"] if item["job_id"] == job["id"])
    response = await client.get(f"/take-analysis-reports/{artifact['id']}")
    assert response.status_code == 200, response.text
    return after, job, artifact, response.json()


@pytest.mark.anyio
async def test_take_analysis_is_free_readonly_cached_and_keeps_selected_take_choices_valid(
    client, session, analyzer
):
    before = await prepare_reviewed_scene(client, session)
    line = before["segments"][0]
    candidate_id = line["selected_candidate_id"]
    stored = session.get(Segment, line["id"])
    stored.selected_candidate_id, stored.version = None, stored.version + 1
    session.commit()
    before = (await client.get(f"/projects/{before['id']}")).json()
    after, job, artifact, report = await analyze(
        client, session, before, candidate_ids=[candidate_id]
    )
    assert len(analyzer) == 1 and after["segments"] == before["segments"]
    assert report["lines"][0]["demo"] and report["lines"][0]["comparison"]["rms_delta_db"] == 10
    assert report["lines"][0]["target_alignment"]["status"] == "not_requested"
    assert report["stale_reason"] is None and report["lines"][0]["stale_reason"] is None
    assert process_analyze_takes(session, session.get(Job, job["id"])) == {
        "performance_artifact_id": artifact["id"]
    }
    cached = (
        await client.post(
            f"/projects/{before['id']}/jobs",
            json={
                "stage": "analyze_takes",
                "candidate_ids": [candidate_id],
            },
        )
    ).json()
    assert cached["id"] == job["id"]
    current = after["segments"][0]
    assert (
        await client.post(
            f"/segments/{current['id']}/candidate",
            json={
                "artifact_id": candidate_id,
                "expected_version": current["version"],
            },
        )
    ).status_code == 200
    # Selection advances an edit version, but not the signal/material being analyzed.
    report = (await client.get(f"/take-analysis-reports/{artifact['id']}")).json()
    assert report["lines"][0]["stale_reason"] is None
    run = session.query(ProviderRun).filter_by(job_id=job["id"]).one()
    assert run.capability == "performance_analyzer" and run.estimated_cost_inr == 0


@pytest.mark.anyio
async def test_analysis_rejects_foreign_stale_or_duplicate_candidates_and_flags_later_edits(
    client, session, analyzer
):
    scene = await prepare_reviewed_scene(client, session)
    other = await prepare_reviewed_scene(client, session)
    url = f"/projects/{scene['id']}/jobs"
    candidate_id = scene["segments"][0]["selected_candidate_id"]
    for ids in ([other["segments"][0]["selected_candidate_id"]], [candidate_id, candidate_id]):
        assert (
            await client.post(url, json={"stage": "analyze_takes", "candidate_ids": ids})
        ).status_code == 422
    _, _, artifact, report = await analyze(client, session, scene, candidate_ids=[candidate_id])
    line = scene["segments"][0]
    assert (
        await client.patch(
            f"/segments/{line['id']}",
            json={
                "source_text": "Changed after analysis",
                "expected_version": line["version"],
            },
        )
    ).status_code == 200
    report = (await client.get(f"/take-analysis-reports/{artifact['id']}")).json()
    assert report["lines"][0]["stale_reason"]
    assert (
        await client.post(url, json={"stage": "analyze_takes", "candidate_ids": [candidate_id]})
    ).status_code == 422


@pytest.mark.anyio
async def test_report_and_audio_changes_are_detected(client, session, analyzer):
    scene = await prepare_reviewed_scene(client, session)
    after, job, artifact, report = await analyze(client, session, scene)
    candidate = session.get(Artifact, report["lines"][0]["candidate_id"])
    Path(candidate.path).write_bytes(Path(candidate.path).read_bytes() + b"altered")
    report = (await client.get(f"/take-analysis-reports/{artifact['id']}")).json()
    assert "bytes changed" in report["lines"][0]["stale_reason"]
    Path(session.get(Artifact, artifact["id"]).path).write_text("{}")
    assert (await client.get(f"/take-analysis-reports/{artifact['id']}")).status_code == 409


@pytest.mark.anyio
async def test_late_edits_do_not_publish_current_comparison(client, session, analyzer, monkeypatch):
    scene = await prepare_reviewed_scene(client, session)
    native = LocalTakeAnalyzer.compare

    def late(self, *args, **kwargs):
        payload = native(self, *args, **kwargs)
        line = session.get(Segment, scene["segments"][0]["id"])
        line.translated_text, line.version = "Late human correction", line.version + 1
        session.commit()
        return payload

    monkeypatch.setattr(LocalTakeAnalyzer, "compare", late)
    response = await client.post(f"/projects/{scene['id']}/jobs", json={"stage": "analyze_takes"})
    assert response.status_code == 202
    assert process_once(session)
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.status == "failed" and not session.query(Artifact).filter_by(job_id=job.id).all()


@pytest.mark.anyio
async def test_malayalam_alignment_is_opt_in_and_demo_tones_never_get_words(
    client, session, analyzer, monkeypatch
):
    scene = await prepare_reviewed_scene(client, session)
    monkeypatch.setattr(
        "cinedub_api.stages.analysis.target_aligner_available", lambda _: (False, "Not installed")
    )
    assert (
        await client.post(
            f"/projects/{scene['id']}/jobs",
            json={
                "stage": "analyze_takes",
                "include_target_alignment": True,
            },
        )
    ).status_code == 422
    await analyze(client, session, scene)  # Signal measurements do not need a word model.
    manifest = {"fixture": "not real model files"}
    monkeypatch.setattr(
        "cinedub_api.stages.analysis.target_aligner_available", lambda _: (True, "test")
    )
    monkeypatch.setattr("cinedub_api.stages.analysis.target_aligner_manifest", lambda _: manifest)
    monkeypatch.setattr(
        "cinedub_api.take_analysis_processing.read_manifest", lambda *a, **k: manifest
    )
    _, job, _, report = await analyze(client, session, scene, include_target_alignment=True)
    assert all(line["target_alignment"]["status"] == "unalignable" for line in report["lines"])
    assert all(not line["target_alignment"]["words"] for line in report["lines"])
    assert (
        not session.query(ProviderRun)
        .filter_by(job_id=job["id"], capability="target_timing_aligner")
        .all()
    )


@pytest.mark.anyio
async def test_clone_revocation_quarantines_analysis_json_and_cancels_queued_work(
    client, session, analyzer
):
    scene, asset, payload = await setup_clone(client, session)
    profile = (await client.post(f"/projects/{scene['id']}/voice-profiles", json=payload)).json()
    await stage(
        client,
        session,
        scene["id"],
        {"stage": "prepare_reference", "voice_profile_id": profile["id"]},
    )
    scene = await stage(
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
    speaker = scene["speakers"][0]
    assert (
        await client.post(
            f"/speakers/{speaker['id']}/voice-profile",
            json={
                "profile_id": profile["id"],
                "expected_profile_id": speaker["voice_profile_id"],
            },
        )
    ).status_code == 200
    scene = await stage(client, session, scene["id"], {"stage": "synthesize", "force_new": True})
    clone_candidate = next(
        item
        for item in scene["artifacts"]
        if item["kind"] == "dialogue_candidate"
        and item["metadata_json"]["voice"]["profile_id"] == profile["id"]
    )
    _, _, artifact, _ = await analyze(client, session, scene, candidate_ids=[clone_candidate["id"]])
    queued = await client.post(
        f"/projects/{scene['id']}/jobs",
        json={
            "stage": "analyze_takes",
            "candidate_ids": [clone_candidate["id"]],
            "force_new": True,
        },
    )
    assert queued.status_code == 202
    revoke = await client.post(
        f"/voice-profiles/{profile['id']}/revoke", json={"attested_by": "Fixture rights holder"}
    )
    assert revoke.status_code == 200
    session.expire_all()
    assert session.get(Job, queued.json()["id"]).status == "cancelled"
    assert (await client.get(f"/take-analysis-reports/{artifact['id']}")).status_code == 403
    for path in (artifact["download_url"], artifact["content_url"]):
        assert (await client.get(path, headers={"Range": "bytes=0-3"})).status_code == 403
        assert (await client.head(path)).status_code == 403


def test_malayalam_blank_id_zero_character_and_unicode_normalization():
    np = pytest.importorskip("numpy")
    from cinedub_api.alignment_dsp import force_align, malayalam_tokens

    vocab = {"ർ": 0, "ക": 1, "|": 2, "[PAD]": 3}
    normalized, tokens = malayalam_tokens("ർക, ക", vocab)
    assert tokens == [0, 1, 2, 1]
    path = [3, 0, 1, 2, 3, 1, 3]
    logits = np.full((len(path), len(vocab)), -8.0)
    logits[np.arange(len(path)), path] = 8
    result = force_align(logits, tokens, normalized, vocab, offset_ms=1000, duration_ms=1140)
    assert result["greedy_text"] == "ർക ക" and len(result["words"]) == 2
    assert result["words"][0]["start_ms"] == 1020
    with pytest.raises(ValueError, match="Unsupported"):
        malayalam_tokens("123 hello", vocab)


def test_comparison_excludes_trailing_padding_from_internal_pauses():
    np = pytest.importorskip("numpy")
    from cinedub_api.acoustics import measure_performance

    source = np.sin(2 * np.pi * 200 * np.arange(32000) / 16000) * 0.1
    target = np.r_[np.sin(2 * np.pi * 400 * np.arange(16000) / 16000) * 0.2, np.zeros(16000)]
    comparison = compare_performance(
        measure_performance(source),
        measure_performance(target),
        start_ms=0,
        end_ms=2000,
        fitted_padding_ms=1000,
    )
    assert abs(comparison["pitch_shift_semitones"] - 12) < 0.1
    assert abs(comparison["rms_delta_db"] - 3.01) < 0.1
    assert comparison["target_internal_pause_ms"] == 0
    assert comparison["active_span_delta_ms"] == -1000 and comparison["fitted_padding_ms"] == 1000


@pytest.mark.anyio
async def test_real_optional_dsp_process_reports_measured_tones_without_emotion(client, session):
    pytest.importorskip("numpy")
    before = await prepare_reviewed_scene(client, session)
    after, _, _, report = await analyze(client, session, before)
    assert before["segments"] == after["segments"]
    assert report["metadata"]["target_alignment_model"] is None
    assert report["metadata"]["peak_rss_mib"] < 2048
    assert report["lines"][0]["source_performance"]["rms_dbfs"] is None
    assert report["lines"][0]["target_performance"]["rms_dbfs"] is not None
    assert "emotion" not in report["lines"][0]["target_performance"]


@pytest.mark.anyio
async def test_new_review_options_do_not_change_other_stage_fingerprints(client, session, analyzer):
    scene = await prepare_reviewed_scene(client, session)
    for job in session.query(Job).filter_by(project_id=scene["id"]).all():
        assert (
            "candidate_ids" not in job.input_json
            and "include_target_alignment" not in job.input_json
        )
    assert (
        await client.post(
            f"/projects/{scene['id']}/jobs",
            json={
                "stage": "translate",
                "include_target_alignment": True,
            },
        )
    ).status_code == 422
    monkey = get_settings()
    assert monkey.performance_analyzer == "local"


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_take_native_process_is_stopped_and_has_no_credentials(tmp_path, monkeypatch, stop):
    native, children = subprocess.Popen, []

    def start(command, **kwargs):
        assert "SARVAM_API_KEY" not in kwargs["env"]
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        process = native([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(process)
        return process

    def cancel():
        if stop == "cancel":
            raise InterruptedError("requested")

    monkeypatch.setenv("SARVAM_API_KEY", "not-a-real-key")
    monkeypatch.setattr("cinedub_api.local_process.subprocess.Popen", start)
    with pytest.raises(InterruptedError if stop == "cancel" else TimeoutError):
        LocalTakeAnalyzer(timeout_seconds=-1).compare(
            {}, tmp_path, cancel=cancel, progress=lambda *_: None
        )
    assert children and children[0].poll() is not None


@pytest.mark.anyio
async def test_recovered_analysis_reuses_committed_evidence_without_duplicate_runs(
    client, session, analyzer
):
    scene = await prepare_reviewed_scene(client, session)
    _, job, artifact, _ = await analyze(client, session, scene)
    saved = session.get(Job, job["id"])
    saved.status, saved.phase = "running", "validating_take_analysis"
    session.commit()
    recover_jobs(session)
    assert saved.status == "queued"
    assert process_once(session)
    session.expire_all()
    saved = session.get(Job, job["id"])
    assert (
        saved.status == "completed"
        and saved.output_json["performance_artifact_id"] == artifact["id"]
    )
    assert session.query(Artifact).filter_by(job_id=job["id"]).count() == 1
    assert session.query(ProviderRun).filter_by(job_id=job["id"]).count() == 1
    assert len(analyzer) == 1


def test_evaluation_seed_refuses_workspace_and_symlinked_databases(tmp_path):
    command = [
        sys.executable,
        "scripts/seed-performance-fixture.py",
        "--project-id",
        "00000000-0000-0000-0000-000000000000",
        "--state-root",
    ]
    rejected = subprocess.run([*command, str(Path.cwd())], capture_output=True, timeout=10)
    assert rejected.returncode != 0 and b"Only an existing isolated" in rejected.stderr
    protected = tmp_path / "not-a-workspace-database"
    protected.write_bytes(b"Do not change this unrelated file")
    with tempfile.TemporaryDirectory(prefix="cinedub-e2e-") as root:
        (Path(root) / "cinedub.db").symlink_to(protected)
        rejected = subprocess.run([*command, root], capture_output=True, timeout=10)
        assert rejected.returncode != 0 and b"Only an existing isolated" in rejected.stderr
    assert protected.read_bytes() == b"Do not change this unrelated file"


def test_explicit_e2e_server_state_must_be_empty():
    import os

    with tempfile.TemporaryDirectory(prefix="cinedub-e2e-") as root:
        (Path(root) / "existing-fixture.txt").write_text("Existing test data must not be reused")
        result = subprocess.run(
            ["bash", "scripts/e2e-server.sh"],
            env={**os.environ, "CINEDUB_E2E_STATE_ROOT": root},
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 1 and b"must be empty" in result.stderr
        assert not (Path(root) / "cinedub.db").exists()
