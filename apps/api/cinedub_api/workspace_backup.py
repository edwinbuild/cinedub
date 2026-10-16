"""Offline SQLite/media snapshots and non-overwriting, quarantined recovery copies."""

import fcntl
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .backup_manifest import (
    BackupFile,
    BackupManifest,
    RestoreReceipt,
    canonical,
    digest,
    inspect_database,
    inventory,
    readonly,
    referenced_files,
    relative_name,
    verify_snapshot,
)
from .workspace_lock import workspace_lease


def new_directory(path, forbidden):
    path = canonical(path)
    if path.exists():
        raise ValueError("Destination already exists; choose a new directory, never overwrite")
    if any(path.is_relative_to(root) or root.is_relative_to(path) for root in forbidden):
        raise ValueError("Destination must be separate from the source workspace/snapshot")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir(mode=0o700)
    return path


def copy_checked(source, target, expected=None):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with Path(source).open("rb") as incoming, target.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
    entry = BackupFile(path="unused", bytes=target.stat().st_size, sha256=digest(target))
    if expected and (entry.bytes != expected.bytes or entry.sha256 != expected.sha256):
        raise ValueError("Copied media changed or does not match its snapshot checksum")
    return entry


def create_snapshot(database, storage, output):
    database, storage = canonical(database), canonical(storage)
    if not database.is_file() or database.is_relative_to(storage):
        raise ValueError("Use an existing SQLite database outside the media storage directory")
    if storage in {Path("/"), Path.home(), Path.cwd()}:
        raise ValueError("Select the media storage directory, not a home or repository root")
    url = "sqlite:///" + str(database)
    with workspace_lease(url, storage, exclusive=True):
        # Also refuse an older worker that predates the shared workspace lease.
        with database.with_name(database.name + ".worker.lock").open("a") as worker:
            try:
                fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Stop the running worker before creating a snapshot") from exc
            with sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=0) as guard:
                guard.execute("BEGIN IMMEDIATE")  # Block other DB writers, allow backup reader.
                paths = inventory(storage)
                if any(p.name == ".env" or p.name.startswith(".env.") for p in paths):
                    raise ValueError("Configuration/secrets do not belong in media snapshots")
                destination = new_directory(output, [storage, database])
                with (
                    readonly(database) as source,
                    sqlite3.connect(destination / "database.sqlite3") as saved,
                ):
                    source.backup(saved)
                entries = [
                    BackupFile(
                        path="database.sqlite3",
                        bytes=(destination / "database.sqlite3").stat().st_size,
                        sha256=digest(destination / "database.sqlite3"),
                    )
                ]
                for path in paths:
                    relative = path.relative_to(storage)
                    entry = copy_checked(path, destination / "storage" / relative)
                    entry.path = "storage/" + relative.as_posix()
                    if digest(path) != entry.sha256:
                        raise ValueError("Source media changed while copying; incomplete snapshot")
                    entries.append(entry)
                (destination / "storage").mkdir(exist_ok=True, mode=0o700)
                if inventory(storage) != paths:
                    raise ValueError("Source media inventory changed; incomplete snapshot")
                for entry in entries[1:]:
                    source_path = storage / Path(entry.path).relative_to("storage")
                    if (
                        source_path.stat().st_size != entry.bytes
                        or digest(source_path) != entry.sha256
                    ):
                        raise ValueError("Source media changed before snapshot completion")
                revision, counts = inspect_database(destination / "database.sqlite3")
                referenced_files(
                    destination / "database.sqlite3", str(storage), {e.path: e for e in entries}
                )
                manifest = BackupManifest(
                    created_at=datetime.now(UTC).isoformat(),
                    schema_revision=revision,
                    original_database=str(database),
                    original_storage=str(storage),
                    files=entries,
                    table_counts=counts,
                )
                # Completion marker is written last. Incomplete directories are never restorable.
                with (destination / "manifest.json").open("x", encoding="utf-8") as handle:
                    handle.write(manifest.model_dump_json(indent=2))
                guard.rollback()
    verify_snapshot(destination)
    return {
        "snapshot": str(destination),
        "schema_revision": revision,
        "files": len(entries),
        "bytes": sum(entry.bytes for entry in entries),
    }


