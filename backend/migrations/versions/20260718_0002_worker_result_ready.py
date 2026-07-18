"""add worker result ready state fields

Revision ID: 20260718_0002
Revises: 20260718_0001
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0002"
down_revision: str | None = "20260718_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _column_exists("generationtask", "result_urls_json"):
        op.add_column(
            "generationtask",
            sa.Column("result_urls_json", sa.Text(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    if _column_exists("generationtask", "result_urls_json"):
        op.drop_column("generationtask", "result_urls_json")
