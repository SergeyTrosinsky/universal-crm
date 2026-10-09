"""История изменений и заметки в карточках клиентов и сделок."""
from sqlalchemy import func, select

from app.models import ActivityEvent, Note
from tests.conftest import PASSWORD, api_login


def web_login(client, email):
    resp = client.post("/login", data={"email": email, "password": PASSWORD})
    assert resp.status_code in (302, 303), resp.text


def admin(client, make_user, email="admin@example.com", name="Админ"):
    make_user(email, role="admin", full_name=name)
    api_login(client, email)


def activity(client, kind, owner_id):
    resp = client.get(f"/api/v1/{kind}/{owner_id}/activity")
    assert resp.status_code == 200, resp.text
    return resp.json()


def field(client, **kw):
    payload = {"entity_type": "client", "label": "Поле", "field_type": "text", **kw}
    resp = client.post("/api/v1/custom-fields", json=payload)
    assert resp.status_code == 201, resp.text


def test_client_created_and_changes_are_logged(client, make_user):
    admin(client, make_user)
    field(client, label="VIN", code="vin")
    cid = client.post("/api/v1/clients", json={"name": "Иван", "phone": "+79991234567", "custom": {"vin": "A1"}}).json()["id"]

    items = activity(client, "clients", cid)
    assert [(i["type"], i["kind"], i["author"]) for i in items] == [("event", "created", "Админ")]

    resp = client.patch(f"/api/v1/clients/{cid}", json={"name": "Иван Петров", "custom": {"vin": "B2"}})
    assert resp.status_code == 200, resp.text
    items = activity(client, "clients", cid)
    assert len(items) == 2
    changes = {c["label"]: (c["old"], c["new"]) for c in items[0]["changes"]}
    assert changes == {"Имя / название": ("Иван", "Иван Петров"), "VIN": ("A1", "B2")}


def test_noop_update_adds_nothing(client, make_user):
    admin(client, make_user)
    cid = client.post("/api/v1/clients", json={"name": "Иван", "email": "i@example.com"}).json()["id"]
    assert client.patch(f"/api/v1/clients/{cid}", json={"name": "Иван", "email": "I@example.com"}).status_code == 200
    assert len(activity(client, "clients", cid)) == 1


def test_clearing_value_is_logged_as_dash(client, make_user):
    admin(client, make_user)
    field(client, label="Госномер", code="plate")
    cid = client.post("/api/v1/clients", json={"name": "Иван", "custom": {"plate": "А1"}}).json()["id"]
    client.patch(f"/api/v1/clients/{cid}", json={"custom": {"plate": None}})
    change = activity(client, "clients", cid)[0]["changes"][0]
    assert (change["label"], change["old"], change["new"]) == ("Госномер", "А1", "—")


def test_deal_status_amount_responsible_and_custom_fields(client, make_user):
    admin(client, make_user)
    emp = make_user("emp@example.com", role="employee", full_name="Борис")
    field(client, entity_type="deal", label="Марка авто", code="brand")
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    deal = client.post("/api/v1/deals", json={"title": "ТО", "client_id": cid, "amount": "1000", "custom": {"brand": "Лада"}}).json()
    statuses = {s["code"]: s for s in client.get("/api/v1/statuses").json()}

    client.post(f"/api/v1/deals/{deal['id']}/status", json={"status_id": statuses["won"]["id"]})
    first = activity(client, "deals", deal["id"])[0]
    assert [(c["label"], c["new"]) for c in first["changes"]] == [("Статус", statuses["won"]["name"])]
    assert first["author"] == "Админ"

    client.patch(
        f"/api/v1/deals/{deal['id']}",
        json={"amount": "1500", "responsible_id": emp, "custom": {"brand": "Kia"}},
    )
    latest = {
        c["label"]: (c["old"].replace("\xa0", " "), c["new"].replace("\xa0", " "))
        for c in activity(client, "deals", deal["id"])[0]["changes"]
    }
    assert latest["Сумма"][0].startswith("1 000") and latest["Сумма"][1].startswith("1 500")
    assert latest["Ответственный"][1] == "Борис"
    assert latest["Марка авто"] == ("Лада", "Kia")
    assert "Статус" not in latest

    count = len(activity(client, "deals", deal["id"]))
    client.post(f"/api/v1/deals/{deal['id']}/status", json={"status_id": statuses["won"]["id"]})
    assert len(activity(client, "deals", deal["id"])) == count


