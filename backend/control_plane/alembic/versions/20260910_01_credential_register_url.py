"""credential register_url: registration URL column for quick sign-up link"""

import sqlalchemy as sa
from alembic import op

revision = "20260910_01_credential_register_url"
down_revision = "20260907_02"
branch_labels = None
depends_on = None

_TABLE = "cp_credentials"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if "register_url" not in columns:
        op.add_column(_TABLE, sa.Column("register_url", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if "register_url" in columns:
        op.drop_column(_TABLE, "register_url")
