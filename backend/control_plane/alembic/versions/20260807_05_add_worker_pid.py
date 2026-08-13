"""Add worker_pid to task nodes for per-node subprocess hard-stop."""
import sqlalchemy as sa
from alembic import op


revision = "20260807_05"
down_revision = "20260809_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    node_columns = {column["name"] for column in inspector.get_columns("cp_task_nodes")}
    if "worker_pid" not in node_columns:
        op.add_column("cp_task_nodes", sa.Column("worker_pid", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("cp_task_nodes", "worker_pid")
