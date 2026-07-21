"""TOAPIS first-last-frame video Canary

Revision ID: 20260721_0018
Revises: 20260721_0017
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0018"
down_revision: str | None = "20260721_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("providerverificationrun") as batch_op:
        batch_op.add_column(sa.Column("end_frame_asset_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tail_frame_asset_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_video_canary_end_asset", "asset", ["end_frame_asset_id"], ["id"])
        batch_op.create_foreign_key("fk_video_canary_tail_asset", "asset", ["tail_frame_asset_id"], ["id"])
    op.execute("UPDATE providerprofile SET live_orchestration_enabled=0 WHERE provider_key='toapis'")


def downgrade() -> None:
    with op.batch_alter_table("providerverificationrun") as batch_op:
        batch_op.drop_constraint("fk_video_canary_tail_asset", type_="foreignkey")
        batch_op.drop_constraint("fk_video_canary_end_asset", type_="foreignkey")
        batch_op.drop_column("tail_frame_asset_id")
        batch_op.drop_column("end_frame_asset_id")
