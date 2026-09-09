"""add cover to creation chapters

Revision ID: 20260909_04
Revises: 20260909_03
"""

import sqlalchemy as sa
from alembic import op


revision = "20260909_04"
down_revision = "20260909_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = set(c["name"] for c in inspector.get_columns("cp_creation_chapters"))
    if "cover" not in cols:
        op.add_column("cp_creation_chapters",
                      sa.Column("cover", sa.String(512), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = set(c["name"] for c in inspector.get_columns("cp_creation_chapters"))
    if "cover" in cols:
        op.drop_column("cp_creation_chapters", "cover")
