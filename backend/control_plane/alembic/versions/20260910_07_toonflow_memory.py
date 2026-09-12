"""toonflow memory table (tf_memories)

Agent 向量化记忆：按 isolationKey(=agent:项目) 隔离，message/summary 两级 +
embedding 向量检索（deepRetrieve：摘要召回 → 原文展开）。

Revision ID: 20260910_07
Revises: 20260910_06
"""

import sqlalchemy as sa
from alembic import op

from backend.toonflow.core.models import TfMemory

revision = "20260910_07"
down_revision = "20260910_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if TfMemory.__tablename__ not in existing:
        op.create_table(TfMemory.__tablename__, *[c.copy() for c in TfMemory.__table__.columns])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if TfMemory.__tablename__ in existing:
        op.drop_table(TfMemory.__tablename__)
