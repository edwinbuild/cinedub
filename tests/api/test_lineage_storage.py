"""Storage boundary and pre-lineage database upgrade/backfill."""

import json
import sqlite3

import pytest
from cinedub_api.storage import LocalStorage
from test_migrations import migrate


def test_storage_keys_are_root_relative_and_never_escape(tmp_path):
    store = LocalStorage(tmp_path / "root")
    directory = store.job_dir("project", "voice", "job", "line")
    assert (
        directory.is_dir() and store.key_for(directory / "a.wav") == "project/voice/job/line/a.wav"
    )
    assert store.resolve("project/voice/job/line/a.wav") == directory / "a.wav"
    assert store.key_for(tmp_path / "outside.wav") is None
    for key in ("../outside.wav", "/etc/passwd", "project/../../outside", "", "a\\b"):
        with pytest.raises(ValueError):
            store.resolve(key)
    for part in ("..", "../.."):
        with pytest.raises(ValueError):
            store.job_path("project", part, part)
    assert not store.job_path("p", "area", "job").exists()  # Provenance checks never create.
    (directory / "a.wav").write_bytes(b"x" * 10)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"x")
    assert store.readable(directory / "a.wav") and not store.readable(outside)
    assert store.usage("project") == 10 and store.usage() == 10
    store.delete_project("project")
    assert not (tmp_path / "root" / "project").exists()
    for bad in ("", "..", "a/b"):
        with pytest.raises(ValueError):
            store.delete_project(bad)


def test_v02_database_upgrades_and_backfills_lineage(tmp_path):
    database = tmp_path / "v02.db"
    storage_root = tmp_path / "storage"
    environment = migrate(database, "0010_speaker_reuse")
    source = storage_root / "p1" / "source" / "a1.wav"
    stem = storage_root / "p1" / "separation" / "j1" / "music.wav"
    preview = storage_root / "p1" / "separation" / "j1" / "music-preview.wav"
    for path, content in [(source, b"source"), (stem, b"stem-bytes"), (preview, b"preview")]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    with sqlite3.connect(database) as connection:
        insert(connection, "projects", id="p1", name="v0.2", status="review")
        insert(
            connection,
            "media_assets",
            id="a1",
            project_id="p1",
            kind="source",
            path=str(source),
            filename="a.wav",
            media_type="audio/wav",
            duration_ms=1000,
            metadata_json=json.dumps({"sha256": "f" * 64}),
        )
        insert(
            connection,
            "jobs",
            id="j1",
            project_id="p1",
            stage="separate",
            status="completed",
            provider="local",
            input_json=json.dumps({"source_asset_id": "a1"}),
        )
        for identifier, path, metadata in [
            ("m1", stem, {"stem": "music", "sha256": "recorded-hash"}),
            ("v1", preview, {"stem": "music", "master_artifact_id": "m1"}),
            ("gone", storage_root / "p1" / "missing.wav", {}),
        ]:
            insert(
                connection,
                "artifacts",
                id=identifier,
                project_id="p1",
                job_id="j1",
                kind="stem",
                path=str(path),
                filename="f.wav",
                media_type="audio/wav",
                metadata_json=json.dumps(metadata),
            )
    migrate(database, "head")
    import subprocess
    import sys

    from test_migrations import ROOT

    subprocess.run(
        [
            sys.executable,
            "-c",
            "from cinedub_api.database import SessionLocal\n"
            "from cinedub_api.lineage import backfill_lineage\n"
            "with SessionLocal() as session:\n"
            "    print(backfill_lineage(session))\n"
            "    print(backfill_lineage(session))",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    with sqlite3.connect(database) as connection:
        rows = {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT id,sha256,size_bytes,storage_key,lineage_version FROM artifacts"
            )
        }
        edges = set(
            connection.execute(
                "SELECT artifact_id,role,input_artifact_id,input_asset_id FROM artifact_inputs"
            )
        )
    # Recorded hashes are kept; unrecorded existing files are hashed; missing files stay null.
    assert rows["m1"] == ("recorded-hash", 10, "p1/separation/j1/music.wav", 1)
    assert rows["v1"][1:] == (7, "p1/separation/j1/music-preview.wav", 1) and rows["v1"][0]
    assert rows["gone"] == (None, None, "p1/missing.wav", 1)
    assert ("v1", "derived_from", "m1", None) in edges
    assert ("m1", "source", None, "a1") in edges
    assert len([edge for edge in edges if edge[0] == "m1"]) == 1  # Idempotent backfill.


def insert(connection, table, **values):
    """Insert into the historical schema, filling other required columns with neutral values."""
    for _, name, kind, required, default, _ in connection.execute(f"PRAGMA table_info({table})"):
        if name in values or not required or default is not None:
            continue
        kind = kind.upper()
        values[name] = (
            "2026-10-01 00:00:00"
            if "DATETIME" in kind
            else "{}"
            if "JSON" in kind
            else 0
            if kind.startswith(("INT", "FLOAT", "BOOL", "NUMERIC", "REAL", "BIGINT"))
            else ""
        )
    columns = ",".join(values)
    marks = ",".join("?" for _ in values)
    connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values()))


def test_only_the_storage_module_builds_media_paths_from_the_root():
    import re
    from pathlib import Path

    import cinedub_api

    package = Path(cinedub_api.__file__).parent
    offenders = []
    for module in package.rglob("*.py"):
        if module.name == "storage.py":
            continue
        for match in re.finditer(r"storage_root\s*/\s*(\S+)", module.read_text()):
            # Workspace/worker lock files are infrastructure, not media.
            if not match.group(1).startswith('".'):
                offenders.append(f"{module.name}: {match.group(0)}")
    assert offenders == []
