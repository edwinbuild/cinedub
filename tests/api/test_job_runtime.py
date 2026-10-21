"""Error taxonomy, declared resume policy, derived project status and retained warnings."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cinedub_api import worker
from cinedub_api.job_errors import (
    BudgetExhausted,
    InvalidJobInput,
    InvalidJobOutput,
    JobErrorCode,
    StaleInput,
    classify,
)
from cinedub_api.media import MediaError
from cinedub_api.models import Artifact, Job
from cinedub_api.processing import add_warnings
from cinedub_api.stages import STAGES
from cinedub_api.worker import process_once
from test_voice_workflow import prepare_reviewed_scene


def stub(stage="export", provider="local", remote=None, phase="running", checkpoint=None):
    return SimpleNamespace(
        stage=stage,
        provider=provider,
        remote_job_id=remote,
        phase=phase,
        checkpoint_json=checkpoint or {},
        status="failed",
        retryable=True,
        error_code=None,
    )


@pytest.mark.parametrize(
    "exc,provider,code",
    [
        (InvalidJobInput("x"), "local", JobErrorCode.INPUT_INVALID),
        (InvalidJobOutput("x"), "local", JobErrorCode.OUTPUT_INVALID),
        (StaleInput("Source media changed"), "local", JobErrorCode.STALE_INPUT),
        (BudgetExhausted("exhausted"), "sarvam", JobErrorCode.BUDGET_EXCEEDED),
        (TimeoutError(), "local", JobErrorCode.DEADLINE_EXCEEDED),
        (TimeoutError(), "sarvam", JobErrorCode.PROVIDER_TIMEOUT),
        (ConnectionError(), "sarvam", JobErrorCode.PROVIDER_TRANSPORT),
        (httpx.ConnectError("x"), "sarvam", JobErrorCode.PROVIDER_TRANSPORT),
        (MediaError("bad codec"), "local", JobErrorCode.MEDIA_INVALID),
        (OSError("disk"), "local", JobErrorCode.IO_ERROR),
        (ValueError("bad"), "local", JobErrorCode.INVALID_REQUEST),
        (RuntimeError("crash"), "local", JobErrorCode.PROCESS_FAILED),
        (KeyError("x"), "local", JobErrorCode.INTERNAL),
    ],
)
def test_failures_map_to_stable_codes_with_safe_messages(exc, provider, code):
    result, message = classify(exc, stub(provider=provider))
    assert result == code and isinstance(message, str) and message
    if code == JobErrorCode.DEADLINE_EXCEEDED:
        assert "deadline exceeded" in message


def test_pending_registration_is_always_uncertain():
    job = stub(stage="register_voice", provider="sarvam", checkpoint={"pending_registration": 1})
    assert classify(ValueError("x"), job)[0] == JobErrorCode.UNCERTAIN_REGISTRATION


@pytest.mark.parametrize(
    "stage,provider,remote,phase,code,retryable",
    [
        # v0.2 behaviour, now declared per stage.
        ("transcribe", "sarvam", "remote", "creating", JobErrorCode.PROVIDER_TIMEOUT, True),
        ("transcribe", "sarvam", "remote", "polling", JobErrorCode.INVALID_REQUEST, True),
        ("transcribe", "sarvam", None, "creating", JobErrorCode.PROVIDER_TIMEOUT, False),
        ("transcribe", "local", None, "local_inference", JobErrorCode.DEADLINE_EXCEEDED, False),
        ("adapt_dialogue", "local", None, "adapting", JobErrorCode.PROCESS_FAILED, True),
        ("adapt_dialogue", "local", None, "adapting", JobErrorCode.INVALID_REQUEST, False),
        # Idempotent local stages now resume after transient failures.
        ("separate", "local", None, "separating", JobErrorCode.DEADLINE_EXCEEDED, True),
        ("export", "local", None, "writing", JobErrorCode.IO_ERROR, True),
        ("render_mix", "local", None, "mixing", JobErrorCode.STALE_INPUT, False),
        # Paid stages are never resumed without a known remote job.
        ("synthesize", "sarvam", None, "voice", JobErrorCode.PROVIDER_TIMEOUT, False),
        ("translate", "sarvam", None, "translating", JobErrorCode.PROVIDER_TRANSPORT, False),
        ("register_voice", "sarvam", None, "x", JobErrorCode.PROVIDER_TIMEOUT, False),
    ],
)
def test_declared_retry_policy(stage, provider, remote, phase, code, retryable):
    job = stub(stage, provider, remote, phase)
    assert STAGES[stage].retry.retryable_after(job, code) is retryable
    job.retryable = retryable
    assert STAGES[stage].retry.can_resume(job) is retryable


def test_restored_holds_resume_only_for_local_work():
    for provider, allowed in [("local", True), ("fake", True), ("sarvam", False)]:
        job = stub(stage="translate", provider=provider)
        job.error_code = JobErrorCode.RESTORED_JOB_HOLD
        assert STAGES["translate"].retry.can_resume(job) is allowed


@pytest.mark.anyio
async def test_transient_local_failure_resumes_without_duplicate_artifacts(
    client, session, monkeypatch
):
    detail = await prepare_reviewed_scene(client, session)
    original = worker.PROCESSORS["export"]
    attempts = []

    def flaky(current, active):
        attempts.append(active.attempts)
        if len(attempts) == 1:
            raise OSError("synthetic transient read failure")
        return original(current, active)

    monkeypatch.setitem(worker.PROCESSORS, "export", flaky)
    response = await client.post(f"/projects/{detail['id']}/jobs", json={"stage": "export"})
    assert process_once(session)
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.status == "failed" and job.error_code == "io_error" and job.retryable
    assert (await client.get(f"/projects/{detail['id']}")).json()["status"] == "failed"
    resumed = await client.post(f"/jobs/{job.id}/resume")
    assert resumed.status_code == 200 and resumed.json()["status"] == "queued"
    assert (await client.get(f"/projects/{detail['id']}")).json()["status"] == "processing"
    assert process_once(session)
    session.expire_all()
    job = session.get(Job, job.id)
    assert job.status == "completed" and attempts == [1, 2]
    produced = session.query(Artifact).filter_by(job_id=job.id).all()
    assert produced and all(Path(item.path).is_file() for item in produced)
    assert (await client.get(f"/projects/{detail['id']}")).json()["status"] == "ready"
    # A completed job is never resumable.
    assert (await client.post(f"/jobs/{job.id}/resume")).status_code == 422


@pytest.mark.anyio
async def test_status_is_derived_from_jobs_and_timeline(client, session):
    project = (await client.post("/projects", json={"name": "Derived status"})).json()
    assert project["status"] == "draft"
    response = await client.post(
        f"/projects/{project['id']}/jobs", json={"stage": "demo_pipeline", "provider": "fake"}
    )
    assert response.status_code == 202
    assert (await client.get(f"/projects/{project['id']}")).json()["status"] == "processing"
    assert process_once(session)
    assert (await client.get(f"/projects/{project['id']}")).json()["status"] == "review"
    await client.post(f"/projects/{project['id']}/jobs", json={"stage": "export"})
    assert process_once(session)
    assert (await client.get(f"/projects/{project['id']}")).json()["status"] == "ready"


def test_warnings_are_appended_not_replaced():
    job = SimpleNamespace(warnings_json=["first"])
    add_warnings(job, ["second", "first"])
    add_warnings(job, ["third"])
    assert job.warnings_json == ["first", "second", "third"]


def test_worker_has_no_stage_specific_policy_branches():
    source = Path(worker.__file__).read_text()
    assert "job.stage ==" not in source and "stage in {" not in source
    assert 'project.status = "' not in source
