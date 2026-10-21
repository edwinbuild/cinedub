import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager

import httpx
import pytest
from cinedub_api.backup_manifest import digest
from cinedub_api.workspace_backup import create_snapshot, restore_snapshot, verify_restored
from test_workspace_backup import workspace as workspace


def environment(database, storage):
    return {
        **os.environ,
        "PYTHONPATH": "apps/api",
        "CINEDUB_DATABASE_URL": "sqlite:///" + str(database),
        "CINEDUB_STORAGE_ROOT": str(storage),
        "SARVAM_API_KEY": "",
        "CINEDUB_SARVAM_API_KEY": "",
        "CINEDUB_TRANSCRIBER": "fake",
        "CINEDUB_TRANSLATOR": "fake",
        "CINEDUB_VOICE_SYNTHESIZER": "fake",
    }


@contextmanager
def application(database, storage, log):
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]
    with log.open("wb") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "cinedub_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=environment(database, storage),
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(
                            "Recovery test API exited; inspect its synthetic test log"
                        )
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.05)
                else:
                    raise RuntimeError("Recovery test API startup timed out")
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def test_live_api_recovery_preserves_media_edits_and_requires_explicit_local_resume(
    workspace, tmp_path
):
    database, storage, ids = workspace
    original_bytes = (storage / "original.wav").read_bytes()
    with application(database, storage, tmp_path / "source-api.log") as client:
        with pytest.raises(RuntimeError, match="Workspace is in use"):
            create_snapshot(database, storage, tmp_path / "must-not-exist")
        assert not (tmp_path / "must-not-exist").exists()
        detail = client.get(f"/projects/{ids['project']}").json()
        clone = next(a for a in detail["artifacts"] if a["id"] == ids["candidates"][0])
        assert (
            client.get(clone["content_url"]).status_code == 200
        )  # Initially valid fixture consent.
        line = next(s for s in detail["segments"] if s["id"] == ids["lines"][1])
        response = client.patch(
            f"/segments/{line['id']}",
            json={
                "expected_version": line["version"],
                "source_text": "Preserve this actual HTTP edit",
            },
        )
        assert response.status_code == 200, response.text
        brief = client.post(
            f"/projects/{ids['project']}/revisions/{detail['active_revision_id']}/dialogue-brief",
            json={"expected_version": 0, "content": {"scene_summary": "Recovered scene intent"}},
        )
        assert brief.status_code == 200, brief.text
    source_hash = digest(database)
    backup, destination = tmp_path / "snapshot", tmp_path / "recovered"
    create_snapshot(database, storage, backup)
    restore_snapshot(backup, destination)
    verify_restored(destination)
    assert digest(database) == source_hash
    restored_db, restored_media = destination / "workspace.sqlite3", destination / "storage"
    with application(restored_db, restored_media, tmp_path / "restored-api.log") as client:
        detail = client.get(f"/projects/{ids['project']}").json()
        assert detail["dialogue_brief"]["content"]["scene_summary"] == "Recovered scene intent"
        line = next(s for s in detail["segments"] if s["id"] == ids["lines"][1])
        assert line["source_text"] == "Preserve this actual HTTP edit"
        history = client.get(f"/segments/{line['id']}/history").json()
        assert len(history["entries"]) == 1 and history["undo_edit_id"]
        clone = next(a for a in detail["artifacts"] if a["id"] == ids["candidates"][0])
        stock = next(a for a in detail["artifacts"] if a["id"] == ids["candidates"][1])
        assert (
            clone["access_blocked_reason"] and client.get(clone["content_url"]).status_code == 403
        )
        response = client.get(stock["content_url"], headers={"Range": "bytes=0-3"})
        assert response.status_code == 206 and response.content == b"RIFF"
        assert client.get(stock["content_url"]).content == original_bytes
        assert client.post(f"/jobs/{ids['jobs'][1]}/resume").status_code == 422
        log = tmp_path / "restored-worker.log"
        with log.open("wb") as output:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "from cinedub_api.worker import run_worker; run_worker(.05)",
                ],
                env=environment(restored_db, restored_media),
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 15
                while "CineDub worker started" not in log.read_text():
                    assert worker.poll() is None, "Restored worker exited unexpectedly"
                    assert time.monotonic() < deadline, "Restored worker did not start"
                    time.sleep(0.05)
                detail = client.get(f"/projects/{ids['project']}").json()
                assert all(j["status"] == "failed" for j in detail["jobs"])
                with sqlite3.connect(restored_db) as connection:
                    assert connection.execute("SELECT attempts FROM jobs").fetchall() == [
                        (0,),
                        (0,),
                    ]
                response = client.post(f"/jobs/{ids['jobs'][0]}/resume")
                assert response.status_code == 200, response.text
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    detail = client.get(f"/projects/{ids['project']}").json()
                    local = next(j for j in detail["jobs"] if j["id"] == ids["jobs"][0])
                    if local["status"] in {"completed", "failed"}:
                        break
                    time.sleep(0.1)
                assert local["status"] == "completed", local
                paid = next(j for j in detail["jobs"] if j["id"] == ids["jobs"][1])
                assert paid["status"] == "failed"
                with sqlite3.connect(restored_db) as connection:
                    assert (
                        connection.execute(
                            "SELECT attempts FROM jobs WHERE id=?", (paid["id"],)
                        ).fetchone()[0]
                        == 0
                    )
                subtitle = next(a for a in detail["artifacts"] if a["kind"] == "subtitle")
                assert "സാങ്കൽപ്പിക വരി" in client.get(subtitle["content_url"]).text
                assert detail["spent_estimate_inr"] == 5.5
            finally:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=10)
    assert digest(database) == source_hash  # Only the new recovery workspace changed.
