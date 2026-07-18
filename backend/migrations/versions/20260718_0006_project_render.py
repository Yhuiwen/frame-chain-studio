"""add project render tasks

Revision ID: 20260718_0006
Revises: 20260718_0005
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0006"
down_revision: str | None = "20260718_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("projectrender"):
        op.create_table(
            "projectrender",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="QUEUED"),
            sa.Column("render_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("requested_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("locked_by", sa.String(), nullable=True),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("input_manifest_json", sa.String(), nullable=False, server_default="[]"),
            sa.Column("settings_json", sa.String(), nullable=False, server_default="{}"),
            sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
            sa.Column("current_stage", sa.String(), nullable=False, server_default=""),
            sa.Column("output_asset_id", sa.Integer(), nullable=True),
            sa.Column("temporary_relative_path", sa.String(), nullable=True),
            sa.Column("final_relative_path", sa.String(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("error_details_json", sa.String(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["output_asset_id"], ["asset.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_projectrender_idempotency_key"),
        )
        op.create_index("ix_projectrender_project_id", "projectrender", ["project_id"])
        op.create_index("ix_projectrender_status", "projectrender", ["status"])
        op.create_index("ix_projectrender_render_version", "projectrender", ["render_version"])
        op.create_index("ix_projectrender_idempotency_key", "projectrender", ["idempotency_key"])
        op.create_index("ix_projectrender_locked_by", "projectrender", ["locked_by"])
        op.create_index("ix_projectrender_locked_until", "projectrender", ["locked_until"])
        op.create_index("ix_projectrender_project_status", "projectrender", ["project_id", "status"])
        op.create_index("ix_projectrender_status_locked_until", "projectrender", ["status", "locked_until"])


def downgrade() -> None:
    if _table_exists("projectrender"):
        op.drop_table("projectrender")
