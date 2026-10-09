"""Демо-сценарий «Континент»: наполнение работает, права и история выглядят правдоподобно."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.demo_scenario import S_CANCEL, S_DONE, S_NEW, USERS, run_scenario
from app.models import (
    ActivityEvent, Client, CustomField, Deal, DealTemplate, Note, Role, Status, Task, TaskStatus, User,
)
from tests.conftest import PASSWORD
from tests.test_roles_and_templates import web_login


def _load(factory, **kwargs):
    with factory() as s:
        return run_scenario(s, password=PASSWORD, **kwargs)


def test_scenario_builds_everything(factory, make_user):
    make_user("old@example.com", role="admin", full_name="Старый админ")
    summary = _load(factory)

    assert summary["deals"] >= 20 and summary["tasks"] >= 12 and summary["clients"] >= 10
    with factory() as s:
        emails = set(s.scalars(select(User.email)))
        assert emails == {email for email, _, _ in USERS.values()}
        assert s.scalar(select(func.count()).select_from(Role).where(Role.code == "beauty_master")) == 1
        assert {t.name for t in s.scalars(select(DealTemplate))} == {"Автосервис", "Салон красоты"}
        labels = {f.label for f in s.scalars(select(CustomField))}
        assert {"Марка и модель авто", "Мастер", "Услуга", "Способ оплаты", "Откуда узнал"} <= labels
        assert "VIN" not in labels and "Госномер" not in labels

        statuses = [st.name for st in s.scalars(select(Status).order_by(Status.sort_order))]
        assert statuses == [S_NEW, "В работе", "Ожидает оплаты", S_DONE, S_CANCEL]
        used = {name for name in s.scalars(select(Status.name).join(Deal, Deal.status_id == Status.id))}
        assert used == set(statuses)
        assert s.scalar(select(func.count()).select_from(Note)) >= 8


def test_scenario_is_repeatable_and_vin_option(factory):
    _load(factory)
    summary = _load(factory, with_vin=True)
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(User)) == len(USERS)
        assert s.scalar(select(func.count()).select_from(Deal)) == summary["deals"]
        labels = {f.label for f in s.scalars(select(CustomField))}
        assert {"VIN", "Госномер"} <= labels


def test_history_is_backdated(factory):
    _load(factory)
    now = datetime.now(timezone.utc)
    with factory() as s:
        def aware(value):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        oldest_event = aware(s.scalar(select(func.min(ActivityEvent.created_at))))
        assert now - oldest_event > timedelta(days=90)
        assert aware(s.scalar(select(func.min(Deal.created_at)))) < now - timedelta(days=90)
        done = s.scalars(select(Deal).join(Status).where(Status.name == S_DONE)).all()
        assert done and all(d.closed_at is not None for d in done)
        assert all(d.closed_at is None for d in s.scalars(select(Deal).join(Status).where(Status.name == S_NEW)))
        deal = s.scalar(select(Deal).where(Deal.title == "ТО-2 Skoda Octavia"))
        events = s.scalars(select(ActivityEvent).where(ActivityEvent.deal_id == deal.id).order_by(ActivityEvent.id)).all()
        assert events[0].kind == "created"
        flat = " ".join(str(e.changes) for e in events)
        assert "Сумма" in flat and "Статус" in flat
        stamps = [aware(e.created_at) for e in events]
        assert stamps == sorted(stamps)
        assert s.scalar(select(func.count()).select_from(Task).where(Task.status == TaskStatus.DONE)) >= 3


def test_roles_see_what_they_should(client, factory):
    _load(factory)

    web_login(client, "director@kontinent.demo")
    deals_page = client.get("/deals")
    assert deals_page.status_code == 200
    for name in ("Стандартная", "Автосервис", "Салон красоты", "Денис Коровин (Сотрудник)"):
        assert name in deals_page.text
    assert client.get("/dashboard").status_code == 200

    web_login(client, "denis@kontinent.demo")
    page = client.get("/deals").text
    assert "Диагностика ходовой Toyota Camry" in page
    assert "Свадебный макияж" not in page and "Курс ухода за волосами" not in page

    web_login(client, "anna@kontinent.demo")
    page = client.get("/deals").text
    assert "Окрашивание AirTouch" in page and "ТО-2 Skoda Octavia" not in page
    assert client.get("/settings/fields").status_code in (302, 303, 403)

    web_login(client, "marina@kontinent.demo")
    assert "ТО-2 Skoda Octavia" in client.get("/deals", params={"q": "Skoda"}).text
    assert "Свадебный макияж" in client.get("/deals", params={"q": "Свадебный"}).text


def test_demo_clients_have_custom_values(factory):
    _load(factory)
    with factory() as s:
        volkov = s.scalar(select(Client).where(Client.name == "Сергей Волков"))
        assert volkov.custom["source"] == "Рекомендация"
        assert volkov.email == "sergey.volkov@example.com"


def test_login_page_uses_company_name(client, factory):
    _load(factory)
    client.cookies.clear()
    page = client.get("/login")
    assert page.status_code == 200 and "Континент" in page.text
