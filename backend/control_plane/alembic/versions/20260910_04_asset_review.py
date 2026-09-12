"""add review fields to cp_creation_assets

生产驾驶舱 P2「产物审查」：给资产加人工审查态（通过/打回/备注）与
N 选 1 主选标记（is_primary），让「生成 → 审查 → 返工」形成闭环。

Revision ID: 20260910_04
Revises: 20260910_02
"""

import sqlalchemy as sa
from alembic import op


revision = "20260910_04"
down_revision = "20260910_02"
branch_labels = None
depends_on = None

COLUMNS = (
    ("review_status", sa.Column("review_status", sa.String(16), nullable=False, server_default="")),
    ("review_note", sa.Column("review_note", sa.Text(), nullable=False, server_default="")),
    ("is_primary", sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false())),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("cp_creation_assets")}
    for name, column in COLUMNS:
        if name in existing:
            continue
        op.add_column("cp_creation_assets", column)


def downgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("cp_creation_assets")}
    for name, _ in reversed(COLUMNS):
        if name in existing:
            op.drop_column("cp_creation_assets", name)
