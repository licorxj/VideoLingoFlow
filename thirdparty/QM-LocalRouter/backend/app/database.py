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
    ]
    async with engine.begin() as conn:
        for table, col, col_def in columns_to_add:
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
            except Exception:
                pass


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _add_missing_columns()

