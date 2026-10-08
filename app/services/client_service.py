"""Клиенты: поиск/фильтры/пагинация, создание и изменение с кастомными полями."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.validators import normalize_email, normalize_phone, parse_optional_int
from app.models import Client, ClientType, CustomField, Deal, EntityType, User
from app.services import activity_service, custom_field_service, eav_service
from app.services.errors import ValidationFailed
from app.services.pagination import Page, clamp_page
from app.services.query_utils import contains, digits_only, phone_digits

SORTS = {
    "name": (func.lower(Client.name).asc(), Client.id.asc()),
    "-name": (func.lower(Client.name).desc(), Client.id.desc()),
    "created": (Client.created_at.asc(), Client.id.asc()),
    "-created": (Client.created_at.desc(), Client.id.desc()),
}
DEFAULT_SORT = "-created"


def get_client(db: Session, client_id: int) -> Client | None:
    return db.get(Client, client_id)


def active_fields(db: Session) -> list[CustomField]:
    return custom_field_service.list_fields(db, EntityType.CLIENT, only_active=True)


def deals_count(db: Session, client_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Deal).where(Deal.client_id == client_id)) or 0


# ------------------------------------------------------------------- список
def _search_condition(text: str):
    parts = [
        contains(Client.name, text),
        contains(Client.company_name, text),
        contains(Client.email, text),
        contains(Client.phone, text),
        contains(Client.address, text),
        eav_service.custom_text_search(Client, text),
    ]
    digits = digits_only(text)
    if len(digits) >= 3:
        parts.append(phone_digits(Client.phone).like(f"%{digits}%"))
    return or_(*parts)


def list_clients(
    db: Session,
    *,
    q: str | None = None,
    client_type: str | None = None,
    owner_id: int | None = None,
    custom_filters: Mapping[str, str] | None = None,
    fields: list[CustomField] | None = None,
    sort: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> Page[Client]:
    fields = fields if fields is not None else active_fields(db)
    conditions = []
    if q and q.strip():
        conditions.append(_search_condition(q.strip()))
    if client_type:
        try:
            conditions.append(Client.type == ClientType(client_type))
        except ValueError:
            pass
    if owner_id is not None:
        conditions.append(Client.owner_id == owner_id)
    if custom_filters:
        conditions.extend(eav_service.build_custom_conditions(Client, fields, custom_filters))

    total = db.scalar(select(func.count()).select_from(Client).where(*conditions)) or 0
    page = clamp_page(page, total, per_page)
    order = SORTS.get(sort or "", SORTS[DEFAULT_SORT])
    stmt = (
        select(Client)
        .where(*conditions)
        .order_by(*order)
        .limit(per_page)
        .offset((page - 1) * per_page)
        .options(selectinload(Client.owner))
    )
    return Page(items=list(db.scalars(stmt)), total=total, page=page, per_page=per_page)


def search_for_picker(db: Session, q: str, limit: int = 10) -> list[Client]:
    stmt = select(Client).order_by(func.lower(Client.name), Client.id).limit(limit)
    if q.strip():
        stmt = stmt.where(_search_condition(q.strip()))
    return list(db.scalars(stmt))


# ----------------------------------------------------------------- валидация
def _text(data: Mapping[str, Any], key: str, limit: int, errors: dict[str, str], out: dict[str, Any]) -> None:
    if key not in data:
        return
    value = str(data.get(key) or "").strip() or None
    if value and len(value) > limit:
        errors[key] = f"Слишком длинный текст (максимум {limit} символов)"
    else:
        out[key] = value


def _clean_base(
    db: Session, data: Mapping[str, Any], *, partial: bool, actor: User | None, creating: bool
) -> tuple[dict[str, Any], dict[str, str]]:
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}

    if "name" in data or not partial:
        name = str(data.get("name") or "").strip()
        if not name:
            errors["name"] = "Укажите имя или название"
        elif len(name) > 255:
            errors["name"] = "Слишком длинное имя (максимум 255 символов)"
        else:
            out["name"] = name

    if "type" in data or not partial:
        try:
            out["type"] = ClientType(str(data.get("type") or ClientType.PERSON.value))
        except ValueError:
            errors["type"] = "Неизвестный тип клиента"

    _text(data, "company_name", 255, errors, out)
    _text(data, "address", 500, errors, out)
    _text(data, "notes", 10000, errors, out)

    if "email" in data:
        value = str(data.get("email") or "").strip()
        try:
            out["email"] = normalize_email(value) if value else None
        except ValueError as e:
            errors["email"] = str(e)

    if "phone" in data:
        value = str(data.get("phone") or "").strip()
        try:
            out["phone"] = normalize_phone(value) if value else None
        except ValueError as e:
            errors["phone"] = str(e)

    if "owner_id" in data:
        try:
            owner_id = parse_optional_int(data.get("owner_id"))
        except ValueError:
            owner_id = None
            errors["owner_id"] = "Ответственный не найден"
        if owner_id is not None and "owner_id" not in errors:
            owner = db.get(User, owner_id)
            if owner is None or not owner.is_active:
                errors["owner_id"] = "Ответственный не найден"
        if "owner_id" not in errors:
            out["owner_id"] = owner_id
    elif creating and actor is not None:
        out["owner_id"] = actor.id

    return out, errors


# ---------------------------------------------------------------------- CRUD
def create_client(
    db: Session, *, data: Mapping[str, Any], custom: Mapping[str, Any], actor: User, commit: bool = True
) -> Client:
    """commit=False — только flush (массовый импорт сам решает, когда подтверждать транзакцию)."""
    fields = active_fields(db)
    base, errors = _clean_base(db, data, partial=False, actor=actor, creating=True)
    clean_custom, custom_errors = eav_service.coerce_values(fields, custom, strict_keys=True)
    errors.update(custom_errors)
    if errors:
        raise ValidationFailed(errors)

    client = Client(**base)
    db.add(client)
    eav_service.apply_values(client, fields, clean_custom)
    db.flush()  # нужен id клиента для записи в журнал
    activity_service.record(db, client, kind=activity_service.CREATED, actor=actor)
    db.commit() if commit else db.flush()
    return client


def update_client(
    db: Session,
    client: Client,
    *,
    data: Mapping[str, Any],
    custom: Mapping[str, Any],
    actor: User,
    partial: bool,
    commit: bool = True,
) -> Client:
    """partial=True (PATCH): меняются только присланные ключи; False (веб-форма): все поля формы."""
    fields = active_fields(db)
    base, errors = _clean_base(db, data, partial=partial, actor=actor, creating=False)
    clean_custom, custom_errors = eav_service.coerce_values(
        fields, custom, partial=partial, strict_keys=partial
    )
    errors.update(custom_errors)
    if errors:
        raise ValidationFailed(errors)

    before = activity_service.snapshot(db, client, fields)
    for key, value in base.items():
        setattr(client, key, value)
    eav_service.apply_values(client, fields, clean_custom)
    changes = activity_service.diff(before, activity_service.snapshot(db, client, fields))
    activity_service.record(db, client, kind=activity_service.UPDATED, actor=actor, changes=changes)
    db.commit() if commit else db.flush()
    db.refresh(client)
    return client


def delete_client(db: Session, client: Client) -> int:
    """Удаляет клиента вместе со сделками и значениями полей. Возвращает число удалённых сделок."""
    count = deals_count(db, client.id)
    db.delete(client)
    db.commit()
    return count


def list_client_deals(db: Session, client_id: int, viewer: User | None = None) -> list[Deal]:
    """Сделки клиента; сотрудник без права deals:read_all видит только свои."""
    from app.services import deal_service  # локально: deal_service сам импортирует client-модели

    stmt = (
        select(Deal)
        .where(Deal.client_id == client_id)
        .order_by(Deal.deal_date.desc(), Deal.id.desc())
        .options(selectinload(Deal.responsible))
    )
    scope = deal_service.visibility(viewer)
    if scope is not None:
        stmt = stmt.where(scope)
    return list(db.scalars(stmt))
