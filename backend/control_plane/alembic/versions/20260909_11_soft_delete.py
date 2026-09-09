"""add soft delete (deleted_at) to creation-domain tables

全表软删除：为创作域模型（含公共素材库）增加 ``deleted_at`` 列，实现软删除。
查询过滤由 ``backend.control_plane.database`` 的 ``do_orm_select`` 监听器统一施加。

Revision ID: 20260909_11
Revises: 20260909_10
"""

import sqlalchemy as sa
from alembic import op


revision = "20260909_11"
down_revision = "20260909_10"
branch_labels = None
depends_on = None


# (表名, 主键列类型) —— 创作域全部继承 SoftDeleteMixin 的表
_SOFT_DELETE_TABLES = [
    "cp_creations",
    "cp_creation_characters",
    "cp_creation_chapters",
    "cp_creation_scenes",
    "cp_creation_props",
    "cp_creation_shots",
    "cp_creation_assets",
    "cp_chapter_stitch",
    "cp_generation_tasks",
    "cp_style_presets",
    "cp_characters",
    "cp_images",
    "cp_videos",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # 应用启动时 create_all 可能已按最新模型建好 deleted_at，避免重复加列
    existing_cols = {c["name"] for c in inspector.get_columns("cp_creations")}
    if "deleted_at" in existing_cols:
        return
    for table in _SOFT_DELETE_TABLES:
        if "deleted_at" in {c["name"] for c in inspector.get_columns(table)}:
            continue
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_SOFT_DELETE_TABLES):
        if "deleted_at" in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.drop_column(table, "deleted_at")
