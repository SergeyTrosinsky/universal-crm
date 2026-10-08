"""Окружение Alembic: метаданные приложения, URL из настроек (DATABASE_URL)."""
from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401  — регистрирует все таблицы в Base.metadata
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import build_engine

config = context.config
if config.config_file_name is not None and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite не умеет большинство ALTER — Alembic пересоздаёт таблицу «пакетом»
        render_as_batch=kwargs.pop("is_sqlite", False),
        **kwargs,
    )


def run_migrations_offline() -> None:
    url = get_settings().DATABASE_URL
    _configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"}, is_sqlite=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Тесты и скрипты могут передать готовое соединение: config.attributes["connection"]
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection, is_sqlite=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = build_engine(get_settings().DATABASE_URL)
    try:
        with engine.connect() as conn:
            _configure(connection=conn, is_sqlite=conn.dialect.name == "sqlite")
            with context.begin_transaction():
                context.run_migrations()
            conn.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
