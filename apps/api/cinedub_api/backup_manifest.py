"""Versioned offline snapshot format and strict filesystem/database verification."""

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path, PurePosixPath

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict, Field


class BackupFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format_version: int = Field(default=1, ge=1, le=1)
    created_at: str
    schema_revision: str
    original_database: str
    original_storage: str
    files: list[BackupFile] = Field(min_length=1, max_length=50000)
    table_counts: dict[str, int]


class RestoreReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format_version: int = Field(default=1, ge=1, le=1)
    restored_at: str
    schema_revision: str
    table_counts: dict[str, int]
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    storage_root: str
    files: list[BackupFile] = Field(min_length=2, max_length=50002)
    held_jobs: list[dict[str, str]]
    quarantined_clone_profiles: list[str]


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def canonical(path):
    path = Path(os.path.abspath(path))
    if path.resolve() != path:
        raise ValueError("Symlinked workspace or backup paths are not supported")
    return path


def inventory(root):
    root = canonical(root)
    if not root.is_dir():
        raise ValueError("Media/backup directory is unavailable")
    result = []
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError("Snapshots reject symlinks and non-regular files")
        for name in sorted(files):
            result.append(Path(directory) / name)
    if len(result) > 50000:
        raise ValueError("Snapshot exceeds the 50000-file manifest limit")
    return sorted(result)


def relative_name(value):
    path = PurePosixPath(value)
    if not value or "\\" in value or "\x00" in value or path.is_absolute() or ".." in path.parts:
        raise ValueError("Invalid snapshot file path")
    if path.as_posix() != value or value == ".":
        raise ValueError("Snapshot file paths must be normalized and relative")
    return path


def readonly(database):
    connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def current_schema():
    root = Path(__file__).resolve().parents[3]
    config = Config()
    config.set_main_option("script_location", str(root / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


def inspect_database(database):
    with readonly(database) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite foreign-key check failed")
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        if revision != [(current_schema(),)]:
            raise ValueError("Snapshot schema does not match this checkout; use matching code")
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        # Identifiers come from the database, so quote even names in a trusted snapshot.
        counts = {
            name: connection.execute(
                'SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"'
            ).fetchone()[0]
            for name in names
        }
    return revision[0][0], counts


def referenced_files(database, original_storage, entries):
    root = Path(original_storage)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("Snapshot source storage must be an absolute normalized path")
    with readonly(database) as connection:
        for table in ("media_assets", "artifacts"):
            for _identifier, value, metadata in connection.execute(
                f"SELECT id,path,metadata_json FROM {table}"
            ):
                path = Path(value)
                if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(root):
                    raise ValueError("Database media reference escapes the captured storage root")
                name = "storage/" + path.relative_to(root).as_posix()
                if name not in entries:
                    raise ValueError("Snapshot is missing a referenced media file")
                saved_hash = json.loads(metadata).get("sha256")
                if saved_hash and saved_hash != entries[name].sha256:
                    raise ValueError("Media bytes do not match their saved artifact provenance")


def verify_snapshot(directory):
    directory = canonical(directory)
    paths = inventory(directory)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 32 * 1024**2:
        raise ValueError("Snapshot completion manifest is missing or oversized")
    manifest = BackupManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    entries = {}
    for entry in manifest.files:
        name = relative_name(entry.path).as_posix()
        if name != "database.sqlite3" and not name.startswith("storage/"):
            raise ValueError("Unexpected snapshot entry; only database and media are allowed")
        if name in entries:
            raise ValueError("Duplicate snapshot entry")
        entries[name] = entry
        path = directory / name
        if not path.is_file() or path.stat().st_size != entry.bytes or digest(path) != entry.sha256:
            raise ValueError("Snapshot file is missing or its bytes/checksum changed")
    if set(entries) != {p.relative_to(directory).as_posix() for p in paths if p != manifest_path}:
        raise ValueError("Snapshot contains unlisted or missing files")
    if "database.sqlite3" not in entries:
        raise ValueError("Snapshot database is missing")
    revision, counts = inspect_database(directory / "database.sqlite3")
    if revision != manifest.schema_revision or counts != manifest.table_counts:
        raise ValueError("Snapshot database schema or row counts changed")
    referenced_files(directory / "database.sqlite3", manifest.original_storage, entries)
    return manifest
