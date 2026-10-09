"""Настраиваемые поля (EAV): определения, порядок, видимость."""
from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CustomField, CustomValue, DealTemplate, EntityType, FieldType
from app.services.errors import ValidationFailed
from app.services.slug import slugify

CODE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
CHOICE_TYPES = {FieldType.SELECT, FieldType.MULTISELECT}
MAX_OPTIONS = 100
EDITABLE = {
    "label", "options", "placeholder", "help_text",
    "is_required", "is_filterable", "show_in_list", "is_active", "template_id",
}


def _enum(enum_cls, value, key: str, message: str):
    try:
        return enum_cls(str(value))
    except ValueError:
        raise ValidationFailed({key: message}) from None


def clean_options(options: Iterable[object] | None) -> list[str]:
    result: list[str] = []
    for option in options or []:
        text = str(option).strip()
        if text and text not in result:
            result.append(text)
    if len(result) > MAX_OPTIONS:
        raise ValidationFailed({"options": f"Слишком много вариантов (максимум {MAX_OPTIONS})"})
    if any(len(o) > 100 for o in result):
        raise ValidationFailed({"options": "Вариант не должен быть длиннее 100 символов"})
    return result


def _check_template(db: Session, entity: EntityType, template_id: object) -> int | None:
    """Шаблон бывает только у полей сделок и должен существовать. Пусто = общее поле."""
    if template_id is None or (isinstance(template_id, str) and not template_id.strip()):
        return None
    if entity != EntityType.DEAL:
        raise ValidationFailed({"template_id": "Шаблон можно задать только полям сделок"})
    try:
        tid = int(str(template_id).strip())
    except ValueError:
        raise ValidationFailed({"template_id": "Выберите шаблон из списка"}) from None
    if db.get(DealTemplate, tid) is None:
        raise ValidationFailed({"template_id": "Выберите шаблон из списка"})
    return tid


def _clean_text(value: object, limit: int, key: str, label: str) -> str | None:
    text = str(value).strip() if value is not None else ""
    if len(text) > limit:
        raise ValidationFailed({key: f"{label}: максимум {limit} символов"})
    return text or None


def list_fields(
    db: Session, entity_type: EntityType | None = None, *, only_active: bool = False
) -> list[CustomField]:
    stmt = select(CustomField)
    if entity_type is not None:
        stmt = stmt.where(CustomField.entity_type == entity_type)
    if only_active:
        stmt = stmt.where(CustomField.is_active.is_(True))
    stmt = stmt.order_by(CustomField.entity_type, CustomField.sort_order, CustomField.id)
    return list(db.scalars(stmt))


def get_field(db: Session, field_id: int) -> CustomField | None:
    return db.get(CustomField, field_id)


def value_counts(db: Session) -> dict[int, int]:
    """{id поля: сколько значений заполнено} — для предупреждения перед удалением."""
    rows = db.execute(select(CustomValue.field_id, func.count()).group_by(CustomValue.field_id)).all()
    return {field_id: count for field_id, count in rows}


