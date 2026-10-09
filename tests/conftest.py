import os

os.environ.setdefault("CSRF_ENABLED", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.init_db import seed_defaults
from app.db.session import build_engine, get_db
from app.main import create_app
from app.models import Role
from app.services import user_service

PASSWORD = "password123"


@pytest.fixture(autouse=True)
def _reset_login_limiter():
    """Счётчики неудачных входов — в памяти процесса; между тестами их обнуляем."""
    from app.core.rate_limit import login_limiter

    login_limiter.reset()
    yield
    login_limiter.reset()


@pytest.fixture()
def factory():
    """Фабрика сессий поверх свежей in-memory SQLite со справочниками по умолчанию."""
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as s:
        seed_defaults(s)
    yield session_factory
    engine.dispose()


@pytest.fixture()
def make_user(factory):
    def _make(email="user@example.com", role="employee", full_name="Тест Пользователь",
              password=PASSWORD, is_active=True) -> int:
        with factory() as s:
            role_obj = s.scalar(select(Role).where(Role.code == role))
            user = user_service.create_user(
                s, email=email, full_name=full_name, password=password,
                role_id=role_obj.id, is_active=is_active,
            )
            return user.id

    return _make


@pytest.fixture()
def client(factory):
    app = create_app()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, follow_redirects=False)


def api_login(client: TestClient, email: str, password: str = PASSWORD) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]
