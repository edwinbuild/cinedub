"""Append-only human review of immutable speech-emotion evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0008_speech_emotion_reviews"
down_revision = "0007_dialogue_briefs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "speech_emotion_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("segment_id", sa.String(36), sa.ForeignKey("segments.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("label", sa.String(32), nullable=True),
        sa.Column("direction", sa.Text, nullable=False),
        sa.Column("reviewed_by", sa.String(120), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("artifact_id", "segment_id", "version"),
    )
    op.create_index(
        "ix_speech_emotion_reviews_artifact_id", "speech_emotion_reviews", ["artifact_id"]
    )
    op.create_index(
        "ix_speech_emotion_reviews_segment_id", "speech_emotion_reviews", ["segment_id"]
    )


def downgrade():
    raise RuntimeError("Restore a backup to retain human speech-performance review history")
