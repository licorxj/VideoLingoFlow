"""seed common credential entries so new users can fill values directly"""

import uuid
from typing import Any

import sqlalchemy as sa
from alembic import op


revision = "20260907_03"
down_revision = "20260907_02"
branch_labels = None
depends_on = None

_TABLE = "cp_credentials"

# (名称, 用途说明) —— value 留空，用户在「设置 → 密钥管理」中自行填入；
# 已存在的同名条目不会被覆盖（含用户已删除后重装升级的场景）。
_SEED = [
    ("BAILIAN_SDK_API_KEY", "阿里百炼的生图/视频用途 key"),
    ("HF_TOKEN", "HuggingFace 访问令牌，用于下载 Whisper 说话人识别（pyannote）等模型"),
    ("KIEAI_API_KEY", "kieAI 平台统一 key（全球多模态）"),
    ("LLM_API_KEY", "LLM 直连 API Key（自定义大模型接口）"),
    ("LLM_ROUTER_API_KEY", "本地模型路由器的访问 key"),
    ("LOCAL", "本地路由器默认 key"),
    ("MIMO_KEY", "小米 MiMo 平台 key，用于 TTS 和 ASR"),
    ("WULI_SDK_API_KEY", "Wuli AI 创作平台 key"),
]


# 本迁移显式写入的列（其余列按表结构动态补齐）
_FIXED_COLUMNS = ("id", "version", "name", "value", "purpose", "rotate", "current_index")


def _fixed_values(name: str, purpose: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "version": 1,
        "name": name,
        "value": "",
        "purpose": purpose,
        "rotate": True,
        "current_index": 0,
    }


def _placeholder_for(column: Any) -> Any:
    """为「本迁移之后才新增」的 NOT NULL 列补一个安全默认值。

    全新安装时首条迁移会用当前模型 ``create_all`` 建表，表里可能已经带有后面才
    加入的列（例如 ``register_url``）。此时硬编码列清单会因 NOT NULL 约束失败，
    因此这里按实际表结构补齐缺失列。可空/已有默认值的列返回 None（交给数据库）。
    """
    if column.get("nullable") or column.get("default") or column.get("server_default"):
        return None
    python_type = getattr(column["type"], "python_type", str)
    if python_type is bool:
        return False
    if python_type in (int, float):
        return 0
    return ""


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    extras: dict[str, Any] = {}
    for column in inspector.get_columns(_TABLE):
        if column["name"] in _FIXED_COLUMNS:
            continue
        value = _placeholder_for(column)
        if value is not None:
            extras[column["name"]] = value

    existing = {row[0] for row in bind.execute(sa.text(f"SELECT name FROM {_TABLE}"))}
    for name, purpose in _SEED:
        if name in existing:
            continue
        values = _fixed_values(name, purpose)
        values.update(extras)
        columns_sql = ", ".join(values)
        placeholders = ", ".join(f":{key}" for key in values)
        bind.execute(
            sa.text(f"INSERT INTO {_TABLE} ({columns_sql}) VALUES ({placeholders})"),
            values,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    for name, _purpose in _SEED:
        bind.execute(sa.text(f"DELETE FROM {_TABLE} WHERE name = :n"), {"n": name})
