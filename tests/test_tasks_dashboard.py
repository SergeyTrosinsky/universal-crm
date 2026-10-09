"""Этап 4: задачи сотрудников и главная страница со статистикой."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Role, Task, TaskStatus
from app.services import dashboard_service
from tests.conftest import PASSWORD, api_login


def login_as(client, make_user, email, role="admin", full_name="Тест"):
    uid = make_user(email, role=role, full_name=full_name)
    client.cookies.clear()
    api_login(client, email)
    return uid


def web_login(client, email):
    client.cookies.clear()
    resp = client.post("/login", data={"email": email, "password": PASSWORD, "next": "/"})
    assert resp.status_code in (302, 303), resp.text


def make_role(factory, code, permissions):
    with factory() as s:
        s.add(Role(code=code, name=code, permissions=permissions, is_system=False))
        s.commit()


def new_client(client, name="Иван"):
    resp = client.post("/api/v1/clients", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def new_task(client, **kw):
    payload = {"title": "Позвонить"}
    payload.update(kw)
    resp = client.post("/api/v1/tasks", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def past():
    return (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()


def future():
    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


def test_task_defaults(client, make_user):
    uid = login_as(client, make_user, "admin@example.com")
    t = new_task(client)
    assert t["status"] == "todo" and t["priority"] == "normal"
    assert t["assignee"]["id"] == uid and t["creator_id"] == uid
    assert t["is_overdue"] is False and t["completed_at"] is None


def test_task_deal_sets_client_and_mismatch_rejected(client, make_user):
    login_as(client, make_user, "admin@example.com")
    c1, c2 = new_client(client, "Первый"), new_client(client, "Второй")
    deal = client.post("/api/v1/deals", json={"title": "Д", "client_id": c1["id"]}).json()
    t = new_task(client, deal_id=deal["id"])
    assert t["client"]["id"] == c1["id"] and t["deal"]["id"] == deal["id"]
    bad = client.post("/api/v1/tasks", json={"title": "X", "deal_id": deal["id"], "client_id": c2["id"]})
    assert bad.status_code == 422
    assert client.post("/api/v1/tasks", json={"title": "X", "client_id": 9999}).status_code == 422
    assert client.post("/api/v1/tasks", json={"title": "X", "assignee_id": 9999}).status_code == 422
    assert client.post("/api/v1/tasks", json={"title": ""}).status_code == 422
    assert client.post("/api/v1/tasks", json={"title": "X", "priority": "meh"}).status_code == 422


def test_task_status_and_completed_at_and_overdue(client, make_user):
    login_as(client, make_user, "admin@example.com")
    t = new_task(client, due_at=past())
    assert t["is_overdue"] is True

    done = client.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "done"}).json()
    assert done["completed_at"] is not None and done["is_overdue"] is False
    reopened = client.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "in_progress"}).json()
    assert reopened["completed_at"] is None and reopened["is_overdue"] is True
    cancelled = client.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "cancelled"}).json()
    assert cancelled["completed_at"] is None and cancelled["is_overdue"] is False
    assert client.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "bad"}).status_code == 422


def test_task_patch_and_delete(client, make_user):
    login_as(client, make_user, "admin@example.com")
    t = new_task(client, due_at=future())
    upd = client.patch(f"/api/v1/tasks/{t['id']}", json={"title": "Новое", "priority": "urgent", "due_at": None})
    assert upd.status_code == 200, upd.text
    assert upd.json()["title"] == "Новое" and upd.json()["priority"] == "urgent" and upd.json()["due_at"] is None
    assert client.patch(f"/api/v1/tasks/{t['id']}", json={"title": ""}).status_code == 422
    assert client.delete(f"/api/v1/tasks/{t['id']}").status_code == 204
    assert client.get(f"/api/v1/tasks/{t['id']}").status_code == 404


def test_task_date_only_means_end_of_day():
    from app.services.task_service import parse_due

    due = parse_due("2025-03-09")
    assert due is not None and due.tzinfo is not None
    assert parse_due("") is None
    with pytest.raises(ValueError):
        parse_due("вчера")


def test_task_lists_views_filters_and_sort(client, make_user):
    login_as(client, make_user, "admin@example.com")
    c = new_client(client, "Мария Сидорова")
    new_task(client, title="Просрочена", due_at=past(), priority="low")
    new_task(client, title="Будущая", due_at=future(), priority="urgent", client_id=c["id"])
    done = new_task(client, title="Готовая")
    client.post(f"/api/v1/tasks/{done['id']}/status", json={"status": "done"})

    def titles(**params):
        data = client.get("/api/v1/tasks", params=params).json()
        return [t["title"] for t in data["items"]]

    assert set(titles()) == {"Просрочена", "Будущая"}
    assert titles(view="overdue") == ["Просрочена"]
    assert titles(view="done") == ["Готовая"]
    assert len(titles(view="all")) == 3
    assert titles(status="done") == ["Готовая"]
    assert titles(q="сидорова") == ["Будущая"]
    assert titles(priority="urgent") == ["Будущая"]
    assert titles(view="all", sort="priority")[0] == "Будущая"
    assert titles(client_id=c["id"]) == ["Будущая"]
    assert titles(due_from=datetime.now().date().isoformat(), view="all") == ["Будущая"]


def test_task_pagination(client, make_user):
    login_as(client, make_user, "admin@example.com")
    for i in range(23):
        new_task(client, title=f"Задача {i:02d}")
    data = client.get("/api/v1/tasks", params={"per_page": 10, "page": 3, "sort": "title"}).json()
    assert data["total"] == 23 and data["pages"] == 3 and len(data["items"]) == 3


def test_task_visibility_between_employees(client, make_user):
    a = make_user("a@example.com", role="employee", full_name="Аня")
    b = make_user("b@example.com", role="employee", full_name="Борис")
    make_user("m@example.com", role="manager", full_name="Мила")

    api_login(client, "a@example.com")
    mine = new_task(client, title="Задача Ани")
    denied = client.post("/api/v1/tasks", json={"title": "Чужому", "assignee_id": b})
    assert denied.status_code == 422 and "assignee_id" in denied.json()["detail"]

    client.cookies.clear()
    api_login(client, "m@example.com")
    for_b = new_task(client, title="Для Бориса", assignee_id=b)

    client.cookies.clear()
    api_login(client, "b@example.com")
    assert client.get(f"/api/v1/tasks/{mine['id']}").status_code == 404
    assert client.patch(f"/api/v1/tasks/{mine['id']}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/v1/tasks/{mine['id']}").status_code == 404
    assert client.get(f"/api/v1/tasks/{for_b['id']}").status_code == 200
    seen = {t["title"] for t in client.get("/api/v1/tasks", params={"assignee": "all", "view": "all"}).json()["items"]}
    assert seen == {"Для Бориса"}

    client.cookies.clear()
    api_login(client, "a@example.com")
    seen_a = {t["title"] for t in client.get("/api/v1/tasks", params={"assignee": "all"}).json()["items"]}
    assert seen_a == {"Задача Ани"}

    client.cookies.clear()
    api_login(client, "m@example.com")
    all_titles = {t["title"] for t in client.get("/api/v1/tasks", params={"assignee": "all"}).json()["items"]}
    assert all_titles == {"Задача Ани", "Для Бориса"}
    by_user = client.get("/api/v1/tasks", params={"assignee": str(b)}).json()["items"]
    assert [t["title"] for t in by_user] == ["Для Бориса"]


def test_tasks_require_permissions(client, make_user, factory):
    make_role(factory, "viewer", ["tasks:read"])
    make_user("v@example.com", role="viewer")
    api_login(client, "v@example.com")
    assert client.get("/api/v1/tasks").status_code == 200
    assert client.post("/api/v1/tasks", json={"title": "X"}).status_code == 403
    make_role(factory, "nobody", ["clients:read"])
    make_user("n@example.com", role="nobody")
    client.cookies.clear()
    api_login(client, "n@example.com")
    assert client.get("/api/v1/tasks").status_code == 403


def test_dashboard_numbers(client, make_user):
    login_as(client, make_user, "admin@example.com")
    c = new_client(client)
    statuses = {s["code"]: s for s in client.get("/api/v1/statuses").json()}
    client.post("/api/v1/deals", json={"title": "Открытая", "client_id": c["id"], "amount": "1000"})
    won = client.post("/api/v1/deals", json={"title": "Выиграна", "client_id": c["id"], "amount": "2500.50",
                                             "status_id": statuses["won"]["id"]})
    assert won.status_code == 201
    client.post("/api/v1/deals", json={"title": "Проиграна", "client_id": c["id"], "amount": "300",
                                       "status_id": statuses["lost"]["id"]})
    client.post("/api/v1/deals", json={"title": "Долларовая", "client_id": c["id"], "amount": "10", "currency": "USD",
                                       "status_id": statuses["won"]["id"]})
    new_task(client, title="Просрочена", due_at=past())
    new_task(client, title="Обычная")

    resp = client.get("/api/v1/dashboard")
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert d["period"] == "30"
    assert d["clients"] == {"total": 1, "new": 1}
    deals = d["deals"]
    assert deals["open_count"] == 1
    assert [(m["currency"], Decimal(m["amount"])) for m in deals["open_amounts"]] == [("RUB", Decimal("1000"))]
    assert deals["won_count"] == 2 and deals["lost_count"] == 1
    won_by_currency = {m["currency"]: Decimal(m["amount"]) for m in deals["won_amounts"]}
    assert won_by_currency == {"RUB": Decimal("2500.50"), "USD": Decimal("10")}
    assert deals["conversion"] == 66.7
    assert deals["created"] == 4
    assert sum(s["count"] for s in deals["by_status"]) == 4
    assert len(deals["monthly"]) == 6 and deals["monthly"][-1]["created"] == 4 and deals["monthly"][-1]["won"] == 2
    assert deals["by_responsible"][0]["won"] == 2
    assert d["tasks"]["open"] == 2 and d["tasks"]["overdue"] == 1 and d["tasks"]["team_overdue"] == 1


def test_dashboard_period_and_unknown_period(client, make_user, factory):
    login_as(client, make_user, "admin@example.com")
    c = new_client(client)
    won_id = {s["code"]: s["id"] for s in client.get("/api/v1/statuses").json()}["won"]
    d = client.post("/api/v1/deals", json={"title": "Старая", "client_id": c["id"], "amount": "100",
                                           "status_id": won_id}).json()
    from app.models import Deal

    with factory() as s:
        deal = s.get(Deal, d["id"])
        deal.closed_at = datetime.now(timezone.utc) - timedelta(days=40)
        s.commit()
    assert client.get("/api/v1/dashboard", params={"period": "7"}).json()["deals"]["won_count"] == 0
    assert client.get("/api/v1/dashboard", params={"period": "all"}).json()["deals"]["won_count"] == 1
    fallback = client.get("/api/v1/dashboard", params={"period": "abc"}).json()
    assert fallback["period"] == "30"
    assert dashboard_service.period_start("all") is None
    assert dashboard_service.period_start("7") < datetime.now(timezone.utc)


def test_dashboard_breakdown_by_custom_select_field(client, make_user):
    login_as(client, make_user, "admin@example.com")
    resp = client.post("/api/v1/custom-fields", json={
        "entity_type": "deal", "label": "Мастер", "field_type": "select", "options": ["Анна", "Ольга"]})
    assert resp.status_code == 201
    c = new_client(client)
    for master in ("Анна", "Анна", "Ольга"):
        client.post("/api/v1/deals", json={"title": "Д", "client_id": c["id"], "custom": {"master": master}})
    d = client.get("/api/v1/dashboard").json()
    assert len(d["breakdowns"]) == 1
    b = d["breakdowns"][0]
    assert b["field"] == "Мастер" and b["entity"] == "deal"
    assert [(i["value"], i["count"]) for i in b["items"]] == [("Анна", 2), ("Ольга", 1)]


def test_dashboard_sections_follow_permissions(client, make_user, factory):
    make_role(factory, "tasker", ["dashboard:read", "tasks:read", "tasks:write"])
    make_user("t@example.com", role="tasker")
    api_login(client, "t@example.com")
    d = client.get("/api/v1/dashboard").json()
    assert d["deals"] is None and d["clients"] is None and d["tasks"] is not None
    assert d["tasks"]["team_overdue"] is None

    make_role(factory, "nodash", ["clients:read"])
    make_user("x@example.com", role="nodash")
    client.cookies.clear()
    api_login(client, "x@example.com")
    assert client.get("/api/v1/dashboard").status_code == 403


def test_home_shows_dashboard_or_redirects(client, make_user, factory):
    make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    home = client.get("/")
    assert home.status_code == 200 and "Главная" in home.text
    assert client.get("/?period=all").status_code == 200

    make_role(factory, "clientonly", ["clients:read"])
    make_user("c@example.com", role="clientonly")
    web_login(client, "c@example.com")
    resp = client.get("/")
    assert resp.status_code == 302 and resp.headers["location"] == "/clients"

    make_role(factory, "taskonly", ["tasks:read"])
    make_user("t@example.com", role="taskonly")
    web_login(client, "t@example.com")
    assert client.get("/").headers["location"] == "/tasks"


def test_web_task_flow(client, make_user, factory):
    admin_id = make_user("admin@example.com", role="admin")
    web_login(client, "admin@example.com")
    cl = new_client_web(client)

    form = client.get(f"/tasks/new?client_id={cl}")
    assert form.status_code == 200 and "Клиент для задач" in form.text

    created = client.post("/tasks/new", data={
        "title": "Подготовить КП", "description": "срочно", "priority": "high", "status": "todo",
        "due_at": "2030-05-01T14:30", "assignee_id": str(admin_id), "client_id": str(cl), "deal_id": "",
    })
    assert created.status_code in (302, 303), created.text[:400]
    url = created.headers["location"]
    page = client.get(url)
    assert "Подготовить КП" in page.text and "01.05.2030 14:30" in page.text

    assert "Подготовить КП" in client.get("/tasks").text
    assert "Подготовить КП" in client.get(f"/clients/{cl}").text

    edit_page = client.get(f"{url}/edit")
    assert 'value="2030-05-01T14:30"' in edit_page.text

    bad = client.post(f"{url}/edit", data={"title": "", "priority": "high", "status": "todo", "due_at": "завтра"})
    assert bad.status_code == 400

    done = client.post(f"{url}/status", data={"status": "done", "next": "/tasks?view=all"})
    assert done.status_code in (302, 303) and done.headers["location"] == "/tasks?view=all"
    with factory() as s:
        t = s.scalar(select(Task))
        assert t.status == TaskStatus.DONE and t.completed_at is not None
    evil = client.post(f"{url}/status", data={"status": "todo", "next": "//evil.example"})
    assert evil.headers["location"] != "//evil.example"

    deleted = client.post(f"{url}/delete")
    assert deleted.status_code in (302, 303) and deleted.headers["location"] == "/tasks"
    with factory() as s:
        assert s.scalar(select(Task.id)) is None


def new_client_web(client) -> int:
    resp = client.post("/clients/new", data={"type": "person", "name": "Клиент для задач"})
    assert resp.status_code in (302, 303)
    return int(resp.headers["location"].rstrip("/").split("/")[-1])


def test_web_task_access_and_search_endpoints(client, make_user):
    make_user("a@example.com", role="employee")
    make_user("b@example.com", role="employee")
    web_login(client, "a@example.com")
    created = client.post("/tasks/new", data={"title": "Личная", "priority": "normal", "status": "todo"})
    url = created.headers["location"]
    cl = new_client_web(client)
    client.post("/deals/new", data={"title": "Поиск сделки", "client_id": str(cl), "amount": "5", "currency": "RUB",
                                    "deal_date": "2025-01-01"})
    found = client.get("/deals/search", params={"q": "поиск"})
    assert found.status_code == 200 and found.json()[0]["name"] == "Поиск сделки"
    assert found.json()[0]["sub"] == "Клиент для задач"

    web_login(client, "b@example.com")
    assert client.get(url).status_code == 404
    assert client.get(f"{url}/edit").status_code == 404
    assert client.post(f"{url}/delete").status_code == 404
