"""add task runtime governance fields"""

import sqlalchemy as sa
from alembic import op


revision = "20260807_03"
down_revision = "20260807_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    task_columns = {column["name"] for column in inspector.get_columns("cp_tasks")}
    for name, column in (
        ("idempotency_key", sa.Column("idempotency_key", sa.String(length=512), unique=True)),
        ("queue", sa.Column("queue", sa.String(length=128), nullable=False, server_default="videolingo_io")),
        ("resource_class", sa.Column("resource_class", sa.String(length=32), nullable=False, server_default="io")),
        ("cancel_reason", sa.Column("cancel_reason", sa.String(length=256))),
        ("error_class", sa.Column("error_class", sa.String(length=64))),
        ("retry_count", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0")),
        ("max_retries", sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3")),
        ("timeout_seconds", sa.Column("timeout_seconds", sa.Integer())),
        ("deletion_requested", sa.Column("deletion_requested", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("worker_id", sa.Column("worker_id", sa.String(length=128))),
    ):
        if name not in task_columns:
            op.add_column("cp_tasks", column)
    node_columns = {column["name"] for column in inspector.get_columns("cp_task_nodes")}
    for name, column in (
        ("resource_class", sa.Column("resource_class", sa.String(length=32), nullable=False, server_default="io")),
        ("queue", sa.Column("queue", sa.String(length=128), nullable=False, server_default="videolingo_io")),
        ("cancel_reason", sa.Column("cancel_reason", sa.String(length=256))),
        ("error_class", sa.Column("error_class", sa.String(length=64))),
        ("worker_id", sa.Column("worker_id", sa.String(length=128))),
        ("checkpoint_key", sa.Column("checkpoint_key", sa.String(length=256))),
    ):
        if name not in node_columns:
            op.add_column("cp_task_nodes", column)


def downgrade() -> None:
    for name in ("checkpoint_key", "worker_id", "error_class", "cancel_reason", "queue", "resource_class"):
        op.drop_column("cp_task_nodes", name)
    for name in ("worker_id", "deletion_requested", "timeout_seconds", "max_retries", "retry_count", "error_class", "cancel_reason", "resource_class", "queue", "idempotency_key"):
        op.drop_column("cp_tasks", name)
