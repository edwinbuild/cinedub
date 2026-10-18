import sqlite3
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings
from .workspace_lock import workspace_lease


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_database() -> None:
    with workspace_lease(settings.database_url, settings.storage_root):
        _upgrade_database()
        from .lineage import backfill_lineage  # Models import this module; load lazily.

        with SessionLocal() as session:
            backfill_lineage(session)


def _upgrade_database() -> None:
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    if settings.database_url.startswith("sqlite:///"):
        path = Path(settings.database_url.removeprefix("sqlite:///"))
        if path.is_file():
            with sqlite3.connect(path) as connection:
                version = connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='alembic_version'"
                ).fetchone()
                current = (
                    connection.execute("SELECT version_num FROM alembic_version").fetchone()
                    if version
                    else None
                )
                if current and current[0] in {
                    "0001_initial_schema",
                    "0002_timeline_revisions",
                    "0003_voice_candidates",
                    "0004_consented_clones",
                    "0005_reviewed_stems",
                    "0006_reviewed_mixes",
                    "0007_dialogue_briefs",
                    "0008_speech_emotion_reviews",
                    "0009_timeline_structure",
                    "0010_speaker_reuse",
                    "0011_artifact_lineage",
                    "0012_correlation_ids",
                }:
                    label = {
                        "0001_initial_schema": "v01",
                        "0002_timeline_revisions": "v02",
                        "0003_voice_candidates": "v02-voices",
                        "0004_consented_clones": "v02-consent",
                        "0005_reviewed_stems": "v02-stems",
                        "0006_reviewed_mixes": "v02-mixes",
                        "0007_dialogue_briefs": "v02-briefs",
                        "0008_speech_emotion_reviews": "v02-emotion",
                        "0009_timeline_structure": "v02-structure",
                        "0010_speaker_reuse": "v02-reuse",
                        "0011_artifact_lineage": "v03-lineage",
                        "0012_correlation_ids": "v03-correlation",
                    }[current[0]]
                    backup = path.with_name(
                        f"{path.name}.{label}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}.bak"
                    )
                    with sqlite3.connect(backup) as destination:
                        connection.backup(destination)
    command.upgrade(config, "head")


async def get_session() -> AsyncGenerator[Session, None]:
    with SessionLocal() as session:
        yield session