def test_notes_add_list_delete(client, make_user):
    admin(client, make_user)
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    created = client.post(f"/api/v1/clients/{cid}/notes", json={"body": "  Позвонить в пятницу  "})
    assert created.status_code == 201, created.text
    assert created.json()["body"] == "Позвонить в пятницу"
    items = activity(client, "clients", cid)
    assert [i["type"] for i in items] == ["note", "event"]

    assert client.post(f"/api/v1/clients/{cid}/notes", json={"body": "   "}).status_code in (422,)
    assert client.delete(f"/api/v1/clients/{cid}/notes/{created.json()['id']}").status_code == 204
    assert [i["type"] for i in activity(client, "clients", cid)] == ["event"]
    assert client.delete(f"/api/v1/clients/{cid}/notes/999").status_code == 404


def test_note_belongs_to_its_card_only(client, make_user):
    admin(client, make_user)
    a = client.post("/api/v1/clients", json={"name": "А"}).json()["id"]
    b = client.post("/api/v1/clients", json={"name": "Б"}).json()["id"]
    note = client.post(f"/api/v1/clients/{a}/notes", json={"body": "для А"}).json()
    assert client.delete(f"/api/v1/clients/{b}/notes/{note['id']}").status_code == 404


def test_only_author_or_admin_deletes_note(client, make_user):
    make_user("mgr@example.com", role="manager", full_name="Мила")
    make_user("emp@example.com", role="employee", full_name="Аня")
    make_user("adm@example.com", role="admin", full_name="Админ")
    api_login(client, "mgr@example.com")
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    note = client.post(f"/api/v1/clients/{cid}/notes", json={"body": "заметка менеджера"}).json()

    client.cookies.clear()
    api_login(client, "emp@example.com")
    assert client.delete(f"/api/v1/clients/{cid}/notes/{note['id']}").status_code == 403

    client.cookies.clear()
    api_login(client, "adm@example.com")
    assert client.delete(f"/api/v1/clients/{cid}/notes/{note['id']}").status_code == 204


def test_employee_cannot_see_history_of_foreign_deal(client, make_user):
    make_user("mgr@example.com", role="manager", full_name="Мила")
    make_user("emp@example.com", role="employee", full_name="Аня")
    api_login(client, "mgr@example.com")
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    deal = client.post("/api/v1/deals", json={"title": "Чужая", "client_id": cid}).json()

    client.cookies.clear()
    api_login(client, "emp@example.com")
    assert client.get(f"/api/v1/deals/{deal['id']}/activity").status_code == 404
    assert client.post(f"/api/v1/deals/{deal['id']}/notes", json={"body": "x"}).status_code == 404


def test_web_cards_show_history_and_notes(client, make_user):
    admin(client, make_user)
    web_login(client, "admin@example.com")
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    deal = client.post("/api/v1/deals", json={"title": "ТО", "client_id": cid, "amount": "1000"}).json()
    client.patch(f"/api/v1/clients/{cid}", json={"name": "Иван Петров"})

    page = client.get(f"/clients/{cid}")
    assert page.status_code == 200
    assert "История и заметки" in page.text and "создал(а) запись" in page.text and "Иван Петров" in page.text

    resp = client.post(f"/clients/{cid}/notes", data={"body": "Любит кофе"})
    assert resp.status_code == 303
    assert "Любит кофе" in client.get(f"/clients/{cid}").text

    resp = client.post(f"/deals/{deal['id']}/notes", data={"body": "Ждём запчасти"})
    assert resp.status_code == 303
    dpage = client.get(f"/deals/{deal['id']}")
    assert "Ждём запчасти" in dpage.text and "История и заметки" in dpage.text

    assert client.post(f"/clients/{cid}/notes", data={"body": "  "}).status_code == 303
    assert client.get(f"/clients/{cid}").text.count("Любит кофе") == 1


