"""task archive: 批次归档后记录归档路径与归档时间

批次「归档批次」把任务产物复制到外部归档目录后，任务标记为已归档（status=archived），
并在 cp_tasks 上记录归档路径 archive_path / 归档时间 archived_at，供后续从已归档项目载回。

Revision ID: 20260910_08
Revises: 20260910_07
"""

import sqlalchemy as sa
from alembic import op

revision = "20260910_08"
down_revision = "20260910_07"
branch_labels = None
depends_on = None

_TABLE = "cp_tasks"
COLUMNS = (
    ("archive_path", sa.Column("archive_path", sa.String(1024), nullable=True)),
    ("archived_at", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, column in COLUMNS:
        if name in existing:
            continue
        op.add_column(_TABLE, column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, _ in reversed(COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)
