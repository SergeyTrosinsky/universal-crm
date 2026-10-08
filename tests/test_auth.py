import pytest
from sqlalchemy import select

from app.models import Role, User
from app.services import role_service, user_service
from app.services.role_service import RoleError
from app.services.user_service import UserError
from tests.conftest import PASSWORD, api_login


# ------------------------------------------------------------------ API: вход
def test_login_returns_token_and_me_works_by_cookie(client, make_user):
    make_user("anna@example.com", full_name="Анна")
    api_login(client, "anna@example.com")
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "anna@example.com"
    assert me.json()["role"]["code"] == "employee"


def test_login_is_case_insensitive_for_email(client, make_user):
    make_user("anna@example.com")
    api_login(client, "  ANNA@Example.com ")


def test_wrong_password_and_unknown_user_look_the_same(client, make_user):
    make_user("anna@example.com")
    bad_pwd = client.post("/api/v1/auth/login", json={"email": "anna@example.com", "password": "nope"})
    unknown = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert bad_pwd.status_code == unknown.status_code == 401
    assert bad_pwd.json() == unknown.json()


def test_inactive_user_cannot_login(client, make_user):
    make_user("off@example.com", is_active=False)
    resp = client.post("/api/v1/auth/login", json={"email": "off@example.com", "password": PASSWORD})
    assert resp.status_code == 401


def test_bearer_token_works_without_cookie(client, make_user):
    make_user("anna@example.com")
    token = api_login(client, "anna@example.com")
    client.cookies.clear()
    assert client.get("/api/v1/auth/me").status_code == 401
    ok = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


def test_garbage_token_rejected(client):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_logout_clears_cookie(client, make_user):
    make_user("anna@example.com")
    api_login(client, "anna@example.com")
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_old_token_dies_after_password_change(client, factory, make_user):
    user_id = make_user("anna@example.com")
    token = api_login(client, "anna@example.com")
    with factory() as s:
        user_service.change_own_password(s, s.get(User, user_id), "another-password-1")
    client.cookies.clear()
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_dies_when_user_deactivated(client, factory, make_user):
    admin_id = make_user("boss@example.com", role="admin")
    user_id = make_user("anna@example.com")
    token = api_login(client, "anna@example.com")
    with factory() as s:
        user_service.update_user(s, s.get(User, user_id), actor=s.get(User, admin_id), is_active=False)
    client.cookies.clear()
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# ------------------------------------------------------------ API: права доступа
def test_users_endpoint_requires_permission(client, make_user):
    make_user("anna@example.com", role="employee")
    make_user("boss@example.com", role="admin")

    api_login(client, "anna@example.com")
    assert client.get("/api/v1/users").status_code == 403

    client.cookies.clear()
    assert client.get("/api/v1/users").status_code == 401

    api_login(client, "boss@example.com")
    resp = client.get("/api/v1/users")
    assert resp.status_code == 200
    assert {u["email"] for u in resp.json()} == {"anna@example.com", "boss@example.com"}


def test_admin_creates_and_updates_user_via_api(client, factory, make_user):
    make_user("boss@example.com", role="admin")
    api_login(client, "boss@example.com")
    with factory() as s:
        manager_id = s.scalar(select(Role).where(Role.code == "manager")).id

    created = client.post("/api/v1/users", json={
        "email": "New@Example.com", "full_name": "Новый", "password": "longenough1", "role_id": manager_id,
    })
    assert created.status_code == 201, created.text
    assert created.json()["email"] == "new@example.com"
    assert "password" not in created.json() and "hashed_password" not in created.json()

    dup = client.post("/api/v1/users", json={
        "email": "new@example.com", "full_name": "Дубль", "password": "longenough1", "role_id": manager_id,
    })
    assert dup.status_code == 400

    weak = client.post("/api/v1/users", json={
        "email": "weak@example.com", "full_name": "Слабый", "password": "123", "role_id": manager_id,
    })
    assert weak.status_code == 422

    patched = client.patch(f"/api/v1/users/{created.json()['id']}", json={"full_name": "Переименован"})
    assert patched.status_code == 200
    assert patched.json()["full_name"] == "Переименован"


