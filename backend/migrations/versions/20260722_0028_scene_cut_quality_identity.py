"""Add deterministic QualityCheck identity for scene-cut evidence."""

from alembic import op
import sqlalchemy as sa


revision = "20260722_0028"
down_revision = "20260722_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_qualitycheck_scene_cut_asset_algorithm",
        "qualitycheckresult",
        ["asset_id", "algorithm_version"],
        unique=True,
        sqlite_where=sa.text("check_type = 'INTRA_SHOT_SCENE_CUT'"),
    )


def downgrade() -> None:
    op.drop_index("uq_qualitycheck_scene_cut_asset_algorithm", table_name="qualitycheckresult")
