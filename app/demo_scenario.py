"""Демонстрационный сценарий «Континент»: сервисная компания с тремя направлениями
(автосервис, салон красоты и корпоративные продажи) в одной CRM.

Скрипт полностью наполняет пустую CRM «рабочими» данными: роли и сотрудники, термины, статусы,
шаблоны сделок с полями, клиенты, заказы со всей историей изменений и заметками, задачи.
Всё создаётся через обычные сервисы приложения, поэтому журнал изменений, закрытие сделок и права
работают так же, как при ручной работе. Даты «разнесены» на пять месяцев назад, чтобы статистика
на главной странице и график по месяцам выглядели живыми.

ВНИМАНИЕ: reset_business_data() удаляет ВСЕХ пользователей, клиентов, сделки, задачи, поля,
шаблоны, дополнительные роли и общие настройки. Запускайте только осознанно (см. app/cli.py)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core import permissions as perms
from app.models import (
    ActivityEvent, Client, CustomField, CustomValue, Deal, DealTemplate, FieldType, Note, Role,
    Status, StatusKind, Task, User,
)
from app.services import (
    activity_service, client_service, custom_field_service, deal_service, deal_template_service,
    role_service, settings_service, status_service, task_service, user_service,
)
from app.services.errors import ValidationFailed

EMAIL_DOMAIN = "kontinent.demo"
COMPANY_NAME = "Континент"

S_NEW, S_WORK, S_PAY, S_DONE, S_CANCEL = (
    "Новая заявка", "В работе", "Ожидает оплаты", "Выполнен", "Отменён",
)

USERS: dict[str, tuple[str, str, str]] = {
    "alexey": (f"director@{EMAIL_DOMAIN}", "Алексей Орлов", "admin"),
    "marina": (f"marina@{EMAIL_DOMAIN}", "Марина Соколова", "manager"),
    "igor": (f"igor@{EMAIL_DOMAIN}", "Игорь Белов", "manager"),
    "denis": (f"denis@{EMAIL_DOMAIN}", "Денис Коровин", "employee"),
    "olga": (f"olga@{EMAIL_DOMAIN}", "Ольга Крылова", "employee"),
    "anna": (f"anna@{EMAIL_DOMAIN}", "Анна Лебедева", "beauty_master"),
}
USER_POSITIONS = {
    "alexey": "директор: видит и настраивает всё",
    "marina": "менеджер: продажи, корпоративные клиенты, назначает задачи",
    "igor": "менеджер автосервиса",
    "denis": "сотрудник: приёмщик автосервиса (видит только свои заказы)",
    "olga": "сотрудник: администратор салона (видит только свои записи)",
    "anna": "мастер салона: своя роль с урезанными правами",
}

MASTER_ROLE_CODE = "beauty_master"
MASTER_PERMISSIONS = [
    perms.CLIENTS_READ, perms.CLIENTS_WRITE, perms.DEALS_READ, perms.DEALS_WRITE,
    perms.TASKS_READ, perms.TASKS_WRITE, perms.DASHBOARD_READ,
]


@dataclass
class ClientSpec:
    key: str
    name: str
    type: str
    owner: str
    phone: str
    email: str | None = None
    address: str | None = None
    custom: dict[str, Any] = field(default_factory=dict)
    notes: list[tuple[str, str]] = field(default_factory=list)
    updates: list[tuple[int, dict[str, str], str]] = field(default_factory=list)


@dataclass
class DealSpec:
    title: str
    client: str
    template: str | None
    amount: int
    days_ago: int
    responsible: str
    creator: str
    path: list[str] = field(default_factory=list)
    span: float = 0.0
    custom: dict[str, Any] = field(default_factory=dict)
    edits: list[tuple[float, dict[str, str], dict[str, Any], str]] = field(default_factory=list)
    notes: list[tuple[float, str, str]] = field(default_factory=list)


@dataclass
class TaskSpec:
    title: str
    assignee: str
    creator: str
    priority: str
    status: str
    due_days: float
    created_days_ago: float
    deal: str | None = None
    client: str | None = None
    description: str | None = None


CLIENTS = [
    ClientSpec(
        "volkov", "Сергей Волков", "person", "denis", "+7 (903) 214-55-18", "s.volkov@example.com",
        custom={"source": "Рекомендация", "birthday": "1984-03-17", "marketing": True},
        notes=[("denis", "Приезжает на ТО строго по регламенту. Просит SMS-напоминание за день до записи.")],
        updates=[(60, {"email": "sergey.volkov@example.com"}, "denis")],
    ),
    ClientSpec(
        "morozova", "Екатерина Морозова", "person", "denis", "+7 (915) 640-12-77", "k.morozova@example.com",
        custom={"source": "Сайт", "marketing": True},
    ),
    ClientSpec(
        "nikitin", "Павел Никитин", "person", "denis", "+7 (926) 118-40-02",
        custom={"source": "Повторное обращение", "birthday": "1979-11-02", "marketing": False},
        notes=[("denis", "Не любит долгие звонки — лучше писать в мессенджер.")],
    ),
    ClientSpec(
        "fomin", "Андрей Фомин", "person", "igor", "+7 (985) 330-67-41",
        custom={"source": "Соцсети", "marketing": True},
    ),
    ClientSpec(
        "logistik", "ООО «Логистик-Юг»", "company", "igor", "+7 (495) 220-14-90", "park@logistik-yug.example.com",
        address="Москва, ул. Складочная, 12, стр. 3",
        custom={"source": "Рекомендация", "marketing": True},
        notes=[("igor", "Автопарк — 12 фургонов Ford Transit. Согласуют работы через механика Олега, оплата по счёту.")],
    ),
    ClientSpec(
        "pavlova", "Анастасия Павлова", "person", "anna", "+7 (916) 777-21-05", "nastya.pavlova@example.com",
        custom={"source": "Соцсети", "birthday": "1993-08-24", "marketing": True},
        notes=[("anna", "Аллергия на аммиачные краски — работаем только с безаммиачными.")],
    ),
    ClientSpec(
        "gerasimova", "Виктория Герасимова", "person", "anna", "+7 (903) 505-18-36",
        custom={"source": "Рекомендация", "marketing": True},
    ),
    ClientSpec(
        "smirnova", "Елена Смирнова", "person", "olga", "+7 (925) 410-92-13", "elena.smirnova@example.com",
        custom={"source": "Сайт", "birthday": "1995-06-30", "marketing": True},
        updates=[(2, {"phone": "+7 (925) 410-92-14"}, "olga")],
    ),
    ClientSpec(
        "kuznetsova", "Ирина Кузнецова", "person", "olga", "+7 (999) 301-47-22",
        custom={"source": "Проходили мимо", "marketing": False},
    ),
    ClientSpec(
        "belousova", "Наталья Белоусова", "person", "anna", "+7 (967) 118-05-66",
        custom={"source": "Повторное обращение", "marketing": True},
    ),
    ClientSpec(
        "frolova", "Мария Фролова", "person", "anna", "+7 (905) 662-30-18",
        custom={"source": "Соцсети", "marketing": True},
    ),
    ClientSpec(
        "romashka", "ООО «Ромашка Тур»", "company", "marina", "+7 (495) 710-33-45", "office@romashka-tur.example.com",
        address="Москва, Тверская ул., 22, офис 41",
        custom={"source": "Рекомендация", "marketing": True},
        notes=[("marina", "Контакт — Ирина, офис-менеджер. Оплата по счёту в течение 5 рабочих дней.")],
    ),
    ClientSpec(
        "kofeynya", "Кофейня «Бодрое утро»", "company", "marina", "+7 (495) 998-12-60", "boss@bodroe-utro.example.com",
        address="Москва, ул. Лесная, 5",
        custom={"source": "Сайт", "marketing": True},
    ),
    ClientSpec(
        "zaharova", "ИП Захарова Д. В.", "company", "marina", "+7 (903) 224-80-71",
        custom={"source": "Рекомендация", "marketing": False},
    ),
]

CAR_BRAND, MILEAGE, WORK = "car_brand", "mileage", "work_type"
MASTER, SERVICE, VISIT, DEPOSIT = "master", "service", "visit_date", "deposit"


def _ago(days: int) -> str:
    """Дата «N дней назад» в формате ISO — для полей-дат внутри сделок."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


