"""structured continuity library and shot specs

Revision ID: 20260720_0010
Revises: 20260720_0009
Create Date: 2026-07-20 12:00:00.000000
"""

from collections.abc import Sequence
import json

import sqlalchemy as sa
from alembic import op


revision: str = "20260720_0010"
down_revision: str | None = "20260720_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "character",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=False),
        sa.Column("appearance", sa.String(length=4000), nullable=False),
        sa.Column("personality", sa.String(length=2000), nullable=False),
        sa.Column("default_clothing", sa.String(length=2000), nullable=False),
        sa.Column("default_props_json", sa.Text(), nullable=False),
        sa.Column("continuity_notes", sa.String(length=4000), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_character_project_name"),
    )
    op.create_index("ix_character_project_id", "character", ["project_id"])
    op.create_index("ix_character_archived_at", "character", ["archived_at"])
    op.create_index("ix_character_project_archived", "character", ["project_id", "archived_at"])

    op.create_table(
        "location",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=False),
        sa.Column("environment", sa.String(length=2000), nullable=False),
        sa.Column("architecture", sa.String(length=2000), nullable=False),
        sa.Column("time_of_day", sa.String(length=120), nullable=False),
        sa.Column("weather", sa.String(length=120), nullable=False),
        sa.Column("lighting", sa.String(length=2000), nullable=False),
        sa.Column("continuity_notes", sa.String(length=4000), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_location_project_name"),
    )
    op.create_index("ix_location_project_id", "location", ["project_id"])
    op.create_index("ix_location_archived_at", "location", ["archived_at"])
    op.create_index("ix_location_project_archived", "location", ["project_id", "archived_at"])

    op.create_table(
        "styleprofile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=False),
        sa.Column("positive_prompt", sa.String(length=4000), nullable=False),
        sa.Column("negative_prompt", sa.String(length=4000), nullable=False),
        sa.Column("color_palette_json", sa.Text(), nullable=False),
        sa.Column("rendering_style", sa.String(length=1000), nullable=False),
        sa.Column("camera_language", sa.String(length=1000), nullable=False),
        sa.Column("aspect_ratio", sa.String(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("default_provider_options_json", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_styleprofile_project_name"),
    )
    op.create_index("ix_styleprofile_project_id", "styleprofile", ["project_id"])
    op.create_index("ix_styleprofile_archived_at", "styleprofile", ["archived_at"])
    op.create_index("ix_styleprofile_project_archived", "styleprofile", ["project_id", "archived_at"])

    op.create_table(
        "characterreference",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.ForeignKeyConstraint(["character_id"], ["character.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("character_id", "asset_id", "reference_type", name="uq_characterreference_character_asset_type"),
    )
    op.create_index("ix_characterreference_character_id", "characterreference", ["character_id"])
    op.create_index("ix_characterreference_asset_id", "characterreference", ["asset_id"])
    op.create_index("ix_characterreference_reference_type", "characterreference", ["reference_type"])
    op.create_index("ix_characterreference_is_primary", "characterreference", ["is_primary"])
    op.create_index("ix_characterreference_sort_order", "characterreference", ["sort_order"])
    op.create_index("ix_characterreference_character_sort", "characterreference", ["character_id", "sort_order"])

    op.create_table(
        "locationreference",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "asset_id", "reference_type", name="uq_locationreference_location_asset_type"),
    )
    op.create_index("ix_locationreference_location_id", "locationreference", ["location_id"])
    op.create_index("ix_locationreference_asset_id", "locationreference", ["asset_id"])
    op.create_index("ix_locationreference_reference_type", "locationreference", ["reference_type"])
    op.create_index("ix_locationreference_is_primary", "locationreference", ["is_primary"])
    op.create_index("ix_locationreference_sort_order", "locationreference", ["sort_order"])
    op.create_index("ix_locationreference_location_sort", "locationreference", ["location_id", "sort_order"])

    op.create_table(
        "shotspec",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("style_profile_id", sa.Integer(), nullable=True),
        sa.Column("summary", sa.String(length=4000), nullable=False),
        sa.Column("action", sa.String(length=4000), nullable=False),
        sa.Column("emotion", sa.String(length=1000), nullable=False),
        sa.Column("composition", sa.String(length=2000), nullable=False),
        sa.Column("shot_size", sa.String(length=120), nullable=False),
        sa.Column("camera_angle", sa.String(length=240), nullable=False),
        sa.Column("camera_movement", sa.String(length=1000), nullable=False),
        sa.Column("lighting", sa.String(length=2000), nullable=False),
        sa.Column("time_of_day", sa.String(length=120), nullable=False),
        sa.Column("weather", sa.String(length=120), nullable=False),
        sa.Column("dialogue", sa.String(length=4000), nullable=False),
        sa.Column("continuity_notes", sa.String(length=4000), nullable=False),
        sa.Column("props_json", sa.Text(), nullable=False),
        sa.Column("provider_overrides_json", sa.Text(), nullable=False),
        sa.Column("compiled_prompt", sa.String(length=12000), nullable=False),
        sa.Column("compiled_negative_prompt", sa.String(length=6000), nullable=False),
        sa.Column("structured_payload_json", sa.Text(), nullable=False),
        sa.Column("compiler_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.ForeignKeyConstraint(["shot_id"], ["shot.id"]),
        sa.ForeignKeyConstraint(["style_profile_id"], ["styleprofile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shot_id", "revision", name="uq_shotspec_shot_revision"),
    )
    op.create_index("ix_shotspec_shot_id", "shotspec", ["shot_id"])
    op.create_index("ix_shotspec_revision", "shotspec", ["revision"])
    op.create_index("ix_shotspec_location_id", "shotspec", ["location_id"])
    op.create_index("ix_shotspec_style_profile_id", "shotspec", ["style_profile_id"])
    op.create_index("ix_shotspec_compiler_version", "shotspec", ["compiler_version"])
    op.create_index("ix_shotspec_location_revision", "shotspec", ["location_id", "revision"])
    op.create_index("ix_shotspec_style_revision", "shotspec", ["style_profile_id", "revision"])

    op.create_table(
        "shotcharacter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shot_spec_id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("appearance_override", sa.String(length=4000), nullable=False),
        sa.Column("clothing_override", sa.String(length=2000), nullable=False),
        sa.Column("expression", sa.String(length=1000), nullable=False),
        sa.Column("action", sa.String(length=2000), nullable=False),
        sa.Column("position", sa.String(length=1000), nullable=False),
        sa.Column("props_json", sa.Text(), nullable=False),
        sa.Column("continuity_notes", sa.String(length=4000), nullable=False),
        sa.Column("reference_asset_ids_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["character.id"]),
        sa.ForeignKeyConstraint(["shot_spec_id"], ["shotspec.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shot_spec_id", "character_id", name="uq_shotcharacter_spec_character"),
    )
    op.create_index("ix_shotcharacter_shot_spec_id", "shotcharacter", ["shot_spec_id"])
    op.create_index("ix_shotcharacter_character_id", "shotcharacter", ["character_id"])
    op.create_index("ix_shotcharacter_role", "shotcharacter", ["role"])
    op.create_index("ix_shotcharacter_sort_order", "shotcharacter", ["sort_order"])
    op.create_index("ix_shotcharacter_spec_sort", "shotcharacter", ["shot_spec_id", "sort_order"])

    with op.batch_alter_table("generationrequest") as batch_op:
        batch_op.add_column(sa.Column("structured_payload_json", sa.Text(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("compiler_version", sa.String(length=80), nullable=False, server_default="legacy-v1"))
        batch_op.create_index("ix_generationrequest_compiler_version", ["compiler_version"])
    with op.batch_alter_table("generationrequest") as batch_op:
        batch_op.alter_column("structured_payload_json", server_default=None)
        batch_op.alter_column("compiler_version", server_default=None)

    op.execute(
        """
        INSERT INTO shotspec (
            shot_id, revision, summary, action, emotion, composition, shot_size,
            camera_angle, camera_movement, lighting, time_of_day, weather, dialogue,
            continuity_notes, props_json, provider_overrides_json, compiled_prompt,
            compiled_negative_prompt, structured_payload_json, compiler_version, created_at
        )
        SELECT
            id,
            spec_revision,
            COALESCE(description, ''),
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            COALESCE(description, ''),
            '[]',
            '{}',
            COALESCE(prompt, ''),
            COALESCE(negative_prompt, ''),
            '{}',
            'structured-continuity-v1',
            COALESCE(updated_at, created_at)
        FROM shot
        WHERE NOT EXISTS (
            SELECT 1 FROM shotspec
            WHERE shotspec.shot_id = shot.id
              AND shotspec.revision = shot.spec_revision
        )
        """
    )
    _backfill_structured_payloads()


def downgrade() -> None:
    with op.batch_alter_table("generationrequest") as batch_op:
        batch_op.drop_index("ix_generationrequest_compiler_version")
        batch_op.drop_column("compiler_version")
        batch_op.drop_column("structured_payload_json")

    op.drop_index("ix_shotcharacter_spec_sort", table_name="shotcharacter")
    op.drop_index("ix_shotcharacter_sort_order", table_name="shotcharacter")
    op.drop_index("ix_shotcharacter_role", table_name="shotcharacter")
    op.drop_index("ix_shotcharacter_character_id", table_name="shotcharacter")
    op.drop_index("ix_shotcharacter_shot_spec_id", table_name="shotcharacter")
    op.drop_table("shotcharacter")

    op.drop_index("ix_shotspec_style_revision", table_name="shotspec")
    op.drop_index("ix_shotspec_location_revision", table_name="shotspec")
    op.drop_index("ix_shotspec_compiler_version", table_name="shotspec")
    op.drop_index("ix_shotspec_style_profile_id", table_name="shotspec")
    op.drop_index("ix_shotspec_location_id", table_name="shotspec")
    op.drop_index("ix_shotspec_revision", table_name="shotspec")
    op.drop_index("ix_shotspec_shot_id", table_name="shotspec")
    op.drop_table("shotspec")

    op.drop_index("ix_locationreference_location_sort", table_name="locationreference")
    op.drop_index("ix_locationreference_sort_order", table_name="locationreference")
    op.drop_index("ix_locationreference_is_primary", table_name="locationreference")
    op.drop_index("ix_locationreference_reference_type", table_name="locationreference")
    op.drop_index("ix_locationreference_asset_id", table_name="locationreference")
    op.drop_index("ix_locationreference_location_id", table_name="locationreference")
    op.drop_table("locationreference")

    op.drop_index("ix_characterreference_character_sort", table_name="characterreference")
    op.drop_index("ix_characterreference_sort_order", table_name="characterreference")
    op.drop_index("ix_characterreference_is_primary", table_name="characterreference")
    op.drop_index("ix_characterreference_reference_type", table_name="characterreference")
    op.drop_index("ix_characterreference_asset_id", table_name="characterreference")
    op.drop_index("ix_characterreference_character_id", table_name="characterreference")
    op.drop_table("characterreference")

    op.drop_index("ix_styleprofile_project_archived", table_name="styleprofile")
    op.drop_index("ix_styleprofile_archived_at", table_name="styleprofile")
    op.drop_index("ix_styleprofile_project_id", table_name="styleprofile")
    op.drop_table("styleprofile")

    op.drop_index("ix_location_project_archived", table_name="location")
    op.drop_index("ix_location_archived_at", table_name="location")
    op.drop_index("ix_location_project_id", table_name="location")
    op.drop_table("location")

    op.drop_index("ix_character_project_archived", table_name="character")
    op.drop_index("ix_character_archived_at", table_name="character")
    op.drop_index("ix_character_project_id", table_name="character")
    op.drop_table("character")


def _backfill_structured_payloads() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT
                shotspec.id AS spec_id,
                shotspec.shot_id AS shot_id,
                shotspec.revision AS revision,
                shot.title AS shot_title,
                shot.prompt AS shot_prompt,
                shot.negative_prompt AS shot_negative_prompt,
                shotspec.summary AS summary,
                shotspec.action AS action,
                shotspec.emotion AS emotion,
                shotspec.composition AS composition,
                shotspec.shot_size AS shot_size,
                shotspec.camera_angle AS camera_angle,
                shotspec.camera_movement AS camera_movement,
                shotspec.lighting AS lighting,
                shotspec.time_of_day AS time_of_day,
                shotspec.weather AS weather,
                shotspec.dialogue AS dialogue,
                shotspec.continuity_notes AS continuity_notes,
                shotspec.props_json AS props_json,
                shotspec.provider_overrides_json AS provider_overrides_json
            FROM shotspec
            JOIN shot ON shot.id = shotspec.shot_id
            """
        )
    ).mappings()
    payloads_by_key: dict[tuple[int, int], str] = {}
    for row in rows:
        payload = {
            "compiler_version": "structured-continuity-v1",
            "shot_revision": row["revision"],
            "shot_title": row["shot_title"] or "",
            "provider_overrides": _loads_dict(row["provider_overrides_json"]),
            "style": {
                "positive_prompt": "",
                "negative_prompt": "",
                "rendering_style": "",
                "camera_language": "",
            },
            "location": {
                "name": "",
                "description": "",
                "environment": "",
                "architecture": "",
                "time_of_day": "",
                "weather": "",
                "lighting": "",
            },
            "shot": {
                "summary": row["summary"] or "",
                "action": row["action"] or "",
                "emotion": row["emotion"] or "",
                "composition": row["composition"] or "",
                "shot_size": row["shot_size"] or "",
                "camera_angle": row["camera_angle"] or "",
                "camera_movement": row["camera_movement"] or "",
                "lighting": row["lighting"] or "",
                "time_of_day": row["time_of_day"] or "",
                "weather": row["weather"] or "",
                "dialogue": row["dialogue"] or "",
                "continuity_notes": row["continuity_notes"] or "",
                "props": _loads_list(row["props_json"]),
                "free_prompt": row["shot_prompt"] or "",
                "negative_prompt": row["shot_negative_prompt"] or "",
            },
            "characters": [],
            "reference_asset_ids": [],
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        payloads_by_key[(int(row["shot_id"]), int(row["revision"]))] = encoded
        connection.execute(
            sa.text("UPDATE shotspec SET structured_payload_json = :payload WHERE id = :spec_id"),
            {"payload": encoded, "spec_id": row["spec_id"]},
        )
    requests = connection.execute(
        sa.text("SELECT id, shot_id, shot_spec_revision FROM generationrequest")
    ).mappings()
    for request in requests:
        payload = payloads_by_key.get((int(request["shot_id"]), int(request["shot_spec_revision"])))
        if payload is None:
            payload = json.dumps(
                {
                    "compiler_version": "structured-continuity-v1",
                    "shot_revision": request["shot_spec_revision"],
                    "characters": [],
                    "reference_asset_ids": [],
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        connection.execute(
            sa.text(
                """
                UPDATE generationrequest
                SET structured_payload_json = :payload,
                    compiler_version = 'structured-continuity-v1'
                WHERE id = :request_id
                """
            ),
            {"payload": payload, "request_id": request["id"]},
        )


def _loads_list(value: str | None) -> list[object]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _loads_dict(value: str | None) -> dict[str, object]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
