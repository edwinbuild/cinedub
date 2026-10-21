import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time

import pytest
from cinedub_api.backup_manifest import digest, verify_snapshot
from cinedub_api.jobs import prepare_job
from cinedub_api.models import (
    Artifact,
    ConsentRecord,
    Job,
    MediaAsset,
    Project,
    Segment,
    Speaker,
    TimelineRevision,
    VoiceProfile,
)
from cinedub_api.schemas import JobCreate
from cinedub_api.workspace_backup import create_snapshot, restore_snapshot, verify_restored
from cinedub_api.workspace_lock import workspace_lease
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_migrations import migrate
from test_timeline import synthetic_wav


@pytest.fixture
def workspace(tmp_path):
    database, storage = tmp_path / "source.db", tmp_path / "media"
    storage.mkdir()
    migrate(database, "head")
    source = storage / "original.wav"
    source.write_bytes(synthetic_wav())
    part = storage / "inflight-part.wav"
    part.write_bytes(synthetic_wav(1))
    engine = create_engine("sqlite:///" + str(database))
    with Session(engine) as session:
        project = Project(name="Original synthetic recovery workspace")
        session.add(project)
        session.flush()
        asset = MediaAsset(
            project_id=project.id,
            kind="audio",
            path=str(source),
            filename=source.name,
            media_type="audio/wav",
            duration_ms=2000,
            metadata_json={"sha256": digest(source)},
        )
        session.add(asset)
        session.flush()
        revision = TimelineRevision(
            project_id=project.id,
            source_asset_id=asset.id,
            provider="fake",
            model="recovery-fixture",
        )
        session.add(revision)
        session.flush()
        project.active_revision_id = revision.id
        profiles, candidates, lines = [], [], []
        for index, kind in enumerate(["clone", "preset"]):
            speaker = Speaker(
                project_id=project.id,
                revision_id=revision.id,
                label=f"synthetic-{index}",
                display_name=f"Fixture {index}",
            )
            session.add(speaker)
            session.flush()
            profile = VoiceProfile(
                project_id=project.id,
                speaker_id=speaker.id,
                display_name=f"Synthetic {kind}",
                provider="fake",
                provider_voice_id=f"fixture-{kind}",
                voice_kind=kind,
                consent_status="approved" if kind == "clone" else "not_required",
                registration_status="ready",
                reference_asset_id=asset.id if kind == "clone" else None,
            )
            session.add(profile)
            session.flush()
            speaker.voice_profile_id = profile.id
            if kind == "clone":
                session.add(
                    ConsentRecord(
                        voice_profile_id=profile.id,
                        status="approved",
                        attested_by="Synthetic fixture",
                        note="No actor voice or real provider was used",
                        scope_json={
                            "terms_version": "cinedub-project-clone-v1",
                            "project_id": project.id,
                            "provider": "fake",
                            "speaker_id": speaker.id,
                            "reference_asset_id": asset.id,
                            "allows_provider_upload": True,
                            "clean_single_speaker": True,
                            "rights_holder": "Synthetic fixture",
                        },
                    )
                )
            candidate = Artifact(
                project_id=project.id,
                kind="dialogue_candidate",
                path=str(source),
                filename="synthetic.wav",
                media_type="audio/wav",
                metadata_json={"sha256": digest(source), "voice": {"profile_id": profile.id}},
            )
            session.add(candidate)
            session.flush()
            line = Segment(
                project_id=project.id,
                revision_id=revision.id,
                speaker_id=speaker.id,
                index=index,
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                source_text=str(storage / "keep-this-literal-text"),
                translated_text="സാങ്കൽപ്പിക വരി",
                status="approved",
                selected_candidate_id=candidate.id,
            )
            session.add(line)
            session.flush()
            profiles.append(profile.id)
            candidates.append(candidate.id)
            lines.append(line.id)
        _, export_inputs, _ = prepare_job(session, project, JobCreate(stage="export"))
        local = Job(
            project_id=project.id,
            provider="fake",
            stage="export",
            status="queued",
            input_json=export_inputs,
            checkpoint_json={"voice_chunks": {lines[0]: [str(part)]}},
            charged_estimate_inr=2.5,
        )
        paid = Job(
            project_id=project.id,
            provider="sarvam",
            stage="translate",
            status="running",
            phase="translating",
            checkpoint_json={"pending_chunk": "uncertain"},
            charged_estimate_inr=3.0,
        )
        session.add_all([local, paid])
        session.commit()
        identities = {
            "project": project.id,
            "profiles": profiles,
            "candidates": candidates,
            "lines": lines,
            "jobs": [local.id, paid.id],
        }
    engine.dispose()
    return database, storage, identities


