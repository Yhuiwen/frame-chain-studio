"""Add visual review audit events.

Revision ID: 20260721_0023
Revises: 20260721_0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0023"
down_revision: str | None = "20260721_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visualcontinuityreviewevent",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("reviewer", sa.String(length=160), nullable=False),
        sa.Column("review_source", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("rejection_reasons_json", sa.String(), nullable=False),
        sa.Column("comment", sa.String(length=2000), nullable=False),
        sa.Column("previous_production_gate_status", sa.String(), nullable=False),
        sa.Column("resulting_production_gate_status", sa.String(), nullable=False),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["visualcontinuityreport.id"]),
    )
    op.create_index(
        "ix_visualreviewevent_report_reviewed",
        "visualcontinuityreviewevent",
        ["report_id", "reviewed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_visualreviewevent_report_reviewed", table_name="visualcontinuityreviewevent")
    op.drop_table("visualcontinuityreviewevent")
