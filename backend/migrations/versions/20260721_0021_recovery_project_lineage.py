"""Allow a failed-run recovery to reuse its verification project.

Revision ID: 20260721_0021
Revises: 20260721_0020
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0021"
down_revision: str | None = "20260721_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_providerverificationrun_verification_project_id", table_name="providerverificationrun")
    op.create_index(
        "ix_providerverificationrun_verification_project_id",
        "providerverificationrun",
        ["verification_project_id"],
        unique=False,
    )
    op.execute("UPDATE providerprofile SET live_orchestration_enabled=0 WHERE provider_key='toapis'")


def downgrade() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            """
            SELECT verification_project_id
            FROM providerverificationrun
            WHERE verification_project_id IS NOT NULL
            GROUP BY verification_project_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade 20260721_0021 while a verification project is shared by a recovery lineage."
        )
    op.drop_index("ix_providerverificationrun_verification_project_id", table_name="providerverificationrun")
    op.create_index(
        "ix_providerverificationrun_verification_project_id",
        "providerverificationrun",
        ["verification_project_id"],
        unique=True,
    )
