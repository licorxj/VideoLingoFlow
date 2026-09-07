"""seed common credential entries so new users can fill values directly"""

import uuid

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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    existing = {row[0] for row in bind.execute(sa.text(f"SELECT name FROM {_TABLE}"))}
    for name, purpose in _SEED:
        if name in existing:
            continue
        bind.execute(
            sa.text(
                f"INSERT INTO {_TABLE} (id, version, name, value, purpose, rotate, current_index) "
                "VALUES (:id, 1, :name, '', :purpose, :rotate, 0)"
            ),
            {"id": uuid.uuid4().hex, "name": name, "purpose": purpose, "rotate": True},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    for name, _purpose in _SEED:
        bind.execute(sa.text(f"DELETE FROM {_TABLE} WHERE name = :n"), {"n": name})
