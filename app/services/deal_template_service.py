"""Шаблоны сделок: именованные наборы дополнительных полей («Автосервис», «Окрашивание»…).

Поле без шаблона — общее и показывается у всех сделок; поле с шаблоном — только у сделок
с этим шаблоном. Сделка без шаблона использует «стандартную форму» (только общие поля)."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CustomField, Deal, DealTemplate
from app.services.errors import ValidationFailed

EDITABLE = {"name", "description", "is_active"}


# ------------------------------------------------------------------ чтение
def list_templates(db: Session, *, only_active: bool = False) -> list[DealTemplate]:
    stmt = select(DealTemplate)
    if only_active:
        stmt = stmt.where(DealTemplate.is_active.is_(True))
    return list(db.scalars(stmt.order_by(DealTemplate.sort_order, DealTemplate.id)))


def get_template(db: Session, template_id: int) -> DealTemplate | None:
    return db.get(DealTemplate, template_id)


def usage(db: Session) -> dict[int, dict[str, int]]:
    """{id шаблона: {"fields": N, "deals": M}} для страницы настроек."""
    result: dict[int, dict[str, int]] = {}
    for tid, cnt in db.execute(
        select(CustomField.template_id, func.count()).where(CustomField.template_id.is_not(None))
        .group_by(CustomField.template_id)
    ):
        result.setdefault(tid, {"fields": 0, "deals": 0})["fields"] = cnt
    for tid, cnt in db.execute(
        select(Deal.template_id, func.count()).where(Deal.template_id.is_not(None)).group_by(Deal.template_id)
    ):
        result.setdefault(tid, {"fields": 0, "deals": 0})["deals"] = cnt
    return result


def fields_for_template(fields: Iterable[CustomField], template_id: int | None) -> list[CustomField]:
    """Общие поля + поля выбранного шаблона."""
    return [f for f in fields if f.template_id is None or f.template_id == template_id]


def find_by_name(db: Session, name: str) -> DealTemplate | None:
    return db.scalar(select(DealTemplate).where(func.lower(DealTemplate.name) == name.strip().lower()))


# ------------------------------------------------------------------ проверка
def _clean_name(db: Session, name: Any, *, exclude_id: int | None = None) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise ValidationFailed({"name": "Укажите название шаблона"})
    if len(text) > 100:
        raise ValidationFailed({"name": "Название слишком длинное (максимум 100 символов)"})
    other = find_by_name(db, text)
    if other is not None and other.id != exclude_id:
        raise ValidationFailed({"name": "Шаблон с таким названием уже есть"})
    return text


def _clean_description(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    if len(text) > 1000:
        raise ValidationFailed({"description": "Описание слишком длинное (максимум 1000 символов)"})
    return text or None


# ------------------------------------------------------------------ запись
def create_template(
    db: Session, *, name: str, description: str | None = None, is_active: bool = True
) -> DealTemplate:
    clean_name = _clean_name(db, name)
    last = db.scalar(select(func.max(DealTemplate.sort_order)))
    template = DealTemplate(
        name=clean_name,
        description=_clean_description(description),
        is_active=bool(is_active),
        sort_order=(last if last is not None else -1) + 1,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_template(db: Session, template: DealTemplate, **changes: Any) -> DealTemplate:
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValidationFailed({"__all__": f"Нельзя изменить: {', '.join(sorted(unknown))}"})
    if "name" in changes:
        template.name = _clean_name(db, changes["name"], exclude_id=template.id)
    if "description" in changes:
        template.description = _clean_description(changes["description"])
    if "is_active" in changes and changes["is_active"] is not None:
        template.is_active = bool(changes["is_active"])
    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, template: DealTemplate) -> None:
    """Удаляет пустой шаблон. Если у него есть поля или сделки — отказ: данные не теряем."""
    used = usage(db).get(template.id, {"fields": 0, "deals": 0})
    if used["fields"] or used["deals"]:
        parts = []
        if used["fields"]:
            parts.append(f"полей: {used['fields']}")
        if used["deals"]:
            parts.append(f"сделок: {used['deals']}")
        raise ValidationFailed(
            {"__all__": f"Шаблон используется ({', '.join(parts)}). Скройте его или сначала уберите поля и сделки."}
        )
    db.delete(template)
    db.commit()


def move_template(db: Session, template: DealTemplate, direction: str) -> None:
    if direction not in ("up", "down"):
        raise ValidationFailed({"__all__": "Неизвестное направление"})
    items = list_templates(db)
    for index, t in enumerate(items):
        t.sort_order = index
    index = next(i for i, t in enumerate(items) if t.id == template.id)
    target = index - 1 if direction == "up" else index + 1
    if 0 <= target < len(items):
        items[index].sort_order, items[target].sort_order = target, index
    db.commit()


def validate_for_deal(
    db: Session, raw: Any, *, current_id: int | None = None
) -> tuple[int | None, str | None]:
    """Шаблон из формы/API -> (id | None, текст ошибки). Пусто = стандартная форма.
    Неактивный шаблон нельзя выбрать заново, но можно оставить у сделки, где он уже стоит."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    try:
        template_id = int(str(raw).strip())
    except ValueError:
        return None, "Выберите шаблон из списка"
    template = db.get(DealTemplate, template_id)
    if template is None or (not template.is_active and template.id != current_id):
        return None, "Выберите шаблон из списка"
    return template.id, None


def assign_fields(db: Session, template: DealTemplate, field_ids: Sequence[int]) -> None:
    """Делает перечисленные поля сделок полями шаблона (остальные его поля не трогает)."""
    for field in db.scalars(select(CustomField).where(CustomField.id.in_(list(field_ids)))):
        field.template_id = template.id
    db.commit()
