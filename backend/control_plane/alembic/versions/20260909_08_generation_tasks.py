"""add generation task ledger table

生成任务台账：登记每次生图/生视频/TTS 调用（kind/目标/接口/模型/prompt/上游任务/结果/
错误/耗时），用于运营排查与单分镜重试（重试记录通过 upstream_task_id 串联）。

Revision ID: 20260909_08
Revises: 20260909_07
"""

import sqlalchemy as sa
from alembic import op


revision = "20260909_08"
down_revision = "20260909_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cp_generation_tasks" in set(inspector.get_table_names()):
        return
    op.create_table(
        "cp_generation_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("creation_id", sa.String(36),
                  sa.ForeignKey("cp_creations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("chapter_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("step_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("interface", sa.String(64), nullable=False, server_default=""),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("mode", sa.String(32), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text, nullable=False, server_default=""),
        sa.Column("upstream_task_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="success"),
        sa.Column("result", sa.Text, nullable=False, server_default=""),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("ix_cp_generation_tasks_creation_kind",
                    "cp_generation_tasks", ["creation_id", "kind"])
    op.create_index("ix_cp_generation_tasks_target",
                    "cp_generation_tasks", ["target_type", "target_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cp_generation_tasks" not in set(inspector.get_table_names()):
        return
    op.drop_index("ix_cp_generation_tasks_target", table_name="cp_generation_tasks")
    op.drop_index("ix_cp_generation_tasks_creation_kind", table_name="cp_generation_tasks")
    op.drop_table("cp_generation_tasks")
