"""Общие настройки: название CRM, валюта по умолчанию, термины."""
from app.services import settings_service
from tests.conftest import PASSWORD, api_login


def setup_admin(client, make_user):
    make_user("admin@example.com", role="admin")
    api_login(client, "admin@example.com")


def web_login(client, email):
    client.cookies.clear()
    resp = client.post("/login", data={"email": email, "password": PASSWORD, "next": "/"})
    assert resp.status_code in (302, 303), resp.text


def test_defaults_and_api_roundtrip(client, make_user):
    setup_admin(client, make_user)
    data = client.get("/api/v1/settings/general").json()
    assert data["default_currency"] == "RUB" and data["client_pl"] == "Клиенты" and data["app_name"] == ""

    upd = client.patch("/api/v1/settings/general", json={"app_name": "  МедЦентр  ", "client_pl": "Пациенты",
                                                         "client_sg": "Пациент", "client_acc": "пациента"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["app_name"] == "МедЦентр" and upd.json()["client_pl"] == "Пациенты"
    assert upd.json()["deal_pl"] == "Сделки"

    reset = client.post("/api/v1/settings/general/reset").json()
    assert reset["client_pl"] == "Клиенты" and reset["app_name"] == ""


def test_validation(client, make_user):
    setup_admin(client, make_user)
    for payload in ({"default_currency": "XXX"}, {"client_pl": "  "}, {"deal_sg": "я" * 61}, {"app_name": "я" * 61}):
        resp = client.patch("/api/v1/settings/general", json=payload)
        assert resp.status_code == 422, payload
    assert client.patch("/api/v1/settings/general", json={"default_currency": "usd"}).json()["default_currency"] == "USD"


def test_manage_requires_permission(client, make_user):
    make_user("mgr@example.com", role="manager")
    api_login(client, "mgr@example.com")
    assert client.get("/api/v1/settings/general").status_code == 200
    assert client.patch("/api/v1/settings/general", json={"client_pl": "X"}).status_code == 403
    web_login(client, "mgr@example.com")
    assert client.get("/settings/general").status_code == 403


def test_terms_are_used_in_pages(client, make_user):
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    saved = client.post("/settings/general", data={
        "app_name": "МедЦентр", "default_currency": "EUR",
        "client_pl": "Пациенты", "client_sg": "Пациент", "client_acc": "пациента",
        "deal_pl": "Приёмы", "deal_sg": "Приём", "deal_acc": "приём",
    })
    assert saved.status_code in (302, 303), saved.text[:400]

    clients = client.get("/clients").text
    assert "Пациенты" in clients and "Добавить пациента" in clients and "МедЦентр" in clients
    assert "Приёмы" in client.get("/deals").text and "Добавить приём" in client.get("/deals/new").text
    home = client.get("/").text
    assert "Пациенты" in home and "Приёмы" in home
    form = client.get("/deals/new").text
    assert '<option value="EUR" selected>' in form


def test_default_currency_applies_via_api(client, make_user):
    setup_admin(client, make_user)
    client.patch("/api/v1/settings/general", json={"default_currency": "KZT"})
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    deal = client.post("/api/v1/deals", json={"title": "Д", "client_id": cid, "amount": "10"}).json()
    assert deal["currency"] == "KZT"
    explicit = client.post("/api/v1/deals", json={"title": "Д2", "client_id": cid, "currency": "USD"}).json()
    assert explicit["currency"] == "USD"


def test_web_form_errors_keep_input(client, make_user):
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    bad = client.post("/settings/general", data={
        "app_name": "", "default_currency": "RUB", "client_pl": "", "client_sg": "Пациент", "client_acc": "пациента",
        "deal_pl": "Сделки", "deal_sg": "Сделка", "deal_acc": "сделку",
    })
    assert bad.status_code == 400 and "Заполните поле" in bad.text and "пациента" in bad.text


def test_preset_renames_terms_once(client, make_user, factory):
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    assert client.post("/settings/fields/preset/auto").status_code in (302, 303)
    with factory() as s:
        assert settings_service.get_all(s)["deal_pl"] == "Заказы"
    client.patch("/api/v1/settings/general", json={"deal_pl": "Работы", "deal_sg": "Работа", "deal_acc": "работу"})
    assert client.post("/settings/fields/preset/beauty").status_code in (302, 303)
    with factory() as s:
        assert settings_service.get_all(s)["deal_pl"] == "Работы"


def test_default_value_is_not_stored(factory):
    with factory() as s:
        settings_service.update(s, {"client_pl": "Пациенты"})
        settings_service.update(s, {"client_pl": "Клиенты"})
        from sqlalchemy import select

        from app.models import AppSetting

        assert s.scalar(select(AppSetting).where(~AppSetting.key.startswith("_"))) is None
