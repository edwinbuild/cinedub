"""API structure, idempotent POSTs, typed events, project deletion and storage cleanup."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cinedub_api import main
from cinedub_api.config import get_settings
from cinedub_api.events import project_event_stream
from cinedub_api.models import Artifact, Job, MediaAsset, Speaker, VoiceProfile
from cinedub_api.schemas import ProjectEvent
from cinedub_api.storage import LocalStorage
from cinedub_api.storage_cleanup import apply_cleanup, plan_cleanup
from cinedub_api.worker import process_once
from pydantic import TypeAdapter
from test_voice_workflow import wav

EVENTS = TypeAdapter(ProjectEvent)


def test_main_only_wires_the_application():
    source = Path(main.__file__).read_text()
    assert len(source.splitlines()) < 120 and "@app.get" not in source and "@app.post" not in source
    routes = {
        (method.upper(), path)
        for path, operations in main.app.openapi()["paths"].items()
        for method in operations
    }
    for expected in [
        ("GET", "/health"),
        ("POST", "/projects/{project_id}/assets"),
        ("POST", "/projects/{project_id}/jobs"),
        ("DELETE", "/projects/{project_id}"),
        ("GET", "/diagnostics/storage"),
        ("GET", "/projects/{project_id}/events"),
        ("GET", "/artifacts/{artifact_id}/lineage"),
        ("POST", "/pipelines/{pipeline_id}/continue"),
    ]:
        assert expected in routes, expected


async def project_with_scene(client, session, name="Structure"):
    project = (await client.post("/projects", json={"name": name})).json()
    asset = (
        await client.post(
            f"/projects/{project['id']}/assets",
            files={"file": ("scene.wav", wav(2), "audio/wav")},
        )
    ).json()
    assert process_once(session)
    return project, asset


@pytest.mark.anyio
async def test_retried_posts_replay_the_first_response(client, session):
    project, asset = await project_with_scene(client, session)
    body = {"stage": "transcribe", "source_asset_id": asset["id"], "force_new": True}
    headers = {"Idempotency-Key": "transcribe-once"}
    first = await client.post(f"/projects/{project['id']}/jobs", json=body, headers=headers)
    again = await client.post(f"/projects/{project['id']}/jobs", json=body, headers=headers)
    assert first.status_code == again.status_code == 202
    assert first.json()["id"] == again.json()["id"]
    assert session.query(Job).filter_by(project_id=project["id"], stage="transcribe").count() == 1
    conflict = await client.post(
        f"/projects/{project['id']}/jobs",
        json={**body, "num_speakers": 2},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert (
        await client.post(
            f"/projects/{project['id']}/jobs", json=body, headers={"Idempotency-Key": ""}
        )
    ).status_code == 422
    assert process_once(session)

    upload = {"file": ("again.wav", wav(1), "audio/wav")}
    one = await client.post(
        f"/projects/{project['id']}/assets", files=upload, headers={"Idempotency-Key": "u1"}
    )
    two = await client.post(
        f"/projects/{project['id']}/assets", files=upload, headers={"Idempotency-Key": "u1"}
    )
    assert one.status_code == two.status_code == 201 and one.json()["id"] == two.json()["id"]
    assert session.query(MediaAsset).filter_by(project_id=project["id"]).count() == 2
    uploads = list((get_settings().storage_root / project["id"] / "source").iterdir())
    assert len(uploads) == 2  # The replayed upload's bytes were not kept twice.


@pytest.mark.anyio
async def test_event_stream_sends_typed_changes_only(client, session):
    project, asset = await project_with_scene(client, session)
    received, polls = [], {"count": 0}

    async def disconnected():
        polls["count"] += 1
        if polls["count"] == 2:
            # Between polls: queue a job; the next poll must report only that change.
            await client.post(
                f"/projects/{project['id']}/jobs",
                json={"stage": "transcribe", "source_asset_id": asset["id"], "force_new": True},
            )
        return polls["count"] > 3

    async for chunk in project_event_stream(
        project["id"], disconnected, poll_seconds=0, heartbeat_seconds=0
    ):
        received.append(chunk)
    events = []
    for chunk in received:
        if chunk.startswith(":"):
            continue
        lines = dict(line.split(": ", 1) for line in chunk.strip().split("\n"))
        payload = EVENTS.validate_python(json.loads(lines["data"]))
        assert lines["event"] == payload.type
        events.append((int(lines["id"]), payload))
    ids = [identifier for identifier, _ in events]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    types = [payload.type for _, payload in events]
    # Initial snapshot, then exactly the queued job and the resulting status change.
    assert types[:4] == ["job", "project", "timeline", "artifact"]
    later = [payload for _, payload in events[4:]]
    assert [item.type for item in later] == ["job", "project"]
    assert later[0].job.stage == "transcribe" and later[1].status == "processing"
    assert any(chunk.startswith(": keepalive") for chunk in received)


@pytest.mark.anyio
async def test_project_deletion_is_confirmed_guarded_and_complete(client, session):
    keep, _ = await project_with_scene(client, session, "Keep me")
    project, asset = await project_with_scene(client, session, "Delete me")
    url = f"/projects/{project['id']}"
    assert (await client.delete(url, params={"confirm": "wrong"})).status_code == 422
    job = (
        await client.post(
            f"/projects/{project['id']}/jobs",
            json={"stage": "transcribe", "source_asset_id": asset["id"]},
        )
    ).json()
    assert (await client.delete(url, params={"confirm": "Delete me"})).status_code == 409
    assert process_once(session)
    speaker = session.query(Speaker).filter_by(project_id=project["id"]).first()
    clone = VoiceProfile(
        project_id=project["id"],
        speaker_id=speaker.id,
        display_name="Actor",
        provider="sarvam",
        voice_kind="clone",
        consent_status="revoked",
        provider_voice_id="remote-voice",
    )
    session.add(clone)
    session.commit()
    blocked = await client.delete(url, params={"confirm": "Delete me"})
    assert blocked.status_code == 409 and "provider deletion" in blocked.text
    clone.provider_voice_id = None  # Provider deletion completed.
    session.commit()
    storage_dir = get_settings().storage_root / project["id"]
    assert storage_dir.is_dir()
    deleted = await client.delete(url, params={"confirm": "Delete me"})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_rows"]["jobs"] >= 2
    assert (await client.get(url)).status_code == 404
    session.expire_all()
    assert not session.get(Job, job["id"]) and not storage_dir.exists()
    assert not session.query(Artifact).filter_by(project_id=project["id"]).count()
    assert (await client.get(f"/projects/{keep['id']}")).status_code == 200
    assert (get_settings().storage_root / keep["id"]).is_dir()


@pytest.mark.anyio
async def test_cleanup_reports_by_default_and_never_touches_needed_files(client, session, tmp_path):
    project = (await client.post("/projects", json={"name": "Cleanup"})).json()
    store = LocalStorage(tmp_path / "root")
    uploads = store.upload_dir(project["id"])
    kept = uploads / "kept.wav"
    kept.write_bytes(b"k")
    session.add(
        MediaAsset(
            project_id=project["id"],
            kind="source",
            path=str(kept),
            filename="kept.wav",
            media_type="audio/wav",
        )
    )
    old = time.time() - 30 * 86400
    stray = uploads / "abandoned.wav"
    stray.write_bytes(b"x" * 100)
    os.utime(stray, (old, old))
    fresh = uploads / "uploading.wav"
    fresh.write_bytes(b"y")
    jobs = {
        status: Job(
            project_id=project["id"],
            stage="separate",
            provider="fake",
            status=status,
            retryable=status == "failed",
            finished_at=datetime.now(UTC) - timedelta(days=30),
        )
        for status in ("cancelled", "failed", "completed")
    }
    session.add_all(jobs.values())
    session.commit()
    for job in jobs.values():
        (store.job_dir(project["id"], "separation", job.id) / "partial.f32").write_bytes(b"z")
    completed_raw = store.job_dir(project["id"], "voice", jobs["completed"].id, "line") / "raw.wav"
    completed_raw.write_bytes(b"provenance")
    leftover = store.root / "0b3c8b2e-5d34-4c2f-9a50-3f8e1d1a2b3c" / "source"
    leftover.mkdir(parents=True)
    (leftover / "a.wav").write_bytes(b"q")
    (store.root / "backups").mkdir()
    (store.root / ".workspace.lock").write_text("")

    report = plan_cleanup(session, store)
    assert report.orphaned_files == [stray.resolve()]
    assert [path.name for path in report.stale_job_directories] == [jobs["cancelled"].id]
    assert [path.name for path in report.orphaned_project_directories] == [
        "0b3c8b2e-5d34-4c2f-9a50-3f8e1d1a2b3c"
    ]
    assert report.reclaimable_bytes == 100 + 1 + 1 and stray.exists()  # Dry run.
    apply_cleanup(store, report)
    assert not stray.exists() and fresh.exists() and kept.exists()
    assert not leftover.parent.exists()
    assert not store.job_path(project["id"], "separation", jobs["cancelled"].id).exists()
    for status in ("failed", "completed"):  # Resumable and completed work is kept whole.
        assert store.job_path(project["id"], "separation", jobs[status].id).exists()
    assert completed_raw.exists()
    assert (store.root / "backups").is_dir() and (store.root / ".workspace.lock").exists()
    usage = (await client.get("/diagnostics/storage")).json()
    assert usage["root_bytes"] >= 0 and usage["free_bytes"] > 0
