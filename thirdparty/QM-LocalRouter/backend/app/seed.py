"""首次安装种子数据：DeepSeek 平台 + 默认模型 + 全部策略。

设计原则
--------
* **只在全新数据库（``providers`` 表为空）时执行**。老用户升级时表里已有数据，
  本模块直接返回，绝不改动其平台 / 模型 / 策略配置。
* 目的是降低新用户学习成本：装好即有一套可用的「平台 + 模型 + 11 个策略」骨架，
  用户只需在「API Keys」里填一个 DeepSeek key（留空是刻意设计，不预置任何密钥）。
* 所有策略都指向同一个默认模型，用户后续按需把规则换成更合适的模型即可。

由 :func:`app.database.init_db` 在 ``create_all`` 之后调用，因此新装（含
``scripts/init_db.py``）与直接启动后端两条路径都会命中。
"""
from __future__ import annotations

import json

from sqlalchemy import func, select

from app.models.model import Model
from app.models.provider import Provider
from app.models.strategy import Strategy, StrategyRule

# --------------------------------------------------------------------------- #
# DeepSeek 平台（base_url 必须带 /v1：forwarder 直接拼 "{base_url}/chat/completions"）
# --------------------------------------------------------------------------- #
DEEPSEEK_NAME = "DeepSeek"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_HOMEPAGE = "https://api-docs.deepseek.com/quick_start/pricing"
DEEPSEEK_ICON = "https://unpkg.com/@lobehub/icons-static-png@latest/light/deepseek.png"
DEEPSEEK_DESCRIPTION = "DeepSeek 官方平台。填入 API Key 后即可使用（密钥留空不影响查看配置）。"

# 默认模型：DeepSeek V4.1 Flash
DEFAULT_MODEL_ID = "deepseek-v4.1-flash"
DEFAULT_MODEL_NAME = "DeepSeek V4.1 Flash"

# 额外预置为「可选」但非默认的模型，方便用户一键切换（默认规则只指向上面的模型）
EXTRA_MODELS = [
    ("deepseek-v4-flash", "DeepSeek V4 Flash"),
    ("deepseek-v4-pro", "DeepSeek V4 Pro"),
]

# --------------------------------------------------------------------------- #
# 11 个策略：名称 / 说明 / 负载均衡策略 / 超时 / 重试次数
# 取值与 VideoLingo 现网使用的策略保持一致，避免新用户得到与老用户不同的行为。
# --------------------------------------------------------------------------- #
STRATEGY_SEEDS = [
    ("vlf-01", "流连视听videolingoFlow的默认模型", "token_threshold", 60, 1),
    ("vlf-02", "流连视听字幕纠错阶段模型", "failover", 60, 1),
    ("vlf-03", "流连视听句子分割模型", "round_robin", 60, 1),
    ("vlf-04", "流连视听-内容总结阶段模型", "failover", 60, 1),
    ("vlf-05", "流连视听-逐句翻译阶段模型", "round_robin", 60, 1),
    ("vlf-06", "流连视听-反思翻译阶段模型", "round_robin", 60, 1),
    ("vlf-07", "流连视听 字幕对齐阶段模型", "round_robin", 60, 1),
    ("vlf-08", "流连视听  配音任务制作阶段模型", "round_robin", 60, 1),
    ("vlf-agent", "流连视听  智能体专用模型", "failover", 60, 1),
    ("vlf-09", "流连视听 -字幕缩减阶段模型", "failover", 60, 0),
    ("vlf-create", "流连视听创意创作专业模型", "failover", 120, 1),
]


async def _seed_app_settings(provider_id: int) -> None:
    """首次安装时把「默认模型」写进 app_settings.json（已存在则不动）。

    该文件只在「转发设置」页展示与本地直连的兜底默认值，真正的路由仍由策略决定。
    文件已存在说明用户已经有自己的设置，一律不改。
    """
    try:
        from app.config import DATA_DIR

        path = DATA_DIR / "app_settings.json"
        if path.exists():
            return
        payload = {
            "output_protocol": "openai",
            "default_model": DEFAULT_MODEL_ID,
            "default_provider_id": provider_id,
            "lan_access": False,
            "auth_mode": "open",
            "enabled_groups": {"openai": True, "media": True, "multi": True, "alias": True},
            "oauth_token_hours": 24,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # 设置文件写失败不影响数据库种子，前端会退回 DEFAULTS
        pass


async def seed_new_install() -> dict | None:
    """全新数据库时写入 DeepSeek 平台 / 默认模型 / 全部策略。

    Returns:
        None   —— 数据库已有数据（老用户），未做任何改动
        dict   —— 实际写入的摘要，便于启动日志展示
    """
    from app.database import async_session

    async with async_session() as session:
        existing = (
            await session.execute(select(func.count()).select_from(Provider))
        ).scalar_one()
        if existing:
            return None

        provider = Provider(
            name=DEEPSEEK_NAME,
            protocol="openai",
            base_url=DEEPSEEK_BASE_URL,
            auth_type="api_key",
            key_strategy="round_robin",
            key_switch_mode="none",
            key_rpm_threshold=0,
            key_count_threshold=0,
            description=DEEPSEEK_DESCRIPTION,
            icon=DEEPSEEK_ICON,
            homepage=DEEPSEEK_HOMEPAGE,
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        default_model = Model(
            provider_id=provider.id,
            model_id=DEFAULT_MODEL_ID,
            display_name=DEFAULT_MODEL_NAME,
            model_type="text",
            is_active=True,
        )
        session.add(default_model)
        await session.flush()

        for model_id, display_name in EXTRA_MODELS:
            session.add(
                Model(
                    provider_id=provider.id,
                    model_id=model_id,
                    display_name=display_name,
                    model_type="text",
                    is_active=True,
                )
            )

        existing_names = set(
            (await session.execute(select(Strategy.name))).scalars()
        )
        seeded_strategies: list[str] = []
        for name, description, lb_strategy, timeout, retry_count in STRATEGY_SEEDS:
            if name in existing_names:
                continue
            seeded_strategies.append(name)
            strategy = Strategy(
                name=name,
                description=description,
                lb_strategy=lb_strategy,
                key_strategy="round_robin",
                key_switch_mode="none",
                key_rpm_threshold=0,
                key_count_threshold=0,
                is_active=True,
                timeout=timeout,
                retry_count=retry_count,
            )
            session.add(strategy)
            await session.flush()
            session.add(
                StrategyRule(
                    strategy_id=strategy.id,
                    provider_id=provider.id,
                    model_id=default_model.id,
                    priority=0,
                    weight=1,
                    is_active=True,
                )
            )

        await session.commit()
        summary = {
            "provider_id": provider.id,
            "provider": DEEPSEEK_NAME,
            "model": DEFAULT_MODEL_ID,
            "strategies": seeded_strategies,
        }

    await _seed_app_settings(summary["provider_id"])
    return summary
