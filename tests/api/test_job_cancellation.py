import pytest
from cinedub_api import worker
from cinedub_api.database import SessionLocal
from cinedub_api.models import Job, Project


def create_job(session, **values):
    project = Project(name="Synthetic cancellation scene", status="processing")
    session.add(project)
    session.flush()
    job = Job(project_id=project.id, **{"stage": "demo_pipeline", **values})
    session.add(job)
    session.commit()
    return job, project


def test_cancelled_claim_never_invokes_processor(session, monkeypatch):
    job, project = create_job(session, cancel_requested=True, retryable=True)
    invoked = []
    monkeypatch.setitem(
        worker.PROCESSORS, "demo_pipeline", lambda *args: invoked.append(True) or {}
    )
    assert worker.process_once(session)
    assert invoked == []
    assert job.status == "cancelled"
    assert job.finished_at is not None
    assert not job.retryable
    assert project.status == "draft"  # Derived: no transcript yet


@pytest.mark.parametrize(
    "provider,remote", [("fake", None), ("local", None), ("sarvam", "known-job")]
)
def test_recovery_finishes_cancelled_work_without_requeue(session, provider, remote):
    job, project = create_job(
        session,
        provider=provider,
        remote_job_id=remote,
        status="running",
        phase="polling",
        cancel_requested=True,
        charged_estimate_inr=2.5,
        estimated_cost_inr=4,
        checkpoint_json={"saved": "checkpoint"},
        retryable=True,
    )
    worker.recover_jobs(session)
    assert job.status == "cancelled"
    assert job.phase == "cancelled" and job.error_code == "cancelled"
    assert job.finished_at is not None and not job.retryable
    assert job.charged_estimate_inr == 2.5
    assert job.remote_job_id == remote and job.checkpoint_json == {"saved": "checkpoint"}
    assert project.status == "draft"  # Derived: no transcript yet
    assert not worker.process_once(session)


@pytest.mark.parametrize(
    "stage,phase,checkpoint",
    [
        ("transcribe", "creating", {}),
        ("translate", "translating", {"pending_chunk": "chunk-1"}),
        ("synthesize", "generating", {"pending_voice": "line-1"}),
        ("register_voice", "uploading", {"pending_registration": True}),
    ],
)
def test_cancelled_uncertain_paid_submission_still_stays_held(session, stage, phase, checkpoint):
    job, project = create_job(
        session,
        provider="sarvam",
        stage=stage,
        phase=phase,
        status="running",
        cancel_requested=True,
        checkpoint_json=checkpoint,
        charged_estimate_inr=2.5,
    )
    worker.recover_jobs(session)
    assert job.status == "failed" and job.error_code == "uncertain_submission"
    assert job.charged_estimate_inr == 2.5
    assert job.cancel_requested and project.status == "failed"
    assert not worker.process_once(session)


@pytest.mark.anyio
async def test_http_cancellation_survives_worker_restart_without_publishing_dialogue(
    client, session
):
    project = (await client.post("/projects", json={"name": "Synthetic restart scene"})).json()
    created = await client.post(
        f"/projects/{project['id']}/jobs", json={"stage": "demo_pipeline", "provider": "fake"}
    )
    assert created.status_code == 202
    claimed = worker.claim_job(session)
    assert claimed.id == created.json()["id"] and claimed.status == "running"
    response = await client.post(f"/jobs/{claimed.id}/cancel")
    assert response.status_code == 200 and response.json()["status"] == "running"
    session.expire_all()
    assert session.get(Job, claimed.id).cancel_requested
    with SessionLocal() as restarted:
        worker.recover_jobs(restarted)
        assert not worker.process_once(restarted)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["segments"] == [] and detail["artifacts"] == []
    saved = next(job for job in detail["jobs"] if job["id"] == claimed.id)
    assert saved["status"] == "cancelled" and saved["charged_estimate_inr"] == 0
    session.expire_all()
    stored = session.get(Job, claimed.id)
    assert stored.finished_at is not None and stored.attempts == 1
    assert detail["status"] == "draft"  # Derived: no transcript yet
