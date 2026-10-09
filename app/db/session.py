"""Engine и сессии. Переключение SQLite/PostgreSQL — только через DATABASE_URL."""
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings


def _unicode_lower(value):
    return value.lower() if isinstance(value, str) else value


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    """В SQLite внешние ключи (а значит и ON DELETE CASCADE) выключены по умолчанию.
    Заодно подменяем lower(): встроенная знает только ASCII, а поиск «иван» должен находить «Иван»."""

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        dbapi_conn.create_function("lower", 1, _unicode_lower, deterministic=True)


def build_engine(url: str, echo: bool = False) -> Engine:
    kwargs: dict = {"echo": echo, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        enable_sqlite_foreign_keys(engine)
    return engine


settings = get_settings()
engine = build_engine(settings.DATABASE_URL, echo=settings.DEBUG)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: одна сессия на запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
