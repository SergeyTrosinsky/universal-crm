"""Сделки: список с фильтрами и итогами, создание/изменение, смена статуса."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.permissions import DEALS_ASSIGN, DEALS_READ_ALL
from app.core.timezone import today_local
from app.core.validators import parse_date, parse_money, parse_optional_int
from app.models import Client, CustomField, Deal, DealTemplate, EntityType, Status, StatusKind, User
from app.services import (
    activity_service, custom_field_service, deal_template_service, eav_service, settings_service, status_service,
)
from app.services.errors import ValidationFailed
from app.services.pagination import Page, clamp_page
from app.services.query_utils import contains

SORTS = {
    "date": (Deal.deal_date.asc(), Deal.id.asc()),
    "-date": (Deal.deal_date.desc(), Deal.id.desc()),
    "amount": (Deal.amount.asc(), Deal.id.asc()),
    "-amount": (Deal.amount.desc(), Deal.id.desc()),
    "title": (func.lower(Deal.title).asc(), Deal.id.asc()),
    "created": (Deal.created_at.asc(), Deal.id.asc()),
    "-created": (Deal.created_at.desc(), Deal.id.desc()),
}
DEFAULT_SORT = "-date"

TEMPLATE_GROUP_ORDER = (
    Deal.template_id.is_(None).desc(),
    select(func.coalesce(DealTemplate.sort_order, 0)).where(DealTemplate.id == Deal.template_id).correlate(Deal).scalar_subquery(),
    Deal.template_id.asc(),
)


def can_see_all(viewer: User) -> bool:
    return viewer.can(DEALS_READ_ALL)


def visibility(viewer: User | None):
    """SQL-условие «какие сделки виден пользователю». None — без ограничений.
    Без права deals:read_all сотрудник видит только сделки, где он ответственный."""
    if viewer is None or can_see_all(viewer):
        return None
    return Deal.responsible_id == viewer.id


def has_access(viewer: User, deal: Deal) -> bool:
    return can_see_all(viewer) or deal.responsible_id == viewer.id


def get_deal(db: Session, deal_id: int, viewer: User | None = None) -> Deal | None:
    """Со viewer чужая сделка недоступна (как будто её нет)."""
    deal = db.get(Deal, deal_id)
    if deal is not None and viewer is not None and not has_access(viewer, deal):
        return None
    return deal


def active_fields(db: Session) -> list[CustomField]:
    return custom_field_service.list_fields(db, EntityType.DEAL, only_active=True)


def search_for_picker(db: Session, q: str, limit: int = 10, viewer: User | None = None) -> list[Deal]:
    stmt = (
        select(Deal).order_by(Deal.deal_date.desc(), Deal.id.desc()).limit(limit)
        .options(selectinload(Deal.client))
    )
    scope = visibility(viewer)
    if scope is not None:
        stmt = stmt.where(scope)
    if q.strip():
        text = q.strip()
        stmt = stmt.where(
            or_(contains(Deal.title, text), Deal.client_id.in_(select(Client.id).where(contains(Client.name, text))))
        )
    return list(db.scalars(stmt))


def _conditions(
    *,
    q: str | None,
    status_id: int | None,
    kind: str | None,
    client_id: int | None,
    responsible_id: int | None,
    date_from: date | None,
    date_to: date | None,
    amount_min: Decimal | None,
    amount_max: Decimal | None,
    fields: list[CustomField],
    custom_filters: Mapping[str, str] | None,
    template: str | None = None,
) -> list:
    conds: list = []
    if template:
        if template == "none":
            conds.append(Deal.template_id.is_(None))
        else:
            tid = _opt_int(template)
            if tid is not None:
                conds.append(Deal.template_id == tid)
    if q and q.strip():
        text = q.strip()
        conds.append(
            or_(
                contains(Deal.title, text),
                contains(Deal.description, text),
                Deal.client_id.in_(select(Client.id).where(contains(Client.name, text))),
                eav_service.custom_text_search(Deal, text),
            )
        )
    if status_id is not None:
        conds.append(Deal.status_id == status_id)
    if kind:
        try:
            conds.append(Deal.status_id.in_(select(Status.id).where(Status.kind == StatusKind(kind))))
        except ValueError:
            pass
    if client_id is not None:
        conds.append(Deal.client_id == client_id)
    if responsible_id is not None:
        conds.append(Deal.responsible_id == responsible_id)
    if date_from:
        conds.append(Deal.deal_date >= date_from)
    if date_to:
        conds.append(Deal.deal_date <= date_to)
    if amount_min is not None:
        conds.append(Deal.amount >= amount_min)
    if amount_max is not None:
        conds.append(Deal.amount <= amount_max)
    if custom_filters:
        conds.extend(eav_service.build_custom_conditions(Deal, fields, custom_filters))
    return conds


def _opt_date(value: str | None) -> date | None:
    try:
        return parse_date(value) if value and value.strip() else None
    except ValueError:
        return None


def _opt_money(value: str | None) -> Decimal | None:
    try:
        return parse_money(value) if value and value.strip() else None
    except ValueError:
        return None


def _opt_int(value: Any) -> int | None:
    try:
        return parse_optional_int(value)
    except ValueError:
        return None


def list_deals(
    db: Session,
    *,
    q: str | None = None,
    status_id: Any = None,
    kind: str | None = None,
    client_id: Any = None,
    responsible_id: Any = None,
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: str | None = None,
    amount_max: str | None = None,
    custom_filters: Mapping[str, str] | None = None,
    fields: list[CustomField] | None = None,
    template: str | None = None,
    sort: str | None = None,
    page: int = 1,
    per_page: int = 20,
    viewer: User | None = None,
) -> Page[Deal]:
    """Параметры фильтров — «сырые» (строки из URL); некорректные значения игнорируются.
    В Page.extra['totals'] — суммы по валютам для всей выборки (не только текущей страницы)."""
    fields = fields if fields is not None else active_fields(db)
    conds = _conditions(
        q=q,
        status_id=_opt_int(status_id),
        kind=kind,
        client_id=_opt_int(client_id),
        responsible_id=_opt_int(responsible_id),
        date_from=_opt_date(date_from),
        date_to=_opt_date(date_to),
        amount_min=_opt_money(amount_min),
        amount_max=_opt_money(amount_max),
        fields=fields,
        custom_filters=custom_filters,
        template=template,
    )
    scope = visibility(viewer)
    if scope is not None:
        conds.append(scope)
    total = db.scalar(select(func.count()).select_from(Deal).where(*conds)) or 0
    page = clamp_page(page, total, per_page)
    stmt = (
        select(Deal)
        .where(*conds)
        .order_by(*TEMPLATE_GROUP_ORDER, *SORTS.get(sort or "", SORTS[DEFAULT_SORT]))
        .limit(per_page)
        .offset((page - 1) * per_page)
        .options(selectinload(Deal.client), selectinload(Deal.responsible))
    )
    totals_rows = db.execute(
        select(Deal.currency, func.sum(Deal.amount)).where(*conds).group_by(Deal.currency).order_by(Deal.currency)
    ).all()
    result = Page(items=list(db.scalars(stmt)), total=total, page=page, per_page=per_page)
    result.extra["totals"] = [(currency, Decimal(str(amount or 0))) for currency, amount in totals_rows]
    return result


BOARD_COLUMN_LIMIT = 50


def board(
    db: Session,
    *,
    q: str | None = None,
    responsible_id: Any = None,
    client_id: Any = None,
    per_column: int = BOARD_COLUMN_LIMIT,
    viewer: User | None = None,
) -> list[dict[str, Any]]:
    """Канбан: колонка на каждый активный статус (и на неактивный, если в нём есть сделки).
    В колонке — последние изменённые сделки (до per_column), точное число и суммы по валютам."""
    conds = _conditions(
        q=q, status_id=None, kind=None, client_id=_opt_int(client_id), responsible_id=_opt_int(responsible_id),
        date_from=None, date_to=None, amount_min=None, amount_max=None, fields=[], custom_filters=None,
    )
    scope = visibility(viewer)
    if scope is not None:
        conds.append(scope)
    counts: dict[int, int] = {}
    totals: dict[int, dict[str, Decimal]] = {}
    for status_id, currency, cnt, total in db.execute(
        select(Deal.status_id, Deal.currency, func.count(), func.sum(Deal.amount))
        .where(*conds).group_by(Deal.status_id, Deal.currency)
    ):
        counts[status_id] = counts.get(status_id, 0) + cnt
        totals.setdefault(status_id, {})[currency] = Decimal(str(total or 0))

    columns = []
    for status in status_service.list_statuses(db):
        if not status.is_active and not counts.get(status.id):
            continue
        deals = list(
            db.scalars(
                select(Deal)
                .where(*conds, Deal.status_id == status.id)
                .order_by(Deal.updated_at.desc(), Deal.id.desc())
                .limit(per_column)
                .options(selectinload(Deal.client), selectinload(Deal.responsible))
            )
        )
        count = counts.get(status.id, 0)
        columns.append(
            {
                "status": status,
                "deals": deals,
                "count": count,
                "hidden": max(0, count - len(deals)),
                "totals": sorted(totals.get(status.id, {}).items()),
            }
        )
    return columns


def _apply_status(deal: Deal, status: Status) -> None:
    deal.status = status
    deal.status_id = status.id
    if status.kind == StatusKind.OPEN:
        deal.closed_at = None
    elif deal.closed_at is None:
        deal.closed_at = datetime.now(timezone.utc)


def _clean_base(
    db: Session,
    data: Mapping[str, Any],
    *,
    partial: bool,
    actor: User | None,
    creating: bool,
    current: Deal | None = None,
) -> tuple[dict[str, Any], Status | None, dict[str, str]]:
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    new_status: Status | None = None

    if "title" in data or not partial:
        title = str(data.get("title") or "").strip()
        if not title:
            errors["title"] = "Укажите название сделки"
        elif len(title) > 255:
            errors["title"] = "Слишком длинное название (максимум 255 символов)"
        else:
            out["title"] = title

    if "description" in data:
        text = str(data.get("description") or "").strip() or None
        if text and len(text) > 10000:
            errors["description"] = "Слишком длинное описание"
        else:
            out["description"] = text

    if "amount" in data or creating:
        raw = data.get("amount")
        try:
            blank = raw is None or (isinstance(raw, str) and not raw.strip())
            out["amount"] = Decimal("0.00") if blank else parse_money(raw)
        except ValueError as e:
            errors["amount"] = str(e)

    if "currency" in data or creating:
        currency = str(data.get("currency") or settings_service.default_currency(db)).strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            errors["currency"] = "Код валюты — три латинские буквы"
        else:
            out["currency"] = currency

    if "deal_date" in data or creating:
        raw = data.get("deal_date")
        try:
            blank = raw is None or (isinstance(raw, str) and not raw.strip())
            out["deal_date"] = today_local() if blank else parse_date(raw)
        except ValueError as e:
            errors["deal_date"] = str(e)

    if "template_id" in data or creating:
        template_id, template_error = deal_template_service.validate_for_deal(
            db, data.get("template_id"), current_id=current.template_id if current is not None else None
        )
        if template_error:
            errors["template_id"] = template_error
        else:
            out["template_id"] = template_id

    if "status_id" in data and not _is_blank(data.get("status_id")):
        try:
            status = status_service.get_status(db, parse_optional_int(data.get("status_id")) or 0)
        except ValueError:
            status = None
        keeps_current = current is not None and status is not None and status.id == current.status_id
        if status is None or (not status.is_active and not keeps_current):
            errors["status_id"] = "Выберите статус из списка"
        else:
            new_status = status
    elif creating:
        default = status_service.get_default_status(db)
        if default is None:
            errors["status_id"] = "В системе нет активных статусов — создайте их в настройках"
        else:
            new_status = default

    if "client_id" in data or creating:
        try:
            client_id = parse_optional_int(data.get("client_id"))
        except ValueError:
            client_id = None
        if client_id is None or db.get(Client, client_id) is None:
            errors["client_id"] = "Выберите клиента"
        else:
            out["client_id"] = client_id

    if actor is not None and not actor.can(DEALS_ASSIGN):
        allowed = {actor.id} | ({current.responsible_id} if current is not None and current.responsible_id else set())
        if "responsible_id" in data and not _is_blank(data.get("responsible_id")):
            try:
                requested = parse_optional_int(data.get("responsible_id"))
            except ValueError:
                requested = -1
            if requested not in allowed:
                errors["responsible_id"] = "Нет права назначать ответственного"
        if creating:
            out["responsible_id"] = actor.id
    elif "responsible_id" in data:
        try:
            responsible_id = parse_optional_int(data.get("responsible_id"))
        except ValueError:
            responsible_id, errors["responsible_id"] = None, "Ответственный не найден"
        if responsible_id is not None and "responsible_id" not in errors:
            user = db.get(User, responsible_id)
            if user is None or not user.is_active:
                errors["responsible_id"] = "Ответственный не найден"
        if "responsible_id" not in errors:
            out["responsible_id"] = responsible_id
    elif creating and actor is not None:
        out["responsible_id"] = actor.id

    return out, new_status, errors


def check_new(db: Session, data: Mapping[str, Any], actor: User) -> tuple[dict[str, Any], dict[str, str]]:
    """Проверяет основные поля новой сделки, ничего не записывая. Возвращает (очищенные значения, ошибки)."""
    base, _status, errors = _clean_base(db, data, partial=False, actor=actor, creating=True)
    return base, errors


def find_duplicate(db: Session, base: Mapping[str, Any]) -> Deal | None:
    """Уже существующая сделка с теми же клиентом, названием, суммой, валютой и датой (из check_new)."""
    needed = ("client_id", "title", "amount", "currency", "deal_date")
    if any(base.get(k) is None for k in needed):
        return None
    stmt = (
        select(Deal)
        .where(
            Deal.client_id == base["client_id"],
            func.lower(Deal.title) == base["title"].lower(),
            Deal.amount == base["amount"],
            Deal.currency == base["currency"],
            Deal.deal_date == base["deal_date"],
        )
        .limit(1)
    )
    return db.scalars(stmt).first()


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def create_deal(
    db: Session, *, data: Mapping[str, Any], custom: Mapping[str, Any], actor: User, commit: bool = True
) -> Deal:
    base, status, errors = _clean_base(db, data, partial=False, actor=actor, creating=True)
    fields = deal_template_service.fields_for_template(active_fields(db), base.get("template_id"))
    clean_custom, custom_errors = eav_service.coerce_values(fields, custom, strict_keys=True)
    errors.update(custom_errors)
    if errors:
        raise ValidationFailed(errors)

    deal = Deal(**base)
    _apply_status(deal, status)
    db.add(deal)
    eav_service.apply_values(deal, fields, clean_custom)
    db.flush()
    activity_service.record(db, deal, kind=activity_service.CREATED, actor=actor)
    db.commit() if commit else db.flush()
    return deal


def update_deal(
    db: Session,
    deal: Deal,
    *,
    data: Mapping[str, Any],
    custom: Mapping[str, Any],
    actor: User,
    partial: bool,
    commit: bool = True,
) -> Deal:
    base, status, errors = _clean_base(
        db, data, partial=partial, actor=actor, creating=False, current=deal
    )
    fields = deal_template_service.fields_for_template(
        active_fields(db), base.get("template_id", deal.template_id)
    )
    clean_custom, custom_errors = eav_service.coerce_values(
        fields, custom, partial=partial, strict_keys=partial
    )
    errors.update(custom_errors)
    if errors:
        raise ValidationFailed(errors)

    before = activity_service.snapshot(db, deal, fields)
    for key, value in base.items():
        setattr(deal, key, value)
    if status is not None and status.id != deal.status_id:
        _apply_status(deal, status)
    eav_service.apply_values(deal, fields, clean_custom)
    changes = activity_service.diff(before, activity_service.snapshot(db, deal, fields))
    activity_service.record(db, deal, kind=activity_service.UPDATED, actor=actor, changes=changes)
    db.commit() if commit else db.flush()
    db.refresh(deal)
    return deal


def change_status(db: Session, deal: Deal, status_id: Any, actor: User | None = None) -> Deal:
    status = status_service.get_status(db, _opt_int(status_id) or 0)
    if status is None or (not status.is_active and status.id != deal.status_id):
        raise ValidationFailed({"status_id": "Выберите статус из списка"})
    if status.id != deal.status_id:
        before = activity_service.snapshot(db, deal, [])
        _apply_status(deal, status)
        changes = activity_service.diff(before, activity_service.snapshot(db, deal, []))
        activity_service.record(db, deal, kind=activity_service.UPDATED, actor=actor, changes=changes)
        db.commit()
        db.refresh(deal)
    return deal


def delete_deal(db: Session, deal: Deal) -> None:
    db.delete(deal)
    db.commit()
