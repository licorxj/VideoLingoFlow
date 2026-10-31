from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def _add_missing_columns():
    columns_to_add = [
        ("models", "is_multimodal", "BOOLEAN DEFAULT 0"),
        ("models", "model_type", "VARCHAR(20) DEFAULT 'text'"),
        ("models", "context_window", "INTEGER"),
        ("models", "temperature", "FLOAT"),
        ("models", "price_input", "FLOAT"),
        ("models", "price_output", "FLOAT"),
        ("providers", "icon", "VARCHAR(500) DEFAULT ''"),
        ("strategies", "key_strategy", "VARCHAR(20) DEFAULT 'round_robin'"),
        ("strategies", "key_switch_mode", "VARCHAR(20) DEFAULT 'none'"),
        ("strategies", "key_rpm_threshold", "INTEGER DEFAULT 0"),
        ("strategies", "key_count_threshold", "INTEGER DEFAULT 0"),
        ("strategies", "rule_token_threshold", "INTEGER DEFAULT 0"),
        ("strategies", "rule_token_period", "VARCHAR(20) DEFAULT 'per_day'"),
        ("request_logs", "prompt_tokens", "INTEGER DEFAULT 0"),
        ("request_logs", "completion_tokens", "INTEGER DEFAULT 0"),
        ("request_logs", "total_tokens", "INTEGER DEFAULT 0"),
        ("conversations", "chat_mode", "VARCHAR(20) DEFAULT 'strategy'"),
        ("conversations", "stream_mode", "BOOLEAN DEFAULT 1"),
        ("conversations", "model_used", "VARCHAR(200) DEFAULT ''"),
        ("conversations", "provider_used", "VARCHAR(200) DEFAULT ''"),
        ("models", "status", "VARCHAR(20) DEFAULT 'untested'"),
        ("models", "last_error", "VARCHAR(500) DEFAULT ''"),
        ("providers", "homepage", "VARCHAR(500) DEFAULT ''"),
        ("providers", "auth_type", "VARCHAR(20) DEFAULT 'api_key'"),
        # 上游 v2.x 在 Provider 模型新增的直连多 Key 策略列（模型有、迁移曾漏登）
        ("providers", "key_strategy", "VARCHAR(20) DEFAULT 'round_robin'"),
        ("providers", "key_switch_mode", "VARCHAR(20) DEFAULT 'none'"),
        ("providers", "key_rpm_threshold", "INTEGER DEFAULT 0"),
        ("providers", "key_count_threshold", "INTEGER DEFAULT 0"),
        ("providers", "key_strategy", "VARCHAR(20) DEFAULT 'round_robin'"),
        ("providers", "key_switch_mode", "VARCHAR(20) DEFAULT 'none'"),
        ("providers", "key_rpm_threshold", "INTEGER DEFAULT 0"),
        ("providers", "key_count_threshold", "INTEGER DEFAULT 0"),
        ("api_keys", "oauth_profile", "VARCHAR(50) DEFAULT ''"),
        ("api_keys", "oauth_refresh", "TEXT DEFAULT ''"),
        ("api_keys", "oauth_expires_at", "INTEGER DEFAULT 0"),
        ("api_keys", "status_until", "INTEGER DEFAULT 0"),
        ("api_keys", "fail_count", "INTEGER DEFAULT 0"),
    ]
    async with engine.begin() as conn:
        for table, col, col_def in columns_to_add:
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
            except Exception:
                pass


async def init_db():
    # 显式导入模型包：确保所有表都注册到 Base.metadata。
    # 直接调用 init_db() 的场景（scripts/init_db.py、独立脚本）若没有先导入
    # routers，models 不会被加载，create_all 会静默建出空库。
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _add_missing_columns()
    # 首次安装（providers 表为空）时预置 DeepSeek 平台 / 默认模型 / 全部策略，
    # 降低新用户学习成本；老用户库已有数据，seed_new_install() 直接返回不改动。
    try:
        from app.seed import seed_new_install

        seeded = await seed_new_install()
        if seeded:
            print(
                "[init_db] 已初始化默认配置: "
                f"平台={seeded['provider']} 默认模型={seeded['model']} "
                f"策略={len(seeded['strategies'])} 个"
            )
    except Exception as exc:  # 种子失败不应阻塞服务启动
        print(f"[init_db] 默认配置初始化跳过: {exc}")

