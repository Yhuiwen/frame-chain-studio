"""Persist recoverable TOAPIS two-shot verification state.

Revision ID: 20260721_0015
Revises: 20260720_0014
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0015"
down_revision: str | None = "20260720_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = [
        sa.Column("workflow_version", sa.String(80), nullable=False, server_default="toapis-two-shot-v1"),
        sa.Column("current_stage", sa.String(80), nullable=False, server_default="CREATED"),
        sa.Column("verification_project_id", sa.Integer(), sa.ForeignKey("project.id", name="fk_verification_project"), nullable=True),
        sa.Column("shot_1_id", sa.Integer(), sa.ForeignKey("shot.id", name="fk_verification_shot_1"), nullable=True),
        sa.Column("shot_2_id", sa.Integer(), sa.ForeignKey("shot.id", name="fk_verification_shot_2"), nullable=True),
        sa.Column("initial_anchor_asset_id", sa.Integer(), sa.ForeignKey("asset.id", name="fk_verification_anchor"), nullable=True),
        sa.Column("shot_1_keyframe_request_id", sa.Integer(), sa.ForeignKey("generationrequest.id", name="fk_verification_s1_keyframe"), nullable=True),
        sa.Column("shot_1_video_request_id", sa.Integer(), sa.ForeignKey("generationrequest.id", name="fk_verification_s1_video"), nullable=True),
        sa.Column("shot_2_keyframe_request_id", sa.Integer(), sa.ForeignKey("generationrequest.id", name="fk_verification_s2_keyframe"), nullable=True),
        sa.Column("shot_2_video_request_id", sa.Integer(), sa.ForeignKey("generationrequest.id", name="fk_verification_s2_video"), nullable=True),
        sa.Column("render_id", sa.Integer(), sa.ForeignKey("projectrender.id", name="fk_verification_render"), nullable=True),
        sa.Column("final_render_asset_id", sa.Integer(), sa.ForeignKey("asset.id", name="fk_verification_final_asset"), nullable=True),
        sa.Column("pricing_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("billing_unit", sa.String(40), nullable=True),
        sa.Column("estimated_billing_units", sa.String(80), nullable=True),
        sa.Column("reserved_billing_units", sa.String(80), nullable=True),
        sa.Column("auto_approve_for_verification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failure_stage", sa.String(80), nullable=True),
        sa.Column("failure_code", sa.String(120), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
    ]
    with op.batch_alter_table("providerverificationrun") as batch_op:
        for column in columns:
            batch_op.add_column(column)
    op.create_index("ix_providerverificationrun_current_stage", "providerverificationrun", ["current_stage"])
    op.create_index("ix_providerverificationrun_verification_project_id", "providerverificationrun", ["verification_project_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_providerverificationrun_verification_project_id", table_name="providerverificationrun")
    op.drop_index("ix_providerverificationrun_current_stage", table_name="providerverificationrun")
    with op.batch_alter_table("providerverificationrun") as batch_op:
        for column in [
            "state_version", "failure_code", "failure_stage", "auto_approve_for_verification",
            "reserved_billing_units", "estimated_billing_units", "billing_unit", "pricing_snapshot_hash",
            "final_render_asset_id", "render_id", "shot_2_video_request_id", "shot_2_keyframe_request_id",
            "shot_1_video_request_id", "shot_1_keyframe_request_id", "initial_anchor_asset_id",
            "shot_2_id", "shot_1_id", "verification_project_id", "current_stage", "workflow_version",
        ]:
            batch_op.drop_column(column)
