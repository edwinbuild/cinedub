import errno
import sqlite3
from pathlib import Path

import pytest
from cinedub_api import core_processing, worker
from cinedub_api.database import Base, get_session
from cinedub_api.main import app, storage_capacity_failure
from cinedub_api.models import Artifact, Job, Segment, SegmentEdit
from cinedub_api.storage_capacity import (
    STORAGE_MESSAGE,
    StorageCapacityError,
    is_storage_capacity_error,
)
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_dialogue_review import scene


@pytest.fixture
def constrained_database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'capacity.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        with Session(bind=connection, expire_on_commit=False) as session:
            yield connection, session, engine
    engine.dispose()


def cap_database(connection):
    limit = connection.exec_driver_sql("PRAGMA max_page_count").scalar_one()
    pages = connection.exec_driver_sql("PRAGMA page_count").scalar_one()
    assert connection.exec_driver_sql(f"PRAGMA max_page_count={pages}").scalar_one() == pages
    connection.commit()
    return limit


def release_database(connection, limit):
    connection.exec_driver_sql(f"PRAGMA max_page_count={limit}")
    connection.commit()


@pytest.mark.anyio
async def test_actual_sqlite_full_returns_safe_api_error_and_preserves_edits(
    client, constrained_database, caplog
):
    connection, session, engine = constrained_database
    project, _, _ = scene(session)
    line = session.query(Segment).filter_by(project_id=project.id).first()
    line_id, version, original = line.id, line.version, line.translated_text
    session.commit()
    observed = []
    event.listen(
        engine,
        "handle_error",
        lambda context: observed.append(
            getattr(context.original_exception, "sqlite_errorcode", None)
        ),
    )
    limit = cap_database(connection)

    async def isolated_session():
        with Session(bind=connection, expire_on_commit=False) as current:
            yield current

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = isolated_session
    try:
        payload = {
            "expected_version": version,
            "translated_text": "PRIVATE_DRAFT_SENTINEL" + "മ" * 3500,
        }
        response = await client.patch(f"/segments/{line_id}", json=payload)
        assert response.status_code == 507, response.text
        assert sqlite3.SQLITE_FULL in observed
        assert "Free space" in response.json()["detail"]
        assert "PRIVATE_DRAFT_SENTINEL" not in response.text + caplog.text
        session.expire_all()
        saved = session.get(Segment, line_id)
        assert (saved.version, saved.translated_text, saved.status) == (
            version,
            original,
            "approved",
        )
        assert session.query(SegmentEdit).filter_by(segment_id=line_id).count() == 0
        session.rollback()
        release_database(connection, limit)
        response = await client.patch(f"/segments/{line_id}", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["version"] == version + 1
        assert response.json()["status"] == "needs_review"
    finally:
        session.rollback()
        release_database(connection, limit)
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.anyio
async def test_actual_sqlite_full_rolls_back_grouped_edits_and_retries_explicitly(
    client, constrained_database, monkeypatch
):
    from cinedub_api.routes import batch_editing

    connection, session, _ = constrained_database
    project, revision, _ = scene(session)
    lines = (
        session.query(Segment).filter_by(project_id=project.id).order_by(Segment.index).all()[:2]
    )
    original = [(line.id, line.version, line.translated_text) for line in lines]
    project_id, revision_id = project.id, revision.id
    session.commit()
    limit = cap_database(connection)
    completed = []
    apply = batch_editing.apply_line_edit

    def observed(*args, **kwargs):
        result = apply(*args, **kwargs)
        completed.append(result.id)
        return result

    monkeypatch.setattr(batch_editing, "apply_line_edit", observed)

    async def isolated_session():
        with Session(bind=connection, expire_on_commit=False) as current:
            yield current

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = isolated_session
    payload = {
        "revision_id": revision_id,
        "lines": [
            {
                "segment_id": original[0][0],
                "expected_version": original[0][1],
                "translated_text": "Short edit",
            },
            {
                "segment_id": original[1][0],
                "expected_version": original[1][1],
                "translated_text": "മ" * 3500,
            },
        ],
    }
    try:
        response = await client.patch(f"/projects/{project_id}/segments", json=payload)
        assert response.status_code == 507, response.text
        assert completed == [original[0][0]], "First edit must have flushed before capacity failure"
        session.expire_all()
        for line_id, version, translated in original:
            saved = session.get(Segment, line_id)
            assert (saved.version, saved.translated_text) == (version, translated)
        assert session.query(SegmentEdit).count() == 0
        session.rollback()
        release_database(connection, limit)
        response = await client.patch(f"/projects/{project_id}/segments", json=payload)
        assert response.status_code == 200, response.text
        assert len(response.json()["lines"]) == 2
    finally:
        session.rollback()
        release_database(connection, limit)
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("paid", [False, True])
def test_actual_full_at_worker_final_commit_preserves_checkpoints_and_recovers_safely(
    constrained_database, monkeypatch, tmp_path, caplog, paid
):
    connection, session, engine = constrained_database
    project, revision, _ = scene(session)
    line = session.query(Segment).filter_by(project_id=project.id).first()
    before = (line.version, line.translated_text, line.status)
    job = Job(
        project_id=project.id,
        stage="synthesize" if paid else "export",
        provider="sarvam" if paid else "local",
        input_json={
            "revision_id": revision.id,
            "segments": [
                {
                    "id": line.id,
                    "version": line.version,
                    "start_ms": line.start_ms,
                    "end_ms": line.end_ms,
                    "source_text": line.source_text,
                    "translated_text": line.translated_text,
                }
            ],
            # Contract-valid frozen inputs: the worker validates them before processing.
            **(
                {
                    "model": "bulbul:v3",
                    "models": ["bulbul:v3"],
                    "voices": {},
                    "unit_rate_inr": 30,
                    "max_timing_speedup": 1.15,
                }
                if paid
                else {}
            ),
        },
    )
    session.add(job)
    session.commit()
    job_id, line_id = job.id, line.id
    observed = []
    event.listen(
        engine,
        "handle_error",
        lambda context: observed.append(
            getattr(context.original_exception, "sqlite_errorcode", None)
        ),
    )
    calls, limits = [], []
    monkeypatch.setattr(
        core_processing,
        "settings",
        core_processing.settings.model_copy(update={"storage_root": tmp_path / "media"}),
    )

    def processor(current, active):
        calls.append(active.id)
        if paid:
            # Simulated provider boundary only: no external call or actual bill.
            active.checkpoint_json = {"pending_voice": "fixture:0"}
            active.charged_estimate_inr = 0.5
            current.commit()
            output = {"artifact_ids": [], "skipped_changed_lines": []}
        else:
            output = core_processing.process_export(current, active)
        if len(calls) == 1:
            limits.append(cap_database(connection))
            # Oversized but contract-valid, so the failure is the database commit itself.
            oversized = "PRIVATE_OUTPUT_SENTINEL" * 20000
            return {**output, "artifact_ids": [*output["artifact_ids"], oversized]}
        return output

    monkeypatch.setitem(worker.PROCESSORS, job.stage, processor)
    try:
        with pytest.raises(StorageCapacityError) as captured:
            worker.process_once(session)
        assert str(captured.value) == STORAGE_MESSAGE
        assert "PRIVATE_OUTPUT_SENTINEL" not in str(captured.value) + caplog.text
        assert sqlite3.SQLITE_FULL in observed
        session.expire_all()
        stored = session.get(Job, job_id)
        assert stored.status == "running" and stored.output_json == {} and stored.attempts == 1
        saved = session.get(Segment, line_id)
        assert (saved.version, saved.translated_text, saved.status) == before
        artifact = session.query(Artifact).filter_by(job_id=job_id).first()
        retained = (
            (Path(artifact.path).read_bytes(), Path(artifact.path).stat().st_mtime_ns)
            if artifact
            else None
        )
        assert bool(retained) is (not paid)
        session.rollback()
        release_database(connection, limits[0])
        session.close()
        with Session(bind=connection, expire_on_commit=False) as restarted:
            worker.recover_jobs(restarted)
            recovered = restarted.get(Job, job_id)
            if paid:
                assert (
                    recovered.status == "failed" and recovered.error_code == "uncertain_submission"
                )
                assert (
                    recovered.charged_estimate_inr == 0.5
                    and recovered.checkpoint_json["pending_voice"]
                )
                assert not worker.process_once(restarted)
                assert len(calls) == 1
            else:
                assert recovered.status == "queued"
                assert worker.process_once(restarted)
                assert recovered.status == "completed" and recovered.attempts == 2
                artifacts = restarted.query(Artifact).filter_by(job_id=job_id).all()
                assert len(artifacts) == 1 and recovered.output_json["artifact_ids"] == [
                    artifacts[0].id
                ]
                assert (
                    Path(artifacts[0].path).read_bytes(),
                    Path(artifacts[0].path).stat().st_mtime_ns,
                ) == retained
            assert (
                restarted.connection().exec_driver_sql("PRAGMA integrity_check").scalar_one()
                == "ok"
            )
    finally:
        session.rollback()
        if limits:
            release_database(connection, limits[0])


@pytest.mark.parametrize("number", [errno.ENOSPC, errno.EDQUOT])
def test_worker_stops_on_media_capacity_without_recording_false_success(
    constrained_database, monkeypatch, number
):
    _, session, _ = constrained_database
    project, revision, _ = scene(session)
    job = Job(
        project_id=project.id,
        stage="export",
        provider="local",
        input_json={"revision_id": revision.id, "segments": []},
    )
    session.add(job)
    session.commit()

    def processor(*args):
        raise OSError(number, "PRIVATE_MEDIA_PATH")

    monkeypatch.setitem(worker.PROCESSORS, "export", processor)
    with pytest.raises(StorageCapacityError, match="Storage capacity exhausted"):
        worker.process_once(session)
    session.expire_all()
    assert session.get(Job, job.id).status == "running"
    assert not session.query(Artifact).filter_by(job_id=job.id).count()


def test_worker_capacity_exit_is_nonzero_and_does_not_log_sensitive_exception(monkeypatch, caplog):
    def full(*args):
        raise OSError(errno.ENOSPC, "PRIVATE_MEDIA_PATH")

    monkeypatch.setattr(worker, "_run_worker", full)
    with pytest.raises(SystemExit) as captured:
        worker.run_worker()
    assert captured.value.code == 1
    assert "storage_capacity_exhausted" in caplog.text
    assert "PRIVATE_MEDIA_PATH" not in caplog.text


def test_capacity_classifier_requires_real_codes_not_strings():
    assert is_storage_capacity_error(OSError(errno.ENOSPC, "example"))
    assert is_storage_capacity_error(OSError(errno.EDQUOT, "example"))
    assert not is_storage_capacity_error(PermissionError(errno.EACCES, "disk full"))
    assert not is_storage_capacity_error(RuntimeError("database or disk is full"))
    error = sqlite3.OperationalError("example")
    error.sqlite_errorcode = sqlite3.SQLITE_FULL
    assert is_storage_capacity_error(error)
    assert is_storage_capacity_error(OperationalError("PRIVATE_SQL", {"secret": "PRIVATE"}, error))
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    assert not is_storage_capacity_error(error)


@pytest.mark.anyio
async def test_non_capacity_errors_keep_existing_failure_behavior():
    error = PermissionError(errno.EACCES, "Not a capacity failure")
    with pytest.raises(PermissionError) as captured:
        await storage_capacity_failure(None, error)
    assert captured.value is error
