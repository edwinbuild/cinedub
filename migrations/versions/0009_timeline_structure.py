"""Preserve replaced lines and audit split/merge/reversal without deleting provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0009_timeline_structure"
down_revision = "0008_speech_emotion_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "segments", sa.Column("retired", sa.Boolean(), nullable=False, server_default="0")
    )
    op.create_table(
        "timeline_structure_edits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "revision_id", sa.String(36), sa.ForeignKey("timeline_revisions.id"), nullable=False
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("parent_edit_id", sa.String(36), sa.ForeignKey("timeline_structure_edits.id")),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for field in ("project_id", "revision_id"):
        op.create_index(f"ix_timeline_structure_edits_{field}", "timeline_structure_edits", [field])


def downgrade():
    raise RuntimeError("Restore a consistent backup to preserve structural edit history")
