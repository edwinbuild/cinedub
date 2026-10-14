"""Stock voice assignment and explicit candidate selection."""

import sqlalchemy as sa
from alembic import op

revision = "0003_voice_candidates"
down_revision = "0002_timeline_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("segments", sa.Column("selected_candidate_id", sa.String(36)))
    op.add_column(
        "voice_profiles",
        sa.Column("voice_kind", sa.String(16), nullable=False, server_default="clone"),
    )
    op.add_column(
        "voice_profiles", sa.Column("settings_json", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "voice_profiles", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )


def downgrade():
    raise RuntimeError("Restore a pre-upgrade backup to preserve candidate history")
