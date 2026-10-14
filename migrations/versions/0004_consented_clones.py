"""Explicit voice selection and scoped clone consent; legacy clones need new consent."""

import sqlalchemy as sa
from alembic import op

revision = "0004_consented_clones"
down_revision = "0003_voice_candidates"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("speakers", sa.Column("voice_profile_id", sa.String(36)))
    op.add_column("voice_profiles", sa.Column("reference_artifact_id", sa.String(36)))
    op.add_column(
        "voice_profiles",
        sa.Column(
            "registration_status", sa.String(32), nullable=False, server_default="unprepared"
        ),
    )
    op.add_column(
        "consent_records", sa.Column("scope_json", sa.JSON(), nullable=False, server_default="{}")
    )
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE voice_profiles SET registration_status='ready' WHERE voice_kind='preset'")
    )
    connection.execute(
        sa.text(
            "UPDATE speakers SET voice_profile_id=(SELECT id FROM voice_profiles "
            "WHERE voice_profiles.speaker_id=speakers.id AND voice_kind='preset' "
            "ORDER BY updated_at DESC, id DESC LIMIT 1)"
        )
    )


def downgrade():
    raise RuntimeError("Restore a backup; do not discard voice consent and selection history")
