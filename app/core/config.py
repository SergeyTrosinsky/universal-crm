"""Настройки приложения из переменных окружения / .env."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Universal CRM"
    DEBUG: bool = False

    # sqlite:///./crm.db  или  postgresql+psycopg2://user:pass@host:5432/crm
    DATABASE_URL: str = "sqlite:///./crm.db"

    # True: таблицы создаются при старте (удобно в разработке). В продакшене поставьте false
    # и применяйте миграции: `alembic upgrade head`.
    AUTO_CREATE_SCHEMA: bool = True

    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8
    AUTH_COOKIE_NAME: str = "crm_access_token"
    AUTH_COOKIE_SECURE: bool = False  # True за HTTPS

    # Защита от подделки запросов (CSRF) и подбора пароля.
    CSRF_ENABLED: bool = True
    LOGIN_MAX_ATTEMPTS: int = 5            # неудачных входов на один email за окно
    LOGIN_MAX_ATTEMPTS_PER_IP: int = 30    # неудачных входов с одного IP за окно
    LOGIN_WINDOW_SECONDS: int = 300        # окно подсчёта и длительность блокировки
    TRUST_PROXY_HEADERS: bool = False      # True за reverse-proxy: IP берётся из X-Forwarded-For

    # Импорт клиентов и сделок из CSV / Excel.
    IMPORT_MAX_ROWS: int = 5000            # строк данных в одном файле
    IMPORT_MAX_FILE_MB: int = 5            # размер загружаемого файла
    IMPORT_DIR: str = ""                   # куда класть файлы до подтверждения; пусто = временная папка ОС

    # Часовой пояс для отображения дат в интерфейсе (в БД всё хранится в UTC).
    APP_TIMEZONE: str = "Europe/Moscow"

    # Если пользователей в БД ещё нет, при старте будет создан администратор.
    FIRST_ADMIN_EMAIL: str | None = None
    FIRST_ADMIN_PASSWORD: str | None = None
    FIRST_ADMIN_NAME: str = "Администратор"

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Heroku/Render отдают postgres:// — SQLAlchemy 2.0 такой диалект не знает.
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
