"""add TOAPIS provider defaults

Revision ID: 20260720_0013
Revises: 20260720_0012
"""
from collections.abc import Sequence
import json
import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0013"
down_revision: str | None = "20260720_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providermodelprofile", sa.Column("remote_model", sa.String(length=160), nullable=False, server_default=""))
    db = op.get_bind()
    now = sa.func.current_timestamp()
    profile = sa.table("providerprofile", *[
        sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("provider_key", sa.String),
        sa.column("adapter_type", sa.String), sa.column("display_name", sa.String), sa.column("description", sa.String),
        sa.column("base_url", sa.String), sa.column("secret_env_var", sa.String), sa.column("enabled", sa.Boolean),
        sa.column("config_json", sa.Text), sa.column("config_revision", sa.Integer),
        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    ])
    provider_id = db.execute(sa.select(profile.c.id).where(profile.c.provider_key == "toapis")).scalar_one_or_none()
    if provider_id is None:
        db.execute(profile.insert().values(
            name="TOAPIS", provider_key="toapis", adapter_type="TOAPIS", display_name="TOAPIS",
            description="Dedicated TOAPIS image and Vidu Q3 Pro adapter.", base_url="https://toapis.com/v1",
            secret_env_var="TOAPIS_API_KEY", enabled=True, config_json="{}", config_revision=1,
            created_at=now, updated_at=now,
        ))
        provider_id = db.execute(sa.select(profile.c.id).where(profile.c.provider_key == "toapis")).scalar_one()
    model = sa.table("providermodelprofile", *[
        sa.column("provider_profile_id", sa.Integer), sa.column("model_key", sa.String), sa.column("remote_model", sa.String),
        sa.column("display_name", sa.String), sa.column("generation_type", sa.String), sa.column("enabled", sa.Boolean),
        sa.column("capabilities_json", sa.Text), sa.column("limits_json", sa.Text), sa.column("pricing_json", sa.Text),
        sa.column("currency", sa.String), sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    ])
    common = {"provider_profile_id": provider_id, "enabled": True, "pricing_json": json.dumps({"rules": []}), "currency": "USD", "created_at": now, "updated_at": now}
    rows = [
        {**common, "model_key": "toapis-seedream-5", "remote_model": "doubao-seedream-5-0", "display_name": "Seedream 5.0", "generation_type": "IMAGE",
         "capabilities_json": json.dumps({"text_to_image": True, "image_to_image": True, "reference_images": True, "max_reference_images": 10, "seed": False, "cancel": False}),
         "limits_json": json.dumps({"supported_aspect_ratios": ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9", "9:21"], "supported_resolutions": ["2K", "3K"], "default_resolution": "2K", "max_output_count": 1, "max_input_file_bytes": 10485760})},
        {**common, "model_key": "toapis-viduq3-pro", "remote_model": "viduq3-pro", "display_name": "Vidu Q3 Pro", "generation_type": "VIDEO",
         "capabilities_json": json.dumps({"text_to_video": True, "start_frame_video": True, "first_last_frame_video": True, "reference_images": False, "max_reference_images": 0, "seed": True, "cancel": False, "audio": True}),
         "limits_json": json.dumps({"min_duration_seconds": 1, "max_duration_seconds": 16, "supported_resolutions": ["540p", "720p", "1080p"], "default_resolution": "720p", "supported_aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"], "max_anchor_images": 2})},
    ]
    for row in rows:
        exists = db.execute(sa.select(model.c.model_key).where(model.c.provider_profile_id == provider_id, model.c.model_key == row["model_key"])).first()
        if exists is None:
            db.execute(model.insert().values(**row))


def downgrade() -> None:
    db = op.get_bind()
    provider_id = db.execute(sa.text("SELECT id FROM providerprofile WHERE provider_key='toapis'")).scalar_one_or_none()
    if provider_id is not None:
        db.execute(sa.text("DELETE FROM providermodelprofile WHERE provider_profile_id=:id"), {"id": provider_id})
        db.execute(sa.text("DELETE FROM providerprofile WHERE id=:id"), {"id": provider_id})
    op.drop_column("providermodelprofile", "remote_model")
