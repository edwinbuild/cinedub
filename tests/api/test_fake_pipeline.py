"""The complete dubbing workflow on deterministic DEMO providers: no models, keys or network."""

import hashlib
import io
import json
import socket
import zipfile
from pathlib import Path

import pytest
from cinedub_api.config import get_settings
from cinedub_api.media import file_digest
from cinedub_api.models import Artifact, Job, MediaAsset, ProviderRun
from cinedub_api.providers.fake_analysis import (
    FakeAligner,
    FakeDialogueAdapter,
    FakeEmotionAnalyzer,
    FakeTakeAnalyzer,
    spread_words,
)
from cinedub_api.schemas import (
    AlignmentReport,
    DialogueNativeLine,
    SpeechEmotionInference,
    TakePerformanceLine,
)
from cinedub_api.worker import process_once
from test_voice_workflow import wav

DEMO_CAPABILITIES = (
    "stem_separator",
    "timing_aligner",
    "target_timing_aligner",
    "performance_analyzer",
    "dialogue_adapter",
    "emotion_analyzer",
)
REVIEW = {"reviewed_by": "Fixture reviewer", "note": "Automated DEMO workflow, no listening"}


@pytest.fixture
def demo_providers(monkeypatch):
    settings = get_settings()
    for capability in DEMO_CAPABILITIES:
        monkeypatch.setattr(settings, capability, "fake")

    def offline(*_args, **_kwargs):
        raise AssertionError("DEMO workflow attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", offline)
    return settings


async def run(client, session, project_id, **payload):
    response = await client.post(f"/projects/{project_id}/jobs", json=payload)
    assert response.status_code == 202, response.text
    assert response.json()["estimated_cost_inr"] == 0
    assert process_once(session)
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.status == "completed", (job.stage, job.error_message)
    assert job.provider in {"fake", "local"}
    return job


async def detail(client, project_id):
    return (await client.get(f"/projects/{project_id}")).json()


async def approve_lines(client, project_id):
    for line in (await detail(client, project_id))["segments"]:
        if line["status"] != "approved":
            response = await client.patch(
                f"/segments/{line['id']}",
                json={"status": "approved", "expected_version": line["version"]},
            )
            assert response.status_code == 200, response.text


