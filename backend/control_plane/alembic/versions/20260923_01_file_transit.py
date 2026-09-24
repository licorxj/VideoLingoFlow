"""add file transit station table"""

import sqlalchemy as sa
from alembic import op

from backend.control_plane.models import Base


revision = "20260923_01"
down_revision = "20260910_08"
branch_labels = None
depends_on = None

_NEW_TABLES = ("cp_file_transit",)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    missing = [table for table in Base.metadata.sorted_tables if table.name in _NEW_TABLES and not inspector.has_table(table.name)]
    if missing:
        Base.metadata.create_all(bind=bind, tables=missing)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [table for table in reversed(Base.metadata.sorted_tables) if table.name in _NEW_TABLES and inspector.has_table(table.name)]
    if existing:
        Base.metadata.drop_all(bind=bind, tables=existing)
