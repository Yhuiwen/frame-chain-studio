"""add retry cancellation timeout commands

Revision ID: 20260718_0003
Revises: 20260718_0002
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0003"
down_revision: str | None = "20260718_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    columns = [
        ("last_retry_delay_seconds", sa.Float(), None),
        ("submission_deadline_at", sa.DateTime(), None),
        ("job_deadline_at", sa.DateTime(), None),
        ("cancellation_deadline_at", sa.DateTime(), None),
        ("cancel_requested_at", sa.DateTime(), None),
        ("cancelled_at", sa.DateTime(), None),
        ("cancel_reason", sa.String(), None),
        ("cancel_requested_by", sa.String(), None),
    ]
    for name, column_type, default in columns:
        if not _column_exists("generationtask", name):
            op.add_column("generationtask", sa.Column(name, column_type, nullable=True, server_default=default))
    indexes = {
        "ix_generationtask_status_submission_deadline": ["status", "submission_deadline_at"],
        "ix_generationtask_status_job_deadline": ["status", "job_deadline_at"],
        "ix_generationtask_status_cancellation_deadline": ["status", "cancellation_deadline_at"],
    }
    for name, fields in indexes.items():
        if not _index_exists("generationtask", name):
            op.create_index(name, "generationtask", fields)

    if not _table_exists("taskcommand"):
        op.create_table(
            "taskcommand",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("command_type", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
            sa.Column("reason", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("result_task_id", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["task_id"], ["generationtask.id"]),
            sa.ForeignKeyConstraint(["result_task_id"], ["generationtask.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("command_type", "idempotency_key", name="uq_taskcommand_type_idempotency"),
        )
        op.create_index("ix_taskcommand_task_id", "taskcommand", ["task_id"])
        op.create_index("ix_taskcommand_command_type", "taskcommand", ["command_type"])
        op.create_index("ix_taskcommand_idempotency_key", "taskcommand", ["idempotency_key"])
        op.create_index("ix_taskcommand_status", "taskcommand", ["status"])
        op.create_index("ix_taskcommand_task_type_created", "taskcommand", ["task_id", "command_type", "created_at"])


def downgrade() -> None:
    if _table_exists("taskcommand"):
        op.drop_table("taskcommand")
    for name in [
        "ix_generationtask_status_cancellation_deadline",
        "ix_generationtask_status_job_deadline",
        "ix_generationtask_status_submission_deadline",
    ]:
        if _index_exists("generationtask", name):
            op.drop_index(name, table_name="generationtask")
    for name in [
        "cancel_requested_by",
        "cancel_reason",
        "cancelled_at",
        "cancel_requested_at",
        "cancellation_deadline_at",
        "job_deadline_at",
        "submission_deadline_at",
        "last_retry_delay_seconds",
    ]:
        if _column_exists("generationtask", name):
            op.drop_column("generationtask", name)
