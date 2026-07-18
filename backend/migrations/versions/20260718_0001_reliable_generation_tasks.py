"""add reliable generation task tables

Revision ID: 20260718_0001
Revises:
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _table_exists("project"):
        op.create_table(
            "project",
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.String(), nullable=False, server_default=""),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _table_exists("shot"):
        op.create_table(
            "shot",
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("description", sa.String(), nullable=False, server_default=""),
            sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="4.0"),
            sa.Column("prompt", sa.String(), nullable=False, server_default=""),
            sa.Column("negative_prompt", sa.String(), nullable=False, server_default=""),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
            sa.Column("start_frame_asset_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
            sa.ForeignKeyConstraint(["start_frame_asset_id"], ["asset.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_shot_project_id", "shot", ["project_id"])
        op.create_index("ix_shot_sort_order", "shot", ["sort_order"])
        op.create_index("ix_shot_status", "shot", ["status"])

    if not _table_exists("asset"):
        op.create_table(
            "asset",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("shot_id", sa.Integer(), nullable=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("path", sa.String(), nullable=False),
            sa.Column("mime_type", sa.String(), nullable=False),
            sa.Column("source_asset_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
            sa.ForeignKeyConstraint(["shot_id"], ["shot.id"]),
            sa.ForeignKeyConstraint(["source_asset_id"], ["asset.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_asset_project_id", "asset", ["project_id"])
        op.create_index("ix_asset_shot_id", "asset", ["shot_id"])
        op.create_index("ix_asset_type", "asset", ["type"])

    if not _table_exists("generationrequest"):
        op.create_table(
            "generationrequest",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("shot_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("provider_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
            sa.Column("prompt_snapshot", sa.String(), nullable=False, server_default=""),
            sa.Column("negative_prompt_snapshot", sa.String(), nullable=False, server_default=""),
            sa.Column("input_asset_ids", sa.String(), nullable=False, server_default=""),
            sa.Column("output_asset_ids", sa.String(), nullable=False, server_default=""),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
            sa.ForeignKeyConstraint(["shot_id"], ["shot.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_generationrequest_project_id", "generationrequest", ["project_id"])
        op.create_index("ix_generationrequest_shot_id", "generationrequest", ["shot_id"])
        op.create_index("ix_generationrequest_kind", "generationrequest", ["kind"])
        op.create_index("ix_generationrequest_status", "generationrequest", ["status"])

    if not _table_exists("shotstatechange"):
        op.create_table(
            "shotstatechange",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("shot_id", sa.Integer(), nullable=False),
            sa.Column("from_status", sa.String(), nullable=True),
            sa.Column("to_status", sa.String(), nullable=False),
            sa.Column("reason", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["shot_id"], ["shot.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_shotstatechange_shot_id", "shotstatechange", ["shot_id"])

    if not _table_exists("tasklog"):
        op.create_table(
            "tasklog",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("request_id", sa.Integer(), nullable=True),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("shot_id", sa.Integer(), nullable=True),
            sa.Column("level", sa.String(length=16), nullable=False, server_default="INFO"),
            sa.Column("message", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["request_id"], ["generationrequest.id"]),
            sa.ForeignKeyConstraint(["shot_id"], ["shot.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_tasklog_request_id", "tasklog", ["request_id"])
        op.create_index("ix_tasklog_shot_id", "tasklog", ["shot_id"])

    if not _table_exists("generationtask"):
        op.create_table(
            "generationtask",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("generation_request_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("shot_id", sa.Integer(), nullable=False),
            sa.Column("task_type", sa.String(), nullable=False),
            sa.Column("provider_id", sa.String(), nullable=False, server_default="mock"),
            sa.Column("status", sa.String(), nullable=False, server_default="QUEUED"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("remote_job_id", sa.String(), nullable=True),
            sa.Column("remote_status", sa.String(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("last_polled_at", sa.DateTime(), nullable=True),
            sa.Column("next_poll_at", sa.DateTime(), nullable=True),
            sa.Column("poll_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("retry_of_task_id", sa.Integer(), nullable=True),
            sa.Column("root_task_id", sa.Integer(), nullable=True),
            sa.Column("request_payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("response_summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("provider_config_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("error_details_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("last_error_at", sa.DateTime(), nullable=True),
            sa.Column("locked_by", sa.String(), nullable=True),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("lock_acquired_at", sa.DateTime(), nullable=True),
            sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("result_asset_id", sa.Integer(), nullable=True),
            sa.CheckConstraint("attempt_number >= 1", name="ck_generationtask_attempt_number"),
            sa.CheckConstraint("retry_count >= 0", name="ck_generationtask_retry_count"),
            sa.CheckConstraint("max_attempts >= 1", name="ck_generationtask_max_attempts"),
            sa.CheckConstraint(
                "retry_of_task_id IS NULL OR retry_of_task_id != id",
                name="ck_generationtask_no_self_retry",
            ),
            sa.ForeignKeyConstraint(["generation_request_id"], ["generationrequest.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
            sa.ForeignKeyConstraint(["shot_id"], ["shot.id"]),
            sa.ForeignKeyConstraint(["retry_of_task_id"], ["generationtask.id"]),
            sa.ForeignKeyConstraint(["root_task_id"], ["generationtask.id"]),
            sa.ForeignKeyConstraint(["result_asset_id"], ["asset.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_generationtask_idempotency_key"),
            sa.UniqueConstraint("provider_id", "remote_job_id", name="uq_generationtask_provider_remote_job"),
        )
        op.create_index("ix_generationtask_generation_request_id", "generationtask", ["generation_request_id"])
        op.create_index("ix_generationtask_project_id", "generationtask", ["project_id"])
        op.create_index("ix_generationtask_shot_id", "generationtask", ["shot_id"])
        op.create_index("ix_generationtask_task_type", "generationtask", ["task_type"])
        op.create_index("ix_generationtask_provider_id", "generationtask", ["provider_id"])
        op.create_index("ix_generationtask_status", "generationtask", ["status"])
        op.create_index("ix_generationtask_created_at", "generationtask", ["created_at"])
        op.create_index("ix_generationtask_remote_job_id", "generationtask", ["remote_job_id"])
        op.create_index("ix_generationtask_last_polled_at", "generationtask", ["last_polled_at"])
        op.create_index("ix_generationtask_next_poll_at", "generationtask", ["next_poll_at"])
        op.create_index("ix_generationtask_next_retry_at", "generationtask", ["next_retry_at"])
        op.create_index("ix_generationtask_locked_by", "generationtask", ["locked_by"])
        op.create_index("ix_generationtask_locked_until", "generationtask", ["locked_until"])
        op.create_index("ix_generationtask_idempotency_key", "generationtask", ["idempotency_key"])
        op.create_index("ix_generationtask_status_next_retry", "generationtask", ["status", "next_retry_at"])
        op.create_index("ix_generationtask_status_next_poll", "generationtask", ["status", "next_poll_at"])
        op.create_index("ix_generationtask_status_locked_until", "generationtask", ["status", "locked_until"])
        op.create_index("ix_generationtask_project_created", "generationtask", ["project_id", "created_at"])
        op.create_index(
            "ix_generationtask_shot_type_created",
            "generationtask",
            ["shot_id", "task_type", "created_at"],
        )

    if not _table_exists("taskstatechange"):
        op.create_table(
            "taskstatechange",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("from_status", sa.String(), nullable=True),
            sa.Column("to_status", sa.String(), nullable=False),
            sa.Column("reason_code", sa.String(), nullable=True),
            sa.Column("reason", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["generationtask.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_taskstatechange_task_id", "taskstatechange", ["task_id"])

    if _table_exists("tasklog") and not _column_exists("tasklog", "task_id"):
        op.add_column("tasklog", sa.Column("task_id", sa.Integer(), nullable=True))
        op.create_index("ix_tasklog_task_id", "tasklog", ["task_id"])


def downgrade() -> None:
    if _table_exists("tasklog") and _column_exists("tasklog", "task_id"):
        op.drop_index("ix_tasklog_task_id", table_name="tasklog")
        op.drop_column("tasklog", "task_id")
    if _table_exists("taskstatechange"):
        op.drop_index("ix_taskstatechange_task_id", table_name="taskstatechange")
        op.drop_table("taskstatechange")
    if _table_exists("generationtask"):
        op.drop_table("generationtask")
