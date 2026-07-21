"""Record the reused keyframe Asset on a recovery lineage.

Revision ID: 20260721_0020
Revises: 20260721_0019
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0020"
down_revision: str | None = "20260721_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("providerverificationrun") as batch_op:
        batch_op.add_column(sa.Column("reused_keyframe_asset_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_verification_reused_keyframe",
            "asset",
            ["reused_keyframe_asset_id"],
            ["id"],
        )
    op.execute("UPDATE providerprofile SET live_orchestration_enabled=0 WHERE provider_key='toapis'")


def downgrade() -> None:
    with op.batch_alter_table("providerverificationrun") as batch_op:
        batch_op.drop_constraint("fk_verification_reused_keyframe", type_="foreignkey")
        batch_op.drop_column("reused_keyframe_asset_id")
