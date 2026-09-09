"""add gen_config to creation chapters

Revision ID: 20260909_05
Revises: 20260909_04
"""

import sqlalchemy as sa
from alembic import op


revision = "20260909_05"
down_revision = "20260909_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = set(c["name"] for c in inspector.get_columns("cp_creation_chapters"))
    if "gen_config" not in cols:
        op.add_column("cp_creation_chapters",
                      sa.Column("gen_config", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = set(c["name"] for c in inspector.get_columns("cp_creation_chapters"))
    if "gen_config" in cols:
        op.drop_column("cp_creation_chapters", "gen_config")
