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


def test_speaker_reuse_upgrade_backs_up_structure_schema_without_rewriting_rows(tmp_path):
    from cinedub_api.models import Project, Segment, Speaker, TimelineRevision, VoiceProfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    database = tmp_path / "structure.db"
    environment = migrate(database, "0009_timeline_structure")
    engine = create_engine("sqlite:///" + str(database))
    with Session(engine) as session:
        project = Project(name="Preserved actor choices")
        session.add(project)
        session.flush()
        revision = TimelineRevision(project_id=project.id, provider="fake", model="prior")
        session.add(revision)
        session.flush()
        project.active_revision_id = revision.id
        speaker = Speaker(
            project_id=project.id, revision_id=revision.id, label="A", display_name="Original actor"
        )
        session.add(speaker)
        session.flush()
        profile = VoiceProfile(
            project_id=project.id,
            speaker_id=speaker.id,
            display_name="Stock",
            provider="fake",
            voice_kind="preset",
            consent_status="not_required",
            provider_voice_id="speaker-a",
        )
        session.add(profile)
        session.flush()
        speaker.voice_profile_id = profile.id
        session.add(
            Segment(
                project_id=project.id,
                revision_id=revision.id,
                speaker_id=speaker.id,
                index=0,
                start_ms=0,
                end_ms=1000,
                source_text="Preserved",
                translated_text="മലയാളം",
                status="approved",
                version=7,
                selected_candidate_id="historical-take",
            )
        )
        session.commit()
    engine.dispose()
    tables = ("projects", "timeline_revisions", "speakers", "segments", "voice_profiles")
    with sqlite3.connect(database) as connection:
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables
        }
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
    backups = list(tmp_path.glob("structure.db.v02-structure-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0009_timeline_structure"
        )
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0010_speaker_reuse"
        )
        assert connection.execute("SELECT COUNT(*) FROM speaker_reuses").fetchone()[0] == 0
        assert {
            table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables
        } == before


def test_fresh_and_upgrade_paths_preserve_legacy_edits(tmp_path):
    fresh = tmp_path / "fresh.db"
    migrate(fresh, "head")
    with sqlite3.connect(fresh) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0010_speaker_reuse"
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


def test_reviewed_stems_survive_mix_upgrade_and_backup(tmp_path):
    database = tmp_path / "stems.db"
    environment = migrate(database, "0005_reviewed_stems")
    now = "2026-10-15 00:00:00"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, source_language, target_language, status, "
            "duration_limit_seconds, created_at, updated_at, budget_inr) "
            "VALUES ('p','Stems','en-IN','ml-IN','review',120,?,?,50)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO media_assets (id, project_id, kind, path, filename, media_type, "
            "duration_ms, metadata_json, created_at, updated_at, active_stem_set_id) "
            "VALUES ('a','p','source','/unused','scene.wav','audio/wav',8000,'{}',?,?,'stems')",
            (now, now),
        )
        connection.execute(
            "INSERT INTO jobs (id, project_id, stage, status, progress, provider, attempts, "
            "cancel_requested, input_json, output_json, created_at, updated_at, phase, "
            "checkpoint_json, estimated_cost_inr, charged_estimate_inr, retryable, warnings_json) "
            "VALUES ('j','p','separate','completed',1,'local',1,0,'{}','{}',"
            "?,?,'completed','{}',0,0,0,'[]')",
            (now, now),
        )
        connection.execute(
            "INSERT INTO stem_sets VALUES "
            "('stems','p','a','j','local','pinned-model','approved',2,'{}','{}',?,?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO stem_review_records VALUES "
            "('r','stems',2,'approved','Fixture reviewer','Preserve review history',?)",
            (now,),
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
    backups = list(tmp_path.glob("stems.db.v02-stems-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0005_reviewed_stems"
        )
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT active_stem_set_id FROM media_assets").fetchone()[0]
            == "stems"
        )
        assert connection.execute("SELECT status, version FROM stem_sets").fetchone() == (
            "approved",
            2,
        )
        assert (
            connection.execute("SELECT note FROM stem_review_records").fetchone()[0]
            == "Preserve review history"
        )
        assert connection.execute("SELECT COUNT(*) FROM mix_renders").fetchone()[0] == 0


def test_brief_upgrade_backs_up_and_preserves_existing_mix_acceptance(tmp_path):
    database = tmp_path / "mixes.db"
    environment = migrate(database, "0006_reviewed_mixes")
    now = "2026-10-15 00:00:00"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO mix_renders VALUES "
            "('mix','p','j','r','a','stems','approved',2,'{}','{}','{}',?,?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO mix_review_records VALUES "
            "('review','mix',2,'approved','Synthetic reviewer','Keep listening acceptance',"
            "'certificate','bundle',?)",
            (now,),
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
    backups = list(tmp_path.glob("mixes.db.v02-mixes-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0006_reviewed_mixes"
        )
        assert connection.execute("SELECT status FROM mix_renders").fetchone()[0] == "approved"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT status,version FROM mix_renders").fetchone() == (
            "approved",
            2,
        )
        assert (
            connection.execute("SELECT note FROM mix_review_records").fetchone()[0]
            == "Keep listening acceptance"
        )
        assert connection.execute("SELECT COUNT(*) FROM dialogue_briefs").fetchone()[0] == 0


def test_emotion_upgrade_preserves_briefs_and_creates_recoverable_backup(tmp_path):
    database = tmp_path / "briefs.db"
    environment = migrate(database, "0007_dialogue_briefs")
    now = "2026-10-16 00:00:00"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO dialogue_briefs VALUES ('brief','p','r',3,?,?)",
            ('{"scene_summary":"Preserved human intent"}', now),
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
    backups = list(tmp_path.glob("briefs.db.v02-briefs-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            "0007_dialogue_briefs"
        )
        original = connection.execute("SELECT * FROM dialogue_briefs").fetchall()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM dialogue_briefs").fetchall() == original
        assert connection.execute("SELECT COUNT(*) FROM speech_emotion_reviews").fetchone()[0] == 0


def test_structure_upgrade_preserves_emotion_reviews_active_lines_and_backup(tmp_path):
    database = tmp_path / "emotion.db"
    environment = migrate(database, "0008_speech_emotion_reviews")
    now = "2026-10-16 00:00:00"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO speech_emotion_reviews VALUES "
            "('review','artifact','line',1,'corrected','other','Quiet','Fixture','Keep note',?)",
            (now,),
        )
        connection.execute(
            'INSERT INTO segments (id, project_id, "index", start_ms, end_ms, source_text, '
            "translated_text, status, delivery_json, version, human_edited, warnings_json, "
            "selected_candidate_id, created_at, updated_at) "
            "VALUES ('line','p',0,0,1000,'Synthetic source','Preserved translation','approved',"
            "'{}',7,1,'[]','take',?,?)",
            (now, now),
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
    backups = list(tmp_path.glob("emotion.db.v02-emotion-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            "0008_speech_emotion_reviews"
        )
        prior = connection.execute("SELECT * FROM speech_emotion_reviews").fetchall()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM speech_emotion_reviews").fetchall() == prior
        assert connection.execute(
            "SELECT retired,status,version,selected_candidate_id FROM segments"
        ).fetchone() == (0, "approved", 7, "take")
        assert (
            connection.execute("SELECT COUNT(*) FROM timeline_structure_edits").fetchone()[0] == 0
        )
