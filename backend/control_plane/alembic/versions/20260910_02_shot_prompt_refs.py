"""add image_prompt_refs to cp_creation_shots

组装分镜提示词节点产出有序参考图（场景→道具→角色），供「分镜首尾帧」
以图生图方式生成分镜图时按序注入，保证画风/角色一致性。

Revision ID: 20260910_02
Revises: 20260909_11
"""

import sqlalchemy as sa
from alembic import op


revision = "20260910_02"
down_revision = "20260909_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("cp_creation_shots")}
    if "image_prompt_refs" in existing:
        return
    op.add_column(
        "cp_creation_shots",
        sa.Column("image_prompt_refs", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("cp_creation_shots")}
    if "image_prompt_refs" in existing:
        op.drop_column("cp_creation_shots", "image_prompt_refs")
