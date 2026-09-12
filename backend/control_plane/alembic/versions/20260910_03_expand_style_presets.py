"""expand builtin style presets

风格预设库扩容：补充市面常见画风，供「项目立项」节点下拉选择，也可在节点内自定义输入。
缺失的内置预设按名称补齐（幂等）。

Revision ID: 20260910_03_style_presets_expand
Revises: 24a2eb1b28a9
"""

import uuid

import sqlalchemy as sa
from alembic import op


revision = "20260910_03_style_presets_expand"
down_revision = "24a2eb1b28a9"
branch_labels = None
depends_on = None


# (name, art_style, genre_tags, audience_tags, description)
_BUILTIN_PRESETS = [
    ("日式动漫", "日式赛璐璐动画风格，清晰线条，明亮平涂色块，精致五官，电影级构图",
     ["科幻", "热血"], ["青少年"], "经典日式动画质感，少年向热血/科幻"),
    ("国漫风", "国产三维动画风格，厚涂质感，东方审美，细腻光影，电影级构图",
     ["玄幻", "武侠"], ["青少年", "成年"], "国漫三维厚涂，玄幻/武侠"),
    ("赛博朋克", "赛博朋克风格，霓虹与暗部强对比，机械义体，雨夜街景，冷色调",
     ["科幻", "悬疑"], ["成年"], "霓虹近未来，科幻/悬疑"),
    ("水墨国风", "中国传统水墨风，留白意境，淡彩晕染，写意线条，古典韵味",
     ["古风", "武侠"], ["全年龄"], "水墨写意，古风/武侠"),
    ("国潮插画", "国潮扁平插画风格，撞色搭配，几何装饰纹样，现代东方审美，平面构成感",
     ["古风", "都市"], ["青少年", "成年"], "现代东方平面插画"),
    ("工笔重彩", "中国传统工笔重彩，精细勾线，矿物颜料质感，古典仕女与亭台楼阁，雅致配色",
     ["古风", "宫廷"], ["成年"], "古典工笔重彩，宫廷/传奇"),
    ("欧美二维动画", "欧美二维动画风格，夸张表情与弹性动作，饱满粗线条，高饱和明快配色，手绘质感",
     ["喜剧", "奇幻"], ["全年龄"], "欧美手绘动画，合家欢/喜剧"),
    ("3D卡通", "三维卡通动画风格，圆润夸张造型，柔和全局光照，细腻毛发与布料质感，明亮配色",
     ["奇幻", "喜剧"], ["全年龄"], "三维卡通，合家欢/奇幻"),
    ("美漫硬核", "美式漫画风格，粗黑描边，强烈高对比阴影，高饱和纯色块，半调网点质感",
     ["科幻", "动作"], ["青少年", "成年"], "硬朗美漫，动作/英雄"),
    ("写实二次元厚涂", "写实比例的二次元厚涂风格，精细皮肤与发丝质感，柔和体积光，低饱和高级灰",
     ["都市", "悬疑"], ["青少年", "成年"], "成人向写实二次元"),
    ("韩漫条漫", "韩国网络漫画风格，清透渐变上色，细腻五官，干净线条，柔和打光",
     ["都市", "言情"], ["青少年", "成年"], "清透韩漫，都市/校园"),
    ("日系治愈手绘", "日系治愈手绘动画风格，水彩背景，柔和自然光，温暖色调，细腻云层与植被",
     ["日常", "治愈"], ["全年龄"], "温暖治愈手绘，日常/成长"),
    ("黑白漫画", "日式黑白漫画风格，墨线干净，网点纸质感，强对比黑白排线，漫画分镜感",
     ["悬疑", "热血"], ["青少年", "成年"], "黑白漫画，悬疑/热血短篇"),
    ("港漫武侠", "港式武侠漫画风格，硬朗墨线，强烈黑白对比，速度线与爆炸特效，复古印刷质感",
     ["武侠", "动作"], ["青少年", "成年"], "港漫硬派武侠"),
    ("蒸汽朋克", "蒸汽朋克风格，黄铜齿轮机械，维多利亚服饰，雾气弥漫的工业城市，暖褐色调",
     ["科幻", "悬疑"], ["成年"], "复古工业机械美学"),
    ("暗黑哥特", "哥特暗黑风格，尖顶建筑与彩窗，暗紫与墨黑主色，诡异神秘氛围，强逆光",
     ["悬疑", "恐怖"], ["成年"], "暗黑哥特，恐怖/黑暗奇幻"),
    ("像素游戏", "像素艺术风格，8/16 位游戏质感，有限色板，清晰像素块，复古电子游戏画面",
     ["科幻", "冒险"], ["全年龄"], "复古像素游戏画面"),
    ("黏土定格", "黏土定格动画风格，手作黏土质感，微缩布景，柔和棚拍光，温馨童话氛围",
     ["童话", "喜剧"], ["全年龄"], "手作黏土定格，童话/儿童"),
    ("儿童绘本", "儿童绘本插画风格，蜡笔与水彩混合，稚拙笔触，温暖纸感，留白构图",
     ["童话", "教育"], ["全年龄"], "儿童绘本插画，早教/童话"),
    ("Q版三头身", "Q 版三头身比例，大头小身，圆润可爱造型，明亮撞色，简洁背景",
     ["喜剧", "日常"], ["全年龄"], "Q 版萌系，搞笑/轻剧情"),
    ("写实电影感", "电影级写实风格，真实材质与光线，浅景深，自然肤色，胶片颗粒感",
     ["都市", "悬疑"], ["成年"], "电影级写实，都市/正剧"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if "cp_style_presets" not in set(sa.inspect(bind).get_table_names()):
        return
    table = sa.table(
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
    # 含软删除记录（name 唯一），已存在的一律跳过，保证幂等
    existing = {row[0] for row in bind.execute(sa.select(table.c.name)).fetchall()}
    rows = [
        {"id": uuid.uuid4().hex, "name": name, "art_style": art_style,
         "genre_tags": genre, "audience_tags": audience,
         "description": desc, "is_builtin": True, "version": 1}
        for name, art_style, genre, audience, desc in _BUILTIN_PRESETS
        if name not in existing
    ]
    if rows:
        op.bulk_insert(table, rows)


def downgrade() -> None:
    # 仅移除本次新增的内置预设（原有 4 条由 20260909_10 管理）
    bind = op.get_bind()
    if "cp_style_presets" not in set(sa.inspect(bind).get_table_names()):
        return
    keep = {"日式动漫", "国漫风", "赛博朋克", "水墨国风"}
    names = [n for n, *_ in _BUILTIN_PRESETS if n not in keep]
    table = sa.table("cp_style_presets", sa.column("name", sa.String),
                     sa.column("is_builtin", sa.Boolean))
    bind.execute(table.delete().where(table.c.name.in_(names), table.c.is_builtin.is_(True)))
