"""add result processing assets

Revision ID: 20260718_0004
Revises: 20260718_0003
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0004"
down_revision: str | None = "20260718_0003"
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
    asset_columns = [
        ("sha256", sa.String(), None),
        ("file_size", sa.Integer(), None),
        ("width", sa.Integer(), None),
        ("height", sa.Integer(), None),
        ("duration_seconds", sa.Float(), None),
        ("fps", sa.Float(), None),
        ("frame_count", sa.Integer(), None),
        ("video_codec", sa.String(), None),
        ("audio_codec", sa.String(), None),
    ]
    for name, column_type, default in asset_columns:
        if not _column_exists("asset", name):
            op.add_column("asset", sa.Column(name, column_type, nullable=True, server_default=default))
    if not _index_exists("asset", "ix_asset_sha256"):
        op.create_index("ix_asset_sha256", "asset", ["sha256"])
    if not _index_exists("asset", "ix_asset_project_shot_type_sha256"):
        op.create_index(
            "ix_asset_project_shot_type_sha256",
            "asset",
            ["project_id", "shot_id", "type", "sha256"],
            unique=True,
        )

    task_columns = [
        ("result_retry_count", sa.Integer(), "0"),
        ("max_result_attempts", sa.Integer(), "3"),
        ("next_result_retry_at", sa.DateTime(), None),
        ("last_result_retry_delay_seconds", sa.Float(), None),
    ]
    for name, column_type, default in task_columns:
        if not _column_exists("generationtask", name):
            op.add_column("generationtask", sa.Column(name, column_type, nullable=True, server_default=default))
    if not _index_exists("generationtask", "ix_generationtask_next_result_retry_at"):
        op.create_index("ix_generationtask_next_result_retry_at", "generationtask", ["next_result_retry_at"])

    if not _table_exists("generationtaskresult"):
        op.create_table(
            "generationtaskresult",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("generation_task_id", sa.Integer(), nullable=False),
            sa.Column("result_index", sa.Integer(), nullable=False),
            sa.Column("source_url", sa.String(), nullable=False),
            sa.Column("source_url_hash", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
            sa.Column("media_kind", sa.String(), nullable=True),
            sa.Column("expected_media_kind", sa.String(), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("download_started_at", sa.DateTime(), nullable=True),
            sa.Column("download_completed_at", sa.DateTime(), nullable=True),
            sa.Column("validation_completed_at", sa.DateTime(), nullable=True),
            sa.Column("finalized_at", sa.DateTime(), nullable=True),
            sa.Column("temporary_relative_path", sa.String(), nullable=True),
            sa.Column("final_relative_path", sa.String(), nullable=True),
            sa.Column("sha256", sa.String(), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("mime_type", sa.String(), nullable=True),
            sa.Column("file_name", sa.String(), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("fps", sa.Float(), nullable=True),
            sa.Column("frame_count", sa.Integer(), nullable=True),
            sa.Column("video_codec", sa.String(), nullable=True),
            sa.Column("audio_codec", sa.String(), nullable=True),
            sa.Column("asset_id", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("error_details_json", sa.String(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
            sa.ForeignKeyConstraint(["generation_task_id"], ["generationtask.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("generation_task_id", "result_index", name="uq_taskresult_task_index"),
            sa.UniqueConstraint("generation_task_id", "source_url_hash", name="uq_taskresult_task_url_hash"),
        )
        op.create_index("ix_generationtaskresult_generation_task_id", "generationtaskresult", ["generation_task_id"])
        op.create_index("ix_generationtaskresult_status", "generationtaskresult", ["status"])
        op.create_index("ix_generationtaskresult_media_kind", "generationtaskresult", ["media_kind"])
        op.create_index("ix_generationtaskresult_expected_media_kind", "generationtaskresult", ["expected_media_kind"])
        op.create_index("ix_generationtaskresult_is_primary", "generationtaskresult", ["is_primary"])
        op.create_index("ix_generationtaskresult_next_retry_at", "generationtaskresult", ["next_retry_at"])
        op.create_index("ix_generationtaskresult_sha256", "generationtaskresult", ["sha256"])
        op.create_index("ix_generationtaskresult_asset_id", "generationtaskresult", ["asset_id"])
        op.create_index("ix_taskresult_task_status", "generationtaskresult", ["generation_task_id", "status"])
        op.create_index("ix_taskresult_status_next_retry", "generationtaskresult", ["status", "next_retry_at"])
        op.create_index("ix_taskresult_source_url_hash", "generationtaskresult", ["source_url_hash"])
        op.create_index("ix_taskresult_asset_id", "generationtaskresult", ["asset_id"])


def downgrade() -> None:
    if _table_exists("generationtaskresult"):
        op.drop_table("generationtaskresult")
    if _index_exists("generationtask", "ix_generationtask_next_result_retry_at"):
        op.drop_index("ix_generationtask_next_result_retry_at", table_name="generationtask")
    for name in [
        "last_result_retry_delay_seconds",
        "next_result_retry_at",
        "max_result_attempts",
        "result_retry_count",
    ]:
        if _column_exists("generationtask", name):
            op.drop_column("generationtask", name)
    for index_name in ["ix_asset_project_shot_type_sha256", "ix_asset_project_type_sha256", "ix_asset_sha256"]:
        if _index_exists("asset", index_name):
            op.drop_index(index_name, table_name="asset")
    for name in [
        "audio_codec",
        "video_codec",
        "frame_count",
        "fps",
        "duration_seconds",
        "height",
        "width",
        "file_size",
        "sha256",
    ]:
        if _column_exists("asset", name):
            op.drop_column("asset", name)
