"""Add reversible project archive metadata."""

from alembic import op
import sqlalchemy as sa

revision = "20260722_0029"
down_revision = "20260722_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("archived_by_source", sa.String(length=80), nullable=True))
        batch.create_index("ix_project_archived_at", ["archived_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.drop_index("ix_project_archived_at")
        batch.drop_column("archived_by_source")
        batch.drop_column("archived_at")
