"""Frozen v0.1 schema. Never import mutable application models in migrations."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _table(name, columns):
    op.create_table(
        name,
        sa.Column("id", sa.String(36), primary_key=True),
        *columns,
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _col(name, kind, nullable=False):
    return sa.Column(name, kind, nullable=nullable)


def _fk(name, target, nullable=False, cascade=False):
    return sa.Column(
        name,
        sa.String(36),
        sa.ForeignKey(target, ondelete="CASCADE" if cascade else None),
        nullable=nullable,
    )


def upgrade() -> None:
    _table(
        "projects",
        [
            _col("name", sa.String(120)),
            _col("source_language", sa.String(16)),
            _col("target_language", sa.String(16)),
            _col("status", sa.String(32)),
            _col("duration_limit_seconds", sa.Integer()),
        ],
    )
    _table(
        "media_assets",
        [
            _fk("project_id", "projects.id", cascade=True),
            _col("kind", sa.String(48)),
            _col("path", sa.Text()),
            _col("filename", sa.String(255)),
            _col("media_type", sa.String(120)),
            _col("duration_ms", sa.Integer(), True),
            _col("metadata_json", sa.JSON()),
        ],
    )
    _table(
        "speakers",
        [
            _fk("project_id", "projects.id", cascade=True),
            _col("label", sa.String(64)),
            _col("display_name", sa.String(120)),
        ],
    )
    _table(
        "segments",
        [
            _fk("project_id", "projects.id", cascade=True),
            _fk("speaker_id", "speakers.id", True),
            _col("index", sa.Integer()),
            _col("start_ms", sa.Integer()),
            _col("end_ms", sa.Integer()),
            _col("source_text", sa.Text()),
            _col("translated_text", sa.Text()),
            _col("status", sa.String(32)),
            _col("emotion_label", sa.String(32), True),
            _col("emotion_confidence", sa.Float(), True),
            _col("energy", sa.Float(), True),
            _col("pace", sa.Float(), True),
            _col("delivery_json", sa.JSON()),
            _col("version", sa.Integer()),
        ],
    )
    _table(
        "voice_profiles",
        [
            _fk("project_id", "projects.id", cascade=True),
            _fk("speaker_id", "speakers.id"),
            _col("display_name", sa.String(120)),
            _col("provider", sa.String(48)),
            _col("provider_voice_id", sa.String(255), True),
            _fk("reference_asset_id", "media_assets.id", True),
            _col("consent_status", sa.String(32)),
        ],
    )
    _table(
        "consent_records",
        [
            _fk("voice_profile_id", "voice_profiles.id", cascade=True),
            _col("status", sa.String(32)),
            _col("attested_by", sa.String(120)),
            _col("note", sa.Text()),
            _col("attested_at", sa.DateTime(timezone=True)),
        ],
    )
    _table(
        "jobs",
        [
            _fk("project_id", "projects.id", cascade=True),
            _col("stage", sa.String(64)),
            _col("status", sa.String(32)),
            _col("progress", sa.Float()),
            _col("provider", sa.String(48)),
            _col("attempts", sa.Integer()),
            _col("cancel_requested", sa.Boolean()),
            _col("error_code", sa.String(80), True),
            _col("error_message", sa.Text(), True),
            _col("input_json", sa.JSON()),
            _col("output_json", sa.JSON()),
            _col("started_at", sa.DateTime(timezone=True), True),
            _col("finished_at", sa.DateTime(timezone=True), True),
        ],
    )
    _table(
        "artifacts",
        [
            _fk("project_id", "projects.id", cascade=True),
            _fk("job_id", "jobs.id", True),
            _col("kind", sa.String(64)),
            _col("path", sa.Text()),
            _col("filename", sa.String(255)),
            _col("media_type", sa.String(120)),
            _col("metadata_json", sa.JSON()),
        ],
    )
    _table(
        "provider_runs",
        [
            _fk("project_id", "projects.id", cascade=True),
            _fk("job_id", "jobs.id", True),
            _col("capability", sa.String(64)),
            _col("provider", sa.String(48)),
            _col("model", sa.String(120)),
            _col("parameters_json", sa.JSON()),
            _col("latency_ms", sa.Integer(), True),
            _col("estimated_cost_inr", sa.Float(), True),
            _col("status", sa.String(32)),
            _col("warning", sa.Text(), True),
        ],
    )
    for table, columns in {
        "media_assets": ["project_id"],
        "speakers": ["project_id"],
        "segments": ["project_id"],
        "voice_profiles": ["project_id", "speaker_id"],
        "consent_records": ["voice_profile_id"],
        "jobs": ["project_id", "stage", "status"],
        "artifacts": ["project_id"],
        "provider_runs": ["project_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in [
        "provider_runs",
        "artifacts",
        "jobs",
        "consent_records",
        "voice_profiles",
        "segments",
        "speakers",
        "media_assets",
        "projects",
    ]:
        op.drop_table(table)