@pytest.mark.anyio
async def test_complete_workflow_runs_on_labelled_demo_providers(client, session, demo_providers):
    project = (await client.post("/projects", json={"name": "DEMO workflow"})).json()
    pid = project["id"]
    asset = (
        await client.post(
            f"/projects/{pid}/assets", files={"file": ("scene.wav", wav(), "audio/wav")}
        )
    ).json()
    assert process_once(session)
    capabilities = (await client.get("/capabilities")).json()
    for item in capabilities:
        if item["capability"] in DEMO_CAPABILITIES:
            assert item["selected_provider"] == "fake" and item["available"]
            assert item["reason"].startswith("DEMO")

    separation = await run(client, session, pid, stage="separate", source_asset_id=asset["id"])
    stems = (await detail(client, pid))["stem_sets"][0]
    assert stems["provider"] == "fake" and stems["metadata_json"]["demo"]
    assert any("DEMO stems" in warning for warning in separation.warnings_json)
    approved = await client.post(
        f"/stem-sets/{stems['id']}/review",
        json={
            **REVIEW,
            "status": "approved",
            "expected_version": 1,
            "expected_active_stem_set_id": None,
        },
    )
    assert approved.status_code == 200, approved.text

    await run(
        client,
        session,
        pid,
        stage="transcribe",
        source_asset_id=asset["id"],
        transcription_input="dialogue_stem",
    )
    await run(client, session, pid, stage="translate")
    await approve_lines(client, pid)
    await run(client, session, pid, stage="review_translation")
    adaptation = await run(client, session, pid, stage="adapt_dialogue")
    artifact_id = adaptation.output_json["adaptation_artifact_id"]
    report = (await client.get(f"/dialogue-adaptation-reports/{artifact_id}")).json()
    assert report["provider"] == "fake" and report["model"] == "deterministic-fixture-v1"
    line = (await detail(client, pid))["segments"][1]
    applied = await client.post(
        f"/dialogue-adaptation-reports/{artifact_id}/apply",
        json={
            "segment_id": line["id"],
            "kind": "concise",
            "expected_version": line["version"],
            "language_reviewed": True,
            "replace_reviewed_text": True,
            "issues_reviewed": True,
        },
    )
    assert applied.status_code == 200, applied.text
    await approve_lines(client, pid)

    current = await detail(client, pid)
    for index, speaker in enumerate(current["speakers"]):
        response = await client.post(
            f"/speakers/{speaker['id']}/stock-voice",
            json={"provider": "fake", "voice_id": "speaker-a" if index == 0 else "speaker-b"},
        )
        assert response.status_code == 200, response.text
    await run(client, session, pid, stage="synthesize")
    current = await detail(client, pid)
    for line in current["segments"]:
        take = next(
            item
            for item in current["artifacts"]
            if item["kind"] == "dialogue_candidate"
            and item["metadata_json"]["segment_id"] == line["id"]
        )
        response = await client.post(
            f"/segments/{line['id']}/candidate",
            json={"artifact_id": take["id"], "expected_version": line["version"]},
        )
        assert response.status_code == 200, response.text

    alignment = await run(client, session, pid, stage="align")
    aligned = (
        await client.get(f"/alignment-reports/{alignment.output_json['alignment_artifact_id']}")
    ).json()
    assert {line["status"] for line in aligned["lines"]} == {"needs_review"}
    takes = await run(client, session, pid, stage="analyze_takes", include_target_alignment=True)
    take_report = (
        await client.get(f"/take-analysis-reports/{takes.output_json['performance_artifact_id']}")
    ).json()
    assert {line["target_alignment"]["status"] for line in take_report["lines"]} == {"unalignable"}
    emotion = await run(client, session, pid, stage="analyze_emotion")
    emotion_report = (
        await client.get(f"/speech-emotion-reports/{emotion.output_json['emotion_artifact_id']}")
    ).json()
    for window in emotion_report["lines"]:
        assert window["status"] == "not_analyzed" and window["suggested_label"] is None
        assert window["scores"] == [] and "DEMO" in window["warnings"][0]

    render = await run(client, session, pid, stage="render_mix")
    mix = (await detail(client, pid))["mixes"][0]
    review = await client.post(
        f"/mixes/{mix['id']}/review",
        json={**REVIEW, "status": "approved", "expected_version": 1, "listening_confirmed": True},
    )
    assert review.status_code == 200, review.text
    assert process_once(session)
    final = await detail(client, pid)
    assert final["jobs"][0]["stage"] == "package_mix" and final["jobs"][0]["status"] == "completed"
    bundle_id = final["mixes"][0]["reviews"][0]["bundle_artifact_id"]
    download = await client.get(f"/artifacts/{bundle_id}/download")
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.testzip() is None
        certificate = json.loads(archive.read("listening-acceptance.json"))
        assert certificate["demo"]
        for item in certificate["files"]:
            assert hashlib.sha256(archive.read(item["filename"])).hexdigest() == item["sha256"]
        exported = json.loads(archive.read("lineage.json"))
    assert "lineage.json" in {item["filename"] for item in certificate["files"]}
    assert [source["id"] for source in exported["sources"]] == [asset["id"]]
    # Every exported file traces back to the uploaded source through recorded edges.
    parents = {}
    for edge in exported["edges"]:
        parents.setdefault(edge["artifact_id"], []).append(edge)

    def reaches_source(identifier, seen=()):
        return any(
            edge["input_asset_id"] == asset["id"]
            or (
                edge["input_artifact_id"]
                and edge["input_artifact_id"] not in seen
                and reaches_source(edge["input_artifact_id"], (*seen, identifier))
            )
            for edge in parents.get(identifier, [])
        )

    assert all(reaches_source(identifier) for identifier in exported["exported_artifact_ids"])
    roles = {edge["role"] for edge in exported["edges"]}
    assert {"source", "take", "background:music", "background:effects"} <= roles
    bundle_lineage = (await client.get(f"/artifacts/{bundle_id}/lineage")).json()
    assert {edge["role"] for edge in bundle_lineage["edges"]} >= {"accepted:master", "source"}
    assert bundle_lineage["sources"][0]["sha256"] == asset_sha256(session, asset["id"])
    nodes = {node["id"]: node for node in bundle_lineage["artifacts"]}
    stem_master = next(node for node in nodes.values() if node["kind"] == "stem_master")
    assert stem_master["job"]["stage"] == "separate" and stem_master["demo"]
    assert stem_master["provider_runs"][0]["provider"] == "fake"

    session.expire_all()
    fake_jobs = session.query(Job).filter_by(project_id=pid, provider="fake").all()
    assert {job.stage for job in fake_jobs} >= {
        "separate",
        "transcribe",
        "translate",
        "adapt_dialogue",
        "synthesize",
        "align",
        "analyze_takes",
        "analyze_emotion",
    }
    for job in fake_jobs:
        for artifact in session.query(Artifact).filter_by(job_id=job.id):
            assert artifact.metadata_json["demo"] is True, (job.stage, artifact.kind)
        for provider_run in session.query(ProviderRun).filter_by(job_id=job.id):
            assert provider_run.provider == "fake"
    mix_artifacts = session.query(Artifact).filter_by(job_id=render.id).all()
    assert mix_artifacts and all(item.metadata_json.get("demo") for item in mix_artifacts)
    for artifact in session.query(Artifact).filter_by(project_id=pid):
        # Integrity facts are recorded for every produced file, with a root-relative key.
        assert artifact.lineage_version == 1 and artifact.storage_key, artifact.kind
        assert not artifact.storage_key.startswith("/") and ".." not in artifact.storage_key
        assert artifact.sha256 == file_digest(artifact.path), artifact.kind
        assert artifact.size_bytes == Path(artifact.path).stat().st_size


