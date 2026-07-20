"""script import and storyboard drafts

Revision ID: 20260720_0011
Revises: 20260720_0010
Create Date: 2026-07-20 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260720_0011"
down_revision: str | None = "20260720_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scriptdocument",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.Enum("PLAIN_TEXT", "MARKDOWN", "FOUNTAIN", "DOCX", "PASTED"), nullable=False),
        sa.Column("original_filename", sa.String(length=260), nullable=False),
        sa.Column("mime_type", sa.String(length=160), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("status", sa.Enum("IMPORTED", "PARSED", "PARSE_WARNING", "ARCHIVED"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_document_id", sa.Integer(), nullable=True),
        sa.Column("parse_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parent_document_id"], ["scriptdocument.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "content_sha256", "version", name="uq_scriptdocument_project_sha_version"),
    )
    op.create_index("ix_scriptdocument_project_id", "scriptdocument", ["project_id"])
    op.create_index("ix_scriptdocument_source_type", "scriptdocument", ["source_type"])
    op.create_index("ix_scriptdocument_status", "scriptdocument", ["status"])
    op.create_index("ix_scriptdocument_content_sha256", "scriptdocument", ["content_sha256"])
    op.create_index("ix_scriptdocument_version", "scriptdocument", ["version"])
    op.create_index("ix_scriptdocument_parent_document_id", "scriptdocument", ["parent_document_id"])
    op.create_index("ix_scriptdocument_parse_revision", "scriptdocument", ["parse_revision"])
    op.create_index("ix_scriptdocument_project_status", "scriptdocument", ["project_id", "status"])
    op.create_index("ix_scriptdocument_project_sha", "scriptdocument", ["project_id", "content_sha256"])

    op.create_table(
        "scriptblock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("script_document_id", sa.Integer(), nullable=False),
        sa.Column("parse_revision", sa.Integer(), nullable=False),
        sa.Column(
            "block_type",
            sa.Enum(
                "SCENE_HEADING",
                "ACTION",
                "DIALOGUE",
                "CHARACTER_CUE",
                "PARENTHETICAL",
                "TRANSITION",
                "COMMENT",
                "UNKNOWN",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_block_type",
            sa.Enum(
                "SCENE_HEADING",
                "ACTION",
                "DIALOGUE",
                "CHARACTER_CUE",
                "PARENTHETICAL",
                "TRANSITION",
                "COMMENT",
                "UNKNOWN",
            ),
            nullable=True,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("source_start", sa.Integer(), nullable=False),
        sa.Column("source_end", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("user_normalized_text", sa.Text(), nullable=True),
        sa.Column("speaker", sa.String(length=160), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("parse_confidence", sa.Float(), nullable=False),
        sa.Column("parse_warnings_json", sa.Text(), nullable=False),
        sa.Column("warnings_confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["script_document_id"], ["scriptdocument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("script_document_id", "parse_revision", "sort_order", name="uq_scriptblock_doc_rev_order"),
    )
    for column in ("script_document_id", "parse_revision", "block_type", "user_block_type", "sort_order", "source_start", "source_end"):
        op.create_index(f"ix_scriptblock_{column}", "scriptblock", [column])
    op.create_index("ix_scriptblock_doc_rev_order", "scriptblock", ["script_document_id", "parse_revision", "sort_order"])

    op.create_table(
        "storyboarddraft",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("script_document_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("parser_version", sa.String(length=120), nullable=False),
        sa.Column("builder_version", sa.String(length=120), nullable=False),
        sa.Column("status", sa.Enum("DRAFT", "REVIEWED", "PARTIALLY_APPLIED", "APPLIED", "ARCHIVED"), nullable=False),
        sa.Column("default_style_profile_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["default_style_profile_id"], ["styleprofile.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["script_document_id"], ["scriptdocument.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storyboarddraft_project_id", "storyboarddraft", ["project_id"])
    op.create_index("ix_storyboarddraft_script_document_id", "storyboarddraft", ["script_document_id"])
    op.create_index("ix_storyboarddraft_status", "storyboarddraft", ["status"])
    op.create_index("ix_storyboarddraft_default_style_profile_id", "storyboarddraft", ["default_style_profile_id"])
    op.create_index("ix_storyboarddraft_project_script", "storyboarddraft", ["project_id", "script_document_id"])

    op.create_table(
        "shotdraft",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("storyboard_draft_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("source_block_start_id", sa.Integer(), nullable=True),
        sa.Column("source_block_end_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.String(length=4000), nullable=False),
        sa.Column("action", sa.String(length=4000), nullable=False),
        sa.Column("dialogue", sa.String(length=4000), nullable=False),
        sa.Column("suggested_duration_seconds", sa.Float(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("location_name", sa.String(length=160), nullable=False),
        sa.Column("style_profile_id", sa.Integer(), nullable=True),
        sa.Column("time_of_day", sa.String(length=120), nullable=False),
        sa.Column("weather", sa.String(length=120), nullable=False),
        sa.Column("shot_size", sa.String(length=120), nullable=False),
        sa.Column("camera_angle", sa.String(length=240), nullable=False),
        sa.Column("camera_movement", sa.String(length=1000), nullable=False),
        sa.Column("composition", sa.String(length=2000), nullable=False),
        sa.Column("lighting", sa.String(length=2000), nullable=False),
        sa.Column("emotion", sa.String(length=1000), nullable=False),
        sa.Column("props_json", sa.Text(), nullable=False),
        sa.Column("continuity_notes", sa.String(length=4000), nullable=False),
        sa.Column("free_prompt", sa.String(length=4000), nullable=False),
        sa.Column("negative_prompt", sa.String(length=2000), nullable=False),
        sa.Column("status", sa.Enum("DRAFT", "READY", "SKIPPED", "APPLIED"), nullable=False),
        sa.Column("applied_shot_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["applied_shot_id"], ["shot.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.ForeignKeyConstraint(["source_block_end_id"], ["scriptblock.id"]),
        sa.ForeignKeyConstraint(["source_block_start_id"], ["scriptblock.id"]),
        sa.ForeignKeyConstraint(["storyboard_draft_id"], ["storyboarddraft.id"]),
        sa.ForeignKeyConstraint(["style_profile_id"], ["styleprofile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storyboard_draft_id", "applied_shot_id", name="uq_shotdraft_storyboard_applied_shot"),
    )
    for column in (
        "storyboard_draft_id",
        "sort_order",
        "source_block_start_id",
        "source_block_end_id",
        "location_id",
        "style_profile_id",
        "status",
        "applied_shot_id",
    ):
        op.create_index(f"ix_shotdraft_{column}", "shotdraft", [column])
    op.create_index("ix_shotdraft_storyboard_order", "shotdraft", ["storyboard_draft_id", "sort_order"])

    op.create_table(
        "shotdraftcharacter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shot_draft_id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=True),
        sa.Column("character_name", sa.String(length=160), nullable=False),
        sa.Column("role", sa.Enum("PRIMARY", "SECONDARY", "BACKGROUND"), nullable=False),
        sa.Column("action", sa.String(length=2000), nullable=False),
        sa.Column("expression", sa.String(length=1000), nullable=False),
        sa.Column("clothing", sa.String(length=2000), nullable=False),
        sa.Column("position", sa.String(length=1000), nullable=False),
        sa.Column("props_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.String(length=4000), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["character.id"]),
        sa.ForeignKeyConstraint(["shot_draft_id"], ["shotdraft.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shot_draft_id", "character_id", "character_name", name="uq_shotdraftcharacter_identity"),
    )
    op.create_index("ix_shotdraftcharacter_shot_draft_id", "shotdraftcharacter", ["shot_draft_id"])
    op.create_index("ix_shotdraftcharacter_character_id", "shotdraftcharacter", ["character_id"])
    op.create_index("ix_shotdraftcharacter_role", "shotdraftcharacter", ["role"])
    op.create_index("ix_shotdraftcharacter_sort_order", "shotdraftcharacter", ["sort_order"])
    op.create_index("ix_shotdraftcharacter_draft_sort", "shotdraftcharacter", ["shot_draft_id", "sort_order"])


def downgrade() -> None:
    op.drop_index("ix_shotdraftcharacter_draft_sort", table_name="shotdraftcharacter")
    op.drop_index("ix_shotdraftcharacter_sort_order", table_name="shotdraftcharacter")
    op.drop_index("ix_shotdraftcharacter_role", table_name="shotdraftcharacter")
    op.drop_index("ix_shotdraftcharacter_character_id", table_name="shotdraftcharacter")
    op.drop_index("ix_shotdraftcharacter_shot_draft_id", table_name="shotdraftcharacter")
    op.drop_table("shotdraftcharacter")

    op.drop_index("ix_shotdraft_storyboard_order", table_name="shotdraft")
    for column in (
        "applied_shot_id",
        "status",
        "style_profile_id",
        "location_id",
        "source_block_end_id",
        "source_block_start_id",
        "sort_order",
        "storyboard_draft_id",
    ):
        op.drop_index(f"ix_shotdraft_{column}", table_name="shotdraft")
    op.drop_table("shotdraft")

    op.drop_index("ix_storyboarddraft_project_script", table_name="storyboarddraft")
    op.drop_index("ix_storyboarddraft_default_style_profile_id", table_name="storyboarddraft")
    op.drop_index("ix_storyboarddraft_status", table_name="storyboarddraft")
    op.drop_index("ix_storyboarddraft_script_document_id", table_name="storyboarddraft")
    op.drop_index("ix_storyboarddraft_project_id", table_name="storyboarddraft")
    op.drop_table("storyboarddraft")

    op.drop_index("ix_scriptblock_doc_rev_order", table_name="scriptblock")
    for column in ("source_end", "source_start", "sort_order", "user_block_type", "block_type", "parse_revision", "script_document_id"):
        op.drop_index(f"ix_scriptblock_{column}", table_name="scriptblock")
    op.drop_table("scriptblock")

    op.drop_index("ix_scriptdocument_project_sha", table_name="scriptdocument")
    op.drop_index("ix_scriptdocument_project_status", table_name="scriptdocument")
    op.drop_index("ix_scriptdocument_parse_revision", table_name="scriptdocument")
    op.drop_index("ix_scriptdocument_parent_document_id", table_name="scriptdocument")
    op.drop_index("ix_scriptdocument_version", table_name="scriptdocument")
    op.drop_index("ix_scriptdocument_content_sha256", table_name="scriptdocument")
    op.drop_index("ix_scriptdocument_status", table_name="scriptdocument")
    op.drop_index("ix_scriptdocument_source_type", table_name="scriptdocument")
    op.drop_index("ix_scriptdocument_project_id", table_name="scriptdocument")
    op.drop_table("scriptdocument")
