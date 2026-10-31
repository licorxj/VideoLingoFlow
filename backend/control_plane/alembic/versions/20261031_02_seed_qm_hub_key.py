"""seed QM_HUB_KEY credential

补入「晴沐智坊官方 key」这一项：
用户填好之后，调用晴沐 HUB 能力的节点可直接引用 ``secret://QM_HUB_KEY``，
不必在每个节点里重复配置。

语义与 ``20261031_01_seed_all_credentials`` 保持一致：

* 条目已存在（用户自己建过或填过值）→ **原样跳过**，绝不覆盖；
* 不存在才新建，``value`` 留空，用户点注册链接拿 key 再粘贴；
* 单 key 场景（官方 key 一人一个），``rotate`` 关闭。
"""

import uuid
from typing import Any

import sqlalchemy as sa
from alembic import op


revision = "20261031_02"
down_revision = "20261031_01"
branch_labels = None
depends_on = None

_TABLE = "cp_credentials"

_NAME = "QM_HUB_KEY"
_PURPOSE = "晴沐智坊官方key，填写之后可以在调用晴沐HUB能力的节点快捷使用key"
_REGISTER_URL = "https://www.licorxj.online/capability-hub"
_ROTATE = False

# 本迁移显式写入的列；其余列按表结构动态补齐（表可能已带有后续版本新增的列）
_FIXED_COLUMNS = (
    "id",
    "version",
    "name",
    "value",
    "purpose",
    "register_url",
    "rotate",
    "current_index",
)


def _placeholder_for(column: Any) -> Any:
    """为「本迁移之后才新增」的 NOT NULL 列补安全默认值。"""
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

    exists = bind.execute(
        sa.text(f"SELECT 1 FROM {_TABLE} WHERE name = :n"), {"n": _NAME}
    ).first()
    if exists:
        return

    extras: dict[str, Any] = {}
    for column in inspector.get_columns(_TABLE):
        if column["name"] in _FIXED_COLUMNS:
            continue
        value = _placeholder_for(column)
        if value is not None:
            extras[column["name"]] = value

    values: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "version": 1,
        "name": _NAME,
        "value": "",
        "purpose": _PURPOSE,
        "register_url": _REGISTER_URL,
        "rotate": _ROTATE,
        "current_index": 0,
    }
    values.update(extras)
    columns_sql = ", ".join(values)
    placeholders = ", ".join(f":{key}" for key in values)
    bind.execute(
        sa.text(f"INSERT INTO {_TABLE} ({columns_sql}) VALUES ({placeholders})"),
        values,
    )


def downgrade() -> None:
    # 只在仍为空值时删除，避免误删用户已填写的 key
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    bind.execute(
        sa.text(
            f"DELETE FROM {_TABLE} "
            "WHERE name = :n AND (value IS NULL OR value = '' OR value = '[]')"
        ),
        {"n": _NAME},
    )
