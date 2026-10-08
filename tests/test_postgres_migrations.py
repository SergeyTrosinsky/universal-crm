"""Миграции на настоящем PostgreSQL. Пропускается, если TEST_POSTGRES_URL не задан.

ВНИМАНИЕ: тест очищает схему public в указанной базе — берите отдельную пустую базу, не рабочую.
Пример (контейнер из docker-compose, порт БД наружу не открыт — запустите отдельную):
    docker run --rm -d --name crm-pg-test -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine
    $env:TEST_POSTGRES_URL="postgresql+psycopg2://postgres:test@localhost:55432/postgres"   # PowerShell
    pytest tests/test_postgres_migrations.py
"""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

URL = os.environ.get("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_POSTGRES_URL не задан")

alembic_command = pytest.importorskip("alembic.command")
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402

import app.models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _config(connection) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["connection"] = connection
    return cfg


@pytest.fixture()
def engine():
    eng = create_engine(URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    yield eng
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    eng.dispose()


def test_upgrade_matches_models_and_downgrades(engine):
    with engine.begin() as conn:
        alembic_command.upgrade(_config(conn), "head")
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        assert diff == [], diff
        alembic_command.downgrade(_config(conn), "base")
        left = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        ).scalars().all()
        assert set(left) <= {"alembic_version"}, left
