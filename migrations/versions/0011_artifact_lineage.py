"""Artifact integrity facts, root-relative storage keys and persisted lineage edges.

Existing rows are not rewritten here: the application backfills hashes, storage keys and
edges idempotently after upgrade (see lineage.backfill_lineage), using the same derivation
as newly completed jobs. A pre-upgrade database backup is taken by create_database().
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_artifact_lineage"
down_revision = "0010_speaker_reuse"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("artifacts") as batch:
        batch.add_column(sa.Column("sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("size_bytes", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("storage_key", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "provider_run_id",
                sa.String(36),
                sa.ForeignKey("provider_runs.id", name="fk_artifacts_provider_run"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("lineage_version", sa.Integer(), nullable=True))
    op.create_table(
        "artifact_inputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.String(36),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column(
            "input_artifact_id",
            sa.String(36),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "input_asset_id",
            sa.String(36),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    for field in ("artifact_id", "input_artifact_id", "input_asset_id"):
        op.create_index(f"ix_artifact_inputs_{field}", "artifact_inputs", [field])


def downgrade():
    raise RuntimeError("Restore a consistent workspace backup to remove lineage evidence")