def asset_sha256(session, asset_id):
    return session.get(MediaAsset, asset_id).metadata_json["sha256"]


@pytest.mark.anyio
async def test_demo_providers_are_refused_when_disabled(client, session, demo_providers):
    project = (await client.post("/projects", json={"name": "Production"})).json()
    asset = (
        await client.post(
            f"/projects/{project['id']}/assets",
            files={"file": ("scene.wav", wav(2), "audio/wav")},
        )
    ).json()
    assert process_once(session)
    for allowed, env in [(False, "development"), (None, "production")]:
        demo_providers.allow_demo_providers = allowed
        demo_providers.env = env
        response = await client.post(
            f"/projects/{project['id']}/jobs",
            json={"stage": "separate", "source_asset_id": asset["id"]},
        )
        assert response.status_code == 422 and "DEMO providers are disabled" in response.text
        capabilities = (await client.get("/capabilities")).json()
        separator = next(item for item in capabilities if item["capability"] == "stem_separator")
        assert not separator["available"]
    demo_providers.allow_demo_providers = None
    demo_providers.env = "development"


def test_fake_outputs_match_their_consuming_contracts(tmp_path):
    line = {"id": "a", "version": 1, "source_text": "One two three", "start_ms": 0, "end_ms": 900}
    aligned = FakeAligner().align(
        tmp_path / "audio.wav",
        tmp_path,
        lines=[line],
        duration_ms=1000,
        language="en-IN",
        cancel=lambda: None,
        progress=lambda *_: None,
    )
    AlignmentReport.model_validate(
        {
            "project_id": "p",
            "revision_id": "r",
            "source_asset_id": "s",
            "source_sha256": "0" * 64,
            "recognition_artifact_id": "a",
            "recognition_sha256": "0" * 64,
            "provider": "fake",
            "model": aligned["model"],
            "language": "en-IN",
            "metadata": aligned["metadata"],
            "lines": aligned["lines"],
            "warnings": [],
        }
    )
    assert [word["text"] for word in aligned["lines"][0]["words"]] == ["One", "two", "three"]
    assert spread_words("", 0, 100) == [] and spread_words("x", 5, 5) == []
    words = spread_words("a b c d", 0, 2)
    assert all(word["start_ms"] < word["end_ms"] <= 2 for word in words)

    take = {
        "candidate_id": "c",
        "start_ms": 0,
        "end_ms": 1000,
        "source_text": "Hello there",
        "translated_text": "നമസ്കാരം",
        "fitted_padding_ms": 40,
    }
    result = FakeTakeAnalyzer().compare(
        {"takes": [take], "include_target_alignment": False},
        tmp_path,
        cancel=lambda: None,
        progress=lambda *_: None,
    )
    TakePerformanceLine.model_validate(
        {
            **take,
            **result["lines"][0],
            "segment_id": "s",
            "speaker_id": None,
            "segment_version": 1,
            "candidate_sha256": "0" * 64,
            "voice": {},
            "signature": "x",
            "demo": True,
            "warnings": [],
        }
    )
    assert result["lines"][0]["target_alignment"]["status"] == "not_requested"

    request = {
        "segment_id": "s",
        "data": {"draft_translation": "ഒന്ന് രണ്ട് മൂന്ന് നാല്", "source_text": "One two three four"},
    }
    seen = []
    adapted = FakeDialogueAdapter().adapt(
        {"prompt_version": "v", "parameters": {}, "lines": [request]},
        tmp_path,
        cancel=lambda: None,
        progress=seen.append,
    )
    native = DialogueNativeLine.model_validate(adapted["lines"][0])
    assert native.output.faithful == "ഒന്ന് രണ്ട് മൂന്ന് നാല്"
    assert native.output.concise == "ഒന്ന് രണ്ട് മൂന്ന്" and seen and "DEMO" in native.output.notes

    emotion = FakeEmotionAnalyzer().analyze(
        tmp_path / "audio.wav",
        tmp_path,
        windows=[{"id": "s", "start_ms": 0, "end_ms": 900, "overlap": False}],
        duration_ms=1000,
        language="en-IN",
        cancel=lambda: None,
        progress=lambda *_: None,
    )
    inference = SpeechEmotionInference.model_validate(emotion["lines"][0])
    assert inference.status == "not_analyzed" and not inference.scores
    assert emotion["metadata"]["emotion_inference_count"] == 0