def relocated(value, old_root, new_root):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(old_root):
        raise ValueError("Stored media/checkpoint path is outside the snapshot storage root")
    return str(new_root / path.relative_to(old_root))


def quarantine_restored_database(database, old_root, new_root):
    now = datetime.now(UTC).isoformat()
    held, quarantined = [], []
    with sqlite3.connect(database) as connection:
        for table in ("media_assets", "artifacts"):
            for identifier, path in connection.execute(f"SELECT id,path FROM {table}").fetchall():
                connection.execute(
                    f"UPDATE {table} SET path=? WHERE id=?",
                    (relocated(path, old_root, new_root), identifier),
                )
        for identifier, value in connection.execute(
            "SELECT id,checkpoint_json FROM jobs"
        ).fetchall():
            checkpoint = json.loads(value)
            if "voice_chunks" in checkpoint:
                checkpoint["voice_chunks"] = {
                    line: [relocated(path, old_root, new_root) for path in paths]
                    for line, paths in checkpoint["voice_chunks"].items()
                }
                connection.execute(
                    "UPDATE jobs SET checkpoint_json=? WHERE id=?",
                    (json.dumps(checkpoint, ensure_ascii=False), identifier),
                )
        for identifier, project_id, status, provider, phase in connection.execute(
            "SELECT id,project_id,status,provider,phase FROM jobs "
            "WHERE status IN ('queued','running')"
        ).fetchall():
            held.append({"id": identifier, "status": status, "provider": provider, "phase": phase})
            connection.execute(
                "UPDATE jobs SET status='failed',error_code='restored_job_hold',error_message=?,"
                "retryable=?,finished_at=?,updated_at=? WHERE id=?",
                (
                    "Restored job held for review; local jobs may resume explicitly. "
                    "Check provider usage before creating any new paid request.",
                    provider in {"local", "fake"},
                    now,
                    now,
                    identifier,
                ),
            )
            connection.execute(
                "UPDATE projects SET status='failed',updated_at=? WHERE id=?", (now, project_id)
            )
        clones = {
            row[0]
            for row in connection.execute("SELECT id FROM voice_profiles WHERE voice_kind='clone'")
        }
        for identifier, consent_status in connection.execute(
            "SELECT id,consent_status FROM voice_profiles WHERE voice_kind='clone'"
        ).fetchall():
            if consent_status != "approved":
                continue
            quarantined.append(identifier)
            connection.execute(
                "UPDATE voice_profiles SET consent_status='recovery_hold',version=version+1,"
                "updated_at=? WHERE id=?",
                (now, identifier),
            )
            connection.execute(
                "INSERT INTO consent_records (id,voice_profile_id,status,attested_by,note,"
                "attested_at,scope_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    identifier,
                    "recovery_hold",
                    "CineDub recovery safety gate",
                    "Historical backup cannot establish current permission; "
                    "fresh verification required",
                    now,
                    json.dumps({"reason": "workspace_restore"}),
                    now,
                    now,
                ),
            )
        for speaker_id, profile_id in connection.execute(
            "SELECT id,voice_profile_id FROM speakers"
        ).fetchall():
            if profile_id in clones:
                connection.execute(
                    "UPDATE speakers SET voice_profile_id=NULL,updated_at=? WHERE id=?",
                    (now, speaker_id),
                )
        metadata = {
            row[0]: json.loads(row[1])
            for row in connection.execute("SELECT id,metadata_json FROM artifacts")
        }
        for line_id, candidate_id in connection.execute(
            "SELECT id,selected_candidate_id FROM segments WHERE selected_candidate_id IS NOT NULL"
        ).fetchall():
            profile_id = metadata.get(candidate_id, {}).get("voice", {}).get("profile_id")
            if profile_id in clones:
                connection.execute(
                    "UPDATE segments SET selected_candidate_id=NULL,version=version+1,"
                    "updated_at=? WHERE id=?",
                    (now, line_id),
                )
    return held, quarantined


