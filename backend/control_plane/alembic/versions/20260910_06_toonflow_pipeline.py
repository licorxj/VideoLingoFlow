"""toonflow pipeline tables

创作链扩展：剧本-资产关联(tf_script_assets)、角色-音色绑定(tf_assets_role_audio)、
分镜表新增 关联资产/视频提示词 列。

Revision ID: 20260910_06
Revises: 837cb0e56934
"""

import sqlalchemy as sa
from alembic import op

from backend.toonflow.core.models import TfAssetRoleAudio, TfScriptAsset

revision = "20260910_06"
down_revision = "837cb0e56934"
branch_labels = None
depends_on = None


def _existing(bind) -> set:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _existing(bind)
    for model in (TfScriptAsset, TfAssetRoleAudio):
        if model.__tablename__ not in existing:
            op.create_table(model.__tablename__, *[c.copy() for c in model.__table__.columns])
    if "tf_storyboards" in existing:
        cols = _columns(bind, "tf_storyboards")
        if "videoPrompt" not in cols:
            op.add_column("tf_storyboards", sa.Column("videoPrompt", sa.Text(), nullable=False, server_default=""))
        if "assetIds" not in cols:
            op.add_column("tf_storyboards", sa.Column("assetIds", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    existing = _existing(bind)
    if "tf_storyboards" in existing:
        cols = _columns(bind, "tf_storyboards")
        if "videoPrompt" in cols:
            op.drop_column("tf_storyboards", "videoPrompt")
        if "assetIds" in cols:
            op.drop_column("tf_storyboards", "assetIds")
    for model in (TfAssetRoleAudio, TfScriptAsset):
        if model.__tablename__ in existing:
            op.drop_table(model.__tablename__)
