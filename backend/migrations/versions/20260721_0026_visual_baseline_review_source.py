"""Add explicit visual baseline review source."""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0026"
down_revision: str | None = "20260721_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projectvisualbaseline", sa.Column("review_source", sa.String(80), nullable=False, server_default="PENDING"))


def downgrade() -> None:
    op.drop_column("projectvisualbaseline", "review_source")
