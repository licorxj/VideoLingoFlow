from pydantic_settings import BaseSettings
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

class Settings(BaseSettings):
    APP_NAME: str = "LLM API Router"
    APP_VERSION: str = "1.0.0"
    HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 12002
    DATABASE_URL: str = f"sqlite+aiosqlite:///{DATA_DIR / 'app.db'}"
    ENCRYPTION_KEY: str = ""
    LOG_RETENTION_DAYS: int = 30
    DEFAULT_TIMEOUT: int = 120
    DEFAULT_RETRY_COUNT: int = 2
    CORS_ORIGINS: list[str] = ["http://localhost:12001", "http://127.0.0.1:12001", "http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def PORT(self) -> int:
        return self.BACKEND_PORT

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"

settings = Settings()
