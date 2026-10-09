"""Динамические статусы сделок: название, цвет, порядок, тип (kind), основной статус."""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Deal, Status, StatusEntity, StatusKind
from app.services.errors import ValidationFailed
from app.services.slug import slugify

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
EDITABLE = {"name", "color", "kind", "is_default", "is_active"}
ENTITY = StatusEntity.DEAL


def list_statuses(db: Session, *, only_active: bool = False) -> list[Status]:
    stmt = select(Status).where(Status.entity_type == ENTITY)
    if only_active:
        stmt = stmt.where(Status.is_active.is_(True))
    return list(db.scalars(stmt.order_by(Status.sort_order, Status.id)))


def get_status(db: Session, status_id: int) -> Status | None:
    status = db.get(Status, status_id)
    return status if status and status.entity_type == ENTITY else None


def get_default_status(db: Session) -> Status | None:
    active = list_statuses(db, only_active=True)
    return next((s for s in active if s.is_default), active[0] if active else None)


def deal_counts(db: Session) -> dict[int, int]:
    rows = db.execute(select(Deal.status_id, func.count()).group_by(Deal.status_id)).all()
    return {status_id: count for status_id, count in rows}


def _ensure_default(db: Session) -> None:
    """Инвариант: среди активных статусов ровно один основной."""
    active = list_statuses(db, only_active=True)
    for s in list_statuses(db):
        if not s.is_active:
            s.is_default = False
    defaults = [s for s in active if s.is_default]
    if active and not defaults:
        active[0].is_default = True
    for extra in defaults[1:]:
        extra.is_default = False


def _clean_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValidationFailed({"name": "Укажите название"})
    if len(name) > 100:
        raise ValidationFailed({"name": "Название слишком длинное (максимум 100 символов)"})
    return name


def _clean_color(value: object) -> str:
    color = str(value or "").strip()
    if not COLOR_RE.match(color):
        raise ValidationFailed({"color": "Цвет в формате #RRGGBB"})
    return color.upper()


def _clean_kind(value: object) -> StatusKind:
    try:
        return StatusKind(str(value))
    except ValueError:
        raise ValidationFailed({"kind": "Выберите тип статуса"}) from None


def _unique_code(db: Session, base: str) -> str:
    taken = set(db.scalars(select(Status.code).where(Status.entity_type == ENTITY)))
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def create_status(
    db: Session,
    *,
    name: str,
    color: str = "#6B7280",
    kind: str | StatusKind = StatusKind.OPEN,
    is_default: bool = False,
    is_active: bool = True,
) -> Status:
    errors: dict[str, str] = {}
    cleaned: dict = {}
    for key, cleaner, value in (("name", _clean_name, name), ("color", _clean_color, color), ("kind", _clean_kind, kind)):
        try:
            cleaned[key] = cleaner(value)
        except ValidationFailed as e:
            errors.update(e.errors)
    if errors:
        raise ValidationFailed(errors)
    if is_default and not is_active:
        raise ValidationFailed({"is_default": "Неактивный статус нельзя сделать основным"})

    last = db.scalar(select(func.max(Status.sort_order)).where(Status.entity_type == ENTITY))
    status = Status(
        entity_type=ENTITY,
        code=_unique_code(db, slugify(cleaned["name"], fallback="status", max_length=60)),
        name=cleaned["name"],
        color=cleaned["color"],
        kind=cleaned["kind"],
        sort_order=(last if last is not None else -1) + 1,
        is_default=bool(is_default),
        is_active=bool(is_active),
    )
    db.add(status)
    db.flush()
    if status.is_default:
        for other in list_statuses(db):
            if other.id != status.id:
                other.is_default = False
    _ensure_default(db)
    db.commit()
    db.refresh(status)
    return status


def update_status(db: Session, status: Status, **changes) -> Status:
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValidationFailed({"__all__": f"Нельзя изменить: {', '.join(sorted(unknown))}"})

    errors: dict[str, str] = {}
    for key, cleaner in (("name", _clean_name), ("color", _clean_color), ("kind", _clean_kind)):
        if key in changes:
            try:
                setattr(status, key, cleaner(changes[key]))
            except ValidationFailed as e:
                errors.update(e.errors)

    final_active = bool(changes["is_active"]) if changes.get("is_active") is not None else status.is_active
    final_default = bool(changes["is_default"]) if changes.get("is_default") is not None else status.is_default
    if not final_active:
        others_active = [s for s in list_statuses(db, only_active=True) if s.id != status.id]
        if status.is_active and not others_active:
            errors["is_active"] = "Должен остаться хотя бы один активный статус"
        final_default = False

    if errors:
        db.rollback()
        raise ValidationFailed(errors)

    status.is_active = final_active
    status.is_default = final_default
    if final_default:
        for other in list_statuses(db):
            if other.id != status.id:
                other.is_default = False
    db.flush()
    _ensure_default(db)
    db.commit()
    db.refresh(status)
    return status


def delete_status(db: Session, status: Status) -> None:
    used = deal_counts(db).get(status.id, 0)
    if used:
        raise ValidationFailed(
            {"__all__": f"Статус используется в сделках ({used}). Отключите его, чтобы скрыть из выбора."}
        )
    others_active = [s for s in list_statuses(db, only_active=True) if s.id != status.id]
    if status.is_active and not others_active:
        raise ValidationFailed({"__all__": "Должен остаться хотя бы один активный статус"})
    db.delete(status)
    db.flush()
    _ensure_default(db)
    db.commit()


def move_status(db: Session, status: Status, direction: str) -> None:
    if direction not in ("up", "down"):
        raise ValidationFailed({"__all__": "Неизвестное направление"})
    statuses = list_statuses(db)
    for index, s in enumerate(statuses):
        s.sort_order = index
    index = next(i for i, s in enumerate(statuses) if s.id == status.id)
    target = index - 1 if direction == "up" else index + 1
    if 0 <= target < len(statuses):
        statuses[index].sort_order, statuses[target].sort_order = target, index
    db.commit()


def reorder_statuses(db: Session, ids: list[int]) -> list[Status]:
    statuses = list_statuses(db)
    by_id = {s.id: s for s in statuses}
    if len(set(ids)) != len(ids) or any(i not in by_id for i in ids):
        raise ValidationFailed({"ids": "Список содержит неизвестные или повторяющиеся статусы"})
    ordered = [by_id[i] for i in ids] + [s for s in statuses if s.id not in set(ids)]
    for index, s in enumerate(ordered):
        s.sort_order = index
    db.commit()
    return ordered
