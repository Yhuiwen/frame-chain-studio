"""TOAPIS live enable and reviewed pricing gate

Revision ID: 20260720_0014
Revises: 20260720_0013
"""
from collections.abc import Sequence
import json
import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0014"
down_revision: str | None = "20260720_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    profile_columns = [
        sa.Column("live_orchestration_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_enabled_at", sa.DateTime(), nullable=True),
        sa.Column("live_enabled_by", sa.String(120), nullable=True),
        sa.Column("live_enable_reason", sa.String(500), nullable=True),
        sa.Column("contract_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("contract_reviewed_by", sa.String(120), nullable=True),
        sa.Column("contract_reference", sa.String(500), nullable=True),
        sa.Column("preflight_checked_at", sa.DateTime(), nullable=True),
        sa.Column("preflight_image_model_accessible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("preflight_video_model_accessible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("preflight_response_schema_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("account_balance_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("account_balance_sufficient", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("account_balance_note", sa.String(500), nullable=True),
    ]
    for column in profile_columns:
        op.add_column("providerprofile", column)
    op.create_index("ix_providerprofile_live_orchestration_enabled", "providerprofile", ["live_orchestration_enabled"])

    model_columns = [
        sa.Column("billing_unit", sa.String(40), nullable=False, server_default="USD"),
        sa.Column("pricing_version", sa.String(120), nullable=False, server_default=""),
        sa.Column("pricing_source", sa.String(500), nullable=False, server_default=""),
        sa.Column("pricing_effective_at", sa.DateTime(), nullable=True),
        sa.Column("pricing_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("pricing_reviewed_by", sa.String(120), nullable=True),
        sa.Column("pricing_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("pricing_review_status", sa.String(20), nullable=False, server_default="PENDING"),
    ]
    for column in model_columns:
        op.add_column("providermodelprofile", column)
    op.create_index("ix_providermodelprofile_billing_unit", "providermodelprofile", ["billing_unit"])
    op.create_index("ix_providermodelprofile_pricing_snapshot_hash", "providermodelprofile", ["pricing_snapshot_hash"])
    op.create_index("ix_providermodelprofile_pricing_review_status", "providermodelprofile", ["pricing_review_status"])

    op.add_column("projectbudgetpolicy", sa.Column("billing_unit", sa.String(40), nullable=False, server_default="USD"))
    op.create_index("ix_projectbudgetpolicy_billing_unit", "projectbudgetpolicy", ["billing_unit"])
    op.add_column("generationusagerecord", sa.Column("billing_unit", sa.String(40), nullable=False, server_default="USD"))
    op.create_index("ix_generationusagerecord_billing_unit", "generationusagerecord", ["billing_unit"])
    request_columns = [
        sa.Column("provider_live_enable_snapshot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pricing_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("billing_unit", sa.String(40), nullable=True),
        sa.Column("estimated_billing_units", sa.String(80), nullable=True),
        sa.Column("contract_review_reference", sa.String(500), nullable=True),
        sa.Column("preflight_checked_at", sa.DateTime(), nullable=True),
    ]
    for column in request_columns:
        op.add_column("generationrequest", column)

    db = op.get_bind()
    candidates = {
        "toapis-seedream-5": {"rules": [{"unit": "IMAGE_REQUEST", "price": "6.3"}]},
        "toapis-viduq3-pro": {"rules": [{"unit": "VIDEO_SECOND", "price": "20"}]},
    }
    for model_key, pricing in candidates.items():
        db.execute(sa.text("""
            UPDATE providermodelprofile
            SET pricing_json=:pricing, billing_unit='TOAPIS_CREDIT',
                pricing_version='toapis-public-2026-07',
                pricing_source='TOAPIS public pricing candidate reviewed manually',
                pricing_review_status='PENDING', pricing_snapshot_hash=NULL,
                pricing_reviewed_at=NULL, pricing_reviewed_by=NULL
            WHERE model_key=:model_key
        """), {"pricing": json.dumps(pricing, separators=(",", ":")), "model_key": model_key})


def downgrade() -> None:
    for table, index in [
        ("generationusagerecord", "ix_generationusagerecord_billing_unit"),
        ("projectbudgetpolicy", "ix_projectbudgetpolicy_billing_unit"),
        ("providermodelprofile", "ix_providermodelprofile_pricing_review_status"),
        ("providermodelprofile", "ix_providermodelprofile_pricing_snapshot_hash"),
        ("providermodelprofile", "ix_providermodelprofile_billing_unit"),
        ("providerprofile", "ix_providerprofile_live_orchestration_enabled"),
    ]:
        op.drop_index(index, table_name=table)
    for column in ["preflight_checked_at", "contract_review_reference", "estimated_billing_units", "billing_unit", "pricing_snapshot_hash", "provider_live_enable_snapshot"]:
        op.drop_column("generationrequest", column)
    op.drop_column("generationusagerecord", "billing_unit")
    op.drop_column("projectbudgetpolicy", "billing_unit")
    for column in ["pricing_review_status", "pricing_snapshot_hash", "pricing_reviewed_by", "pricing_reviewed_at", "pricing_effective_at", "pricing_source", "pricing_version", "billing_unit"]:
        op.drop_column("providermodelprofile", column)
    for column in ["account_balance_note", "account_balance_sufficient", "account_balance_reviewed_at", "preflight_response_schema_valid", "preflight_video_model_accessible", "preflight_image_model_accessible", "preflight_checked_at", "contract_reference", "contract_reviewed_by", "contract_reviewed_at", "live_enable_reason", "live_enabled_by", "live_enabled_at", "live_orchestration_enabled"]:
        op.drop_column("providerprofile", column)
