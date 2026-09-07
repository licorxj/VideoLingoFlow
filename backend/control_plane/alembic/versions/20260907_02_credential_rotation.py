"""credential rotation: rotate flag + current_index columns"""

import sqlalchemy as sa
from alembic import op


revision = "20260907_02"
down_revision = "20260907_01"
branch_labels = None
depends_on = None

_TABLE = "cp_credentials"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        # 新库：由 Base.metadata.create_all 的 initial/credentials 迁移负责建表（含新列）
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if "rotate" not in columns:
        op.add_column(_TABLE, sa.Column("rotate", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "current_index" not in columns:
        op.add_column(_TABLE, sa.Column("current_index", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if "current_index" in columns:
        op.drop_column(_TABLE, "current_index")
    if "rotate" in columns:
        op.drop_column(_TABLE, "rotate")
