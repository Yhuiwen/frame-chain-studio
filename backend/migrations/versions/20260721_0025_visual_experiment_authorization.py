"""Add project visual baselines and experiment authorization packages."""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0025"
down_revision: str | None = "20260721_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projectvisualbaseline",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_asset_id", sa.Integer(), nullable=False), sa.Column("source_run_id", sa.Integer()),
        sa.Column("source_shot_id", sa.Integer()), sa.Column("baseline_version", sa.String(), nullable=False),
        sa.Column("baseline_hash", sa.String(64), nullable=False), sa.Column("status", sa.String(), nullable=False),
        sa.Column("character_lock_json", sa.String(), nullable=False), sa.Column("camera_lock_json", sa.String(), nullable=False),
        sa.Column("environment_lock_json", sa.String(), nullable=False), sa.Column("style_lock_json", sa.String(), nullable=False),
        sa.Column("forbidden_changes_json", sa.String(), nullable=False), sa.Column("automatic_metrics_json", sa.String(), nullable=False),
        sa.Column("human_review_status", sa.String(), nullable=False), sa.Column("human_review_comment", sa.String(2000), nullable=False),
        sa.Column("approved_at", sa.DateTime()), sa.Column("superseded_by_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]), sa.ForeignKeyConstraint(["source_asset_id"], ["asset.id"]),
        sa.ForeignKeyConstraint(["source_run_id"], ["providerverificationrun.id"]), sa.ForeignKeyConstraint(["source_shot_id"], ["shot.id"]),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["projectvisualbaseline.id"]),
    )
    for c in ("project_id","source_asset_id","baseline_version","baseline_hash","status","human_review_status","created_at"):
        op.create_index(f"ix_projectvisualbaseline_{c}", "projectvisualbaseline", [c])
    op.create_table(
        "visualexperimentauthorizationpackage",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_run_id", sa.Integer(), nullable=False), sa.Column("regeneration_plan_id", sa.Integer()),
        sa.Column("candidate_type", sa.String(), nullable=False), sa.Column("visual_baseline_id", sa.Integer()),
        sa.Column("baseline_hash", sa.String(64)), sa.Column("prompt_contract_hash", sa.String(64), nullable=False),
        sa.Column("compiled_prompt_hashes_json", sa.String(), nullable=False), sa.Column("regeneration_plan_hash", sa.String(64), nullable=False),
        sa.Column("experiment_plan_hash", sa.String(64), nullable=False), sa.Column("target_shot_count", sa.Integer(), nullable=False),
        sa.Column("maximum_image_submits", sa.Integer(), nullable=False), sa.Column("maximum_video_submits", sa.Integer(), nullable=False),
        sa.Column("video_duration_seconds_each", sa.Integer(), nullable=False), sa.Column("maximum_total_video_seconds", sa.Integer(), nullable=False),
        sa.Column("estimated_billing_units", sa.String(), nullable=False), sa.Column("maximum_billing_units", sa.String(), nullable=False),
        sa.Column("billing_unit", sa.String(), nullable=False), sa.Column("pricing_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("pricing_reviewed", sa.Boolean(), nullable=False), sa.Column("balance_review_valid", sa.Boolean(), nullable=False),
        sa.Column("model_access_valid", sa.Boolean(), nullable=False), sa.Column("human_plan_review_status", sa.String(), nullable=False),
        sa.Column("human_baseline_review_status", sa.String(), nullable=False), sa.Column("authorization_status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]), sa.ForeignKeyConstraint(["source_run_id"], ["providerverificationrun.id"]),
        sa.ForeignKeyConstraint(["regeneration_plan_id"], ["visualregenerationplan.id"]), sa.ForeignKeyConstraint(["visual_baseline_id"], ["projectvisualbaseline.id"]),
    )
    for c in ("project_id","source_run_id","candidate_type","experiment_plan_hash","human_plan_review_status","human_baseline_review_status","authorization_status","created_at"):
        op.create_index(f"ix_visualexperimentauthorizationpackage_{c}", "visualexperimentauthorizationpackage", [c])


def downgrade() -> None:
    op.drop_table("visualexperimentauthorizationpackage")
    op.drop_table("projectvisualbaseline")
