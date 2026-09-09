"""add creation scene/prop tables and enrich creation shots

Revision ID: 20260909_01
Revises: 20260907_03
"""

import sqlalchemy as sa
from alembic import op

from backend.control_plane.models import Base


revision = "20260909_01"
down_revision = "20260907_03"
branch_labels = None
depends_on = None

_NEW_TABLES = ("cp_creation_scenes", "cp_creation_props")

# (列名, sa.Column) —— 给已存在的 cp_creation_shots 追加字段
_SHOT_COLUMNS = [
    ("scene_id", sa.Column("scene_id", sa.String(32), nullable=True)),
    ("shot_type", sa.Column("shot_type", sa.String(64), nullable=False, server_default="")),
    ("angle", sa.Column("angle", sa.String(64), nullable=False, server_default="")),
    ("movement", sa.Column("movement", sa.String(64), nullable=False, server_default="")),
    ("atmosphere", sa.Column("atmosphere", sa.Text(), nullable=False, server_default="")),
    ("location", sa.Column("location", sa.String(256), nullable=False, server_default="")),
    ("time", sa.Column("time", sa.String(64), nullable=False, server_default="")),
    ("duration_seconds", sa.Column("duration_seconds", sa.Float(), nullable=True)),
    ("image_prompt", sa.Column("image_prompt", sa.Text(), nullable=False, server_default="")),
    ("video_prompt", sa.Column("video_prompt", sa.Text(), nullable=False, server_default="")),
    ("reference_images", sa.Column("reference_images", sa.JSON(), nullable=False, server_default="[]")),
    ("status", sa.Column("status", sa.String(32), nullable=False, server_default="pending")),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1) 新建场景表 / 道具表
    missing = [t for t in Base.metadata.sorted_tables if t.name in _NEW_TABLES and not inspector.has_table(t.name)]
    if missing:
        Base.metadata.create_all(bind=bind, tables=missing)

    # 2) 给已存在的分镜表追加字段（仅补缺失列，幂等）
    if inspector.has_table("cp_creation_shots"):
        existing_cols = set(c["name"] for c in inspector.get_columns("cp_creation_shots"))
        for name, col in _SHOT_COLUMNS:
            if name not in existing_cols:
                op.add_column("cp_creation_shots", col)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("cp_creation_shots"):
        existing_cols = set(c["name"] for c in inspector.get_columns("cp_creation_shots"))
        for name, _col in reversed(_SHOT_COLUMNS):
            if name in existing_cols:
                op.drop_column("cp_creation_shots", name)

    existing = [t for t in reversed(Base.metadata.sorted_tables) if t.name in _NEW_TABLES and inspector.has_table(t.name)]
    if existing:
        Base.metadata.drop_all(bind=bind, tables=existing)