def test_admin_cannot_deactivate_self(client, make_user):
    admin_id = make_user("boss@example.com", role="admin")
    api_login(client, "boss@example.com")
    resp = client.patch(f"/api/v1/users/{admin_id}", json={"is_active": False})
    assert resp.status_code == 400


# ------------------------------------------------------------- сервисы: правила
def test_non_admin_cannot_touch_or_create_admins(factory, make_user):
    """Пользователь с правом users:manage, но без полного доступа, не может ни править
    администраторов, ни выдавать роль администратора (повышение прав)."""
    with factory() as s:
        hr_role = role_service.create_role(
            s, code="hr", name="HR", description=None, permissions=["users:manage"]
        )
        hr_role_id = hr_role.id
        admin_role_id = s.scalar(select(Role).where(Role.code == "admin")).id
        employee_role_id = s.scalar(select(Role).where(Role.code == "employee")).id
    admin_id = make_user("boss@example.com", role="admin")
    employee_id = make_user("anna@example.com", role="employee")
    with factory() as s:
        hr = user_service.create_user(
            s, email="hr@example.com", full_name="HR", password=PASSWORD, role_id=hr_role_id
        )
        with pytest.raises(UserError):  # править администратора нельзя
            user_service.update_user(s, s.get(User, admin_id), actor=hr, role_id=employee_role_id)
        with pytest.raises(UserError):  # назначить роль администратора нельзя
            user_service.update_user(s, s.get(User, employee_id), actor=hr, role_id=admin_role_id)
        with pytest.raises(UserError):  # создать администратора нельзя
            user_service.create_user(
                s, email="x@example.com", full_name="X", password=PASSWORD, role_id=admin_role_id, actor=hr
            )
        # а обычного сотрудника править можно
        renamed = user_service.update_user(s, s.get(User, employee_id), actor=hr, full_name="Анна К.")
        assert renamed.full_name == "Анна К."


def test_admin_roles_changes_are_guarded(factory, make_user):
    admin1 = make_user("a1@example.com", role="admin")
    admin2 = make_user("a2@example.com", role="admin")
    with factory() as s:
        employee_role_id = s.scalar(select(Role).where(Role.code == "employee")).id
        with pytest.raises(UserError):  # свою роль менять нельзя
            user_service.update_user(s, s.get(User, admin1), actor=s.get(User, admin1), role_id=employee_role_id)
        # другого администратора понизить можно, пока остаётся ещё один
        user_service.update_user(s, s.get(User, admin2), actor=s.get(User, admin1), role_id=employee_role_id)
        assert s.get(User, admin2).role.code == "employee"


