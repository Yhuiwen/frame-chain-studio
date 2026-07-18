"""add frontend provider and worker state

Revision ID: 20260718_0005
Revises: 20260718_0004
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0005"
down_revision: str | None = "20260718_0004"
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
    project_columns = [
        ("image_provider_id", sa.String(), None),
        ("video_provider_id", sa.String(), None),
        ("image_model", sa.String(), None),
        ("video_model", sa.String(), None),
        ("default_aspect_ratio", sa.String(), "16:9"),
        ("default_video_duration_seconds", sa.Float(), None),
        ("default_seed", sa.Integer(), None),
    ]
    for name, column_type, default in project_columns:
        if not _column_exists("project", name):
            op.add_column("project", sa.Column(name, column_type, nullable=True, server_default=default))

    request_columns = [
        ("effective_provider_id", sa.String(), None),
        ("model", sa.String(), None),
        ("generation_mode", sa.String(), None),
        ("aspect_ratio", sa.String(), None),
        ("seed", sa.Integer(), None),
        ("duration_seconds", sa.Float(), None),
        ("allow_capability_fallback", sa.Boolean(), sa.false()),
    ]
    for name, column_type, default in request_columns:
        if not _column_exists("generationrequest", name):
            op.add_column("generationrequest", sa.Column(name, column_type, nullable=True, server_default=default))
    if not _index_exists("generationrequest", "ix_generationrequest_effective_provider_id"):
        op.create_index("ix_generationrequest_effective_provider_id", "generationrequest", ["effective_provider_id"])
    if not _index_exists("generationrequest", "ix_generationrequest_generation_mode"):
        op.create_index("ix_generationrequest_generation_mode", "generationrequest", ["generation_mode"])

    task_columns = [
        ("remote_progress", sa.Float(), None),
        ("processing_stage", sa.String(), None),
        ("processing_progress", sa.Float(), None),
    ]
    for name, column_type, default in task_columns:
        if not _column_exists("generationtask", name):
            op.add_column("generationtask", sa.Column(name, column_type, nullable=True, server_default=default))

    if not _table_exists("workerheartbeat"):
        op.create_table(
            "workerheartbeat",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("worker_id", sa.String(), nullable=False),
            sa.Column("worker_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="STARTING"),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("current_task_id", sa.Integer(), nullable=True),
            sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error_code", sa.String(), nullable=True),
            sa.Column("last_error_message", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.String(), nullable=False, server_default="{}"),
            sa.ForeignKeyConstraint(["current_task_id"], ["generationtask.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("worker_type", "worker_id", name="uq_workerheartbeat_type_id"),
        )
        op.create_index("ix_workerheartbeat_worker_id", "workerheartbeat", ["worker_id"])
        op.create_index("ix_workerheartbeat_worker_type", "workerheartbeat", ["worker_type"])
        op.create_index("ix_workerheartbeat_status", "workerheartbeat", ["status"])
        op.create_index("ix_workerheartbeat_last_seen_at", "workerheartbeat", ["last_seen_at"])
        op.create_index("ix_workerheartbeat_current_task_id", "workerheartbeat", ["current_task_id"])
        op.create_index("ix_workerheartbeat_type_last_seen", "workerheartbeat", ["worker_type", "last_seen_at"])
        op.create_index("ix_workerheartbeat_status_last_seen", "workerheartbeat", ["status", "last_seen_at"])


def downgrade() -> None:
    if _table_exists("workerheartbeat"):
        op.drop_table("workerheartbeat")
    for name in ["processing_progress", "processing_stage", "remote_progress"]:
        if _column_exists("generationtask", name):
            op.drop_column("generationtask", name)
    for index_name in ["ix_generationrequest_generation_mode", "ix_generationrequest_effective_provider_id"]:
        if _index_exists("generationrequest", index_name):
            op.drop_index(index_name, table_name="generationrequest")
    for name in [
        "allow_capability_fallback",
        "duration_seconds",
        "seed",
        "aspect_ratio",
        "generation_mode",
        "model",
        "effective_provider_id",
    ]:
        if _column_exists("generationrequest", name):
            op.drop_column("generationrequest", name)
    for name in [
        "default_seed",
        "default_video_duration_seconds",
        "default_aspect_ratio",
        "video_model",
        "image_model",
        "video_provider_id",
        "image_provider_id",
    ]:
        if _column_exists("project", name):
            op.drop_column("project", name)