def build_deals() -> list[DealSpec]:
    return [
        DealSpec(
            "ТО-2 Skoda Octavia", "volkov", "auto", 16200, 62, "denis", "marina", [S_WORK, S_PAY, S_DONE], 3,
            {CAR_BRAND: "Skoda Octavia", MILEAGE: 61200, WORK: "Плановое ТО", "payment": "Карта"},
            edits=[(0.4, {"amount": "18400"}, {}, "denis")],
            notes=[(0.4, "denis", "Нашли загрязнённые воздушный и салонный фильтры — согласовали замену по телефону, +2 200 ₽.")],
        ),
        DealSpec(
            "Замена тормозных колодок Kia Rio", "morozova", "auto", 9600, 40, "denis", "marina", [S_WORK, S_DONE], 2,
            {CAR_BRAND: "Kia Rio", MILEAGE: 84300, WORK: "Ремонт ходовой", "payment": "Наличные"},
        ),
        DealSpec(
            "Диагностика ходовой Toyota Camry", "nikitin", "auto", 4500, 3, "denis", "marina", [S_WORK], 1,
            {CAR_BRAND: "Toyota Camry", MILEAGE: 112500, WORK: "Диагностика", "payment": "Карта"},
            edits=[(0.9, {"amount": "6200"}, {}, "denis")],
            notes=[
                (0.5, "denis", "Клиент жалуется на стук спереди при поворотах. Предварительно — стойки стабилизатора "
                               "и опора амортизатора, нужна проверка на подъёмнике."),
                (0.9, "denis", "Подтвердилось: износ опоры амортизатора. К диагностике добавили замену — итог 6 200 ₽."),
            ],
        ),
        DealSpec(
            "Кузовной ремонт бампера Hyundai Solaris", "fomin", "auto", 32000, 6, "igor", "igor", [S_WORK, S_PAY], 5,
            {CAR_BRAND: "Hyundai Solaris", MILEAGE: 45800, WORK: "Кузовной ремонт", "payment": "Карта"},
            edits=[(0.5, {"amount": "38000"}, {}, "igor")],
            notes=[(0.5, "igor", "После дефектовки: кроме бампера повреждено крепление фары. Цена выросла до 38 000 ₽, клиент согласен.")],
        ),
        DealSpec(
            "Сезонный шиномонтаж, 4 фургона", "logistik", "auto", 14400, 20, "igor", "igor", [S_WORK, S_DONE], 3,
            {CAR_BRAND: "Ford Transit ×4", WORK: "Шиномонтаж", "payment": "Безналичный расчёт"},
        ),
        DealSpec(
            "Компьютерная диагностика Ford Transit", "logistik", "auto", 3000, 1, "igor", "igor", [], 0,
            {CAR_BRAND: "Ford Transit", MILEAGE: 198000, WORK: "Диагностика", "payment": "Безналичный расчёт"},
        ),
        DealSpec(
            "Замена ремня ГРМ Skoda Octavia", "volkov", "auto", 27500, 28, "denis", "marina", [S_WORK, S_CANCEL], 4,
            {CAR_BRAND: "Skoda Octavia", MILEAGE: 61900, WORK: "Плановое ТО"},
            notes=[(1.0, "denis", "Клиент отказался: нашёл дешевле в другом сервисе. Предложить скидку 10% при следующем ТО.")],
        ),
        DealSpec(
            "ТО Toyota Camry", "nikitin", "auto", 12900, 95, "denis", "marina", [S_WORK, S_DONE], 2,
            {CAR_BRAND: "Toyota Camry", MILEAGE: 104000, WORK: "Плановое ТО", "payment": "Карта"},
        ),
        DealSpec(
            "Замена масла и фильтров Kia Rio", "morozova", "auto", 6700, 120, "denis", "marina", [S_WORK, S_DONE], 1,
            {CAR_BRAND: "Kia Rio", MILEAGE: 78000, WORK: "Плановое ТО", "payment": "Наличные"},
        ),
        DealSpec(
            "Покраска дисков", "nikitin", "auto", 15000, 70, "igor", "igor", [S_WORK, S_DONE], 4,
            {CAR_BRAND: "Toyota Camry", WORK: "Кузовной ремонт", "payment": "Карта"},
        ),
        DealSpec(
            "Окрашивание и стрижка", "pavlova", "beauty", 7800, 35, "anna", "marina", [S_WORK, S_DONE], 1,
            {MASTER: "Анна", SERVICE: "Окрашивание", VISIT: _ago(34), DEPOSIT: True, "payment": "Карта"},
            notes=[(0.5, "anna", "Безаммиачная краска, оттенок 7.1. Клиентка довольна, записалась на уход.")],
        ),
        DealSpec(
            "Маникюр с покрытием", "gerasimova", "beauty", 2600, 12, "olga", "marina", [S_WORK, S_DONE], 1,
            {MASTER: "Мария", SERVICE: "Маникюр", VISIT: _ago(11), DEPOSIT: False, "payment": "Наличные"},
        ),
        DealSpec(
            "Свадебный макияж и причёска", "smirnova", "beauty", 12000, 2, "olga", "marina", [S_WORK, S_PAY], 1.5,
            {MASTER: "Ольга", SERVICE: "Макияж", VISIT: _ago(-9), DEPOSIT: True, "payment": "Карта"},
            notes=[(0.8, "olga", "Невеста просит пробный макияж за неделю до даты. Внесён депозит 3 000 ₽.")],
        ),
        DealSpec(
            "Педикюр", "kuznetsova", "beauty", 3200, 0, "olga", "marina", [S_WORK], 0,
            {MASTER: "Мария", SERVICE: "Педикюр", VISIT: _ago(0), DEPOSIT: False},
        ),
        DealSpec(
            "Стрижка", "belousova", "beauty", 1800, 0, "anna", "marina", [], 0,
            {MASTER: "Анна", SERVICE: "Стрижка", VISIT: _ago(-2), DEPOSIT: False},
        ),
        DealSpec(
            "Окрашивание AirTouch", "frolova", "beauty", 11500, 9, "anna", "marina", [S_WORK, S_CANCEL], 3,
            {MASTER: "Анна", SERVICE: "Окрашивание", VISIT: _ago(2), DEPOSIT: False},
            notes=[(1.0, "anna", "Клиентка перенесла запись на следующий месяц — пока отменили, вернёмся к ней 1-го числа.")],
        ),
        DealSpec(
            "Курс ухода за волосами (5 процедур)", "pavlova", "beauty", 15000, 14, "anna", "marina", [S_WORK], 6,
            {MASTER: "Анна", SERVICE: "Уход за волосами", VISIT: _ago(-1), DEPOSIT: True, "payment": "Карта"},
        ),
        DealSpec(
            "Окрашивание", "gerasimova", "beauty", 6900, 80, "anna", "marina", [S_WORK, S_DONE], 1,
            {MASTER: "Анна", SERVICE: "Окрашивание", VISIT: _ago(79), DEPOSIT: False, "payment": "Карта"},
        ),
        DealSpec(
            "Маникюр и педикюр", "smirnova", "beauty", 5400, 100, "olga", "marina", [S_WORK, S_DONE], 1,
            {MASTER: "Мария", SERVICE: "Маникюр", VISIT: _ago(99), DEPOSIT: False, "payment": "Наличные"},
        ),
        DealSpec(
            "Макияж", "kuznetsova", "beauty", 3500, 130, "olga", "marina", [S_WORK, S_DONE], 1,
            {MASTER: "Ольга", SERVICE: "Макияж", VISIT: _ago(129), DEPOSIT: False, "payment": "Карта"},
        ),
        DealSpec(
            "Корпоративный абонемент на маникюр (10 сотрудниц)", "romashka", None, 65000, 15, "marina", "marina",
            [S_WORK], 8, {"payment": "Безналичный расчёт"},
            notes=[(0.6, "marina", "Согласовали график: два мастера по вторникам и четвергам в офисе клиента.")],
        ),
        DealSpec(
            "Договор на обслуживание автопарка (3 авто)", "kofeynya", None, 90000, 8, "marina", "marina",
            [S_WORK, S_PAY], 6, {"payment": "Безналичный расчёт"},
            edits=[(0.6, {"amount": "84000"}, {}, "marina")],
            notes=[(0.6, "marina", "Дали скидку 7% при предоплате за квартал. Счёт выставлен, ждём оплату.")],
        ),
        DealSpec(
            "Подарочные сертификаты на 20 000", "zaharova", None, 20000, 26, "marina", "marina", [S_WORK, S_DONE], 4,
            {"payment": "Карта"},
        ),
        DealSpec(
            "Абонемент на шиномонтаж", "logistik", None, 22000, 110, "igor", "igor", [S_WORK, S_DONE], 5,
            {"payment": "Безналичный расчёт"},
        ),
        DealSpec(
            "Подарочные сертификаты на 10 000", "zaharova", None, 10000, 140, "marina", "marina", [S_WORK, S_DONE], 3,
            {"payment": "Карта"},
        ),
    ]


