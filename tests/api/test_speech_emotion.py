import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cinedub_api.emotion_processing import process_analyze_emotion
from cinedub_api.models import Artifact, Job, ProviderRun, Segment, SegmentEdit
from cinedub_api.providers import ProviderRegistry
from cinedub_api.providers.local_emotion import MODEL_NAME, PROFILE
from cinedub_api.worker import process_once
from test_timeline import prepare_scene, transcribe


@pytest.fixture
def analyzer(monkeypatch):
    manifest = {"vad_id": "recorded-vad", "vad_revision": "fixture"}
    monkeypatch.setattr("cinedub_api.jobs.emotion_availability", lambda _: (True, None))
    monkeypatch.setattr("cinedub_api.jobs.emotion_manifest", lambda _: manifest)
    monkeypatch.setattr("cinedub_api.emotion_processing.read_manifest", lambda _: manifest)
    control = {"calls": [], "mode": "normal"}

    class Recorded:
        def analyze(self, audio, directory, *, windows, duration_ms, language, cancel, progress):
            cancel()
            assert audio.is_file() and language == "en-IN" and duration_ms == 2000
            assert all(set(line) == {"id", "start_ms", "end_ms", "overlap"} for line in windows)
            control["calls"].append(copy.deepcopy(windows))
            lines = []
            for window in windows:
                overlap = window["overlap"]
                lines.append(
                    {
                        "segment_id": window["id"],
                        "start_ms": window["start_ms"],
                        "end_ms": window["end_ms"],
                        "status": "overlap" if overlap else "needs_review",
                        "suggested_label": None if overlap else "neutral",
                        "scores": []
                        if overlap
                        else [
                            {"label": label, "score": score}
                            for label, score in zip(
                                ["neutral", "happy", "angry", "sad"],
                                [0.8, 0.1, 0.05, 0.05],
                                strict=True,
                            )
                        ],
                        "score_margin": None if overlap else 0.7,
                        "speech_ms": 0 if overlap else window["end_ms"] - window["start_ms"],
                        "speech_fraction": 0 if overlap else 1,
                        "rms_dbfs": -20,
                        "warnings": ["Recorded fixture, not measured model quality"],
                    }
                )
            progress(len(windows), len(windows))
            payload = {
                "provider": "local",
                "model": MODEL_NAME,
                "profile": PROFILE,
                "lines": lines,
                "metadata": {
                    "elapsed_ms": 5,
                    "peak_rss_mib": 10,
                    "threads": 4,
                    "emotion_inference_count": sum(not w["overlap"] for w in windows),
                    "vad_frame_count": 10,
                },
            }
            if control["mode"] == "wrong_model":
                payload["model"] = "foreign"
            elif control["mode"] == "wrong_window":
                lines[0]["start_ms"] += 1
            elif control["mode"] == "wrong_scores":
                lines[0]["scores"][0]["score"] = 0.5
            elif control["mode"] == "invented_skip":
                lines[0]["status"] = "no_speech"
            if control.get("on_complete"):
                control["on_complete"]()
            return payload

    monkeypatch.setattr(ProviderRegistry, "emotion_analyzer", lambda self, *args: Recorded())
    return control


async def scene(client, session):
    project, asset = await prepare_scene(client, session)
    detail = await transcribe(client, session, project, asset)
    return project, detail


async def analyze(client, session, project, **extra):
    response = await client.post(
        f"/projects/{project['id']}/jobs", json={"stage": "analyze_emotion", **extra}
    )
    assert response.status_code == 202, response.text
    assert process_once(session)
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.status == "completed", job.error_message
    artifact_id = job.output_json["emotion_artifact_id"]
    response = await client.get(f"/speech-emotion-reports/{artifact_id}")
    assert response.status_code == 200, response.text
    return job, artifact_id, response.json()


@pytest.mark.anyio
async def test_audio_only_report_and_append_only_review_never_change_timeline(
    client, session, analyzer
):
    project, initial = await scene(client, session)
    job, artifact_id, report = await analyze(client, session, project)
    current = (await client.get(f"/projects/{project['id']}")).json()
    assert current["segments"] == initial["segments"]
    assert report["stale_reason"] is None and all(
        not line["review_history"] for line in report["lines"]
    )
    assert len(analyzer["calls"]) == 1
    assert any("6/14" in warning and "7/8" in warning for warning in report["warnings"])
    runs = session.query(ProviderRun).filter_by(job_id=job.id).all()
    assert {r.capability for r in runs} == {"emotion_analyzer", "speech_presence_detector"}
    assert all(r.estimated_cost_inr == 0 for r in runs)
    url = f"/speech-emotion-reports/{artifact_id}/review"
    payload = {
        "segment_id": report["lines"][0]["segment_id"],
        "expected_review_version": 0,
        "status": "accepted",
        "reviewed_by": "Fixture editor",
    }
    assert (await client.post(url, json=payload)).status_code == 422
    payload["listening_confirmed"] = True
    response = await client.post(url, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["label"] == "neutral" and response.json()["version"] == 1
    assert (await client.post(url, json=payload)).status_code == 409
    payload.update(expected_review_version=1, status="corrected", label="fearful")
    assert (await client.post(url, json=payload)).status_code == 200
    payload.update(expected_review_version=2, status="rejected", label=None)
    assert (await client.post(url, json=payload)).status_code == 200
    saved = (await client.get(f"/speech-emotion-reports/{artifact_id}")).json()
    assert saved["warnings"] == report["warnings"]
    assert [r["version"] for r in saved["lines"][0]["review_history"]] == [1, 2, 3]
    assert (await client.get(f"/projects/{project['id']}")).json()["segments"] == initial[
        "segments"
    ]
    assert session.query(SegmentEdit).count() == 0
    assert process_analyze_emotion(session, job) == {"emotion_artifact_id": artifact_id}
    cached = await client.post(f"/projects/{project['id']}/jobs", json={"stage": "analyze_emotion"})
    assert cached.json()["id"] == job.id


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["wrong_model", "wrong_window", "wrong_scores", "invented_skip"])
async def test_invalid_inference_never_publishes(client, session, analyzer, mode):
    project, _ = await scene(client, session)
    analyzer["mode"] = mode
    response = await client.post(
        f"/projects/{project['id']}/jobs", json={"stage": "analyze_emotion"}
    )
    assert response.status_code == 202
    assert process_once(session)
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.status == "failed"
    assert not session.query(Artifact).filter_by(job_id=job.id).all()
    assert not session.query(ProviderRun).filter_by(job_id=job.id).all()


