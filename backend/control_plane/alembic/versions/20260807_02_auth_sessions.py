"""add local account credentials and sessions"""

import sqlalchemy as sa
from alembic import op


revision = "20260807_02"
down_revision = "20260807_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("cp_users")}
    if "password_hash" not in user_columns:
        op.add_column("cp_users", sa.Column("password_hash", sa.String(length=256), nullable=False, server_default=""))
    if "is_active" not in user_columns:
        op.add_column("cp_users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    if not inspector.has_table("cp_sessions"):
        op.create_table(
            "cp_sessions",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
            sa.Column("user_id", sa.String(length=32), sa.ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("cp_sessions")
    op.drop_column("cp_users", "is_active")
    op.drop_column("cp_users", "password_hash")
