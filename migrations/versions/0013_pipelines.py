"""Pipelines: ordered stage runs that pause at human review gates."""

import sqlalchemy as sa
from alembic import op

revision = "0013_pipelines"
down_revision = "0012_correlation_ids"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pipelines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_asset_id", sa.String(36), sa.ForeignKey("media_assets.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("steps_json", sa.JSON(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("gate_reason", sa.Text(), nullable=True),
        sa.Column("budget_confirmed_inr", sa.Float(), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for field in ("project_id", "status", "correlation_id"):
        op.create_index(f"ix_pipelines_{field}", "pipelines", [field])


def downgrade():
    raise RuntimeError("Restore a consistent workspace backup to remove pipeline history")
