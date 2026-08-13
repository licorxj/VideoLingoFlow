"""add collaboration join applications and user last_seen_at"""

import sqlalchemy as sa
from alembic import op


revision = "20260809_01"
down_revision = "20260807_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("cp_users")}
    if "last_seen_at" not in user_columns:
        op.add_column("cp_users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    if not inspector.has_table("cp_join_applications"):
        op.create_table(
            "cp_join_applications",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("username", sa.String(length=128), nullable=False, unique=True),
            sa.Column("display_name", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("password_hash", sa.String(length=256), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.String(length=32), sa.ForeignKey("cp_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
        )
        op.create_index("ix_cp_join_applications_status", "cp_join_applications", ["status"])


def downgrade() -> None:
    op.drop_index("ix_cp_join_applications_status", table_name="cp_join_applications")
    op.drop_table("cp_join_applications")
    op.drop_column("cp_users", "last_seen_at")
