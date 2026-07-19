"""reliability hardening constraints

Revision ID: 20260719_0007
Revises: 20260718_0006
Create Date: 2026-07-19 09:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260719_0007"
down_revision: str | None = "20260718_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projectrender") as batch_op:
        batch_op.add_column(sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("generationtask") as batch_op:
        batch_op.add_column(sa.Column("raw_result_urls_json", sa.Text(), nullable=False, server_default="[]"))
    with op.batch_alter_table("projectrender") as batch_op:
        batch_op.alter_column("lock_version", server_default=None)
    with op.batch_alter_table("generationtask") as batch_op:
        batch_op.alter_column("raw_result_urls_json", server_default=None)
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY project_id
                    ORDER BY
                        CASE WHEN sort_order IS NULL THEN 1 ELSE 0 END,
                        sort_order,
                        created_at,
                        id
                ) - 1 AS new_sort_order
            FROM shot
        )
        UPDATE shot
        SET sort_order = (
            SELECT new_sort_order FROM ranked WHERE ranked.id = shot.id
        )
        """
    )
    with op.batch_alter_table("shot") as batch_op:
        batch_op.create_unique_constraint("uq_shot_project_sort_order", ["project_id", "sort_order"])
    op.create_table(
        "providerassetcache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_sha256", sa.String(), nullable=False),
        sa.Column("reference_kind", sa.String(), nullable=False),
        sa.Column("reference_value", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "asset_id", "asset_sha256", name="uq_providerassetcache_provider_asset_sha"),
    )
    op.create_index("ix_providerassetcache_provider_asset", "providerassetcache", ["provider_id", "asset_id"])
    op.create_index("ix_providerassetcache_asset_id", "providerassetcache", ["asset_id"])
    op.create_index("ix_providerassetcache_asset_sha256", "providerassetcache", ["asset_sha256"])
    op.create_index("ix_providerassetcache_expires_at", "providerassetcache", ["expires_at"])
    op.create_index("ix_providerassetcache_provider_id", "providerassetcache", ["provider_id"])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_shot")
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_projectrender")
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_generationtask")
    with op.batch_alter_table("shot") as batch_op:
        batch_op.drop_constraint("uq_shot_project_sort_order", type_="unique")
    with op.batch_alter_table("projectrender") as batch_op:
        batch_op.drop_column("lock_version")
    with op.batch_alter_table("generationtask") as batch_op:
        batch_op.drop_column("raw_result_urls_json")
    op.drop_index("ix_providerassetcache_provider_id", table_name="providerassetcache", if_exists=True)
    op.drop_index("ix_providerassetcache_expires_at", table_name="providerassetcache", if_exists=True)
    op.drop_index("ix_providerassetcache_asset_sha256", table_name="providerassetcache", if_exists=True)
    op.drop_index("ix_providerassetcache_asset_id", table_name="providerassetcache", if_exists=True)
    op.drop_index("ix_providerassetcache_provider_asset", table_name="providerassetcache", if_exists=True)
    op.execute("DROP TABLE IF EXISTS providerassetcache")
