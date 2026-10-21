"""Correlation IDs linking a request to its job, provider runs and artifacts."""

import sqlalchemy as sa
from alembic import op

revision = "0012_correlation_ids"
down_revision = "0011_artifact_lineage"
branch_labels = None
depends_on = None

TABLES = ("jobs", "provider_runs", "artifacts")


def upgrade():
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("correlation_id", sa.String(64), nullable=True))
        op.create_index(f"ix_{table}_correlation_id", table, ["correlation_id"])


def downgrade():
    for table in TABLES:
        op.drop_index(f"ix_{table}_correlation_id", table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("correlation_id")
