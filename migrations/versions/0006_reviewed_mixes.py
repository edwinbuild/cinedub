"""Versioned retained-background renders and separate listening acceptance records."""

import sqlalchemy as sa
from alembic import op

revision = "0006_reviewed_mixes"
down_revision = "0005_reviewed_stems"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mix_renders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False, index=True
        ),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column(
            "revision_id", sa.String(36), sa.ForeignKey("timeline_revisions.id"), nullable=False
        ),
        sa.Column(
            "source_asset_id", sa.String(36), sa.ForeignKey("media_assets.id"), nullable=False
        ),
        sa.Column("stem_set_id", sa.String(36), sa.ForeignKey("stem_sets.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="needs_review"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("settings_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("artifacts_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("quality_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "mix_review_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "mix_id", sa.String(36), sa.ForeignKey("mix_renders.id"), nullable=False, index=True
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reviewed_by", sa.String(120), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("certificate_artifact_id", sa.String(36)),
        sa.Column("bundle_artifact_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    raise RuntimeError("Restore a backup to retain mix/export acceptance history")
