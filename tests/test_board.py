"""Канбан-доска сделок."""
from decimal import Decimal

from app.models import Role
from app.services import deal_service
from tests.conftest import PASSWORD, api_login


def web_login(client, email):
    client.cookies.clear()
    resp = client.post("/login", data={"email": email, "password": PASSWORD, "next": "/"})
    assert resp.status_code in (302, 303), resp.text


def setup_admin(client, make_user):
    make_user("admin@example.com", role="admin", full_name="Анна Админова")
    api_login(client, "admin@example.com")
    web_login(client, "admin@example.com")


def mk_client(client, name="Иван"):
    return client.post("/api/v1/clients", json={"name": name}).json()["id"]


def mk_deal(client, client_id, title, **kw):
    resp = client.post("/api/v1/deals", json={"title": title, "client_id": client_id, **kw})
    assert resp.status_code == 201, resp.text
    return resp.json()


def statuses(client):
    return {s["code"]: s for s in client.get("/api/v1/statuses").json()}


def column(html: str, status_id: int) -> str:
    """Кусок HTML одной колонки доски."""
    start = html.index(f'data-status-id="{status_id}"')
    end = html.find("<section", start)
    return html[start:] if end == -1 else html[start:end]


def test_board_requires_login(client):
    resp = client.get("/deals/board")
    assert resp.status_code in (302, 303) and "/login" in resp.headers["location"]


def test_board_groups_deals_by_status(client, make_user):
    setup_admin(client, make_user)
    st = statuses(client)
    c = mk_client(client)
    mk_deal(client, c, "Новая сделка", amount="100")
    mk_deal(client, c, "Рабочая сделка", amount="250.50", status_id=st["in_progress"]["id"])
    mk_deal(client, c, "Выигранная сделка", amount="10", currency="USD", status_id=st["won"]["id"])

    page = client.get("/deals/board")
    assert page.status_code == 200
    html = page.text
    assert "Новая сделка" in column(html, st["new"]["id"])
    assert "Новая сделка" not in column(html, st["in_progress"]["id"])
    assert "Рабочая сделка" in column(html, st["in_progress"]["id"])
    assert "Выигранная сделка" in column(html, st["won"]["id"])
    assert 'draggable="true"' in html and "/static/js/board.js" in html
    assert "250,50" in column(html, st["in_progress"]["id"])  # сумма колонки


def test_board_reflects_status_change(client, make_user):
    setup_admin(client, make_user)
    st = statuses(client)
    c = mk_client(client)
    deal = mk_deal(client, c, "Двигаемая")
    moved = client.post(f"/api/v1/deals/{deal['id']}/status", json={"status_id": st["won"]["id"]})
    assert moved.status_code == 200 and moved.json()["closed_at"] is not None
    html = client.get("/deals/board").text
    assert "Двигаемая" in column(html, st["won"]["id"])
    assert "Двигаемая" not in column(html, st["new"]["id"])


def test_board_filters(client, make_user):
    setup_admin(client, make_user)
    c1, c2 = mk_client(client, "Первый Клиент"), mk_client(client, "Второй Клиент")
    mk_deal(client, c1, "Сделка А")
    mk_deal(client, c2, "Сделка Б")
    by_q = client.get("/deals/board", params={"q": "второй"}).text
    assert "Сделка Б" in by_q and "Сделка А" not in by_q
    by_client = client.get("/deals/board", params={"client": c1}).text
    assert "Сделка А" in by_client and "Сделка Б" not in by_client
    assert "Первый Клиент" in by_client


def test_board_inactive_status_only_when_it_has_deals(client, make_user):
    setup_admin(client, make_user)
    st = statuses(client)
    c = mk_client(client)
    work_id = st["in_progress"]["id"]

    client.patch(f"/api/v1/statuses/{work_id}", json={"is_active": False})
    assert f'data-status-id="{work_id}"' not in client.get("/deals/board").text  # пустой отключённый — скрыт

    client.patch(f"/api/v1/statuses/{work_id}", json={"is_active": True})
    deal = mk_deal(client, c, "Остаток", status_id=work_id)
    client.patch(f"/api/v1/statuses/{work_id}", json={"is_active": False})
    html = client.get("/deals/board").text
    assert "Остаток" in column(html, work_id) and "(откл.)" in html  # с делами — виден, помечен
    assert deal["id"]


def test_board_service_limits_and_counts(factory, make_user):
    from sqlalchemy import select

    from app.models import Client, Deal, Status, User

    make_user("a@example.com", role="admin")
    with factory() as s:
        user = s.scalar(select(User))
        new = s.scalar(select(Status).where(Status.code == "new"))
        cl = Client(name="К")
        s.add(cl)
        s.flush()
        for i in range(5):
            s.add(Deal(title=f"Д{i}", client_id=cl.id, status_id=new.id, amount=Decimal("10"), responsible_id=user.id))
        s.commit()
        cols = deal_service.board(s, per_column=2)
        first = next(c for c in cols if c["status"].code == "new")
        assert first["count"] == 5 and len(first["deals"]) == 2 and first["hidden"] == 3
        assert first["totals"] == [("RUB", Decimal("50"))]
        # отключённый статус с делами остаётся в доске
        new.is_active = False
        s.commit()
        assert any(c["status"].code == "new" for c in deal_service.board(s))
        # фильтр по ответственному
        assert next(c for c in deal_service.board(s, responsible_id=user.id) if c["status"].code == "new")["count"] == 5
        # при фильтре без совпадений пустая колонка отключённого статуса не показывается
        assert not any(c["status"].code == "new" for c in deal_service.board(s, responsible_id=9999))


def test_board_overflow_link(client, make_user, monkeypatch):
    setup_admin(client, make_user)
    c = mk_client(client)
    for i in range(3):
        mk_deal(client, c, f"Сделка {i}")
    original = deal_service.board
    monkeypatch.setattr(deal_service, "board", lambda db, **kw: original(db, per_column=2, **kw))
    html = client.get("/deals/board").text
    assert "Ещё 1" in html and "/deals?status=" in html


def test_board_read_only_for_user_without_write(client, make_user, factory):
    with factory() as s:
        s.add(Role(code="viewer", name="viewer", permissions=["deals:read"], is_system=False))
        s.commit()
    make_user("v@example.com", role="viewer")
    web_login(client, "v@example.com")
    html = client.get("/deals/board").text
    assert 'data-movable="false"' in html and 'draggable="true"' not in html
    assert "data-move-select" not in html


def test_deals_list_links_to_board(client, make_user):
    setup_admin(client, make_user)
    assert "/deals/board" in client.get("/deals").text