def test_web_status_change_and_note_delete(client, make_user, factory):
    admin(client, make_user)
    web_login(client, "admin@example.com")
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    deal = client.post("/api/v1/deals", json={"title": "ТО", "client_id": cid}).json()
    statuses = {s["code"]: s for s in client.get("/api/v1/statuses").json()}
    client.post(f"/deals/{deal['id']}/status", data={"status_id": statuses["won"]["id"]})
    assert "изменил(а)" in client.get(f"/deals/{deal['id']}").text

    client.post(f"/deals/{deal['id']}/notes", data={"body": "Временная"})
    with factory() as s:
        note_id = s.scalar(select(Note.id).where(Note.deal_id == deal["id"]))
    assert client.post(f"/deals/{deal['id']}/notes/{note_id}/delete").status_code == 303
    assert "Временная" not in client.get(f"/deals/{deal['id']}").text
    assert client.post(f"/deals/{deal['id']}/notes/{note_id}/delete").status_code == 404


def test_deleting_client_removes_history_and_notes(client, make_user, factory):
    admin(client, make_user)
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    deal = client.post("/api/v1/deals", json={"title": "ТО", "client_id": cid}).json()
    client.post(f"/api/v1/clients/{cid}/notes", json={"body": "a"})
    client.post(f"/api/v1/deals/{deal['id']}/notes", json={"body": "b"})
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(ActivityEvent)) == 2
    assert client.delete(f"/api/v1/clients/{cid}").status_code == 204
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(ActivityEvent)) == 0
        assert s.scalar(select(func.count()).select_from(Note)) == 0


def test_user_deleted_name_stays_in_history(client, make_user, factory):
    admin(client, make_user)
    author = make_user("tmp@example.com", role="manager", full_name="Временный")
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    client.cookies.clear()
    api_login(client, "tmp@example.com")
    client.post(f"/api/v1/clients/{cid}/notes", json={"body": "от временного"})
    from app.models import User

    with factory() as s:
        s.delete(s.get(User, author))
        s.commit()
    client.cookies.clear()
    api_login(client, "admin@example.com")
    note = next(i for i in activity(client, "clients", cid) if i["type"] == "note")
    assert note["author"] == "Временный"


def test_import_update_is_logged(client, make_user):
    from tests.test_import_export import confirm, csv_file, token_of, upload

    admin(client, make_user)
    web_login(client, "admin@example.com")
    cid = client.post("/api/v1/clients", json={"name": "Иван", "phone": "+7 999 123-45-67"}).json()["id"]
    data = csv_file([["Имя", "Телефон", "Email"], ["Иван Новый", "+7 999 123-45-67", "new@example.com"]])
    preview = upload(client, "clients", "c.csv", data, duplicates="update")
    confirm(client, "clients", token_of(preview))
    events = [i for i in activity(client, "clients", cid) if i["type"] == "event"]
    labels = {c["label"] for e in events for c in (e["changes"] or [])}
    assert {"Имя / название", "Email"} <= labels
    assert events[0]["author"] == "Админ"


def test_amount_in_history_uses_currency_symbol(client, make_user):
    admin(client, make_user)
    cid = client.post("/api/v1/clients", json={"name": "Иван"}).json()["id"]
    deal = client.post("/api/v1/deals", json={"title": "Д", "client_id": cid, "amount": "100"}).json()
    client.patch(f"/api/v1/deals/{deal['id']}", json={"amount": "250"})
    flat = " ".join(str(i.get("changes")) for i in activity(client, "deals", deal["id"]))
    assert "₽" in flat and "RUB" not in flat
