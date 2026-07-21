"""TOAPIS balance evidence and paid image canary

Revision ID: 20260721_0017
Revises: 20260721_0016
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0017"
down_revision: str | None = "20260721_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in [
        sa.Column("account_balance_pricing_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("account_balance_confirmed_units", sa.String(80), nullable=True),
        sa.Column("account_balance_evidence_type", sa.String(80), nullable=True),
    ]:
        op.add_column("providerprofile", column)
    op.add_column(
        "providerverificationrun",
        sa.Column("canary_image_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE providerprofile SET live_orchestration_enabled=0 WHERE provider_key='toapis'")


def downgrade() -> None:
    op.drop_column("providerverificationrun", "canary_image_only")
    for column in [
        "account_balance_evidence_type",
        "account_balance_confirmed_units",
        "account_balance_pricing_snapshot_hash",
    ]:
        op.drop_column("providerprofile", column)