def restore_snapshot(snapshot, output):
    snapshot = canonical(snapshot)
    manifest = verify_snapshot(snapshot)
    destination = new_directory(output, [snapshot, Path(manifest.original_storage)])
    database, storage = destination / "workspace.sqlite3", destination / "storage"
    storage.mkdir(mode=0o700)
    with workspace_lease("sqlite:///" + str(database), storage, exclusive=True):
        for entry in manifest.files:
            target = database if entry.path == "database.sqlite3" else destination / entry.path
            copy_checked(snapshot / entry.path, target, entry)
        copy_checked(snapshot / "manifest.json", destination / "source-manifest.json")
        held, quarantined = quarantine_restored_database(
            database, Path(manifest.original_storage), storage
        )
        revision, counts = inspect_database(database)
        entries = [
            BackupFile(
                path=path.relative_to(destination).as_posix(),
                bytes=path.stat().st_size,
                sha256=digest(path),
            )
            for path in inventory(destination)
            if path != destination / "workspace.sqlite3.workspace.lock"
        ]
        referenced_files(
            database,
            str(storage),
            {entry.path: entry for entry in entries if entry.path.startswith("storage/")},
        )
        receipt = RestoreReceipt(
            restored_at=datetime.now(UTC).isoformat(),
            schema_revision=revision,
            table_counts=counts,
            source_manifest_sha256=digest(snapshot / "manifest.json"),
            storage_root=str(storage),
            files=entries,
            held_jobs=held,
            quarantined_clone_profiles=quarantined,
        )
        with (destination / "restore-receipt.json").open("x", encoding="utf-8") as handle:
            handle.write(receipt.model_dump_json(indent=2))
        _verify_restored(destination)
    return {
        "restored_workspace": str(destination),
        "database": str(database),
        "storage": str(storage),
        "held_jobs": len(held),
        "quarantined_clones": len(quarantined),
    }


def verify_restored(directory):
    directory = canonical(directory)
    if not (directory / "restore-receipt.json").is_file():
        raise ValueError("Completed recovery receipt is missing")
    with workspace_lease(
        "sqlite:///" + str(directory / "workspace.sqlite3"), directory / "storage", exclusive=True
    ):
        return _verify_restored(directory)


def _verify_restored(directory):
    directory = canonical(directory)
    path = directory / "restore-receipt.json"
    if path.stat().st_size > 32 * 1024**2:
        raise ValueError("Recovery receipt is oversized")
    receipt = RestoreReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    if receipt.storage_root != str(directory / "storage"):
        raise ValueError("Recovery receipt does not match this destination")
    entries = {entry.path: entry for entry in receipt.files}
    if len(entries) != len(receipt.files):
        raise ValueError("Duplicate recovery receipt entry")
    actual = {path.relative_to(directory).as_posix() for path in inventory(directory)}
    actual -= {
        "restore-receipt.json",
        "workspace.sqlite3.workspace.lock",
        "workspace.sqlite3.worker.lock",
    }
    if actual != set(entries):
        raise ValueError("Restored workspace inventory changed")
    for entry in entries.values():
        relative_name(entry.path)
        path = directory / entry.path
        if path.stat().st_size != entry.bytes or digest(path) != entry.sha256:
            raise ValueError("Restored baseline changed; verify current work with a new snapshot")
    revision, counts = inspect_database(directory / "workspace.sqlite3")
    if revision != receipt.schema_revision or counts != receipt.table_counts:
        raise ValueError("Restored database no longer matches its recovery receipt")
    if digest(directory / "source-manifest.json") != receipt.source_manifest_sha256:
        raise ValueError("Recovery source manifest changed")
    referenced_files(directory / "workspace.sqlite3", str(directory / "storage"), entries)
    return {
        "restored_workspace": str(directory),
        "schema_revision": revision,
        "files": len(entries),
    }
