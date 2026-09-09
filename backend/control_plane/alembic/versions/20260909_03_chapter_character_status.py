"""add status to creation chapters and characters

Revision ID: 20260909_03
Revises: 20260909_02
"""

import sqlalchemy as sa
from alembic import op


revision = "20260909_03"
down_revision = "20260909_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    ch_cols = set(c["name"] for c in inspector.get_columns("cp_creation_chapters"))
    if "status" not in ch_cols:
        op.add_column("cp_creation_chapters",
                      sa.Column("status", sa.String(32), nullable=False, server_default="draft"))

    ch_cols2 = set(c["name"] for c in inspector.get_columns("cp_creation_characters"))
    if "status" not in ch_cols2:
        op.add_column("cp_creation_characters",
                      sa.Column("status", sa.String(32), nullable=False, server_default="pending"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    ch_cols = set(c["name"] for c in inspector.get_columns("cp_creation_chapters"))
    if "status" in ch_cols:
        op.drop_column("cp_creation_chapters", "status")

    ch_cols2 = set(c["name"] for c in inspector.get_columns("cp_creation_characters"))
    if "status" in ch_cols2:
        op.drop_column("cp_creation_characters", "status")
