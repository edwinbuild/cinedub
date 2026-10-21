"""Source-bound separation candidates and auditable manual stem review."""

import sqlalchemy as sa
from alembic import op

revision = "0005_reviewed_stems"
down_revision = "0004_consented_clones"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media_assets", sa.Column("active_stem_set_id", sa.String(36)))
    op.create_table(
        "stem_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False, index=True
        ),
        sa.Column(
            "source_asset_id",
            sa.String(36),
            sa.ForeignKey("media_assets.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="needs_review"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("artifacts_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "stem_review_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "stem_set_id", sa.String(36), sa.ForeignKey("stem_sets.id"), nullable=False, index=True
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reviewed_by", sa.String(120), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    raise RuntimeError("Restore a backup to retain separated media and review history")