@pytest.mark.anyio
async def test_text_edits_do_not_stale_audio_but_timing_edits_and_changed_bytes_do(
    client, session, analyzer
):
    project, _ = await scene(client, session)
    _, artifact_id, report = await analyze(client, session, project)
    line = session.get(Segment, report["lines"][0]["segment_id"])
    line.source_text = "A transcript correction, same recorded performance"
    line.translated_text = "A human translation"
    line.version += 1
    session.commit()
    url = f"/speech-emotion-reports/{artifact_id}"
    assert (await client.get(url)).json()["lines"][0]["stale_reason"] is None
    line.end_ms -= 50
    session.commit()
    assert (await client.get(url)).json()["lines"][0]["stale_reason"]
    review = {
        "segment_id": line.id,
        "expected_review_version": 0,
        "status": "accepted",
        "reviewed_by": "Fixture editor",
        "listening_confirmed": True,
    }
    assert (await client.post(url + "/review", json=review)).status_code == 409
    audio = session.get(Artifact, report["recognition_artifact_id"])
    Path(audio.path).write_bytes(b"changed synthetic audio")
    assert (await client.get(url)).json()["stale_reason"]
    Path(session.get(Artifact, artifact_id).path).write_text("{}")
    assert (await client.get(url)).status_code == 409


@pytest.mark.anyio
async def test_queued_and_late_timing_changes_block_publication(client, session, analyzer):
    project, initial = await scene(client, session)

    def edit():
        line = session.get(Segment, initial["segments"][0]["id"])
        line.end_ms -= 10
        session.commit()

    for late in [False, True]:
        response = await client.post(
            f"/projects/{project['id']}/jobs", json={"stage": "analyze_emotion", "force_new": True}
        )
        if late:
            analyzer["on_complete"] = edit
        else:
            edit()
        assert process_once(session)
        session.expire_all()
        job = session.get(Job, response.json()["id"])
        assert job.status == "failed"
        assert not session.query(Artifact).filter_by(job_id=job.id).all()
    assert len(analyzer["calls"]) == 1


def test_emotion_native_import_does_not_initialize_database_or_settings():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys;import cinedub_api.local_emotion_runner;"
            "from cinedub_api.config import get_settings;"
            "assert 'cinedub_api.database' not in sys.modules;"
            "assert get_settings.cache_info().currsize == 0",
        ],
        env={"PATH": os.environ["PATH"], "PYTHONPATH": "apps/api"},
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert not result.stdout


def test_logits_are_stable_normalized_and_weak_scores_do_not_suggest_emotion():
    np = pytest.importorskip("numpy")
    from cinedub_api.local_emotion_runner import scores_from_logits

    scores, label, margin = scores_from_logits([[1000, 0, 0, 0]])
    assert label == "neutral" and margin == 1 and sum(s["score"] for s in scores) == 1
    scores, label, margin = scores_from_logits([[0, 0, 0, 0]])
    assert label is None and margin == 0 and all(s["score"] == 0.25 for s in scores)
    for values in ([[np.nan, 0, 0, 0]], [[np.inf, 0, 0, 0]], [[0, 0]]):
        with pytest.raises(ValueError, match="invalid logits"):
            scores_from_logits(values)


def test_vad_padding_is_not_counted_as_speech_and_state_resets_between_lines():
    np = pytest.importorskip("numpy")
    from cinedub_api.local_emotion_runner import speech_presence

    class Detector:
        def __init__(self):
            self.calls = []

        def run(self, names, feed):
            self.calls.append(feed)
            return np.array([[1.0]]), np.ones((2, 1, 128), dtype=np.float32)

    model = Detector()
    for _ in range(2):
        milliseconds, fraction, count = speech_presence(model, np.ones(600, dtype=np.float32))
        assert milliseconds == 38 and fraction == 1 and count == 2
    assert not model.calls[0]["state"].any() and not model.calls[2]["state"].any()
    assert model.calls[0]["input"].shape == (1, 576)


@pytest.mark.anyio
async def test_replaced_window_preserves_emotion_report_but_blocks_new_review(
    client, session, analyzer
):
    project, detail = await scene(client, session)
    _, artifact_id, report = await analyze(client, session, project)
    line = detail["segments"][0]
    response = await client.post(
        f"/segments/{line['id']}/split",
        json={
            "revision_id": detail["active_revision_id"],
            "expected_version": line["version"],
            "split_ms": (line["start_ms"] + line["end_ms"]) // 2,
            "first": {"source_text": "Manual first half"},
            "second": {"source_text": "Manual second half"},
            "replacement_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    url = f"/speech-emotion-reports/{artifact_id}"
    updated = (await client.get(url)).json()
    assert updated["lines"][0]["stale_reason"]
    response = await client.post(
        url + "/review",
        json={
            "segment_id": line["id"],
            "expected_review_version": 0,
            "status": "accepted",
            "reviewed_by": "Synthetic fixture editor",
            "listening_confirmed": True,
        },
    )
    assert response.status_code == 409
