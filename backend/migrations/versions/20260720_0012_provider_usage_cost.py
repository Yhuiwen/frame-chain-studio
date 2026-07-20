"""provider profiles usage costs and budgets

Revision ID: 20260720_0012
Revises: 20260720_0011
Create Date: 2026-07-20 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260720_0012"
down_revision: str | None = "20260720_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generationrequest", sa.Column("provider_key", sa.String(), nullable=True))
    op.add_column("generationrequest", sa.Column("provider_model_key", sa.String(), nullable=True))
    op.add_column("generationrequest", sa.Column("provider_config_revision", sa.Integer(), nullable=True))
    op.add_column("generationrequest", sa.Column("provider_capability_snapshot_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("generationrequest", sa.Column("pricing_snapshot_json", sa.Text(), nullable=False, server_default="{}"))
    op.create_index("ix_generationrequest_provider_key", "generationrequest", ["provider_key"])
    op.create_index("ix_generationrequest_provider_model_key", "generationrequest", ["provider_model_key"])
    op.create_index("ix_generationrequest_provider_config_revision", "generationrequest", ["provider_config_revision"])

    op.create_table(
        "providerprofile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("provider_key", sa.String(length=120), nullable=False),
        sa.Column("adapter_type", sa.Enum("FAKE", "MAPPED_ASYNC_HTTP"), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=False),
        sa.Column("secret_env_var", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_key", name="uq_providerprofile_provider_key"),
    )
    for column in ("provider_key", "adapter_type", "enabled", "archived_at", "config_revision"):
        op.create_index(f"ix_providerprofile_{column}", "providerprofile", [column])
    op.create_index("ix_providerprofile_enabled_archived", "providerprofile", ["enabled", "archived_at"])

    op.create_table(
        "providermodelprofile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_profile_id", sa.Integer(), nullable=False),
        sa.Column("model_key", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("generation_type", sa.Enum("IMAGE", "VIDEO"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.Column("limits_json", sa.Text(), nullable=False),
        sa.Column("pricing_json", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_profile_id"], ["providerprofile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_profile_id", "model_key", name="uq_providermodel_profile_model"),
    )
    for column in ("provider_profile_id", "model_key", "generation_type", "enabled", "currency"):
        op.create_index(f"ix_providermodelprofile_{column}", "providermodelprofile", [column])
    op.create_index("ix_providermodel_profile_type", "providermodelprofile", ["provider_profile_id", "generation_type"])

    op.create_table(
        "generationusagerecord",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=True),
        sa.Column("generation_request_id", sa.Integer(), nullable=True),
        sa.Column("generation_task_id", sa.Integer(), nullable=True),
        sa.Column("provider_profile_id", sa.Integer(), nullable=True),
        sa.Column("provider_model_profile_id", sa.Integer(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("record_type", sa.Enum("ESTIMATE", "PROVIDER_REPORTED", "MANUAL_ADJUSTMENT"), nullable=False),
        sa.Column("status", sa.Enum("ESTIMATED", "ACTUAL", "UNKNOWN", "WAIVED"), nullable=False),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column("estimated_units_json", sa.Text(), nullable=False),
        sa.Column("actual_units_json", sa.Text(), nullable=False),
        sa.Column("estimated_cost", sa.String(length=80), nullable=True),
        sa.Column("actual_cost", sa.String(length=80), nullable=True),
        sa.Column("cost_source", sa.Enum("PRICING_RULE", "PROVIDER_RESPONSE", "MANUAL", "FAKE_PROVIDER", "UNKNOWN"), nullable=False),
        sa.Column("provider_usage_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["generation_request_id"], ["generationrequest.id"]),
        sa.ForeignKeyConstraint(["generation_task_id"], ["generationtask.id"]),
        sa.ForeignKeyConstraint(["provider_model_profile_id"], ["providermodelprofile.id"]),
        sa.ForeignKeyConstraint(["provider_profile_id"], ["providerprofile.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["shot_id"], ["shot.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_task_id", "attempt_number", "record_type", name="uq_usagerecord_task_attempt_type"),
    )
    for column in (
        "project_id",
        "shot_id",
        "generation_request_id",
        "generation_task_id",
        "provider_profile_id",
        "provider_model_profile_id",
        "attempt_number",
        "record_type",
        "status",
        "currency",
        "cost_source",
        "created_at",
    ):
        op.create_index(f"ix_generationusagerecord_{column}", "generationusagerecord", [column])
    op.create_index("ix_usagerecord_project_created", "generationusagerecord", ["project_id", "created_at"])
    op.create_index("ix_usagerecord_request_type", "generationusagerecord", ["generation_request_id", "record_type"])

    op.create_table(
        "projectbudgetpolicy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column("warning_limit", sa.String(length=80), nullable=True),
        sa.Column("hard_limit", sa.String(length=80), nullable=True),
        sa.Column("per_request_limit", sa.String(length=80), nullable=True),
        sa.Column("period_type", sa.Enum("PROJECT_TOTAL", "MONTHLY"), nullable=False),
        sa.Column("unknown_cost_policy", sa.Enum("ALLOW_WITH_WARNING", "BLOCK"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "period_type", name="uq_projectbudget_project_period"),
    )
    for column in ("project_id", "currency", "period_type", "unknown_cost_policy", "enabled"):
        op.create_index(f"ix_projectbudgetpolicy_{column}", "projectbudgetpolicy", [column])
    op.create_index("ix_projectbudget_project_enabled", "projectbudgetpolicy", ["project_id", "enabled"])

    op.create_table(
        "providerverificationrun",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_profile_id", sa.Integer(), nullable=False),
        sa.Column("model_profile_id", sa.Integer(), nullable=True),
        sa.Column("verification_type", sa.Enum("CONTRACT", "LIVE_IMAGE", "LIVE_VIDEO", "LIVE_CHAIN"), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "RUNNING", "PASSED", "FAILED", "BLOCKED", "CANCELLED"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("max_cost", sa.String(length=80), nullable=True),
        sa.Column("actual_cost", sa.String(length=80), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["model_profile_id"], ["providermodelprofile.id"]),
        sa.ForeignKeyConstraint(["provider_profile_id"], ["providerprofile.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("provider_profile_id", "model_profile_id", "verification_type", "status", "created_at"):
        op.create_index(f"ix_providerverificationrun_{column}", "providerverificationrun", [column])
    op.create_index("ix_providerverification_provider_created", "providerverificationrun", ["provider_profile_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_providerverification_provider_created", table_name="providerverificationrun")
    for column in ("created_at", "status", "verification_type", "model_profile_id", "provider_profile_id"):
        op.drop_index(f"ix_providerverificationrun_{column}", table_name="providerverificationrun")
    op.drop_table("providerverificationrun")

    op.drop_index("ix_projectbudget_project_enabled", table_name="projectbudgetpolicy")
    for column in ("enabled", "unknown_cost_policy", "period_type", "currency", "project_id"):
        op.drop_index(f"ix_projectbudgetpolicy_{column}", table_name="projectbudgetpolicy")
    op.drop_table("projectbudgetpolicy")

    op.drop_index("ix_usagerecord_request_type", table_name="generationusagerecord")
    op.drop_index("ix_usagerecord_project_created", table_name="generationusagerecord")
    for column in (
        "created_at",
        "cost_source",
        "currency",
        "status",
        "record_type",
        "attempt_number",
        "provider_model_profile_id",
        "provider_profile_id",
        "generation_task_id",
        "generation_request_id",
        "shot_id",
        "project_id",
    ):
        op.drop_index(f"ix_generationusagerecord_{column}", table_name="generationusagerecord")
    op.drop_table("generationusagerecord")

    op.drop_index("ix_providermodel_profile_type", table_name="providermodelprofile")
    for column in ("currency", "enabled", "generation_type", "model_key", "provider_profile_id"):
        op.drop_index(f"ix_providermodelprofile_{column}", table_name="providermodelprofile")
    op.drop_table("providermodelprofile")

    op.drop_index("ix_providerprofile_enabled_archived", table_name="providerprofile")
    for column in ("config_revision", "archived_at", "enabled", "adapter_type", "provider_key"):
        op.drop_index(f"ix_providerprofile_{column}", table_name="providerprofile")
    op.drop_table("providerprofile")

    op.drop_index("ix_generationrequest_provider_config_revision", table_name="generationrequest")
    op.drop_index("ix_generationrequest_provider_model_key", table_name="generationrequest")
    op.drop_index("ix_generationrequest_provider_key", table_name="generationrequest")
    op.drop_column("generationrequest", "pricing_snapshot_json")
    op.drop_column("generationrequest", "provider_capability_snapshot_json")
    op.drop_column("generationrequest", "provider_config_revision")
    op.drop_column("generationrequest", "provider_model_key")
    op.drop_column("generationrequest", "provider_key")
