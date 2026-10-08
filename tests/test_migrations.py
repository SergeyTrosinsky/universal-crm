"""Миграции Alembic должны давать ровно ту схему, что описана в моделях."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

alembic_command = pytest.importorskip("alembic.command")
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

import app.models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _config(connection=None) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    yield eng
    eng.dispose()


def test_single_head():
    heads = ScriptDirectory.from_config(_config()).get_heads()
    assert len(heads) == 1, f"Несколько голов миграций: {heads}"


def test_upgrade_matches_models(engine):
    with engine.begin() as conn:
        alembic_command.upgrade(_config(conn), "head")
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], f"Миграции расходятся с моделями — создайте новую ревизию: {diff}"


def test_downgrade_removes_everything(engine):
    with engine.begin() as conn:
        alembic_command.upgrade(_config(conn), "head")
        alembic_command.downgrade(_config(conn), "base")
        tables = set(inspect(conn).get_table_names())
    assert tables <= {"alembic_version"}, tables
