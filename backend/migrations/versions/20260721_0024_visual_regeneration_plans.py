"""Add visual regeneration plans and review events."""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0024"
down_revision: str | None = "20260721_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visualregenerationplan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_run_id", sa.Integer(), nullable=False),
        sa.Column("source_render_id", sa.Integer()),
        sa.Column("source_visual_report_ids_json", sa.String(), nullable=False),
        sa.Column("plan_version", sa.String(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("target_shot_ids_json", sa.String(), nullable=False),
        sa.Column("preserved_shot_ids_json", sa.String(), nullable=False),
        sa.Column("source_asset_ids_json", sa.String(), nullable=False),
        sa.Column("replacement_asset_policy", sa.String(), nullable=False),
        sa.Column("prompt_contract_json", sa.String(), nullable=False),
        sa.Column("keyframe_plan_json", sa.String(), nullable=False),
        sa.Column("video_plan_json", sa.String(), nullable=False),
        sa.Column("reason_codes_json", sa.String(), nullable=False),
        sa.Column("automatic_recommendation", sa.String(), nullable=False),
        sa.Column("human_decision", sa.String(), nullable=False),
        sa.Column("review_comment", sa.String(2000), nullable=False),
        sa.Column("estimated_image_submits", sa.Integer(), nullable=False),
        sa.Column("estimated_video_submits", sa.Integer(), nullable=False),
        sa.Column("estimated_video_seconds", sa.String(), nullable=False),
        sa.Column("estimated_billing_units", sa.String(), nullable=False),
        sa.Column("maximum_billing_units", sa.String(), nullable=False),
        sa.Column("billing_unit", sa.String(), nullable=False),
        sa.Column("pricing_snapshot_hash", sa.String(64)),
        sa.Column("superseded_by_plan_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime()),
        sa.Column("executed_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["source_run_id"], ["providerverificationrun.id"]),
        sa.ForeignKeyConstraint(["source_render_id"], ["projectrender.id"]),
        sa.ForeignKeyConstraint(["superseded_by_plan_id"], ["visualregenerationplan.id"]),
        sa.UniqueConstraint(
            "source_run_id",
            "plan_version",
            "config_hash",
            "strategy",
            name="uq_visualregen_source_version_config_strategy",
        ),
    )
    for column in (
        "project_id",
        "source_run_id",
        "plan_version",
        "config_hash",
        "plan_hash",
        "status",
        "scope",
        "strategy",
        "human_decision",
        "created_at",
    ):
        op.create_index(f"ix_visualregenerationplan_{column}", "visualregenerationplan", [column])
    op.create_table(
        "visualregenerationreviewevent",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("expected_plan_hash", sa.String(64), nullable=False),
        sa.Column("review_comment", sa.String(2000), nullable=False),
        sa.Column("acknowledged_visual_failures", sa.Boolean(), nullable=False),
        sa.Column("acknowledged_estimated_cost", sa.Boolean(), nullable=False),
        sa.Column("acknowledged_no_execution", sa.Boolean(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["visualregenerationplan.id"]),
    )
    op.create_index(
        "ix_visualregenerationreviewevent_plan_id", "visualregenerationreviewevent", ["plan_id"]
    )
    op.create_index(
        "ix_visualregenerationreviewevent_reviewed_at",
        "visualregenerationreviewevent",
        ["reviewed_at"],
    )


def downgrade() -> None:
    op.drop_table("visualregenerationreviewevent")
    op.drop_table("visualregenerationplan")
