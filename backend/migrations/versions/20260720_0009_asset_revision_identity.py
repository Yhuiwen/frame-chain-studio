"""asset revision identity and quality metadata

Revision ID: 20260720_0009
Revises: 20260720_0008
Create Date: 2026-07-20 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260720_0009"
down_revision: str | None = "20260720_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("asset") as batch_op:
        batch_op.drop_index("ix_asset_project_shot_type_sha256")
        batch_op.create_index(
            "ix_asset_project_shot_type_revision_sha256",
            ["project_id", "shot_id", "type", "revision", "sha256"],
            unique=True,
        )

    with op.batch_alter_table("qualitycheckresult") as batch_op:
        batch_op.add_column(sa.Column("reference_asset_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("algorithm_version", sa.String(), nullable=False, server_default="quality-v1"))
        batch_op.create_index("ix_qualitycheckresult_reference_asset_id", ["reference_asset_id"])
        batch_op.create_index("ix_qualitycheckresult_algorithm_version", ["algorithm_version"])
        batch_op.create_foreign_key(
            "fk_qualitycheckresult_reference_asset_id_asset",
            "asset",
            ["reference_asset_id"],
            ["id"],
        )
        batch_op.alter_column("algorithm_version", server_default=None)
    op.execute(
        """
        CREATE UNIQUE INDEX uq_qualitycheckresult_current_algorithm
        ON qualitycheckresult (
            asset_id,
            COALESCE(reference_asset_id, -1),
            check_type,
            algorithm_version
        )
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            """
            SELECT project_id, shot_id, type, sha256, COUNT(*) AS count
            FROM asset
            WHERE sha256 IS NOT NULL
            GROUP BY project_id, shot_id, type, sha256
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade asset identity: duplicate asset SHA rows exist across revisions."
        )

    op.drop_index("uq_qualitycheckresult_current_algorithm", table_name="qualitycheckresult")

    with op.batch_alter_table("qualitycheckresult") as batch_op:
        batch_op.drop_constraint("fk_qualitycheckresult_reference_asset_id_asset", type_="foreignkey")
        batch_op.drop_index("ix_qualitycheckresult_algorithm_version")
        batch_op.drop_index("ix_qualitycheckresult_reference_asset_id")
        batch_op.drop_column("algorithm_version")
        batch_op.drop_column("reference_asset_id")

    with op.batch_alter_table("asset") as batch_op:
        batch_op.drop_index("ix_asset_project_shot_type_revision_sha256")
        batch_op.create_index("ix_asset_project_shot_type_sha256", ["project_id", "shot_id", "type", "sha256"], unique=True)