def test_ensure_first_admin_only_on_empty_db(factory, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "FIRST_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setattr(settings, "FIRST_ADMIN_PASSWORD", "long-password-1")
    with factory() as s:
        first = user_service.ensure_first_admin(s)
        assert first is not None and first.role.code == "admin"
        assert user_service.ensure_first_admin(s) is None  # второй раз ничего не создаёт


# --------------------------------------------------------------------- роли
def test_role_rules(factory, make_user):
    make_user("anna@example.com", role="employee")
    with factory() as s:
        employee = s.scalar(select(Role).where(Role.code == "employee"))
        admin = s.scalar(select(Role).where(Role.code == "admin"))
        with pytest.raises(RoleError):
            role_service.delete_role(s, employee)  # системная
        with pytest.raises(RoleError):
            role_service.update_role(s, admin, permissions=["clients:read"])  # права админа фиксированы

        custom = role_service.create_role(
            s, code="master", name="Мастер", description="Салон", permissions=["clients:read", "clients:read"]
        )
        assert custom.permissions == ["clients:read"]
        with pytest.raises(RoleError):
            role_service.create_role(s, code="master", name="Дубль", description=None, permissions=[])
        with pytest.raises(RoleError):
            role_service.create_role(s, code="bad", name="X", description=None, permissions=["*"])
        role_service.delete_role(s, custom)


# ------------------------------------------------------------------- веб-страницы
def test_web_redirects_anonymous_to_login(client):
    resp = client.get("/profile")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=%2Fprofile"


def test_web_login_flow(client, make_user):
    make_user("anna@example.com", full_name="Анна Иванова")
    page = client.get("/login")
    assert page.status_code == 200 and "Войдите" in page.text

    bad = client.post("/login", data={"email": "anna@example.com", "password": "wrong", "next": "/"})
    assert bad.status_code == 401 and "Неверный email или пароль" in bad.text

    ok = client.post("/login", data={"email": "anna@example.com", "password": PASSWORD, "next": "/profile"})
    assert ok.status_code == 303 and ok.headers["location"] == "/profile"

    profile = client.get("/profile")
    assert profile.status_code == 200 and "Анна Иванова" in profile.text

    out = client.post("/logout")
    assert out.status_code == 303 and out.headers["location"] == "/login"
    assert client.get("/profile").status_code == 303


@pytest.mark.parametrize("evil", ["//evil.com", "https://evil.com", "/\\evil.com"])
def test_login_blocks_open_redirect(client, make_user, evil):
    make_user("anna@example.com")
    resp = client.post("/login", data={"email": "anna@example.com", "password": PASSWORD, "next": evil})
    assert resp.status_code == 303 and resp.headers["location"] == "/"


def test_web_user_pages_need_permission(client, make_user):
    make_user("anna@example.com", role="employee")
    client.post("/login", data={"email": "anna@example.com", "password": PASSWORD, "next": "/"})
    resp = client.get("/settings/users", headers={"accept": "text/html"})
    assert resp.status_code == 403 and "Доступ запрещён" in resp.text


def test_web_admin_manages_users_and_roles(client, factory, make_user):
    make_user("boss@example.com", role="admin")
    client.post("/login", data={"email": "boss@example.com", "password": PASSWORD, "next": "/"})
    with factory() as s:
        employee_id = s.scalar(select(Role).where(Role.code == "employee")).id

    assert client.get("/settings/users").status_code == 200
    assert client.get("/settings/roles").status_code == 200

    created = client.post("/settings/users/new", data={
        "email": "kate@example.com", "full_name": "Катя", "password": "longenough1",
        "role_id": employee_id, "is_active": "1",
    })
    assert created.status_code == 303
    assert "Катя" in client.get("/settings/users").text

    dup = client.post("/settings/users/new", data={
        "email": "kate@example.com", "full_name": "Катя 2", "password": "longenough1", "role_id": employee_id,
    })
    assert dup.status_code == 400 and "уже существует" in dup.text

    role = client.post("/settings/roles/new", data={
        "code": "master", "name": "Мастер", "description": "", "permissions": ["clients:read", "deals:read"],
    })
    assert role.status_code == 303
    assert "Мастер" in client.get("/settings/roles").text


def test_web_change_password_keeps_session_alive(client, make_user):
    make_user("anna@example.com")
    client.post("/login", data={"email": "anna@example.com", "password": PASSWORD, "next": "/"})

    wrong = client.post("/profile/password", data={
        "current_password": "bad", "new_password": "new-password-1", "confirm_password": "new-password-1",
    })
    assert wrong.status_code == 400

    ok = client.post("/profile/password", data={
        "current_password": PASSWORD, "new_password": "new-password-1", "confirm_password": "new-password-1",
    })
    assert ok.status_code == 303
    assert client.get("/profile").status_code == 200  # выданный новый токен принят

    client.post("/logout")
    relog = client.post("/login", data={"email": "anna@example.com", "password": "new-password-1", "next": "/"})
    assert relog.status_code == 303 and relog.headers["location"] == "/"


def test_unknown_page_renders_html_error_for_browsers_and_json_for_api(client):
    html = client.get("/nope", headers={"accept": "text/html"})
    assert html.status_code == 404 and "Страница не найдена" in html.text
    api = client.get("/api/v1/nope")
    assert api.status_code == 404 and api.json()["detail"] == "Not Found"
