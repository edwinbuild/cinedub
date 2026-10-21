"""Pipeline orchestration through human review gates, on DEMO providers."""

import pytest
from cinedub_api import worker
from cinedub_api.config import get_settings
from cinedub_api.models import Job, Pipeline
from cinedub_api.providers import ProviderRegistry
from cinedub_api.providers.base import TranslationResult
from cinedub_api.worker import process_once, recover_jobs
from test_fake_pipeline import DEMO_CAPABILITIES, REVIEW, approve_lines
from test_voice_workflow import wav


@pytest.fixture
def demo(monkeypatch):
    settings = get_settings()
    for capability in DEMO_CAPABILITIES:
        monkeypatch.setattr(settings, capability, "fake")
    return settings


async def scene(client, session, seconds=8):
    project = (await client.post("/projects", json={"name": "Pipeline"})).json()
    asset = (
        await client.post(
            f"/projects/{project['id']}/assets",
            files={"file": ("scene.wav", wav(seconds), "audio/wav")},
        )
    ).json()
    assert process_once(session)  # Upload already queued media preparation.
    return project["id"], asset["id"]


async def drain(client, session, pipeline_id):
    """Run queued jobs until the pipeline waits, fails, finishes or is cancelled."""
    for _ in range(20):
        state = (await client.get(f"/pipelines/{pipeline_id}")).json()
        if state["status"] != "running":
            return state
        assert process_once(session), state
    raise AssertionError("Pipeline did not settle")


def current(state):
    return state["steps_json"][state["current_step"]]


async def proceed(client, session, pipeline_id, **body):
    response = await client.post(f"/pipelines/{pipeline_id}/continue", json=body)
    assert response.status_code == 200, response.text
    return await drain(client, session, pipeline_id)


@pytest.mark.anyio
async def test_pipeline_runs_every_stage_and_waits_at_each_review_gate(client, session, demo):
    pid, source = await scene(client, session)
    options = {
        "source_asset_id": source,
        "separate_dialogue": True,
        "adapt_dialogue": True,
        "analyze_performance": True,
    }
    plan = (await client.post(f"/projects/{pid}/pipelines/plan", json=options)).json()
    gates = [step["key"] for step in plan["steps"] if step["kind"] == "gate"]
    assert gates == [
        "stems_approved",
        "speakers_assigned",
        "lines_approved",
        "voices_assigned",
        "takes_selected",
        "mix_accepted",
    ]
    assert not session.query(Pipeline).count()  # Planning queues nothing.
    created = await client.post(f"/projects/{pid}/pipelines", json=options)
    assert created.status_code == 201, created.text
    pipeline = created.json()["id"]
    assert (await client.post(f"/projects/{pid}/pipelines", json=options)).status_code == 409

    state = await drain(client, session, pipeline)
    assert state["status"] == "awaiting_review" and current(state)["key"] == "stems_approved"
    # A gate never opens before the saved human review satisfies it.
    refused = await client.post(f"/pipelines/{pipeline}/continue", json={})
    assert refused.status_code == 409
    stems = (await client.get(f"/projects/{pid}")).json()["stem_sets"][0]
    await client.post(
        f"/stem-sets/{stems['id']}/review",
        json={
            **REVIEW,
            "status": "approved",
            "expected_version": 1,
            "expected_active_stem_set_id": None,
        },
    )
    state = await proceed(client, session, pipeline)
    assert current(state)["key"] == "speakers_assigned"
    transcribe = session.get(Job, state["steps_json"][3]["job_id"])
    assert transcribe.stage == "transcribe"
    assert transcribe.input_json["transcription_input"] == "dialogue_stem"

    state = await proceed(client, session, pipeline)
    assert current(state)["key"] == "lines_approved"
    assert [step["status"] for step in state["steps_json"][5:8]] == ["completed"] * 3
    await approve_lines(client, pid)
    state = await proceed(client, session, pipeline)
    assert current(state)["key"] == "voices_assigned"
    assert "speakers have no voice" in state["gate_reason"]
    detail = (await client.get(f"/projects/{pid}")).json()
    for index, speaker in enumerate(detail["speakers"]):
        await client.post(
            f"/speakers/{speaker['id']}/stock-voice",
            json={"provider": "fake", "voice_id": "speaker-a" if index == 0 else "speaker-b"},
        )
    state = await proceed(client, session, pipeline)
    assert current(state)["key"] == "takes_selected"
    detail = (await client.get(f"/projects/{pid}")).json()
    for line in detail["segments"]:
        take = next(
            item
            for item in detail["artifacts"]
            if item["kind"] == "dialogue_candidate"
            and item["metadata_json"]["segment_id"] == line["id"]
        )
        await client.post(
            f"/segments/{line['id']}/candidate",
            json={"artifact_id": take["id"], "expected_version": line["version"]},
        )
    state = await proceed(client, session, pipeline)
    assert current(state)["key"] == "mix_accepted"
    stages = [
        session.get(Job, step["job_id"]).stage
        for step in state["steps_json"]
        if step["kind"] == "job"
    ]
    assert stages[-4:] == ["align", "analyze_takes", "analyze_emotion", "render_mix"]
    mix = (await client.get(f"/projects/{pid}")).json()["mixes"][0]
    await client.post(
        f"/mixes/{mix['id']}/review",
        json={**REVIEW, "status": "approved", "expected_version": 1, "listening_confirmed": True},
    )
    # The accepted bundle is packaged by its own job before the final gate can open.
    assert (await client.post(f"/pipelines/{pipeline}/continue", json={})).status_code == 409
    assert process_once(session)
    state = await proceed(client, session, pipeline)
    assert state["status"] == "completed" and state["finished_at"]
    assert all(step["status"] == "completed" for step in state["steps_json"])
    assert (await client.get(f"/projects/{pid}")).json()["status"] == "ready"