TASKS = [
    TaskSpec("Позвонить Никитину: согласовать замену опоры амортизатора", "denis", "marina", "high", "in_progress",
             0.25, 1, deal="Диагностика ходовой Toyota Camry",
             description="Озвучить итоговую цену 6 200 ₽ и срок — до конца дня."),
    TaskSpec("Заказать бампер и краску для Hyundai Solaris", "igor", "igor", "high", "todo", -1, 5,
             deal="Кузовной ремонт бампера Hyundai Solaris"),
    TaskSpec("Выставить счёт ООО «Логистик-Юг» за шиномонтаж", "igor", "igor", "normal", "done", -18, 20,
             deal="Сезонный шиномонтаж, 4 фургона"),
    TaskSpec("Подготовить предложение по обслуживанию автопарка", "marina", "marina", "normal", "in_progress", 2, 9,
             deal="Договор на обслуживание автопарка (3 авто)"),
    TaskSpec("Проверить оплату по договору с «Бодрое утро»", "marina", "alexey", "urgent", "todo", 1, 1,
             deal="Договор на обслуживание автопарка (3 авто)",
             description="Счёт выставлен неделю назад. Если оплаты нет — напомнить клиенту."),
    TaskSpec("Подготовить отчёт по продажам за месяц", "marina", "alexey", "normal", "todo", 5, 2),
    TaskSpec("Закупить расходники для курса ухода за волосами", "anna", "marina", "normal", "todo", 1, 3,
             deal="Курс ухода за волосами (5 процедур)"),
    TaskSpec("Подтвердить запись на свадебный макияж", "olga", "marina", "high", "todo", 0.1, 2,
             deal="Свадебный макияж и причёска"),
    TaskSpec("Предложить Белоусовой свободные окна на неделе", "olga", "olga", "low", "todo", 3, 0.2,
             deal="Стрижка"),
    TaskSpec("Согласовать скидку для корпоративных клиентов", "alexey", "alexey", "high", "in_progress", 4, 6),
    TaskSpec("Напомнить Морозовой о плановом ТО", "denis", "denis", "low", "done", -30, 38, client="morozova"),
    TaskSpec("Проверить остатки расходников салона", "olga", "marina", "normal", "todo", -2, 8),
    TaskSpec("Согласовать график мастеров на следующую неделю", "anna", "marina", "normal", "done", -3, 10),
    TaskSpec("Отправить сертификаты ИП Захаровой", "marina", "marina", "normal", "done", -22, 26,
             deal="Подарочные сертификаты на 20 000"),
    TaskSpec("Найти другого поставщика ремней ГРМ", "denis", "denis", "low", "cancelled", -20, 28,
             deal="Замена ремня ГРМ Skoda Octavia"),
]


