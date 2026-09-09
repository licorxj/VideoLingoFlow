"""add chapter stitch history table

章节拼接历史：记录每次章节导出的拼接配置（转场/封面/分辨率）+ 有序分镜成片源列表 +
产物路径，支持「可重拼」——复用历史源并更换转场重新拼接，无需重新生成分镜视频。

Revision ID: 20260909_07
Revises: 20260909_06
"""

import sqlalchemy as sa
from alembic import op


revision = "20260909_07"
down_revision = "20260909_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cp_chapter_stitch" in set(inspector.get_tables()):
        return
    op.create_table(
        "cp_chapter_stitch",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("creation_id", sa.String(36),
                  sa.ForeignKey("cp_creations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chapter_id", sa.String(36),
                  sa.ForeignKey("cp_creation_chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transition", sa.String(32), nullable=False, server_default="none"),
        sa.Column("transition_duration", sa.Float, nullable=False, server_default="0.4"),
        sa.Column("resolution", sa.String(16), nullable=False, server_default="original"),
        sa.Column("aspect_ratio", sa.String(16), nullable=False, server_default="original"),
        sa.Column("make_cover", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("cover_duration", sa.Float, nullable=False, server_default="3.0"),
        sa.Column("cover_image", sa.String(1024), nullable=False, server_default=""),
        sa.Column("sources", sa.Text, nullable=False, server_default=""),
        sa.Column("output", sa.String(1024), nullable=False, server_default=""),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("ix_cp_chapter_stitch_chapter", "cp_chapter_stitch", ["chapter_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cp_chapter_stitch" not in set(inspector.get_tables()):
        return
    op.drop_index("ix_cp_chapter_stitch_chapter", table_name="cp_chapter_stitch")
    op.drop_table("cp_chapter_stitch")
