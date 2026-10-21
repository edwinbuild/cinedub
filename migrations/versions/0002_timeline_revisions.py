"""Revision-bound timelines, edits and resumable provider jobs."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0002_timeline_revisions"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("active_revision_id", sa.String(36)))
    op.add_column(
        "projects", sa.Column("budget_inr", sa.Float(), nullable=False, server_default="50")
    )
    op.create_table(
        "timeline_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("source_asset_id", sa.String(36), sa.ForeignKey("media_assets.id")),
        sa.Column("job_id", sa.String(36)),
        sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_timeline_revisions_project_id", "timeline_revisions", ["project_id"])
    for table in ("speakers", "segments"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("revision_id", sa.String(36)))
            batch.create_foreign_key(
                f"fk_{table}_revision", "timeline_revisions", ["revision_id"], ["id"]
            )
    op.add_column(
        "segments",
        sa.Column("human_edited", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "segments", sa.Column("warnings_json", sa.JSON(), nullable=False, server_default="[]")
    )
    op.create_table(
        "segment_edits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("segment_id", sa.String(36), sa.ForeignKey("segments.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_segment_edits_segment_id", "segment_edits", ["segment_id"])
    for column in [
        sa.Column("phase", sa.String(48), nullable=False, server_default="queued"),
        sa.Column("remote_job_id", sa.String(255)),
        sa.Column("checkpoint_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("estimated_cost_inr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("charged_estimate_inr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warnings_json", sa.JSON(), nullable=False, server_default="[]"),
    ]:
        op.add_column("jobs", column)
    connection = op.get_bind()
    projects = (
        connection.execute(sa.text("SELECT DISTINCT project_id FROM segments")).scalars().all()
    )
    for project_id in projects:
        revision_id = str(uuid4())
        connection.execute(
            sa.text(
                "INSERT INTO timeline_revisions (id, project_id, provider, model, warnings_json, "
                "created_at, updated_at) VALUES (:id, :project, 'fake', 'legacy-v0.1', :warnings, "
                ":now, :now)"
            ),
            {
                "id": revision_id,
                "project": project_id,
                "warnings": json.dumps(["Legacy/demo timeline; source linkage is unknown"]),
                "now": datetime.now(UTC),
            },
        )
        for table in ("speakers", "segments"):
            connection.execute(
                sa.text(f"UPDATE {table} SET revision_id=:revision WHERE project_id=:project"),
                {"revision": revision_id, "project": project_id},
            )
        connection.execute(
            sa.text("UPDATE projects SET active_revision_id=:revision WHERE id=:project"),
            {"revision": revision_id, "project": project_id},
        )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade SQLite backup to return to v0.1")
