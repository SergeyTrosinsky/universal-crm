"""Главная страница: сводные показатели. Каждый блок строится только если у пользователя
есть право на соответствующий раздел. Суммы всегда группируются по валютам."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.permissions import CLIENTS_READ, DEALS_READ, TASKS_READ
from app.core.timezone import local_day_bounds_utc, to_local, today_local
from app.models import (
    Client, CustomField, CustomValue, Deal, EntityType, FieldType, StatusKind, Task, User,
)
from app.services import deal_service, status_service, task_service

PERIODS: dict[str, tuple[str, int | None]] = {
    "7": ("7 дней", 7),
    "30": ("30 дней", 30),
    "90": ("90 дней", 90),
    "365": ("Год", 365),
    "all": ("Всё время", None),
}
DEFAULT_PERIOD = "30"
MONTH_NAMES = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MAX_BREAKDOWN_FIELDS = 3
MAX_BREAKDOWN_VALUES = 8


def _money(rows: dict[str, Decimal]) -> list[dict[str, Any]]:
    return [{"currency": c, "amount": a} for c, a in sorted(rows.items())]


def period_start(period: str) -> datetime | None:
    days = PERIODS.get(period, PERIODS[DEFAULT_PERIOD])[1]
    if days is None:
        return None
    start_day = today_local() - timedelta(days=days - 1)
    return local_day_bounds_utc(start_day)[0]


def _month_keys(count: int = 6) -> list[tuple[int, int]]:
    today = today_local()
    year, month = today.year, today.month
    keys = []
    for _ in range(count):
        keys.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(keys))


def _clients_block(db: Session, since: datetime | None) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(Client)) or 0
    new = total
    if since is not None:
        new = db.scalar(select(func.count()).select_from(Client).where(Client.created_at >= since)) or 0
    return {"total": total, "new": new}


def _deal_scope(viewer: User) -> list:
    """Условия видимости сделок: сотрудник без deals:read_all считает только свои."""
    cond = deal_service.visibility(viewer)
    return [] if cond is None else [cond]


def _deals_block(db: Session, since: datetime | None, scope: list, personal: bool) -> dict[str, Any]:
    statuses = status_service.list_statuses(db)
    kind_by_status = {s.id: s.kind for s in statuses}

    per_status: dict[int, dict[str, Decimal]] = defaultdict(dict)
    counts: dict[int, int] = defaultdict(int)
    for status_id, currency, cnt, total in db.execute(
        select(Deal.status_id, Deal.currency, func.count(), func.sum(Deal.amount))
        .where(*scope)
        .group_by(Deal.status_id, Deal.currency)
    ):
        counts[status_id] += cnt
        per_status[status_id][currency] = Decimal(str(total or 0))

    open_amounts: dict[str, Decimal] = defaultdict(Decimal)
    open_count = 0
    by_status = []
    for s in statuses:
        if not s.is_active and not counts.get(s.id):
            continue
        by_status.append(
            {
                "id": s.id, "name": s.name, "color": s.color, "kind": s.kind.value,
                "count": counts.get(s.id, 0), "amounts": _money(per_status.get(s.id, {})),
            }
        )
        if s.kind == StatusKind.OPEN:
            open_count += counts.get(s.id, 0)
            for currency, amount in per_status.get(s.id, {}).items():
                open_amounts[currency] += amount

    def closed(kind: StatusKind):
        conds = [Deal.status_id.in_([sid for sid, k in kind_by_status.items() if k == kind]), *scope]
        if since is not None:
            conds.append(Deal.closed_at >= since)
        amounts: dict[str, Decimal] = {}
        count = 0
        for currency, cnt, total in db.execute(
            select(Deal.currency, func.count(), func.sum(Deal.amount)).where(*conds).group_by(Deal.currency)
        ):
            count += cnt
            amounts[currency] = Decimal(str(total or 0))
        return count, amounts

    won_count, won_amounts = closed(StatusKind.WON)
    lost_count, lost_amounts = closed(StatusKind.LOST)
    decided = won_count + lost_count
    conversion = round(won_count * 100 / decided, 1) if decided else None

    created = db.scalar(
        select(func.count()).select_from(Deal).where(*scope, *([Deal.created_at >= since] if since else []))
    ) or 0

    return {
        "open_count": open_count,
        "open_amounts": _money(open_amounts),
        "won_count": won_count,
        "won_amounts": _money(won_amounts),
        "lost_count": lost_count,
        "lost_amounts": _money(lost_amounts),
        "created": created,
        "conversion": conversion,
        "by_status": by_status,
        "monthly": _monthly(db, kind_by_status, scope),
        "by_responsible": [] if personal else _by_responsible(db, kind_by_status, since),
    }


def _monthly(db: Session, kind_by_status: dict[int, StatusKind], scope: list) -> list[dict[str, Any]]:
    keys = _month_keys(6)
    first_year, first_month = keys[0]
    first_day = datetime(first_year, first_month, 1).date()
    created: dict[tuple[int, int], int] = defaultdict(int)
    for (deal_date,) in db.execute(select(Deal.deal_date).where(Deal.deal_date >= first_day, *scope)):
        created[(deal_date.year, deal_date.month)] += 1

    won_ids = [sid for sid, kind in kind_by_status.items() if kind == StatusKind.WON]
    won: dict[tuple[int, int], int] = defaultdict(int)
    if won_ids:
        start_utc = local_day_bounds_utc(first_day)[0]
        for (closed_at,) in db.execute(
            select(Deal.closed_at).where(Deal.status_id.in_(won_ids), Deal.closed_at >= start_utc, *scope)
        ):
            local = to_local(closed_at)
            won[(local.year, local.month)] += 1

    return [
        {"month": f"{y}-{m:02d}", "label": f"{MONTH_NAMES[m - 1]} {str(y)[2:]}",
         "created": created.get((y, m), 0), "won": won.get((y, m), 0)}
        for y, m in keys
    ]


def _by_responsible(db: Session, kind_by_status: dict[int, StatusKind], since: datetime | None) -> list[dict]:
    open_ids = [sid for sid, k in kind_by_status.items() if k == StatusKind.OPEN]
    won_ids = [sid for sid, k in kind_by_status.items() if k == StatusKind.WON]
    rows: dict[int | None, dict[str, Any]] = {}

    def row(uid):
        return rows.setdefault(uid, {"user_id": uid, "open": 0, "won": 0, "won_amounts": {}})

    if open_ids:
        for uid, cnt in db.execute(
            select(Deal.responsible_id, func.count()).where(Deal.status_id.in_(open_ids)).group_by(
                Deal.responsible_id
            )
        ):
            row(uid)["open"] = cnt
    if won_ids:
        conds = [Deal.status_id.in_(won_ids)]
        if since is not None:
            conds.append(Deal.closed_at >= since)
        for uid, currency, cnt, total in db.execute(
            select(Deal.responsible_id, Deal.currency, func.count(), func.sum(Deal.amount))
            .where(*conds).group_by(Deal.responsible_id, Deal.currency)
        ):
            r = row(uid)
            r["won"] += cnt
            r["won_amounts"][currency] = Decimal(str(total or 0))

    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_([k for k in rows if k]))) }
    out = []
    for uid, r in rows.items():
        out.append(
            {
                "user_id": uid, "name": names.get(uid, "Не назначен") if uid else "Не назначен",
                "open": r["open"], "won": r["won"], "won_amounts": _money(r["won_amounts"]),
            }
        )
    out.sort(key=lambda r: (-r["won"], -r["open"], r["name"]))
    return out[:10]


def _tasks_block(db: Session, viewer: User) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    start, end = local_day_bounds_utc(today_local())
    mine = [Task.assignee_id == viewer.id, Task.status.in_(task_service.OPEN_STATUSES)]

    def count(*extra) -> int:
        return db.scalar(select(func.count()).select_from(Task).where(*mine, *extra)) or 0

    block: dict[str, Any] = {
        "open": count(),
        "overdue": count(Task.due_at.is_not(None), Task.due_at < now),
        "today": count(Task.due_at >= start, Task.due_at < end),
        "team_overdue": None,
    }
    if task_service.can_see_all(viewer):
        block["team_overdue"] = db.scalar(
            select(func.count()).select_from(Task).where(
                Task.status.in_(task_service.OPEN_STATUSES), Task.due_at.is_not(None), Task.due_at < now
            )
        ) or 0
    return block


def _breakdowns(db: Session, *, deals: bool, clients: bool, scope: list | None = None) -> list[dict[str, Any]]:
    """Распределение по значениям пользовательских полей-списков — работает для любой отрасли
    («Мастер», «Услуга», «Марка авто»…) без правок кода."""
    out: list[dict[str, Any]] = []
    for entity, allowed, owner_col in (
        (EntityType.DEAL, deals, CustomValue.deal_id),
        (EntityType.CLIENT, clients, CustomValue.client_id),
    ):
        if not allowed:
            continue
        fields = list(
            db.scalars(
                select(CustomField)
                .where(
                    CustomField.entity_type == entity,
                    CustomField.field_type == FieldType.SELECT,
                    CustomField.is_active.is_(True),
                )
                .order_by(CustomField.sort_order, CustomField.id)
                .limit(MAX_BREAKDOWN_FIELDS)
            )
        )
        for f in fields:
            rows = db.execute(
                select(CustomValue.value_text, func.count())
                .where(
                    CustomValue.field_id == f.id, owner_col.is_not(None), CustomValue.value_text.is_not(None),
                    *([CustomValue.deal_id.in_(select(Deal.id).where(*scope))] if scope and entity == EntityType.DEAL else []),
                )
                .group_by(CustomValue.value_text)
                .order_by(func.count().desc(), CustomValue.value_text)
                .limit(MAX_BREAKDOWN_VALUES)
            ).all()
            if rows:
                out.append(
                    {
                        "entity": entity.value, "field_id": f.id, "field": f.label,
                        "items": [{"value": v, "count": c} for v, c in rows],
                    }
                )
    return out


def build_dashboard(db: Session, viewer: User, period: str | None = None) -> dict[str, Any]:
    period = period if period in PERIODS else DEFAULT_PERIOD
    since = period_start(period)
    can_deals, can_clients, can_tasks = viewer.can(DEALS_READ), viewer.can(CLIENTS_READ), viewer.can(TASKS_READ)
    scope = _deal_scope(viewer)
    personal = bool(scope)

    data: dict[str, Any] = {
        "period": period,
        "period_label": PERIODS[period][0],
        "since": since,
        "clients": _clients_block(db, since) if can_clients else None,
        "personal": personal and can_deals,
        "deals": _deals_block(db, since, scope, personal) if can_deals else None,
        "tasks": _tasks_block(db, viewer) if can_tasks else None,
        "breakdowns": _breakdowns(db, deals=can_deals, clients=can_clients, scope=scope),
    }
    return data


def recent_items(db: Session, viewer: User) -> dict[str, Any]:
    """Живые объекты для HTML-страницы (в API не отдаются)."""
    out: dict[str, Any] = {"deals": [], "clients": [], "tasks": []}
    if viewer.can(DEALS_READ):
        out["deals"] = list(
            db.scalars(
                select(Deal).where(*_deal_scope(viewer)).order_by(Deal.created_at.desc(), Deal.id.desc()).limit(6)
                .options(selectinload(Deal.client))
            )
        )
    if viewer.can(CLIENTS_READ):
        out["clients"] = list(db.scalars(select(Client).order_by(Client.created_at.desc(), Client.id.desc()).limit(6)))
    if viewer.can(TASKS_READ):
        out["tasks"] = list(
            db.scalars(
                select(Task)
                .where(Task.assignee_id == viewer.id, Task.status.in_(task_service.OPEN_STATUSES))
                .order_by(*task_service.SORTS["due"]).limit(6)
                .options(selectinload(Task.client), selectinload(Task.deal))
            )
        )
    return out
