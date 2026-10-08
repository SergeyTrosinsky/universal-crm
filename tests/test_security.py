"""CSRF-защита форм и API по cookie, ограничение неудачных попыток входа."""
import re
import time

import pytest

from app.core import rate_limit
from app.core.config import get_settings
from tests.conftest import PASSWORD, api_login

LOGIN = "/api/v1/auth/login"


@pytest.fixture()
def csrf_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "CSRF_ENABLED", True)


def form_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "в форме нет скрытого поля csrf_token"
    return match.group(1)


def meta_token(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match
    return match.group(1)


def web_login_with_token(client, email):
    client.cookies.clear()
    token = form_token(client.get("/login").text)
    resp = client.post("/login", data={"email": email, "password": PASSWORD, "csrf_token": token})
    assert resp.status_code in (302, 303), resp.text[:300]


# ------------------------------------------------------------------ CSRF
def test_login_form_requires_token(client, make_user, csrf_on):
    make_user("a@example.com")
    token = form_token(client.get("/login").text)
    creds = {"email": "a@example.com", "password": PASSWORD}
    assert client.post("/login", data=creds).status_code == 403
    assert client.post("/login", data={**creds, "csrf_token": "подделка"}).status_code == 403
    assert client.post("/login", data={**creds, "csrf_token": token}).status_code in (302, 303)


def test_every_post_form_carries_token_and_post_needs_it(client, make_user, csrf_on):
    make_user("admin@example.com", role="admin")
    web_login_with_token(client, "admin@example.com")
    for url in ("/clients", "/clients/new", "/deals/new", "/settings/fields", "/settings/templates", "/tasks/new"):
        html = client.get(url).text
        forms = re.findall(r'<form[^>]*method="post"', html)
        assert forms and len(forms) == html.count('name="csrf_token"'), url

    token = form_token(client.get("/clients/new").text)
    data = {"type": "person", "name": "Анна"}
    assert client.post("/clients/new", data=data).status_code == 403
    assert client.post("/clients/new", data={**data, "csrf_token": token}).status_code in (302, 303)
    # изменяющий запрос без токена не должен менять данные (удаление)
    assert client.post("/logout").status_code == 403
    assert client.get("/clients").status_code == 200


def test_token_is_rotated_on_login_and_logout(client, make_user, csrf_on):
    make_user("a@example.com")
    page = client.get("/login")
    before = form_token(page.text)
    login = client.post("/login", data={"email": "a@example.com", "password": PASSWORD, "csrf_token": before})
    assert login.status_code in (302, 303)
    after = meta_token(client.get("/clients").text)
    assert after != before  # та же сессия, но токен после входа новый
    out = client.post("/logout", data={"csrf_token": after})
    assert out.status_code in (302, 303)
    assert form_token(client.get("/login").text) != after


def test_api_cookie_auth_needs_header_but_bearer_does_not(client, make_user, csrf_on):
    make_user("admin@example.com", role="admin")
    bearer = api_login(client, "admin@example.com")  # вход без токена разрешён, ставит cookie
    assert client.post("/api/v1/clients", json={"name": "A"}).status_code == 403
    assert client.delete("/api/v1/clients/1").status_code == 403

    token = meta_token(client.get("/clients").text)  # cookie-вход, страница отдаёт токен
    assert client.post("/api/v1/clients", json={"name": "A"}, headers={"X-CSRF-Token": token}).status_code == 201
    assert client.post("/api/v1/clients", json={"name": "B"}, headers={"X-CSRF-Token": "x"}).status_code == 403
    assert client.get("/api/v1/clients").status_code == 200  # чтение токена не требует

    client.cookies.clear()
    created = client.post("/api/v1/clients", json={"name": "C"}, headers={"Authorization": f"Bearer {bearer}"})
    assert created.status_code == 201  # Bearer браузер сам не подставляет — CSRF невозможен


def test_csrf_can_be_disabled(client, make_user):
    # по умолчанию в тестах защита выключена (CSRF_ENABLED=false)
    make_user("a@example.com")
    resp = client.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert resp.status_code in (302, 303)


# ------------------------------------------------------------------ вход: ограничение попыток
def test_api_login_locks_after_failures(client, make_user, monkeypatch):
    make_user("a@example.com")
    make_user("b@example.com")
    settings = get_settings()
    monkeypatch.setattr(settings, "LOGIN_MAX_ATTEMPTS", 3)
    bad = {"email": "a@example.com", "password": "неверный"}
    for _ in range(3):
        assert client.post(LOGIN, json=bad).status_code == 401

    blocked = client.post(LOGIN, json={"email": "A@example.com", "password": PASSWORD})  # даже верный пароль
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0 and "Слишком много" in blocked.json()["detail"]
    assert client.post(LOGIN, json={"email": "b@example.com", "password": PASSWORD}).status_code == 200

    later = time.monotonic() + settings.LOGIN_WINDOW_SECONDS + 5
    monkeypatch.setattr(rate_limit.login_limiter, "_now", lambda: later)
    assert client.post(LOGIN, json={"email": "a@example.com", "password": PASSWORD}).status_code == 200


def test_success_resets_failure_counter(client, make_user, monkeypatch):
    make_user("a@example.com")
    monkeypatch.setattr(get_settings(), "LOGIN_MAX_ATTEMPTS", 3)
    bad = {"email": "a@example.com", "password": "неверный"}
    good = {"email": "a@example.com", "password": PASSWORD}
    for _ in range(2):
        client.post(LOGIN, json=bad)
    assert client.post(LOGIN, json=good).status_code == 200
    for _ in range(2):
        assert client.post(LOGIN, json=bad).status_code == 401  # счёт начался заново
    assert client.post(LOGIN, json=good).status_code == 200


def test_web_login_locks_with_429_page(client, make_user, monkeypatch):
    make_user("a@example.com")
    monkeypatch.setattr(get_settings(), "LOGIN_MAX_ATTEMPTS", 2)
    for _ in range(2):
        assert client.post("/login", data={"email": "a@example.com", "password": "нет"}).status_code == 401
    locked = client.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert locked.status_code == 429 and "Слишком много неудачных попыток" in locked.text
    assert "Retry-After" in locked.headers


def test_ip_limit_covers_many_accounts(client, make_user, monkeypatch):
    make_user("ok@example.com")
    monkeypatch.setattr(get_settings(), "LOGIN_MAX_ATTEMPTS_PER_IP", 3)
    for i in range(3):
        assert client.post(LOGIN, json={"email": f"user{i}@example.com", "password": "x"}).status_code == 401
    resp = client.post(LOGIN, json={"email": "ok@example.com", "password": PASSWORD})
    assert resp.status_code == 429


def test_unknown_email_is_limited_too(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "LOGIN_MAX_ATTEMPTS", 2)
    for _ in range(2):
        assert client.post(LOGIN, json={"email": "ghost@example.com", "password": "x"}).status_code == 401
    assert client.post(LOGIN, json={"email": "ghost@example.com", "password": "x"}).status_code == 429
