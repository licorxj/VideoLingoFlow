"""add seed_value & reference_images to creation characters

重生成一致性：记录每个角色的生图种子（确定性）与参考图集合（图生图 conditioning）。

Revision ID: 20260909_06
Revises: 20260909_05
"""

import sqlalchemy as sa
from alembic import op


revision = "20260909_06"
down_revision = "20260909_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = set(c["name"] for c in inspector.get_columns("cp_creation_characters"))
    if "seed_value" not in cols:
        op.add_column("cp_creation_characters",
                      sa.Column("seed_value", sa.Integer, nullable=True))
    if "reference_images" not in cols:
        op.add_column("cp_creation_characters",
                      sa.Column("reference_images", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = set(c["name"] for c in inspector.get_columns("cp_creation_characters"))
    if "reference_images" in cols:
        op.drop_column("cp_creation_characters", "reference_images")
    if "seed_value" in cols:
        op.drop_column("cp_creation_characters", "seed_value")
