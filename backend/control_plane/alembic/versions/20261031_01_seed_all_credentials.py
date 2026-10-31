"""seed all credential entries referenced by shipped configs

为什么需要这个迁移
------------------
配置文件（``config.yaml`` / ``*_interfaces.json``）里只保存 ``secret://NAME`` 引用，
真实值存放在 ``cp_credentials``。新用户装完打开「密钥管理器」时，如果这些条目
根本不存在，就不知道该建哪个名字、去哪注册——学习成本很高。

本迁移把**软件内所有实际被引用的密钥名**一次性补齐：

* 已存在的同名条目**原样保留**（含 purpose / value / rotate / register_url），
  只补缺失项，绝不覆盖用户自己填过的 key；
* 新补条目 ``value`` 为空（前端显示「未设置」），并附上用途说明与注册链接，
  用户照着点进去拿 key 粘贴即可；
* 用户主动删除过的条目不会被重新创建（迁移只跑一次，不在每次启动时执行）。

``20260907_03_seed_credentials`` 已种入其中 8 项，本迁移是它的超集，用于覆盖后续
新增的 AGNES / ACESTEP / HUOSHAN / WULI_VIDEO / WHISPERX 等引用。
"""

import uuid
from typing import Any

import sqlalchemy as sa
from alembic import op


revision = "20261031_01"
down_revision = "20260923_01"
branch_labels = None
depends_on = None

_TABLE = "cp_credentials"

# (名称, 用途说明, 注册/获取地址)
# 名称集合 = 全仓库 ``secret://NAME`` 引用的并集（排除文档里的占位符 NAME）。
# 元组含义：(名称, 用途说明, 注册/获取地址, 是否多 key 轮换)
_SEED = [
    (
        "ACESTEP_API_KEY",
        "免费的AI音乐生成平台ACEstep-music",
        "https://acemusic.ai/playground/api-key",
        True,
    ),
    (
        "AGNES_API_KEY",
        "agnes平台的免费生图接口，flash的视频生成也是免费的",
        "https://platform.agnes-ai.com",
        True,
    ),
    (
        "BAILIAN_SDK_API_KEY",
        "阿里百炼的生图生视频用途key",
        "https://help.aliyun.com/zh/model-studio/get-api-key",
        False,
    ),
    (
        "HF_TOKEN",
        "HuggingFace 访问令牌，用于下载 Whisper 说话人识别（pyannote）等模型；不用可留空",
        "https://huggingface.co/settings/tokens",
        False,
    ),
    (
        "HUOSHAN_KEY",
        "火山引擎（豆包/火山方舟）key，用于生图生视频",
        "https://console.volcengine.com/ark/region:cn-beijing/apiKey",
        True,
    ),
    (
        "KIEAI_API_KEY",
        "kieAI-全球多模态顶尖模型聚合平台，价格实惠，用于生图、视频、音乐",
        "https://kie.ai?ref=1ef5b0d4df5fc43ae85034755f9bf754",
        True,
    ),
    (
        "LLM_API_KEY",
        "大模型直连 API Key（不经路由器、直连兼容 OpenAI 的接口时使用），一般不用填",
        "",
        False,
    ),
    (
        "LLM_ROUTER_API_KEY",
        "大模型路由器的访问 key（路由器默认 open 模式，一般不用填）",
        "",
        False,
    ),
    (
        "LOCAL",
        "大模型路由器本地默认 key，不用填",
        "",
        False,
    ),
    (
        "MIMO_KEY",
        "小米mimo平台key，用于TTS和ASR",
        "https://platform.xiaomimimo.com?ref=HKEQ8J",
        True,
    ),
    (
        "WHISPERX_LOCAL_HF_TOKEN",
        "WhisperX 本地说话人识别所需的 HuggingFace 令牌（需同意 pyannote 模型条款），不用可留空",
        "https://huggingface.co/settings/tokens",
        False,
    ),
    (
        "WULI_SDK_API_KEY",
        "阿里呜哩AI创作平台（生图）",
        "https://wuli.art/generate?openRegisterModal=true&inviteCode=WL-WULIGVKDM8GQ",
        False,
    ),
    (
        "WULI_VIDEO_SDK_API_KEY",
        "阿里呜哩AI创作平台（生视频）",
        "https://wuli.art/generate?openRegisterModal=true&inviteCode=WL-WULIGVKDM8GQ",
        False,
    ),
]

# 本迁移显式写入的列；其余列按表结构动态补齐（表可能已带有后续版本新增的列）
_FIXED_COLUMNS = ("id", "version", "name", "value", "purpose", "register_url", "rotate", "current_index")


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

    extras: dict[str, Any] = {}
    for column in inspector.get_columns(_TABLE):
        if column["name"] in _FIXED_COLUMNS:
            continue
        value = _placeholder_for(column)
        if value is not None:
            extras[column["name"]] = value

    existing = {row[0] for row in bind.execute(sa.text(f"SELECT name FROM {_TABLE}"))}
    for name, purpose, register_url, rotate in _SEED:
        if name in existing:
            continue
        values: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "version": 1,
            "name": name,
            "value": "",
            "purpose": purpose,
            "register_url": register_url,
            "rotate": rotate,
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
    # 只删除本迁移新增、且仍为空的条目，避免误删用户已填写的 key
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    for name, _purpose, _register_url, _rotate in _SEED:
        bind.execute(
            sa.text(f"DELETE FROM {_TABLE} WHERE name = :n AND (value IS NULL OR value = '' OR value = '[]')"),
            {"n": name},
        )
