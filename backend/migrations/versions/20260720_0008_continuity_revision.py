"""continuity revision and asset lifecycle

Revision ID: 20260720_0008
Revises: 20260719_0007
Create Date: 2026-07-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260720_0008"
down_revision: str | None = "20260719_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("shot") as batch_op:
        batch_op.add_column(sa.Column("spec_revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("approved_keyframe_asset_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("approved_video_asset_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("locked_tail_frame_asset_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("start_frame_source_type", sa.String(), nullable=False, server_default="NONE"))
        batch_op.create_index("ix_shot_spec_revision", ["spec_revision"])
        batch_op.create_index("ix_shot_start_frame_source_type", ["start_frame_source_type"])
        batch_op.create_foreign_key("fk_shot_approved_keyframe_asset_id_asset", "asset", ["approved_keyframe_asset_id"], ["id"])
        batch_op.create_foreign_key("fk_shot_approved_video_asset_id_asset", "asset", ["approved_video_asset_id"], ["id"])
        batch_op.create_foreign_key("fk_shot_locked_tail_frame_asset_id_asset", "asset", ["locked_tail_frame_asset_id"], ["id"])

    op.execute(
        """
        UPDATE shot
        SET start_frame_source_type = CASE
            WHEN start_frame_asset_id IS NULL THEN 'NONE'
            WHEN EXISTS (
                SELECT 1 FROM asset
                WHERE asset.id = shot.start_frame_asset_id
                  AND asset.source_asset_id IS NOT NULL
            ) THEN 'INHERITED'
            ELSE 'MANUAL'
        END
        """
    )

    with op.batch_alter_table("asset") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"))
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("superseded_by_asset_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_asset_status", ["status"])
        batch_op.create_index("ix_asset_revision", ["revision"])
        batch_op.create_foreign_key("fk_asset_superseded_by_asset_id_asset", "asset", ["superseded_by_asset_id"], ["id"])

    with op.batch_alter_table("generationrequest") as batch_op:
        batch_op.add_column(sa.Column("shot_spec_revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.create_index("ix_generationrequest_shot_spec_revision", ["shot_spec_revision"])

    op.execute(
        """
        UPDATE generationrequest
        SET shot_spec_revision = COALESCE(
            (SELECT spec_revision FROM shot WHERE shot.id = generationrequest.shot_id),
            1
        )
        """
    )

    op.execute(
        """
        WITH approved_video AS (
            SELECT shot_id, asset_id
            FROM (
                SELECT
                    gr.shot_id,
                    asset.id AS asset_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY gr.shot_id
                        ORDER BY gr.updated_at DESC, gr.created_at DESC, gr.id DESC, asset.created_at DESC, asset.id DESC
                    ) AS rank
                FROM generationrequest AS gr
                JOIN json_each(CASE WHEN json_valid(gr.output_asset_ids) THEN gr.output_asset_ids ELSE '[]' END) AS output
                JOIN asset ON asset.id = CAST(output.value AS INTEGER)
                WHERE gr.kind = 'VIDEO'
                  AND gr.status = 'SUCCEEDED'
                  AND asset.type = 'VIDEO'
                  AND asset.shot_id = gr.shot_id
            )
            WHERE rank = 1
        )
        UPDATE shot
        SET approved_video_asset_id = (
            SELECT asset_id FROM approved_video WHERE approved_video.shot_id = shot.id
        )
        WHERE status = 'COMPLETED'
          AND EXISTS (SELECT 1 FROM approved_video WHERE approved_video.shot_id = shot.id)
        """
    )

    op.execute(
        """
        WITH approved_video_request AS (
            SELECT shot_id, request_id
            FROM (
                SELECT
                    gr.shot_id,
                    gr.id AS request_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY gr.shot_id
                        ORDER BY gr.updated_at DESC, gr.created_at DESC, gr.id DESC
                    ) AS rank
                FROM generationrequest AS gr
                JOIN json_each(CASE WHEN json_valid(gr.output_asset_ids) THEN gr.output_asset_ids ELSE '[]' END) AS output
                JOIN asset ON asset.id = CAST(output.value AS INTEGER)
                JOIN shot ON shot.id = gr.shot_id AND shot.approved_video_asset_id = asset.id
                WHERE gr.kind = 'VIDEO'
                  AND gr.status = 'SUCCEEDED'
                  AND asset.type = 'VIDEO'
            )
            WHERE rank = 1
        ),
        keyframe_from_video_input AS (
            SELECT shot_id, asset_id
            FROM (
                SELECT
                    gr.shot_id,
                    asset.id AS asset_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY gr.shot_id
                        ORDER BY asset.created_at DESC, asset.id DESC
                    ) AS rank
                FROM approved_video_request AS avr
                JOIN generationrequest AS gr ON gr.id = avr.request_id
                JOIN json_each(CASE WHEN json_valid(gr.input_asset_ids) THEN gr.input_asset_ids ELSE '[]' END) AS input
                JOIN asset ON asset.id = CAST(input.value AS INTEGER)
                WHERE asset.type = 'KEYFRAME'
                  AND asset.shot_id = gr.shot_id
            )
            WHERE rank = 1
        ),
        latest_successful_keyframe AS (
            SELECT shot_id, asset_id
            FROM (
                SELECT
                    gr.shot_id,
                    asset.id AS asset_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY gr.shot_id
                        ORDER BY gr.updated_at DESC, gr.created_at DESC, gr.id DESC, asset.created_at DESC, asset.id DESC
                    ) AS rank
                FROM generationrequest AS gr
                JOIN json_each(CASE WHEN json_valid(gr.output_asset_ids) THEN gr.output_asset_ids ELSE '[]' END) AS output
                JOIN asset ON asset.id = CAST(output.value AS INTEGER)
                WHERE gr.kind = 'KEYFRAME'
                  AND gr.status = 'SUCCEEDED'
                  AND asset.type = 'KEYFRAME'
                  AND asset.shot_id = gr.shot_id
            )
            WHERE rank = 1
        )
        UPDATE shot
        SET approved_keyframe_asset_id = COALESCE(
            (SELECT asset_id FROM keyframe_from_video_input WHERE keyframe_from_video_input.shot_id = shot.id),
            (SELECT asset_id FROM latest_successful_keyframe WHERE latest_successful_keyframe.shot_id = shot.id)
        )
        WHERE status IN ('KEYFRAME_APPROVED', 'VIDEO_REVIEW', 'VIDEO_APPROVED', 'TAIL_FRAME_LOCKED', 'COMPLETED')
          AND (
              EXISTS (SELECT 1 FROM keyframe_from_video_input WHERE keyframe_from_video_input.shot_id = shot.id)
              OR EXISTS (SELECT 1 FROM latest_successful_keyframe WHERE latest_successful_keyframe.shot_id = shot.id)
          )
        """
    )

    op.execute(
        """
        UPDATE shot
        SET locked_tail_frame_asset_id = (
            SELECT tail.id
            FROM asset AS tail
            WHERE tail.shot_id = shot.id
              AND tail.type = 'TAIL_FRAME'
              AND tail.source_asset_id = shot.approved_video_asset_id
            ORDER BY tail.created_at DESC, tail.id DESC
            LIMIT 1
        )
        WHERE status = 'COMPLETED'
          AND approved_video_asset_id IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM asset AS tail
              WHERE tail.shot_id = shot.id
                AND tail.type = 'TAIL_FRAME'
                AND tail.source_asset_id = shot.approved_video_asset_id
          )
        """
    )

    op.execute(
        """
        UPDATE asset
        SET status = 'APPROVED'
        WHERE id IN (
            SELECT approved_keyframe_asset_id FROM shot WHERE approved_keyframe_asset_id IS NOT NULL
            UNION
            SELECT approved_video_asset_id FROM shot WHERE approved_video_asset_id IS NOT NULL
            UNION
            SELECT locked_tail_frame_asset_id FROM shot WHERE locked_tail_frame_asset_id IS NOT NULL
        )
        """
    )

    op.create_table(
        "qualitycheckresult",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("check_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["shot_id"], ["shot.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qualitycheckresult_asset_id", "qualitycheckresult", ["asset_id"])
    op.create_index("ix_qualitycheckresult_check_type", "qualitycheckresult", ["check_type"])
    op.create_index("ix_qualitycheckresult_created_at", "qualitycheckresult", ["created_at"])
    op.create_index("ix_qualitycheckresult_project_id", "qualitycheckresult", ["project_id"])
    op.create_index("ix_qualitycheckresult_severity", "qualitycheckresult", ["severity"])
    op.create_index("ix_qualitycheckresult_shot_id", "qualitycheckresult", ["shot_id"])
    op.create_index(
        "ix_qualitycheck_project_shot_created",
        "qualitycheckresult",
        ["project_id", "shot_id", "created_at"],
    )
    op.create_index(
        "ix_qualitycheck_asset_type_created",
        "qualitycheckresult",
        ["asset_id", "check_type", "created_at"],
    )

    with op.batch_alter_table("shot") as batch_op:
        batch_op.alter_column("spec_revision", server_default=None)
        batch_op.alter_column("start_frame_source_type", server_default=None)
    with op.batch_alter_table("asset") as batch_op:
        batch_op.alter_column("status", server_default=None)
        batch_op.alter_column("revision", server_default=None)
    with op.batch_alter_table("generationrequest") as batch_op:
        batch_op.alter_column("shot_spec_revision", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_qualitycheck_asset_type_created", table_name="qualitycheckresult")
    op.drop_index("ix_qualitycheck_project_shot_created", table_name="qualitycheckresult")
    op.drop_index("ix_qualitycheckresult_shot_id", table_name="qualitycheckresult")
    op.drop_index("ix_qualitycheckresult_severity", table_name="qualitycheckresult")
    op.drop_index("ix_qualitycheckresult_project_id", table_name="qualitycheckresult")
    op.drop_index("ix_qualitycheckresult_created_at", table_name="qualitycheckresult")
    op.drop_index("ix_qualitycheckresult_check_type", table_name="qualitycheckresult")
    op.drop_index("ix_qualitycheckresult_asset_id", table_name="qualitycheckresult")
    op.drop_table("qualitycheckresult")

    with op.batch_alter_table("generationrequest") as batch_op:
        batch_op.drop_index("ix_generationrequest_shot_spec_revision")
        batch_op.drop_column("shot_spec_revision")

    with op.batch_alter_table("asset") as batch_op:
        batch_op.drop_constraint("fk_asset_superseded_by_asset_id_asset", type_="foreignkey")
        batch_op.drop_index("ix_asset_revision")
        batch_op.drop_index("ix_asset_status")
        batch_op.drop_column("superseded_by_asset_id")
        batch_op.drop_column("revision")
        batch_op.drop_column("status")

    with op.batch_alter_table("shot") as batch_op:
        batch_op.drop_constraint("fk_shot_locked_tail_frame_asset_id_asset", type_="foreignkey")
        batch_op.drop_constraint("fk_shot_approved_video_asset_id_asset", type_="foreignkey")
        batch_op.drop_constraint("fk_shot_approved_keyframe_asset_id_asset", type_="foreignkey")
        batch_op.drop_index("ix_shot_start_frame_source_type")
        batch_op.drop_index("ix_shot_spec_revision")
        batch_op.drop_column("start_frame_source_type")
        batch_op.drop_column("locked_tail_frame_asset_id")
        batch_op.drop_column("approved_video_asset_id")
        batch_op.drop_column("approved_keyframe_asset_id")
        batch_op.drop_column("spec_revision")
