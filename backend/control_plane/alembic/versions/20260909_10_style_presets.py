"""add style presets table

风格预设库：立项节点可复用的题材/画风/受众组合，并预置若干内置预设。

Revision ID: 20260909_10
Revises: 20260909_09
"""

import sqlalchemy as sa
from alembic import op


revision = "20260909_10"
down_revision = "20260909_09"
branch_labels = None
depends_on = None


_BUILTIN_PRESETS = [
    ("日式动漫", "日式赛璐璐动画风格，清晰线条，明亮平涂色块，精致五官，电影级构图",
     ["科幻", "热血"], ["青少年"], "经典日式 TV 动画质感，适合少年向热血/科幻题材"),
    ("国漫风", "国产三维动画风格，厚涂质感，东方审美，细腻光影，电影级构图",
     ["玄幻", "武侠"], ["青少年", "成年"], "国漫主流三维厚涂风，适合玄幻/武侠题材"),
    ("赛博朋克", "赛博朋克风格，霓虹灯与暗部强对比，机械义体，雨夜街景，冷色调",
     ["科幻", "悬疑"], ["成年"], "高对比霓虹夜景，适合近未来科幻/悬疑题材"),
    ("水墨国风", "中国传统水墨风，留白意境，淡彩晕染，写意线条，古典韵味",
     ["古风", "武侠"], ["全年龄"], "水墨留白写意风，适合古风/武侠题材"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cp_style_presets" not in set(inspector.get_table_names()):
        op.create_table(
            "cp_style_presets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False, unique=True),
            sa.Column("art_style", sa.Text, nullable=False, server_default=""),
            sa.Column("genre_tags", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("audience_tags", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("description", sa.Text, nullable=False, server_default=""),
            sa.Column("is_builtin", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
    # 预置内置风格预设：仅在表为空时插入（应用启动时 create_all 可能已建表）
    import uuid

    _probe = sa.table("cp_style_presets", sa.column("id", sa.String))
    if (bind.execute(sa.select(sa.func.count()).select_from(_probe)).scalar() or 0) > 0:
        return

    presets = sa.table(
        "cp_style_presets",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("art_style", sa.Text),
        sa.column("genre_tags", sa.JSON),
        sa.column("audience_tags", sa.JSON),
        sa.column("description", sa.Text),
        sa.column("is_builtin", sa.Boolean),
        sa.column("version", sa.Integer),
    )
    op.bulk_insert(presets, [
        {"id": uuid.uuid4().hex, "name": name, "art_style": art_style,
         "genre_tags": genre, "audience_tags": audience,
         "description": desc, "is_builtin": True, "version": 1}
        for name, art_style, genre, audience, desc in _BUILTIN_PRESETS
    ])


def downgrade() -> None:
    bind = op.get_bind()
    if "cp_style_presets" not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_table("cp_style_presets")
