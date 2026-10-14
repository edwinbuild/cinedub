"""Initial CineDub project, timeline, job, artifact, and provenance schema."""

from alembic import op
from cinedub_api import models  # noqa: F401
from cinedub_api.database import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