class _Stamper:
    """Журнал и заметки создаются «сейчас»; этот помощник переписывает им время на нужное прошлое."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.last_event = db.scalar(select(func.max(ActivityEvent.id))) or 0
        self.last_note = db.scalar(select(func.max(Note.id))) or 0

    def stamp(self, when: datetime) -> None:
        self.db.execute(update(ActivityEvent).where(ActivityEvent.id > self.last_event).values(created_at=when))
        self.db.execute(update(Note).where(Note.id > self.last_note).values(created_at=when))
        self.db.commit()
        self.last_event = self.db.scalar(select(func.max(ActivityEvent.id))) or 0
        self.last_note = self.db.scalar(select(func.max(Note.id))) or 0


class _Clock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self._tick = 0

    def ago(self, days: float) -> datetime:
        """Момент «N дней назад» в рабочее время (8–14 UTC, т. е. 11–17 по Москве), но не позже «сейчас»."""
        base = self.now - timedelta(days=days)
        self._tick += 1
        moment = base.replace(hour=8 + (self._tick * 3) % 7, minute=(self._tick * 17) % 60, second=0)
        return min(moment, self.now - timedelta(minutes=1))

    def clamp(self, moment: datetime) -> datetime:
        return min(moment, self.now - timedelta(minutes=1))

    def workday(self, moment: datetime, after: datetime | None = None) -> datetime:
        """Переносит момент на рабочее время того же дня (11–17 по Москве), не раньше `after` + 20 минут."""
        self._tick += 1
        snapped = moment.replace(hour=8 + (self._tick * 5) % 6, minute=(self._tick * 23) % 60, second=0)
        if after is not None and snapped <= after:
            snapped = after + timedelta(minutes=20 + self._tick % 25)
        return self.clamp(snapped)


def reset_business_data(db: Session) -> None:
    """Удаляет пользователей, клиентов, сделки, задачи, поля, шаблоны, свои роли и общие настройки."""
    for model in (ActivityEvent, Note, Task, CustomValue, Deal, Client, CustomField, DealTemplate, User):
        db.execute(delete(model))
    db.execute(delete(Role).where(Role.is_system.is_(False)))
    db.commit()
    settings_service.reset(db)
    db.expire_all()


def setup_statuses(db: Session) -> dict[str, Status]:
    """Переименовывает четыре стандартных статуса под сервисный бизнес и добавляет «Ожидает оплаты»."""
    by_code = {s.code: s for s in status_service.list_statuses(db)}
    plan = [
        ("new", S_NEW, "#3B82F6", StatusKind.OPEN),
        ("in_progress", S_WORK, "#F59E0B", StatusKind.OPEN),
        ("won", S_DONE, "#10B981", StatusKind.WON),
        ("lost", S_CANCEL, "#EF4444", StatusKind.LOST),
    ]
    for code, name, color, kind in plan:
        status = by_code.get(code)
        if status is None:
            status_service.create_status(db, name=name, color=color, kind=kind)
        else:
            status_service.update_status(db, status, name=name, color=color, kind=kind, is_active=True)
    pay = next((s for s in status_service.list_statuses(db) if s.name == S_PAY), None)
    if pay is None:
        status_service.create_status(db, name=S_PAY, color="#8B5CF6", kind=StatusKind.OPEN)

    by_name = {s.name: s for s in status_service.list_statuses(db)}
    status_service.update_status(db, by_name[S_NEW], is_default=True)
    keep = {S_NEW, S_WORK, S_PAY, S_DONE, S_CANCEL}
    for status in list(status_service.list_statuses(db)):
        if status.name not in keep:
            try:
                status_service.delete_status(db, status)
            except ValidationFailed:
                pass
    by_name = {s.name: s for s in status_service.list_statuses(db)}
    order = [S_NEW, S_WORK, S_PAY, S_DONE, S_CANCEL]
    status_service.reorder_statuses(db, [by_name[n].id for n in order])
    return {s.name: s for s in status_service.list_statuses(db)}


def setup_users(db: Session, password: str) -> dict[str, User]:
    role = role_service.create_role(
        db, code=MASTER_ROLE_CODE, name="Мастер салона",
        description="Работает со своими записями и задачами; назначать и видеть чужое не может.",
        permissions=MASTER_PERMISSIONS,
    )
    roles = {r.code: r for r in db.scalars(select(Role))}
    roles[MASTER_ROLE_CODE] = role
    users: dict[str, User] = {}
    for key, (email, name, role_code) in USERS.items():
        users[key] = user_service.create_user(
            db, email=email, full_name=name, password=password, role_id=roles[role_code].id
        )
    return users


def setup_settings_and_fields(db: Session, with_vin: bool) -> dict[str, DealTemplate]:
    settings_service.update(db, {
        "app_name": COMPANY_NAME,
        "default_currency": "RUB",
        "deal_pl": "Заказы", "deal_sg": "Заказ", "deal_acc": "заказ",
    })
    auto = deal_template_service.create_template(
        db, name="Автосервис", description="Ремонт и обслуживание автомобилей: марка, пробег, вид работ."
    )
    beauty = deal_template_service.create_template(
        db, name="Салон красоты", description="Запись клиента к мастеру: мастер, услуга, дата посещения."
    )
    cf = custom_field_service.create_field
    cf(db, entity_type="client", label="Откуда узнал", field_type=FieldType.SELECT, code="source",
       options=["Рекомендация", "Сайт", "Соцсети", "Проходили мимо", "Повторное обращение"], show_in_list=True)
    cf(db, entity_type="client", label="День рождения", field_type=FieldType.DATE, code="birthday")
    cf(db, entity_type="client", label="Согласие на рассылку", field_type=FieldType.BOOLEAN, code="marketing")
    cf(db, entity_type="deal", label="Способ оплаты", field_type=FieldType.SELECT, code="payment",
       options=["Карта", "Наличные", "Безналичный расчёт"])
    cf(db, entity_type="deal", label="Марка и модель авто", field_type=FieldType.TEXT, code=CAR_BRAND,
       template_id=auto.id)
    cf(db, entity_type="deal", label="Пробег, км", field_type=FieldType.INTEGER, code=MILEAGE, template_id=auto.id)
    cf(db, entity_type="deal", label="Вид работ", field_type=FieldType.SELECT, code=WORK, template_id=auto.id,
       options=["Плановое ТО", "Диагностика", "Ремонт ходовой", "Кузовной ремонт", "Шиномонтаж"])
    if with_vin:
        cf(db, entity_type="deal", label="VIN", field_type=FieldType.TEXT, code="vin", template_id=auto.id)
        cf(db, entity_type="deal", label="Госномер", field_type=FieldType.TEXT, code="plate", template_id=auto.id)
    cf(db, entity_type="deal", label="Мастер", field_type=FieldType.SELECT, code=MASTER, template_id=beauty.id,
       options=["Анна", "Мария", "Ольга"])
    cf(db, entity_type="deal", label="Услуга", field_type=FieldType.SELECT, code=SERVICE, template_id=beauty.id,
       options=["Стрижка", "Окрашивание", "Уход за волосами", "Маникюр", "Педикюр", "Макияж"])
    cf(db, entity_type="deal", label="Дата посещения", field_type=FieldType.DATE, code=VISIT, template_id=beauty.id)
    cf(db, entity_type="deal", label="Депозит внесён", field_type=FieldType.BOOLEAN, code=DEPOSIT,
       template_id=beauty.id)
    return {"auto": auto, "beauty": beauty}


def create_clients(
    db: Session, users: dict[str, User], deals: list[DealSpec], clock: _Clock, stamper: _Stamper
) -> dict[str, Client]:
    first_deal_age: dict[str, int] = {}
    for spec in deals:
        first_deal_age[spec.client] = max(first_deal_age.get(spec.client, 0), spec.days_ago)
    out: dict[str, Client] = {}
    for spec in CLIENTS:
        age = first_deal_age.get(spec.key, 5) + 3
        created = clock.ago(age)
        data = {
            "name": spec.name, "type": spec.type, "phone": spec.phone, "email": spec.email,
            "address": spec.address, "owner_id": users[spec.owner].id,
        }
        client = client_service.create_client(db, data=data, custom=spec.custom, actor=users[spec.owner])
        stamper.stamp(created)
        db.execute(update(Client).where(Client.id == client.id).values(created_at=created, updated_at=created))
        db.commit()
        step = 1
        for author, text in spec.notes:
            client = db.get(Client, client.id)
            activity_service.add_note(db, client, author=users[author], body=text)
            stamper.stamp(clock.workday(created + timedelta(hours=step), after=created))
            step += 3
        for days_ago, change, who in spec.updates:
            client = db.get(Client, client.id)
            when = clock.ago(days_ago)
            client_service.update_client(
                db, client, data=change, custom={}, actor=users[who], partial=True
            )
            stamper.stamp(when)
        out[spec.key] = db.get(Client, client.id)
    return out


def create_deals(
    db: Session,
    specs: list[DealSpec],
    users: dict[str, User],
    clients: dict[str, Client],
    templates: dict[str, DealTemplate],
    statuses: dict[str, Status],
    clock: _Clock,
    stamper: _Stamper,
) -> dict[str, Deal]:
    out: dict[str, Deal] = {}
    for spec in specs:
        start = clock.ago(spec.days_ago)
        template = templates.get(spec.template) if spec.template else None
        data = {
            "title": spec.title,
            "client_id": clients[spec.client].id,
            "amount": str(spec.amount),
            "currency": "RUB",
            "deal_date": start.date().isoformat(),
            "template_id": template.id if template else None,
            "responsible_id": users[spec.responsible].id,
            "status_id": statuses[S_NEW].id,
        }
        deal = deal_service.create_deal(db, data=data, custom=spec.custom, actor=users[spec.creator])
        stamper.stamp(start)
        db.execute(update(Deal).where(Deal.id == deal.id).values(created_at=start, updated_at=start))
        db.commit()
        deal_id = deal.id

        steps: list[tuple[float, int, str, Any]] = []
        for index, name in enumerate(spec.path):
            steps.append(((index + 1) / (len(spec.path) + 1), 0, "status", name))
        for frac, change, custom, who in spec.edits:
            steps.append((frac, 1, "edit", (change, custom, who)))
        for frac, who, text in spec.notes:
            steps.append((frac, 2, "note", (who, text)))
        steps.sort(key=lambda s: (s[0], s[1]))

        last = start
        for index, (frac, _, kind, payload) in enumerate(steps):
            when = clock.workday(start + timedelta(days=spec.span * frac), after=last)
            when = max(when, last)
            last = when
            deal = db.get(Deal, deal_id)
            if kind == "status":
                deal_service.change_status(db, deal, statuses[payload].id, actor=users[spec.responsible])
            elif kind == "edit":
                change, custom, who = payload
                deal_service.update_deal(db, deal, data=change, custom=custom, actor=users[who], partial=True)
            else:
                who, text = payload
                activity_service.add_note(db, deal, author=users[who], body=text)
            stamper.stamp(when)
            if kind == "status" and statuses[payload].kind != StatusKind.OPEN:
                db.execute(update(Deal).where(Deal.id == deal_id).values(closed_at=when))
                db.commit()
        db.execute(update(Deal).where(Deal.id == deal_id).values(updated_at=last))
        db.commit()
        out[spec.title] = db.get(Deal, deal_id)
    return out


def create_tasks(
    db: Session,
    users: dict[str, User],
    clients: dict[str, Client],
    deals: dict[str, Deal],
    clock: _Clock,
) -> list[Task]:
    out: list[Task] = []
    for spec in TASKS:
        data: dict[str, Any] = {
            "title": spec.title,
            "description": spec.description,
            "priority": spec.priority,
            "due_at": clock.now + timedelta(days=spec.due_days),
            "assignee_id": users[spec.assignee].id,
        }
        if spec.deal:
            data["deal_id"] = deals[spec.deal].id
        if spec.client:
            data["client_id"] = clients[spec.client].id
        task = task_service.create_task(db, data=data, actor=users[spec.creator])
        created = clock.ago(spec.created_days_ago)
        values: dict[str, Any] = {"created_at": created, "updated_at": created}
        if spec.status != "todo":
            task = task_service.change_status(db, task, spec.status)
            done_at = clock.clamp(max(created, clock.now + timedelta(days=spec.due_days - 0.2)))
            values["updated_at"] = done_at
            if spec.status == "done":
                values["completed_at"] = done_at
        db.execute(update(Task).where(Task.id == task.id).values(**values))
        db.commit()
        out.append(task)
    return out


def run_scenario(db: Session, *, password: str, with_vin: bool = False) -> dict[str, Any]:
    """Полный сброс и наполнение. Возвращает сводку для вывода в консоль."""
    reset_business_data(db)
    statuses = setup_statuses(db)
    users = setup_users(db, password)
    templates = setup_settings_and_fields(db, with_vin)

    clock = _Clock()
    stamper = _Stamper(db)
    deal_specs = build_deals()
    clients = create_clients(db, users, deal_specs, clock, stamper)
    deals = create_deals(db, deal_specs, users, clients, templates, statuses, clock, stamper)
    tasks = create_tasks(db, users, clients, deals, clock)
    db.expire_all()
    return {
        "users": [(key, *USERS[key], USER_POSITIONS[key]) for key in USERS],
        "clients": len(clients), "deals": len(deals), "tasks": len(tasks),
        "password": password,
    }
