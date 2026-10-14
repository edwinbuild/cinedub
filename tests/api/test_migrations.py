import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def migrate(path, revision):
    environment = {
        **os.environ,
        "CINEDUB_DATABASE_URL": f"sqlite:///{path}",
        "CINEDUB_STORAGE_ROOT": str(path.parent / "storage"),
        "PYTHONPATH": "apps/api",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return environment


def test_fresh_and_upgrade_paths_preserve_legacy_edits(tmp_path):
    fresh = tmp_path / "fresh.db"
    migrate(fresh, "head")
    with sqlite3.connect(fresh) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0005_reviewed_stems"
        )
        fresh_columns = {row[1] for row in connection.execute("PRAGMA table_info(segments)")}
    legacy = tmp_path / "legacy.db"
    environment = migrate(legacy, "0001_initial_schema")
    now = "2026-10-14 00:00:00"
    with sqlite3.connect(legacy) as connection:
        assert "revision_id" not in {
            row[1] for row in connection.execute("PRAGMA table_info(segments)")
        }
        connection.execute(
            "INSERT INTO projects VALUES "
            "('p', 'Legacy scene', 'en-IN', 'ml-IN', 'review', 120, ?, ?)",
            (now, now),
        )
        connection.execute(
            'INSERT INTO segments (id, project_id, "index", start_ms, end_ms, source_text, '
            "translated_text, status, delivery_json, version, created_at, updated_at) "
            "VALUES ('s', 'p', 0, 0, 1000, 'Source', ?, 'approved', '{}', 7, ?, ?)",
            ("അംഗീകരിച്ച വരി", now, now),
        )
    # Exercise the application's backup path, not only Alembic's schema upgrade.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from cinedub_api.database import create_database; create_database()",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    backups = list(tmp_path.glob("legacy.db.v01-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0001_initial_schema"
        )
    with sqlite3.connect(legacy) as connection:
        assert fresh_columns == {
            row[1] for row in connection.execute("PRAGMA table_info(segments)")
        }
        row = connection.execute(
            "SELECT translated_text, status, version, revision_id FROM segments WHERE id='s'"
        ).fetchone()
        assert row[:3] == ("അംഗീകരിച്ച വരി", "approved", 7)
        active = connection.execute(
            "SELECT active_revision_id FROM projects WHERE id='p'"
        ).fetchone()[0]
        assert row[3] == active
        assert connection.execute("SELECT provider FROM timeline_revisions").fetchone()[0] == "fake"


def test_voice_upgrade_preserves_stock_selection_without_approving_legacy_clones(tmp_path):
    database = tmp_path / "voices.db"
    environment = migrate(database, "0003_voice_candidates")
    now = "2026-10-14 00:00:00"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, source_language, target_language, status, "
            "duration_limit_seconds, created_at, updated_at, budget_inr) "
            "VALUES ('p', 'Voices', 'en-IN', 'ml-IN', 'review', 120, ?, ?, 50)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO speakers (id, project_id, label, display_name, created_at, updated_at) "
            "VALUES ('s', 'p', 'SPEAKER_00', 'Actor', ?, ?)",
            (now, now),
        )
        for profile_id, kind, consent_status in [
            ("preset", "preset", "not_required"),
            ("legacy-clone", "clone", "approved"),
        ]:
            connection.execute(
                "INSERT INTO voice_profiles (id, project_id, speaker_id, display_name, provider, "
                "provider_voice_id, consent_status, voice_kind, settings_json, version, "
                "created_at, updated_at) VALUES "
                "(?, 'p', 's', ?, 'fake', 'speaker-a', ?, ?, '{}', 1, ?, ?)",
                (profile_id, profile_id, consent_status, kind, now, now),
            )
        connection.execute(
            "INSERT INTO consent_records (id, voice_profile_id, status, attested_by, note, "
            "attested_at, created_at, updated_at) "
            "VALUES ('c', 'legacy-clone', 'approved', 'Legacy operator', '', ?, ?, ?)",
            (now, now, now),
        )
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from cinedub_api.database import create_database; create_database()",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert len(list(tmp_path.glob("voices.db.v02-voices-*.bak"))) == 1
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT voice_profile_id FROM speakers WHERE id='s'").fetchone()[0]
            == "preset"
        )
        assert (
            connection.execute(
                "SELECT registration_status FROM voice_profiles WHERE id='legacy-clone'"
            ).fetchone()[0]
            == "unprepared"
        )
        assert (
            connection.execute("SELECT scope_json FROM consent_records WHERE id='c'").fetchone()[0]
            == "{}"
        )
