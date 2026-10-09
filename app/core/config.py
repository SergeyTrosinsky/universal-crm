"""Настройки приложения из переменных окружения / .env."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Universal CRM"
    DEBUG: bool = False

    DATABASE_URL: str = "sqlite:///./crm.db"

    AUTO_CREATE_SCHEMA: bool = True

    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8
    AUTH_COOKIE_NAME: str = "crm_access_token"
    AUTH_COOKIE_SECURE: bool = False

    CSRF_ENABLED: bool = True
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_MAX_ATTEMPTS_PER_IP: int = 30
    LOGIN_WINDOW_SECONDS: int = 300
    TRUST_PROXY_HEADERS: bool = False

    IMPORT_MAX_ROWS: int = 5000
    IMPORT_MAX_FILE_MB: int = 5
    IMPORT_DIR: str = ""

    APP_TIMEZONE: str = "Europe/Moscow"

    FIRST_ADMIN_EMAIL: str | None = None
    FIRST_ADMIN_PASSWORD: str | None = None
    FIRST_ADMIN_NAME: str = "Администратор"

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+psycopg2://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