def test_snapshot_and_relocated_restore_preserve_bytes_history_and_quarantine(workspace, tmp_path):
    database, storage, ids = workspace
    before = digest(database)
    snapshot = tmp_path / "backup"
    result = create_snapshot(database, storage, snapshot)
    assert result["files"] == 3 and digest(database) == before
    assert snapshot.stat().st_mode & 0o777 == 0o700
    verify_snapshot(snapshot)
    destination = tmp_path / "recovery"
    result = restore_snapshot(snapshot, destination)
    assert result["held_jobs"] == 2 and result["quarantined_clones"] == 1
    verify_restored(destination)
    assert digest(database) == before and digest(storage / "original.wav") == digest(
        destination / "storage/original.wav"
    )
    with sqlite3.connect(destination / "workspace.sqlite3") as connection:
        statuses = connection.execute(
            "SELECT status,error_code,retryable FROM jobs ORDER BY provider"
        ).fetchall()
        assert statuses == [("failed", "restored_job_hold", 1), ("failed", "restored_job_hold", 0)]
        assert connection.execute("SELECT SUM(charged_estimate_inr) FROM jobs").fetchone()[0] == 5.5
        clone = connection.execute(
            "SELECT consent_status,provider_voice_id FROM voice_profiles WHERE id=?",
            (ids["profiles"][0],),
        ).fetchone()
        assert clone == ("recovery_hold", "fixture-clone")
        assert connection.execute(
            "SELECT status FROM consent_records ORDER BY created_at"
        ).fetchall() == [("approved",), ("recovery_hold",)]
        assert (
            connection.execute(
                "SELECT selected_candidate_id FROM segments WHERE id=?", (ids["lines"][0],)
            ).fetchone()[0]
            is None
        )
        assert (
            connection.execute(
                "SELECT selected_candidate_id FROM segments WHERE id=?", (ids["lines"][1],)
            ).fetchone()[0]
            == ids["candidates"][1]
        )
        checkpoint, request = connection.execute(
            "SELECT checkpoint_json,input_json FROM jobs WHERE id=?", (ids["jobs"][0],)
        ).fetchone()
        assert json.loads(checkpoint)["voice_chunks"][ids["lines"][0]] == [
            str(destination / "storage/inflight-part.wav")
        ]
        assert json.loads(request)["segments"][0]["source_text"] == str(
            storage / "keep-this-literal-text"
        )
    assert not (snapshot / ".env").exists()


