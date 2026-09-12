"""toonflow core tables (tf_*)

创作画布（Toonflow 迁移）核心表：项目/小说章节/剧本/资产/图/分镜/视频/轨道/
提示词模板/Agent槽位/设置/任务台账。结构对齐源系统 o_* 表精简版。

Revision ID: 20260910_05
Revises: 20260910_04
"""

import sqlalchemy as sa
from alembic import op

from backend.toonflow.core.models import TfBase

revision = "20260910_05"
down_revision = "20260910_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in TfBase.metadata.sorted_tables:
        if table.name not in existing:
            op.create_table(table.name, *[
                column.copy() for column in table.columns
            ])


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in reversed(TfBase.metadata.sorted_tables):
        if table.name in existing:
            op.drop_table(table.name)