@pytest.mark.anyio
async def test_failed_transcription_stops_pipeline_and_requires_a_new_request(
    client, session, demo, monkeypatch
):
    pid, source = await scene(client, session)
    original = worker.PROCESSORS["transcribe"]
    calls = []

    def flaky(current_session, job):
        calls.append(job.id)
        if len(calls) == 1:
            raise OSError("synthetic transient failure")
        return original(current_session, job)

    monkeypatch.setitem(worker.PROCESSORS, "transcribe", flaky)
    pipeline = (
        await client.post(f"/projects/{pid}/pipelines", json={"source_asset_id": source})
    ).json()
    state = await drain(client, session, pipeline["id"])
    assert state["status"] == "failed" and current(state)["key"] == "transcribe"
    assert state["gate_reason"]
    job_id = current(state)["job_id"]
    # Transcription by the DEMO provider is not a resumable local stage: it must be rerequested.
    assert (await client.post(f"/jobs/{job_id}/resume")).status_code == 422


@pytest.mark.anyio
async def test_resumable_local_failure_resumes_the_pipeline(client, session, demo, monkeypatch):
    pid, source = await scene(client, session)
    original = worker.PROCESSORS["separate"]
    calls = []

    def flaky(current_session, job):
        calls.append(job.id)
        if len(calls) == 1:
            raise OSError("synthetic transient failure")
        return original(current_session, job)

    monkeypatch.setitem(worker.PROCESSORS, "separate", flaky)
    body = {"source_asset_id": source, "separate_dialogue": True}
    pipeline = (await client.post(f"/projects/{pid}/pipelines", json=body)).json()["id"]
    state = await drain(client, session, pipeline)
    assert state["status"] == "failed"
    resumed = await client.post(f"/jobs/{current(state)['job_id']}/resume")
    assert resumed.status_code == 200, resumed.text
    assert (await client.get(f"/pipelines/{pipeline}")).json()["status"] == "running"
    state = await drain(client, session, pipeline)
    assert state["status"] == "awaiting_review" and current(state)["key"] == "stems_approved"


@pytest.mark.anyio
async def test_cancel_stops_the_running_job_and_keeps_completed_work(client, session, demo):
    pid, source = await scene(client, session)
    body = {"source_asset_id": source, "separate_dialogue": True}
    pipeline = (await client.post(f"/projects/{pid}/pipelines", json=body)).json()
    queued = next(step for step in pipeline["steps_json"] if step["status"] == "running")
    cancelled = (await client.post(f"/pipelines/{pipeline['id']}/cancel")).json()
    assert cancelled["status"] == "cancelled"
    session.expire_all()
    assert session.get(Job, queued["job_id"]).status == "cancelled"
    assert not process_once(session)
    # A new pipeline can start afterwards.
    again = await client.post(f"/projects/{pid}/pipelines", json=body)
    assert again.status_code == 201, again.text


@pytest.mark.anyio
async def test_worker_restart_mid_pipeline_continues_safely(client, session, demo):
    pid, source = await scene(client, session)
    pipeline = (
        await client.post(f"/projects/{pid}/pipelines", json={"source_asset_id": source})
    ).json()
    job = session.get(Job, current(pipeline)["job_id"])
    job.status = "running"  # Simulate a worker that died mid-job.
    session.commit()
    recover_jobs(session)
    session.expire_all()
    assert session.get(Job, job.id).status == "queued"
    state = await drain(client, session, pipeline["id"])
    assert state["status"] == "awaiting_review" and current(state)["key"] == "speakers_assigned"


@pytest.mark.anyio
async def test_paid_step_pauses_until_a_sufficient_budget_is_confirmed(
    client, session, demo, monkeypatch
):
    monkeypatch.setattr(demo, "translator", "sarvam")
    monkeypatch.setattr(demo, "sarvam_api_key", "synthetic-test-only")

    class Recorded:
        def translate(self, text, source_language, target_language):
            return TranslationResult(f"[ml] {text}", "sarvam", "mayura:v1", "request-1")

    monkeypatch.setattr(ProviderRegistry, "translator", lambda *args: Recorded())
    pid, source = await scene(client, session)
    pipeline = (
        await client.post(f"/projects/{pid}/pipelines", json={"source_asset_id": source})
    ).json()
    state = await drain(client, session, pipeline["id"])
    state = await proceed(client, session, pipeline["id"])  # Speakers came from diarization.
    assert state["status"] == "awaiting_review" and current(state)["key"] == "translate"
    assert "Confirm a pipeline budget" in state["gate_reason"]
    assert current(state)["job_id"] is None  # Nothing was submitted or reserved.
    too_low = await client.post(
        f"/pipelines/{pipeline['id']}/continue", json={"confirmed_budget_inr": 0}
    )
    assert too_low.status_code == 200 and too_low.json()["status"] == "awaiting_review"
    state = await proceed(client, session, pipeline["id"], confirmed_budget_inr=5)
    assert current(state)["key"] == "lines_approved"
    translate = session.get(
        Job, next(step for step in state["steps_json"] if step["key"] == "translate")["job_id"]
    )
    assert translate.provider == "sarvam" and translate.estimated_cost_inr > 0
