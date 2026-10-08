"""Этап 3: кастомные поля, статусы, клиенты, сделки (сервисы, API и веб-формы)."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.validators import parse_date, parse_money
from app.models import Client, CustomValue, Deal, Status, User
from app.services import (
    client_service, custom_field_service, deal_service, presets, status_service,
)
from app.services.errors import ValidationFailed
from app.services.slug import slugify
from tests.conftest import PASSWORD, api_login


# ------------------------------------------------------------------ вспомогательное
def admin_api(client, make_user, email="admin@example.com"):
    make_user(email, role="admin", full_name="Админ")
    api_login(client, email)


def web_login(client, email):
    resp = client.post("/login", data={"email": email, "password": PASSWORD, "next": "/"})
    assert resp.status_code in (302, 303), resp.text
    return resp


def make_field(client, **kw):
    payload = {"entity_type": "client", "label": "Поле", "field_type": "text"}
    payload.update(kw)
    resp = client.post("/api/v1/custom-fields", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ------------------------------------------------------------------ утилиты
def test_slugify_transliterates():
    assert slugify("Марка авто") == "marka_avto"
    assert slugify("Дата посещения") == "data_posescheniya"
    assert slugify("!!!", fallback="field") == "field"


def test_parse_money_rules():
    assert parse_money("1 234,5") == Decimal("1234.50")
    assert parse_money("0") == Decimal("0.00")
    with pytest.raises(ValueError):
        parse_money("-1")
    with pytest.raises(ValueError):
        parse_money("abc")


def test_parse_date_formats():
    assert parse_date("2025-03-09") == date(2025, 3, 9)
    assert parse_date("09.03.2025") == date(2025, 3, 9)
    with pytest.raises(ValueError):
        parse_date("32.13.2025")


# ------------------------------------------------------------------ API: кастомные поля
def test_field_crud_and_immutable_code(client, make_user):
    admin_api(client, make_user)
    f = make_field(client, label="Марка авто", show_in_list=True)
    assert f["code"] == "marka_avto"
    assert f["sort_order"] >= 0

    upd = client.patch(f"/api/v1/custom-fields/{f['id']}", json={"label": "Марка", "is_active": False})
    assert upd.status_code == 200
    assert upd.json()["label"] == "Марка"
    assert upd.json()["code"] == "marka_avto"
    assert upd.json()["is_active"] is False

    assert client.delete(f"/api/v1/custom-fields/{f['id']}").status_code == 204
    assert client.get(f"/api/v1/custom-fields/{f['id']}").status_code == 404


def test_field_duplicate_code_rejected(client, make_user):
    admin_api(client, make_user)
    make_field(client, label="VIN", code="vin")
    resp = client.post("/api/v1/custom-fields", json={"entity_type": "client", "label": "Другой", "field_type": "text", "code": "vin"})
    assert resp.status_code == 422
    # тот же код для другой сущности допустим
    make_field(client, label="VIN", code="vin", entity_type="deal")


def test_select_field_requires_options_and_bad_code_rejected(client, make_user):
    admin_api(client, make_user)
    bad = client.post("/api/v1/custom-fields", json={"entity_type": "client", "label": "Мастер", "field_type": "select"})
    assert bad.status_code == 422
    bad_code = client.post("/api/v1/custom-fields", json={"entity_type": "client", "label": "X", "field_type": "text", "code": "a__b"})
    assert bad_code.status_code == 422
    ok = make_field(client, label="Мастер", field_type="select", options=["Анна", "Ольга", "Анна"])
    assert ok["options"] == ["Анна", "Ольга"]


def test_field_reorder_and_move(client, make_user):
    admin_api(client, make_user)
    a = make_field(client, label="A")
    b = make_field(client, label="B")
    c = make_field(client, label="C")
    resp = client.post("/api/v1/custom-fields/reorder", json={"entity_type": "client", "ids": [c["id"], a["id"], b["id"]]})
    assert resp.status_code == 200, resp.text
    assert [f["id"] for f in resp.json()] == [c["id"], a["id"], b["id"]]
    listing = client.get("/api/v1/custom-fields", params={"entity_type": "client"}).json()
    assert [f["id"] for f in listing][:3] == [c["id"], a["id"], b["id"]]


def test_fields_manage_requires_permission(client, make_user):
    make_user("mgr@example.com", role="manager")
    api_login(client, "mgr@example.com")
    assert client.get("/api/v1/custom-fields").status_code == 200  # читать можно
    resp = client.post("/api/v1/custom-fields", json={"entity_type": "client", "label": "X", "field_type": "text"})
    assert resp.status_code == 403


# ------------------------------------------------------------------ API: статусы
def test_status_crud_and_rules(client, make_user, factory):
    admin_api(client, make_user)
    statuses = client.get("/api/v1/statuses").json()
    assert {s["code"] for s in statuses} >= {"new", "won", "lost"}

    created = client.post("/api/v1/statuses", json={"name": "Ждём оплату", "color": "#aabbcc", "kind": "open"})
    assert created.status_code == 201, created.text
    st = created.json()
    assert st["color"] == "#AABBCC"

    bad = client.post("/api/v1/statuses", json={"name": "Плохой", "color": "red"})
    assert bad.status_code == 422

    made_default = client.patch(f"/api/v1/statuses/{st['id']}", json={"is_default": True})
    assert made_default.status_code == 200
    assert sum(s["is_default"] for s in client.get("/api/v1/statuses").json()) == 1

    assert client.delete(f"/api/v1/statuses/{st['id']}").status_code == 204


def test_status_used_by_deal_cannot_be_deleted(client, make_user, factory):
    admin_api(client, make_user)
    cl = client.post("/api/v1/clients", json={"name": "Иван"}).json()
    new = client.post("/api/v1/statuses", json={"name": "Особый"}).json()
    deal = client.post("/api/v1/deals", json={"title": "Д", "client_id": cl["id"], "status_id": new["id"]})
    assert deal.status_code == 201, deal.text
    resp = client.delete(f"/api/v1/statuses/{new['id']}")
    assert resp.status_code == 422
    assert "используется" in str(resp.json())


def test_status_reorder(client, make_user):
    admin_api(client, make_user)
    ids = [s["id"] for s in client.get("/api/v1/statuses").json()]
    rev = list(reversed(ids))
    resp = client.post("/api/v1/statuses/reorder", json={"ids": rev})
    assert resp.status_code == 200, resp.text
    assert [s["id"] for s in resp.json()] == rev


# ------------------------------------------------------------------ API: клиенты
def test_client_with_custom_fields_and_search(client, make_user):
    admin_api(client, make_user)
    make_field(client, label="VIN", code="vin")
    make_field(client, label="Госномер", code="plate")
    make_field(client, label="Пробег", code="mileage", field_type="integer")
    created = client.post("/api/v1/clients", json={
        "name": "Иван Петров", "phone": "+7 (999) 123-45-67",
        "custom": {"vin": "XTA210930Y2765499", "plate": "А123ВС77", "mileage": 120000},
    })
    assert created.status_code == 201, created.text
    assert created.json()["custom"]["vin"] == "XTA210930Y2765499"
    assert created.json()["custom"]["mileage"] == 120000
    client.post("/api/v1/clients", json={"name": "Мария Сидорова", "custom": {"vin": "ZZZ"}})

    by_vin = client.get("/api/v1/clients", params={"q": "xta2109"}).json()
    assert by_vin["total"] == 1
    # регистронезависимый поиск по кириллице
    assert client.get("/api/v1/clients", params={"q": "петров"}).json()["total"] == 1
    assert client.get("/api/v1/clients", params={"q": "СИДОРОВА"}).json()["total"] == 1
    # по цифрам телефона
    assert client.get("/api/v1/clients", params={"q": "9991234567"}).json()["total"] == 1
    # по значению кастомного поля-госномера
    assert client.get("/api/v1/clients", params={"q": "а123вс"}).json()["total"] == 1
    # фильтры по кастомным полям
    assert client.get("/api/v1/clients", params={"cf_vin": "ZZZ"}).json()["total"] == 1
    assert client.get("/api/v1/clients", params={"cf_mileage__from": 100000}).json()["total"] == 1
    assert client.get("/api/v1/clients", params={"cf_mileage__to": 1000}).json()["total"] == 0


def test_client_patch_partial_custom_and_unknown_key(client, make_user):
    admin_api(client, make_user)
    make_field(client, label="VIN", code="vin")
    make_field(client, label="Госномер", code="plate")
    cl = client.post("/api/v1/clients", json={"name": "Иван", "custom": {"vin": "A", "plate": "B"}}).json()

    upd = client.patch(f"/api/v1/clients/{cl['id']}", json={"custom": {"vin": "NEW"}})
    assert upd.status_code == 200, upd.text
    assert upd.json()["custom"]["vin"] == "NEW"
    assert upd.json()["custom"]["plate"] == "B"  # нетронутое сохранилось

    cleared = client.patch(f"/api/v1/clients/{cl['id']}", json={"custom": {"plate": None}})
    assert cleared.status_code == 200
    assert cleared.json()["custom"].get("plate") in (None, "")

    unknown = client.patch(f"/api/v1/clients/{cl['id']}", json={"custom": {"nope": 1}})
    assert unknown.status_code == 422
    assert "custom.nope" in str(unknown.json())


def test_client_required_custom_field_and_type_errors(client, make_user):
    admin_api(client, make_user)
    make_field(client, label="Год", code="year", field_type="integer", is_required=True)
    missing = client.post("/api/v1/clients", json={"name": "Иван"})
    assert missing.status_code == 422
    assert "custom.year" in str(missing.json())
    bad = client.post("/api/v1/clients", json={"name": "Иван", "custom": {"year": "abc"}})
    assert bad.status_code == 422


def test_client_pagination(client, make_user):
    admin_api(client, make_user)
    for i in range(25):
        assert client.post("/api/v1/clients", json={"name": f"Клиент {i:02d}"}).status_code == 201
    first = client.get("/api/v1/clients", params={"per_page": 10, "sort": "name"}).json()
    assert first["total"] == 25 and first["pages"] == 3 and len(first["items"]) == 10
    last = client.get("/api/v1/clients", params={"per_page": 10, "page": 3, "sort": "name"}).json()
    assert len(last["items"]) == 5
    assert first["items"][0]["name"] == "Клиент 00"


def test_inactive_field_hidden_from_values(client, make_user):
    admin_api(client, make_user)
    f = make_field(client, label="VIN", code="vin")
    cl = client.post("/api/v1/clients", json={"name": "Иван", "custom": {"vin": "A"}}).json()
    client.patch(f"/api/v1/custom-fields/{f['id']}", json={"is_active": False})
    assert "vin" not in client.get(f"/api/v1/clients/{cl['id']}").json()["custom"]
    client.patch(f"/api/v1/custom-fields/{f['id']}", json={"is_active": True})
    assert client.get(f"/api/v1/clients/{cl['id']}").json()["custom"]["vin"] == "A"  # данные не потеряны


def test_delete_client_removes_deals_and_values(client, make_user, factory):
    admin_api(client, make_user)
    make_field(client, label="VIN", code="vin")
    cl = client.post("/api/v1/clients", json={"name": "Иван", "custom": {"vin": "A"}}).json()
    client.post("/api/v1/deals", json={"title": "Д", "client_id": cl["id"]})
    assert client.delete(f"/api/v1/clients/{cl['id']}").status_code == 204
    with factory() as s:
        assert s.scalar(select(Deal.id)) is None
        assert s.scalar(select(CustomValue.id)) is None


def test_employee_cannot_delete_client(client, make_user):
    make_user("emp@example.com", role="employee")
    api_login(client, "emp@example.com")
    cl = client.post("/api/v1/clients", json={"name": "Иван"})
    assert cl.status_code == 201
    assert client.delete(f"/api/v1/clients/{cl.json()['id']}").status_code == 403


# ------------------------------------------------------------------ API: сделки
def test_deal_defaults_and_status_closed_at(client, make_user):
    admin_api(client, make_user)
    cl = client.post("/api/v1/clients", json={"name": "Иван"}).json()
    deal = client.post("/api/v1/deals", json={"title": "Замена масла", "client_id": cl["id"], "amount": "1500.5"})
    assert deal.status_code == 201, deal.text
    d = deal.json()
    assert d["status"]["is_default"] is True
    assert d["closed_at"] is None
    assert Decimal(d["amount"]) == Decimal("1500.50")
    assert d["deal_date"]  # сегодняшняя дата в часовом поясе приложения
    assert d["responsible"] is not None

    statuses = {s["code"]: s for s in client.get("/api/v1/statuses").json()}
    won = client.post(f"/api/v1/deals/{d['id']}/status", json={"status_id": statuses["won"]["id"]})
    assert won.status_code == 200, won.text
    closed_at = won.json()["closed_at"]
    assert closed_at is not None

    again = client.post(f"/api/v1/deals/{d['id']}/status", json={"status_id": statuses["lost"]["id"]})
    assert again.json()["closed_at"] == closed_at  # момент закрытия не перезаписывается

    reopened = client.post(f"/api/v1/deals/{d['id']}/status", json={"status_id": statuses["in_progress"]["id"]})
    assert reopened.json()["closed_at"] is None


def test_deal_validation(client, make_user):
    admin_api(client, make_user)
    cl = client.post("/api/v1/clients", json={"name": "Иван"}).json()
    neg = client.post("/api/v1/deals", json={"title": "Д", "client_id": cl["id"], "amount": "-5"})
    assert neg.status_code == 422
    nocl = client.post("/api/v1/deals", json={"title": "Д", "client_id": 9999})
    assert nocl.status_code == 422
    nostatus = client.post("/api/v1/deals", json={"title": "Д", "client_id": cl["id"], "status_id": 9999})
    assert nostatus.status_code == 422


def test_deal_custom_fields_filters_and_totals(client, make_user):
    admin_api(client, make_user)
    make_field(client, entity_type="deal", label="Мастер", code="master", field_type="select", options=["Анна", "Ольга"])
    make_field(client, entity_type="deal", label="Дата посещения", code="visit", field_type="date")
    cl = client.post("/api/v1/clients", json={"name": "Иван"}).json()
    client.post("/api/v1/deals", json={"title": "Стрижка", "client_id": cl["id"], "amount": "1000",
                                       "custom": {"master": "Анна", "visit": "2025-05-01"}})
    client.post("/api/v1/deals", json={"title": "Окрашивание", "client_id": cl["id"], "amount": "2500.25",
                                       "custom": {"master": "Ольга", "visit": "2025-06-10"}})
    bad = client.post("/api/v1/deals", json={"title": "X", "client_id": cl["id"], "custom": {"master": "Никто"}})
    assert bad.status_code == 422

    listing = client.get("/api/v1/deals").json()
    assert listing["total"] == 2
    assert Decimal(listing["totals"][0]["amount"]) == Decimal("3500.25")
    assert client.get("/api/v1/deals", params={"cf_master": "Анна"}).json()["total"] == 1
    assert client.get("/api/v1/deals", params={"cf_visit__from": "2025-06-01"}).json()["total"] == 1
    assert client.get("/api/v1/deals", params={"q": "стриж"}).json()["total"] == 1
    assert client.get("/api/v1/deals", params={"amount_min": "2000"}).json()["total"] == 1
    assert client.get("/api/v1/deals", params={"client_id": cl["id"], "sort": "-amount"}).json()["items"][0]["title"] == "Окрашивание"


def test_deal_kind_filter(client, make_user):
    admin_api(client, make_user)
    cl = client.post("/api/v1/clients", json={"name": "Иван"}).json()
    won = {s["code"]: s for s in client.get("/api/v1/statuses").json()}["won"]
    client.post("/api/v1/deals", json={"title": "A", "client_id": cl["id"]})
    client.post("/api/v1/deals", json={"title": "B", "client_id": cl["id"], "status_id": won["id"]})
    assert client.get("/api/v1/deals", params={"kind": "won"}).json()["total"] == 1
    assert client.get("/api/v1/deals", params={"kind": "open"}).json()["total"] == 1


# ------------------------------------------------------------------ пресеты и сервисы
def test_presets_apply_is_idempotent(factory):
    with factory() as s:
        new_fields, new_statuses = presets.apply_preset(s, "auto")
        assert new_fields > 0
        assert presets.apply_preset(s, "auto") == (0, 0)
        labels = {f.label for f in custom_field_service.list_fields(s)}
        assert "VIN" in labels


def test_status_service_keeps_one_default_and_one_active(factory):
    with factory() as s:
        a = status_service.create_status(s, name="Свой", is_default=True)
        assert sum(x.is_default for x in status_service.list_statuses(s)) == 1
        assert status_service.get_default_status(s).id == a.id
        for st in status_service.list_statuses(s):
            if st.id != a.id:
                status_service.update_status(s, st, is_active=False)
        with pytest.raises(ValidationFailed):
            status_service.update_status(s, a, is_active=False)


def test_coerce_errors_use_cf_prefix(factory, make_user):
    make_user("admin@example.com", role="admin")
    with factory() as s:
        custom_field_service.create_field(s, entity_type="client", label="Год", field_type="integer", code="year")
        actor = s.scalar(select(User))
        with pytest.raises(ValidationFailed) as exc:
            client_service.create_client(s, data={"name": "Иван"}, custom={"year": "abc"}, actor=actor)
        assert "cf_year" in exc.value.errors


# ------------------------------------------------------------------ веб-интерфейс
def test_pages_require_login(client):
    for url in ("/clients", "/deals", "/settings/fields", "/settings/statuses"):
        resp = client.get(url)
        assert resp.status_code in (302, 303, 401), url
        if resp.status_code in (302, 303):
            assert "/login" in resp.headers["location"]


def test_web_pages_render_for_admin(client, make_user):
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    for url in ("/clients", "/clients/new", "/deals", "/deals/new", "/settings/fields",
                "/settings/fields?entity=deal", "/settings/fields/new", "/settings/statuses", "/settings/statuses/new"):
        resp = client.get(url)
        assert resp.status_code == 200, (url, resp.text[:300])


def test_web_field_and_client_flow(client, make_user, factory):
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")

    resp = client.post("/settings/fields/new", data={
        "entity": "client", "label": "Госномер", "code": "", "field_type": "text",
        "is_filterable": "on", "show_in_list": "on", "is_active": "on",
    })
    assert resp.status_code in (302, 303), resp.text[:500]

    form = client.get("/clients/new")
    assert 'name="cf_gosnomer"' in form.text

    created = client.post("/clients/new", data={"type": "person", "name": "Пётр", "phone": "+7 900 000-00-00", "cf_gosnomer": "А777АА77"})
    assert created.status_code in (302, 303), created.text[:500]
    detail_url = created.headers["location"]
    assert "А777АА77" in client.get(detail_url).text

    listing = client.get("/clients", params={"q": "а777аа"})
    assert "Пётр" in listing.text

    edited = client.post(f"{detail_url}/edit", data={"type": "person", "name": "Пётр Иванов", "cf_gosnomer": "В111ВВ77"})
    assert edited.status_code in (302, 303)
    assert "Пётр Иванов" in client.get(detail_url).text

    deleted = client.post(f"{detail_url}/delete")
    assert deleted.status_code in (302, 303)
    with factory() as s:
        assert s.scalar(select(Client.id)) is None


def test_web_client_form_error_keeps_input(client, make_user):
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    resp = client.post("/clients/new", data={"type": "person", "name": "", "email": "не-почта"})
    assert resp.status_code == 400
    assert "не-почта" in resp.text


def test_web_deal_flow(client, make_user, factory):
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    with factory() as s:
        cl = client_service.create_client(
            s, data={"name": "Анна"}, custom={},
            actor=s.scalar(select(User)),
        )
        s.commit()
        client_id = cl.id
        status_id = status_service.get_default_status(s).id
        won_id = s.scalar(select(Status.id).where(Status.code == "won"))

    form = client.get(f"/deals/new?client_id={client_id}")
    assert form.status_code == 200
    assert "Анна" in form.text and "RUB" in form.text  # клиент подставлен, валюты есть

    created = client.post("/deals/new", data={
        "title": "Консультация", "client_id": str(client_id), "amount": "2 500,50",
        "currency": "RUB", "deal_date": "2025-04-01", "status_id": str(status_id),
    })
    assert created.status_code in (302, 303), created.text[:500]
    url = created.headers["location"]
    assert "Консультация" in client.get(url).text

    changed = client.post(f"{url}/status", data={"status_id": str(won_id)})
    assert changed.status_code in (302, 303)
    with factory() as s:
        deal = s.scalar(select(Deal))
        assert deal.status_id == won_id and deal.closed_at is not None
        assert deal.amount == Decimal("2500.50")

    bad = client.post(f"{url}/edit", data={
        "title": "", "client_id": str(client_id), "amount": "abc", "currency": "RUB",
        "deal_date": "2025-04-01", "status_id": str(status_id),
    })
    assert bad.status_code == 400

    deleted = client.post(f"{url}/delete")
    assert deleted.status_code in (302, 303)
    assert deleted.headers["location"].startswith("/clients/")
    with factory() as s:
        assert s.scalar(select(Deal.id)) is None


def test_client_search_endpoint(client, make_user):
    admin_api(client, make_user)
    client.post("/api/v1/clients", json={"name": "Иван Петров"})
    client.post("/api/v1/clients", json={"name": "Мария"})
    resp = client.get("/clients/search", params={"q": "иван"})
    assert resp.status_code == 200
    assert [c["name"] for c in resp.json()] == ["Иван Петров"]


def test_settings_pages_forbidden_for_manager(client, make_user):
    make_user("mgr@example.com", role="manager")
    web_login(client, "mgr@example.com")
    assert client.get("/settings/fields").status_code == 403
    assert client.get("/settings/statuses").status_code == 403
    assert client.get("/clients").status_code == 200


def test_employee_has_no_delete_button(client, make_user):
    make_user("emp@example.com", role="employee")
    web_login(client, "emp@example.com")
    created = client.post("/clients/new", data={"type": "person", "name": "Пётр"})
    assert created.status_code in (302, 303)
    detail = client.get(created.headers["location"])
    assert "/delete" not in detail.text
    assert client.post(created.headers["location"] + "/delete").status_code == 403