def _unique_code(db: Session, entity_type: EntityType, base: str) -> str:
    taken = set(db.scalars(select(CustomField.code).where(CustomField.entity_type == entity_type)))
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def create_field(
    db: Session,
    *,
    entity_type: str | EntityType,
    label: str,
    field_type: str | FieldType,
    code: str | None = None,
    options: Iterable[object] | None = None,
    placeholder: str | None = None,
    help_text: str | None = None,
    is_required: bool = False,
    is_filterable: bool = True,
    show_in_list: bool = False,
    is_active: bool = True,
    template_id: int | str | None = None,
) -> CustomField:
    errors: dict[str, str] = {}
    entity = _enum(EntityType, entity_type, "entity_type", "Выберите сущность")
    ftype = _enum(FieldType, field_type, "field_type", "Выберите тип поля")

    label = (label or "").strip()
    if not label:
        errors["label"] = "Укажите название поля"
    elif len(label) > 150:
        errors["label"] = "Название слишком длинное (максимум 150 символов)"

    code = (code or "").strip().lower()
    if code:
        if len(code) > 64 or not CODE_RE.match(code):
            errors["code"] = "Код: латиница, цифры и одиночное «_», начинается с буквы"
        elif db.scalar(
            select(CustomField.id).where(CustomField.entity_type == entity, CustomField.code == code)
        ):
            errors["code"] = "Поле с таким кодом уже есть"

    opts = clean_options(options) if ftype in CHOICE_TYPES else []
    if ftype in CHOICE_TYPES and not opts:
        errors["options"] = "Добавьте хотя бы один вариант (по одному в строке)"

    try:
        placeholder = _clean_text(placeholder, 255, "placeholder", "Подсказка")
        help_text = _clean_text(help_text, 1000, "help_text", "Описание")
    except ValidationFailed as e:
        errors.update(e.errors)

    template: int | None = None
    try:
        template = _check_template(db, entity, template_id)
    except ValidationFailed as e:
        errors.update(e.errors)

    if errors:
        raise ValidationFailed(errors)

    if not code:
        code = _unique_code(db, entity, slugify(label, fallback="field"))

    last = db.scalar(select(func.max(CustomField.sort_order)).where(CustomField.entity_type == entity))
    field = CustomField(
        entity_type=entity,
        code=code,
        label=label,
        field_type=ftype,
        options=opts,
        placeholder=placeholder,
        help_text=help_text,
        is_required=bool(is_required) and ftype != FieldType.BOOLEAN,
        is_filterable=bool(is_filterable),
        show_in_list=bool(show_in_list),
        is_active=bool(is_active),
        template_id=template,
        sort_order=(last if last is not None else -1) + 1,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


def update_field(db: Session, field: CustomField, **changes) -> CustomField:
    """Меняются только перечисленные в EDITABLE ключи. Код и тип неизменны:
    под них уже могут лежать данные."""
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValidationFailed({"__all__": f"Нельзя изменить: {', '.join(sorted(unknown))}"})

    errors: dict[str, str] = {}
    if "label" in changes:
        label = (changes["label"] or "").strip()
        if not label:
            errors["label"] = "Укажите название поля"
        elif len(label) > 150:
            errors["label"] = "Название слишком длинное (максимум 150 символов)"
        else:
            field.label = label
    if "options" in changes and field.field_type in CHOICE_TYPES:
        opts = clean_options(changes["options"])
        if not opts:
            errors["options"] = "Добавьте хотя бы один вариант (по одному в строке)"
        else:
            field.options = opts
    for key, limit, title in (("placeholder", 255, "Подсказка"), ("help_text", 1000, "Описание")):
        if key in changes:
            try:
                setattr(field, key, _clean_text(changes[key], limit, key, title))
            except ValidationFailed as e:
                errors.update(e.errors)
    for key in ("is_required", "is_filterable", "show_in_list", "is_active"):
        if key in changes and changes[key] is not None:
            setattr(field, key, bool(changes[key]))
    if "template_id" in changes:
        try:
            field.template_id = _check_template(db, field.entity_type, changes["template_id"])
        except ValidationFailed as e:
            errors.update(e.errors)
    if field.field_type == FieldType.BOOLEAN:
        field.is_required = False

    if errors:
        db.rollback()
        raise ValidationFailed(errors)
    db.commit()
    db.refresh(field)
    return field


def delete_field(db: Session, field: CustomField) -> int:
    """Удаляет поле вместе со всеми значениями. Возвращает, сколько значений удалено."""
    count = value_counts(db).get(field.id, 0)
    db.delete(field)
    db.commit()
    return count


def _normalize_order(db: Session, entity_type: EntityType) -> list[CustomField]:
    fields = list_fields(db, entity_type)
    for index, f in enumerate(fields):
        f.sort_order = index
    return fields


def move_field(db: Session, field: CustomField, direction: str) -> None:
    if direction not in ("up", "down"):
        raise ValidationFailed({"__all__": "Неизвестное направление"})
    fields = _normalize_order(db, field.entity_type)
    index = next(i for i, f in enumerate(fields) if f.id == field.id)
    target = index - 1 if direction == "up" else index + 1
    if 0 <= target < len(fields):
        fields[index].sort_order, fields[target].sort_order = target, index
    db.commit()


def reorder_fields(db: Session, entity_type: EntityType, ids: list[int]) -> list[CustomField]:
    """ids — желаемый порядок. Поля, не попавшие в список, остаются в конце."""
    fields = list_fields(db, entity_type)
    by_id = {f.id: f for f in fields}
    if len(set(ids)) != len(ids) or any(i not in by_id for i in ids):
        raise ValidationFailed({"ids": "Список содержит неизвестные или повторяющиеся поля"})
    ordered = [by_id[i] for i in ids] + [f for f in fields if f.id not in set(ids)]
    for index, f in enumerate(ordered):
        f.sort_order = index
    db.commit()
    return ordered
