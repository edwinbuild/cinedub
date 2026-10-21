"""Append-only reviewed cross-revision speaker reuse; existing voices stay scoped."""

import sqlalchemy as sa
from alembic import op

revision = "0010_speaker_reuse"
down_revision = "0009_timeline_structure"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "speaker_reuses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("source_speaker_id", sa.String(36), sa.ForeignKey("speakers.id"), nullable=False),
        sa.Column("target_speaker_id", sa.String(36), sa.ForeignKey("speakers.id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("target_speaker_id", "fingerprint"),
    )
    for field in ("project_id", "target_speaker_id"):
        op.create_index(f"ix_speaker_reuses_{field}", "speaker_reuses", [field])


def downgrade():
    raise RuntimeError("Restore a consistent workspace backup to preserve reuse history")