@pytest.mark.parametrize("mutation", ["media", "database", "extra", "missing", "path", "symlink"])
def test_tampered_or_escaping_snapshot_is_refused_before_restore(workspace, tmp_path, mutation):
    database, storage, _ = workspace
    snapshot = tmp_path / "backup"
    create_snapshot(database, storage, snapshot)
    if mutation == "media":
        (snapshot / "storage/original.wav").write_bytes(b"changed")
    elif mutation == "database":
        with sqlite3.connect(snapshot / "database.sqlite3") as connection:
            connection.execute("UPDATE projects SET name='Changed'")
    elif mutation == "extra":
        (snapshot / "unexpected").write_bytes(b"not listed")
    elif mutation == "missing":
        (snapshot / "storage/original.wav").unlink()
    elif mutation == "path":
        manifest = json.loads((snapshot / "manifest.json").read_text())
        manifest["files"][0]["path"] = "../outside"
        (snapshot / "manifest.json").write_text(json.dumps(manifest))
    else:
        (snapshot / "escape").symlink_to(storage, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        restore_snapshot(snapshot, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()


def test_running_workspace_refuses_snapshot_and_offline_lock_refuses_start(workspace, tmp_path):
    database, storage, _ = workspace
    url = "sqlite:///" + str(database)
    with workspace_lease(url, storage):
        with pytest.raises(RuntimeError, match="Workspace is in use"):
            create_snapshot(database, storage, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
    with workspace_lease(url, storage, exclusive=True):
        with pytest.raises(RuntimeError, match="Workspace is in use"):
            with workspace_lease(url, storage):
                pytest.fail("API/worker must not start during an offline snapshot")


def test_existing_destinations_and_missing_references_never_overwrite(workspace, tmp_path):
    database, storage, _ = workspace
    existing = tmp_path / "owned"
    existing.mkdir()
    marker = existing / "keep"
    marker.write_text("User owned")
    with pytest.raises(ValueError, match="already exists"):
        create_snapshot(database, storage, existing)
    assert marker.read_text() == "User owned"
    snapshot = tmp_path / "backup"
    create_snapshot(database, storage, snapshot)
    with pytest.raises(ValueError, match="already exists"):
        restore_snapshot(snapshot, existing)
    (storage / "original.wav").unlink()
    with pytest.raises(ValueError, match="missing a referenced"):
        create_snapshot(database, storage, tmp_path / "incomplete")
    assert not (tmp_path / "incomplete/manifest.json").exists()


def test_cli_and_imports_do_not_initialize_app_database_or_expose_keys(workspace, tmp_path):
    database, storage, _ = workspace
    environment = {**os.environ, "PYTHONPATH": "apps/api", "SARVAM_API_KEY": "synthetic-secret"}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/workspace-backup.py",
            "create",
            "--database",
            str(database),
            "--storage",
            str(storage),
            "--output",
            str(tmp_path / "cli-backup"),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert json.loads(result.stdout)["files"] == 3
    assert "synthetic-secret" not in result.stdout + result.stderr
    code = (
        "import sys;import cinedub_api.workspace_backup;"
        "from cinedub_api.config import get_settings;"
        "assert 'cinedub_api.database' not in sys.modules;"
        "assert get_settings.cache_info().currsize == 0"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )


def test_orphan_native_descendant_keeps_workspace_and_worker_locked(tmp_path):
    database, storage = tmp_path / "source.db", tmp_path / "media"
    worker_lock = database.with_name(database.name + ".worker.lock")
    ready = tmp_path / "ready"
    grandchild = (
        f"from pathlib import Path; import time; Path({str(ready)!r}).touch(); time.sleep(30)"
    )
    child = (
        "import subprocess, sys; from cinedub_api.workspace_lock import child_process_options; "
        f"p=subprocess.Popen([sys.executable, '-c', {grandchild!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **child_process_options()); "
        "print(p.pid, flush=True)"
    )
    parent = (
        "import fcntl, subprocess, sys; from pathlib import Path; "
        "from cinedub_api.workspace_lock import workspace_lease, inherit_lease, "
        "child_process_options, child_lease_environment; "
        f"lease=workspace_lease({'sqlite:///' + str(database)!r}, Path({str(storage)!r})); "
        "lease.__enter__(); "
        f"lock=open({str(worker_lock)!r}, 'a'); fcntl.flock(lock, fcntl.LOCK_EX); "
        "inherit=inherit_lease(lock.fileno()); inherit.__enter__(); "
        f"subprocess.run([sys.executable, '-c', {child!r}], "
        "env={'PYTHONPATH':'apps/api', **child_lease_environment()}, "
        "check=True, **child_process_options())"
    )
    result = subprocess.run(
        [sys.executable, "-c", parent],
        env={**os.environ, "PYTHONPATH": "apps/api"},
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    descendant_pid = int(result.stdout.strip())
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        with pytest.raises(RuntimeError, match="Workspace is in use"):
            with workspace_lease("sqlite:///" + str(database), storage, exclusive=True):
                pytest.fail("Orphan media writer must prevent offline backup")
        with worker_lock.open("a") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.kill(descendant_pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while True:
        try:
            with workspace_lease("sqlite:///" + str(database), storage, exclusive=True):
                break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)
    with worker_lock.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
