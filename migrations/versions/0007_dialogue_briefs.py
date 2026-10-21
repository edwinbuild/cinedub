"""Append-only, revision-bound editorial briefs; existing dialogue is unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "0007_dialogue_briefs"
down_revision = "0006_reviewed_mixes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dialogue_briefs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "revision_id", sa.String(36), sa.ForeignKey("timeline_revisions.id"), nullable=False
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("revision_id", "version"),
    )
    op.create_index("ix_dialogue_briefs_project_id", "dialogue_briefs", ["project_id"])
    op.create_index("ix_dialogue_briefs_revision_id", "dialogue_briefs", ["revision_id"])


def downgrade():
    raise RuntimeError("Restore a backup to retain editorial brief history")
