"""add final_prompt to creation characters

Revision ID: 20260909_02
Revises: 20260909_01
"""

import sqlalchemy as sa
from alembic import op

from backend.control_plane.models import Base


revision = "20260909_02"
down_revision = "20260909_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = set(c["name"] for c in inspector.get_columns("cp_creation_characters"))
    if "final_prompt" not in cols:
        op.add_column("cp_creation_characters",
                      sa.Column("final_prompt", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = set(c["name"] for c in inspector.get_columns("cp_creation_characters"))
    if "final_prompt" in cols:
        op.drop_column("cp_creation_characters", "final_prompt")
