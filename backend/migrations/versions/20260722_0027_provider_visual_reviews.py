"""Add Asset-bound Provider verification visual review history.

Revision ID: 20260722_0027
Revises: 20260721_0026
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0027"
down_revision: str | None = "20260721_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "providervisualreview",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("provider_verification_run_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_sha256", sa.String(length=64), nullable=False),
        sa.Column("review_scope", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=False),
        sa.Column("reviewer_source", sa.String(), nullable=False),
        sa.Column("reviewer_reference", sa.String(length=160), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["provider_verification_run_id"], ["providerverificationrun.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.UniqueConstraint(
            "provider_verification_run_id",
            "idempotency_key",
            name="uq_providervisualreview_run_idempotency",
        ),
    )
    op.create_index("ix_providervisualreview_project_id", "providervisualreview", ["project_id"])
    op.create_index(
        "ix_providervisualreview_provider_verification_run_id",
        "providervisualreview",
        ["provider_verification_run_id"],
    )
    op.create_index("ix_providervisualreview_asset_id", "providervisualreview", ["asset_id"])
    op.create_index(
        "ix_providervisualreview_asset_sha256", "providervisualreview", ["asset_sha256"]
    )
    op.create_index("ix_providervisualreview_decision", "providervisualreview", ["decision"])
    op.create_index("ix_providervisualreview_reviewed_at", "providervisualreview", ["reviewed_at"])
    op.create_index(
        "ix_providervisualreview_run_asset_reviewed",
        "providervisualreview",
        ["provider_verification_run_id", "asset_id", "reviewed_at"],
    )


def downgrade() -> None:
    op.drop_table("providervisualreview")
