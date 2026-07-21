"""Failed TOAPIS run recovery lineage and normalized video frames.

Revision ID: 20260721_0019
Revises: 20260721_0018
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0019"
down_revision: str | None = "20260721_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("providerverificationrun") as batch_op:
        batch_op.add_column(sa.Column("recovery_of_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("lineage_root_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("normalized_start_asset_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("normalized_end_asset_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("historical_image_submits", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("historical_video_submits", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("remaining_image_submit_limit", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("remaining_video_submit_limit", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("historical_billing_units", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("estimated_remaining_billing_units", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("estimated_lineage_billing_units", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("maximum_lineage_billing_units", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("recovery_plan_hash", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("recovery_authorization_reference", sa.String(200), nullable=True))
        batch_op.create_foreign_key("fk_verification_recovery_of", "providerverificationrun", ["recovery_of_run_id"], ["id"])
        batch_op.create_foreign_key("fk_verification_lineage_root", "providerverificationrun", ["lineage_root_run_id"], ["id"])
        batch_op.create_foreign_key("fk_verification_normalized_start", "asset", ["normalized_start_asset_id"], ["id"])
        batch_op.create_foreign_key("fk_verification_normalized_end", "asset", ["normalized_end_asset_id"], ["id"])
        batch_op.create_unique_constraint("uq_providerverification_recovery_of_run", ["recovery_of_run_id"])
        batch_op.create_index("ix_providerverificationrun_recovery_of_run_id", ["recovery_of_run_id"])
        batch_op.create_index("ix_providerverificationrun_lineage_root_run_id", ["lineage_root_run_id"])
        batch_op.create_index("ix_providerverificationrun_recovery_plan_hash", ["recovery_plan_hash"])

    with op.batch_alter_table("generationtask") as batch_op:
        batch_op.add_column(sa.Column("recovery_run_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_generationtask_recovery_run", "providerverificationrun", ["recovery_run_id"], ["id"])
        batch_op.create_index("ix_generationtask_recovery_run_id", ["recovery_run_id"])

    op.create_table(
        "videoinputframenormalization",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_asset_id", sa.Integer(), sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("normalized_asset_id", sa.Integer(), sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("purpose", sa.String(80), nullable=False),
        sa.Column("frame_role", sa.String(16), nullable=False),
        sa.Column("normalization_version", sa.String(80), nullable=False),
        sa.Column("target_width", sa.Integer(), nullable=False),
        sa.Column("target_height", sa.Integer(), nullable=False),
        sa.Column("resize_mode", sa.String(40), nullable=False),
        sa.Column("crop_applied", sa.Boolean(), nullable=False),
        sa.Column("padding_applied", sa.Boolean(), nullable=False),
        sa.Column("padding_left", sa.Integer(), nullable=False),
        sa.Column("padding_right", sa.Integer(), nullable=False),
        sa.Column("padding_top", sa.Integer(), nullable=False),
        sa.Column("padding_bottom", sa.Integer(), nullable=False),
        sa.Column("padding_color", sa.String(32), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_asset_id", "normalization_version", "target_width", "target_height", name="uq_video_input_normalization_source_version_size"),
        sa.UniqueConstraint("normalized_asset_id", name="uq_video_input_normalization_asset"),
    )
    op.create_index("ix_videoinputframenormalization_source_asset_id", "videoinputframenormalization", ["source_asset_id"])
    op.create_index("ix_videoinputframenormalization_normalized_asset_id", "videoinputframenormalization", ["normalized_asset_id"])
    op.create_index("ix_videoinputframenormalization_normalization_version", "videoinputframenormalization", ["normalization_version"])
    op.create_index("ix_videoinputframenormalization_normalized_sha256", "videoinputframenormalization", ["normalized_sha256"])
    op.execute("UPDATE providerprofile SET live_orchestration_enabled=0 WHERE provider_key='toapis'")


def downgrade() -> None:
    op.drop_table("videoinputframenormalization")
    with op.batch_alter_table("generationtask") as batch_op:
        batch_op.drop_index("ix_generationtask_recovery_run_id")
        batch_op.drop_constraint("fk_generationtask_recovery_run", type_="foreignkey")
        batch_op.drop_column("recovery_run_id")
    with op.batch_alter_table("providerverificationrun") as batch_op:
        batch_op.drop_index("ix_providerverificationrun_recovery_plan_hash")
        batch_op.drop_index("ix_providerverificationrun_lineage_root_run_id")
        batch_op.drop_index("ix_providerverificationrun_recovery_of_run_id")
        batch_op.drop_constraint("uq_providerverification_recovery_of_run", type_="unique")
        batch_op.drop_constraint("fk_verification_normalized_end", type_="foreignkey")
        batch_op.drop_constraint("fk_verification_normalized_start", type_="foreignkey")
        batch_op.drop_constraint("fk_verification_lineage_root", type_="foreignkey")
        batch_op.drop_constraint("fk_verification_recovery_of", type_="foreignkey")
        for name in (
            "recovery_authorization_reference", "recovery_plan_hash", "maximum_lineage_billing_units",
            "estimated_lineage_billing_units", "estimated_remaining_billing_units", "historical_billing_units",
            "remaining_video_submit_limit", "remaining_image_submit_limit", "historical_video_submits",
            "historical_image_submits", "normalized_end_asset_id", "normalized_start_asset_id",
            "lineage_root_run_id", "recovery_of_run_id",
        ):
            batch_op.drop_column(name)
