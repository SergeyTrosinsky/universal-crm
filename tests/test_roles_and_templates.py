"""Права сотрудника/менеджера (свои сделки, статистика, назначение) и шаблоны сделок."""
from decimal import Decimal

from sqlalchemy import select

from app.db.init_db import upgrade_system_roles
from app.models import AppSetting, CustomField, Deal, DealTemplate, Role, User
from app.services import custom_field_service, deal_service, deal_template_service, presets, status_service
from tests.conftest import PASSWORD, api_login


def web_login(client, email):
    client.cookies.clear()
    resp = client.post("/login", data={"email": email, "password": PASSWORD})
    assert resp.status_code in (302, 303), resp.text[:300]


def mk_client(client, name="Анна") -> int:
    resp = client.post("/api/v1/clients", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def mk_deal(client, client_id, title, **extra):
    resp = client.post("/api/v1/deals", json={"title": title, "client_id": client_id, **extra})
    return resp


def test_employee_sees_and_edits_only_own_deals(client, make_user):
    make_user("emp1@example.com", role="employee", full_name="Аня")
    emp2 = make_user("emp2@example.com", role="employee", full_name="Борис")
    make_user("mgr@example.com", role="manager", full_name="Мила")

    api_login(client, "emp1@example.com")
    cid = mk_client(client)
    own = mk_deal(client, cid, "Сделка Ани")
    assert own.status_code == 201 and own.json()["responsible"]["full_name"] == "Аня"
    denied = mk_deal(client, cid, "Чужая", responsible_id=emp2)
    assert denied.status_code == 422 and "responsible_id" in denied.json()["detail"]

    client.cookies.clear()
    api_login(client, "mgr@example.com")
    assigned = mk_deal(client, cid, "Сделка Бориса", responsible_id=emp2)
    assert assigned.status_code == 201 and assigned.json()["responsible"]["full_name"] == "Борис"
    assert {d["title"] for d in client.get("/api/v1/deals").json()["items"]} == {"Сделка Ани", "Сделка Бориса"}

    client.cookies.clear()
    api_login(client, "emp2@example.com")
    assert {d["title"] for d in client.get("/api/v1/deals").json()["items"]} == {"Сделка Бориса"}
    other_id = own.json()["id"]
    assert client.get(f"/api/v1/deals/{other_id}").status_code == 404
    assert client.patch(f"/api/v1/deals/{other_id}", json={"title": "x"}).status_code == 404
    assert client.post(f"/api/v1/deals/{other_id}/status", json={"status_id": 1}).status_code == 404
    mine_id = assigned.json()["id"]
    assert client.patch(f"/api/v1/deals/{mine_id}", json={"title": "Обновлено"}).status_code == 200
    manager = client.patch(f"/api/v1/deals/{mine_id}", json={"responsible_id": 999})
    assert manager.status_code == 422


def test_employee_web_pages_hide_other_people_deals(client, make_user, factory):
    make_user("emp1@example.com", role="employee", full_name="Аня")
    make_user("emp2@example.com", role="employee", full_name="Борис")
    make_user("mgr@example.com", role="manager", full_name="Мила")

    api_login(client, "mgr@example.com")
    cid = mk_client(client)
    with factory() as s:
        boris = s.scalar(select(User).where(User.email == "emp2@example.com"))
        anna = s.scalar(select(User).where(User.email == "emp1@example.com"))
        boris_id, anna_id = boris.id, anna.id
    mk_deal(client, cid, "Для Ани", responsible_id=anna_id)
    secret = mk_deal(client, cid, "Для Бориса", responsible_id=boris_id).json()

    web_login(client, "emp1@example.com")
    listing = client.get("/deals")
    assert "Для Ани" in listing.text and "Для Бориса" not in listing.text
    assert 'name="responsible"' not in listing.text
    assert client.get(f"/deals/{secret['id']}").status_code == 404
    assert client.get(f"/deals/{secret['id']}/edit").status_code == 404
    board = client.get("/deals/board")
    assert "Для Ани" in board.text and "Для Бориса" not in board.text
    assert "Для Бориса" not in client.get(f"/clients/{cid}").text
    assert client.get("/deals/search", params={"q": "борис"}).json() == []
    form = client.get("/deals/new")
    assert 'name="responsible_id"' not in form.text

    web_login(client, "mgr@example.com")
    assert 'name="responsible_id"' in client.get("/deals/new").text
    assert "Для Бориса" in client.get("/deals").text


def test_dashboard_is_personal_for_employee(client, make_user, factory):
    make_user("emp1@example.com", role="employee", full_name="Аня")
    boris = make_user("emp2@example.com", role="employee", full_name="Борис")
    make_user("mgr@example.com", role="manager", full_name="Мила")

    api_login(client, "mgr@example.com")
    cid = mk_client(client)
    with factory() as s:
        anna = s.scalar(select(User).where(User.email == "emp1@example.com")).id
        won = status_service.list_statuses(s)
        won_id = next(x.id for x in won if x.code == "won")
    for title, who in (("A1", anna), ("A2", anna), ("B1", boris)):
        deal = mk_deal(client, cid, title, responsible_id=who, amount="100").json()
        client.post(f"/api/v1/deals/{deal['id']}/status", json={"status_id": won_id})

    team = client.get("/api/v1/dashboard", params={"period": "all"}).json()
    assert team["personal"] is False
    assert team["deals"]["won_count"] == 3 and team["deals"]["by_responsible"]

    client.cookies.clear()
    api_login(client, "emp1@example.com")
    mine = client.get("/api/v1/dashboard", params={"period": "all"}).json()
    assert mine["personal"] is True
    assert mine["deals"]["won_count"] == 2
    assert Decimal(mine["deals"]["won_amounts"][0]["amount"]) == Decimal("200")
    assert mine["deals"]["by_responsible"] == []
    assert sum(m["won"] for m in mine["deals"]["monthly"]) == 2


def test_employee_cannot_assign_tasks_manager_can(client, make_user):
    make_user("emp@example.com", role="employee", full_name="Аня")
    b = make_user("emp2@example.com", role="employee", full_name="Борис")
    make_user("mgr@example.com", role="manager")

    api_login(client, "emp@example.com")
    ok = client.post("/api/v1/tasks", json={"title": "Себе"})
    assert ok.status_code == 201 and ok.json()["assignee"]["full_name"] == "Аня"
    assert client.post("/api/v1/tasks", json={"title": "Другому", "assignee_id": b}).status_code == 422

    web_login(client, "emp@example.com")
    page = client.get("/tasks/new")
    assert 'name="assignee_id"' not in page.text
    created = client.post("/tasks/new", data={"title": "Из формы", "priority": "normal", "status": "todo"})
    assert created.status_code in (302, 303)

    web_login(client, "mgr@example.com")
    assert 'name="assignee_id"' in client.get("/tasks/new").text
    api_login(client, "mgr@example.com")
    assert client.post("/api/v1/tasks", json={"title": "Поручено", "assignee_id": b}).status_code == 201


def test_manager_role_gets_new_permissions_once(factory):
    with factory() as s:
        manager = s.scalar(select(Role).where(Role.code == "manager"))
        manager.permissions = [p for p in manager.permissions if p not in ("deals:read_all", "deals:assign", "tasks:assign")]
        s.delete(s.get(AppSetting, "_roles_rev"))
        s.commit()
        upgrade_system_roles(s)
        s.refresh(manager)
        assert {"deals:read_all", "deals:assign", "tasks:assign"} <= set(manager.permissions)
        manager.permissions = [p for p in manager.permissions if p != "deals:assign"]
        s.commit()
        upgrade_system_roles(s)
        s.refresh(manager)
        assert "deals:assign" not in manager.permissions


def make_templates(factory):
    with factory() as s:
        auto = deal_template_service.create_template(s, name="Автосервис")
        beauty = deal_template_service.create_template(s, name="Салон")
        custom_field_service.create_field(s, entity_type="deal", label="Общее", field_type="text", code="common")
        custom_field_service.create_field(s, entity_type="deal", label="VIN", field_type="text", code="vin", template_id=auto.id)
        custom_field_service.create_field(
            s, entity_type="deal", label="Мастер", field_type="select", options=["Анна"], code="master",
            template_id=beauty.id, is_required=True,
        )
        return auto.id, beauty.id


def test_template_limits_fields_of_deal(client, make_user, factory):
    auto_id, beauty_id = make_templates(factory)
    make_user("admin@example.com", role="admin")
    api_login(client, "admin@example.com")
    cid = mk_client(client)

    ok = mk_deal(client, cid, "Ремонт", template_id=auto_id, custom={"vin": "XTA123", "common": "да"})
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["template"]["name"] == "Автосервис"
    assert body["custom"] == {"common": "да", "vin": "XTA123"}

    bad = mk_deal(client, cid, "Стрижка", template_id=auto_id, custom={"master": "Анна"})
    assert bad.status_code == 422 and "custom.master" in bad.json()["detail"]
    plain = mk_deal(client, cid, "Без шаблона")
    assert plain.status_code == 201 and plain.json()["template"] is None
    need = mk_deal(client, cid, "Салон без мастера", template_id=beauty_id)
    assert need.status_code == 422 and "custom.master" in need.json()["detail"]
    assert mk_deal(client, cid, "Салон", template_id=beauty_id, custom={"master": "Анна"}).status_code == 201
    assert mk_deal(client, cid, "Нет такого", template_id=999).status_code == 422

    changed = client.patch(f"/api/v1/deals/{body['id']}", json={"template_id": beauty_id, "custom": {"master": "Анна"}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["custom"] == {"common": "да", "master": "Анна"}
    back = client.patch(f"/api/v1/deals/{body['id']}", json={"template_id": auto_id})
    assert back.json()["custom"]["vin"] == "XTA123"

    only_auto = client.get("/api/v1/deals", params={"template": str(auto_id)}).json()
    assert [d["title"] for d in only_auto["items"]] == ["Ремонт"]
    standard = client.get("/api/v1/deals", params={"template": "none"}).json()
    assert [d["title"] for d in standard["items"]] == ["Без шаблона"]


def test_web_deal_form_with_template(client, make_user, factory):
    auto_id, _ = make_templates(factory)
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    cid = int(client.post("/clients/new", data={"type": "person", "name": "Пётр"}).headers["location"].split("/")[-1])

    form = client.get("/deals/new")
    assert "Стандартная форма" in form.text and 'name="template_id"' in form.text
    assert 'data-field-template="%d"' % auto_id in form.text

    created = client.post("/deals/new", data={
        "title": "Ремонт", "client_id": str(cid), "amount": "100", "currency": "RUB", "deal_date": "2025-01-01",
        "template_id": str(auto_id), "cf_vin": "XTA777", "cf_common": "ок",
    })
    assert created.status_code in (302, 303), created.text[:500]
    detail = client.get(created.headers["location"])
    assert "XTA777" in detail.text and "Автосервис" in detail.text
    assert "Мастер" not in detail.text

    plain = client.post("/deals/new", data={
        "title": "Простая", "client_id": str(cid), "amount": "1", "currency": "RUB", "deal_date": "2025-01-01",
        "template_id": "", "cf_vin": "НЕ СОХРАНЯТЬ",
    })
    assert plain.status_code in (302, 303)
    assert "НЕ СОХРАНЯТЬ" not in client.get(plain.headers["location"]).text


def test_template_settings_and_delete_rules(client, make_user, factory):
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    created = client.post("/settings/templates/new", data={"name": "Диагностика", "is_active": "1"})
    assert created.status_code in (302, 303)
    assert "/settings/fields/new?entity=deal&template=" in created.headers["location"]
    page = client.get("/settings/templates")
    assert page.status_code == 200 and "Диагностика" in page.text
    dup = client.post("/settings/templates/new", data={"name": "диагностика"})
    assert dup.status_code == 400 and "уже есть" in dup.text

    with factory() as s:
        tid = s.scalar(select(DealTemplate.id))
    resp = client.post("/settings/fields/new", data={
        "entity_type": "deal", "label": "Пробег", "field_type": "integer", "template_id": str(tid), "is_filterable": "1",
        "is_active": "1",
    })
    assert resp.status_code in (302, 303), resp.text[:400]
    with factory() as s:
        assert s.scalar(select(CustomField.template_id).where(CustomField.label == "Пробег")) == tid
    client.post(f"/settings/templates/{tid}/delete")
    with factory() as s:
        assert s.get(DealTemplate, tid) is not None
    client.post(f"/settings/templates/{tid}/toggle")
    with factory() as s:
        assert s.get(DealTemplate, tid).is_active is False
    assert ">Диагностика</option>" not in client.get("/deals/new").text


def test_preset_creates_template_and_moves_old_fields(factory):
    with factory() as s:
        custom_field_service.create_field(s, entity_type="deal", label="VIN", field_type="text")
        presets.apply_preset(s, "auto")
        template = deal_template_service.find_by_name(s, "Автосервис")
        assert template is not None
        in_template = {f.label for f in custom_field_service.list_fields(s) if f.template_id == template.id}
        assert in_template == {"Марка авто", "VIN", "Госномер"}
        assert presets.apply_preset(s, "auto") == (0, 0)


def test_deal_template_service_rules(factory):
    with factory() as s:
        t = deal_template_service.create_template(s, name="  Мой   шаблон ")
        assert t.name == "Мой шаблон"
        from app.services.errors import ValidationFailed
        import pytest

        with pytest.raises(ValidationFailed):
            deal_template_service.create_template(s, name="мой шаблон")
        with pytest.raises(ValidationFailed):
            deal_template_service.create_template(s, name="")
        deal_template_service.delete_template(s, t)
        assert s.get(DealTemplate, t.id) is None
        with pytest.raises(ValidationFailed):
            custom_field_service.create_field(s, entity_type="client", label="X", field_type="text", template_id=1)


def test_responsible_selects_show_role(client, make_user):
    make_user("admin@example.com", role="admin", full_name="Глава")
    make_user("emp@example.com", role="employee", full_name="Денис Коровин")
    web_login(client, "admin@example.com")
    for url in ("/deals/new", "/tasks/new", "/deals", "/clients"):
        text = client.get(url).text
        assert "Денис Коровин (" in text, url


def test_deals_list_grouped_by_template(client, make_user, factory):
    auto_id, beauty_id = make_templates(factory)
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    cid = int(client.post("/clients/new", data={"type": "person", "name": "Пётр"}).headers["location"].split("/")[-1])
    base = {"client_id": str(cid), "amount": "1", "currency": "RUB", "deal_date": "2025-01-01"}
    client.post("/deals/new", data={**base, "title": "Д-салон", "template_id": str(beauty_id), "cf_master": "Анна"})
    client.post("/deals/new", data={**base, "title": "Д-авто", "template_id": str(auto_id), "cf_vin": "XTA1"})
    client.post("/deals/new", data={**base, "title": "Д-простая", "template_id": ""})

    page = client.get("/deals").text
    tbl = page[page.index("<table"):]
    for title in ("Д-салон", "Д-авто", "Д-простая"):
        assert title in tbl
    assert tbl.index("Стандартная") < tbl.index("Д-простая") < tbl.index("Автосервис") < tbl.index("Д-авто")
    assert tbl.index("Д-авто") < tbl.index("Салон") < tbl.index("Д-салон")
    assert "XTA1" not in tbl
