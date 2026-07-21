"""Add independent offline visual continuity reports.

Revision ID: 20260721_0022
Revises: 20260721_0021
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0022"
down_revision: str | None = "20260721_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visualcontinuityreport",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("shot_id", sa.Integer(), sa.ForeignKey("shot.id"), nullable=True),
        sa.Column("video_asset_id", sa.Integer(), sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("start_anchor_asset_id", sa.Integer(), sa.ForeignKey("asset.id"), nullable=True),
        sa.Column("target_keyframe_asset_id", sa.Integer(), sa.ForeignKey("asset.id"), nullable=True),
        sa.Column("tail_frame_asset_id", sa.Integer(), sa.ForeignKey("asset.id"), nullable=True),
        sa.Column("analysis_version", sa.String(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("report_hash", sa.String(64), nullable=False),
        sa.Column("technical_status", sa.String(12), nullable=False),
        sa.Column("automatic_visual_status", sa.String(12), nullable=False),
        sa.Column("human_visual_status", sa.String(12), nullable=False),
        sa.Column("overall_visual_status", sa.String(12), nullable=False),
        sa.Column("scene_cut_status", sa.String(12), nullable=False),
        sa.Column("anchor_match_status", sa.String(12), nullable=False),
        sa.Column("target_match_status", sa.String(12), nullable=False),
        sa.Column("camera_stability_status", sa.String(12), nullable=False),
        sa.Column("composition_drift_status", sa.String(12), nullable=False),
        sa.Column("subject_scale_drift_status", sa.String(12), nullable=False),
        sa.Column("style_drift_status", sa.String(12), nullable=False),
        sa.Column("cross_shot_seam_status", sa.String(12), nullable=False),
        sa.Column("production_gate_status", sa.String(12), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("rejection_reasons_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "video_asset_id", "analysis_version", "config_hash",
            name="uq_visualcontinuity_asset_version_config",
        ),
    )
    op.create_index("ix_visualcontinuityreport_project_id", "visualcontinuityreport", ["project_id"])
    op.create_index("ix_visualcontinuityreport_shot_id", "visualcontinuityreport", ["shot_id"])
    op.create_index("ix_visualcontinuityreport_video_asset_id", "visualcontinuityreport", ["video_asset_id"])
    op.create_index("ix_visualcontinuityreport_analysis_version", "visualcontinuityreport", ["analysis_version"])
    op.create_index("ix_visualcontinuityreport_config_hash", "visualcontinuityreport", ["config_hash"])
    op.create_index("ix_visualcontinuityreport_report_hash", "visualcontinuityreport", ["report_hash"])
    op.create_index(
        "ix_visualcontinuity_project_shot_created",
        "visualcontinuityreport", ["project_id", "shot_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("visualcontinuityreport")
