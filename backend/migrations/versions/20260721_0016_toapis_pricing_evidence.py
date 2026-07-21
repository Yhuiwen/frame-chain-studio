"""TOAPIS structured pricing evidence

Revision ID: 20260721_0016
Revises: 20260721_0015
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0016"
down_revision: str | None = "20260721_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = [
        sa.Column("pricing_source_kind", sa.String(80), nullable=False, server_default=""),
        sa.Column("pricing_source_checked_at", sa.DateTime(), nullable=True),
        sa.Column("pricing_source_reference", sa.String(500), nullable=False, server_default=""),
        sa.Column("pricing_assumptions_json", sa.Text(), nullable=False, server_default="{}"),
    ]
    for column in columns:
        op.add_column("providermodelprofile", column)
    op.execute(
        """UPDATE providermodelprofile
           SET pricing_version='toapis-public-2026-07-21',
               pricing_review_status='PENDING', pricing_snapshot_hash=NULL,
               pricing_reviewed_at=NULL, pricing_reviewed_by=NULL
           WHERE model_key IN ('toapis-seedream-5', 'toapis-viduq3-pro')"""
    )
    op.execute("UPDATE providerprofile SET live_orchestration_enabled=0 WHERE provider_key='toapis'")


def downgrade() -> None:
    for column in [
        "pricing_assumptions_json",
        "pricing_source_reference",
        "pricing_source_checked_at",
        "pricing_source_kind",
    ]:
        op.drop_column("providermodelprofile", column)
