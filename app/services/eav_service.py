"""EAV-слой: приведение введённых значений к типу поля, запись в custom_values,
подготовка значений для форм/отображения и SQL-фильтры по кастомным полям.

Значения приходят в двух видах: строки из HTML-форм и типизированный JSON из API —
coerce_value принимает оба."""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Text, cast, exists, or_

from app.core.timezone import local_day_bounds_utc, local_to_utc, to_local
from app.core.validators import (
    normalize_email,
    normalize_phone,
    parse_date,
    parse_decimal,
)
from app.models import Client, CustomField, CustomValue, FieldType
from app.services.query_utils import contains

TEXT_TYPES = {FieldType.TEXT, FieldType.TEXTAREA, FieldType.PHONE, FieldType.EMAIL, FieldType.URL}
URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
TRUE_WORDS = {"1", "true", "on", "yes", "y", "да"}
FALSE_WORDS = {"0", "false", "off", "no", "n", "нет"}
FORM_PREFIX = "cf_"


def _is_blank(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, str):
        return not raw.strip()
    if isinstance(raw, (list, tuple, set)):
        return not any(not _is_blank(item) for item in raw)
    return False


def coerce_value(field: CustomField, raw: Any) -> Any:
    """Возвращает значение для хранения (None = «не заполнено»). ValueError — текст для пользователя."""
    ftype = field.field_type

    if ftype == FieldType.BOOLEAN:
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        if isinstance(raw, bool):
            return raw
        word = str(raw).strip().lower()
        if word in TRUE_WORDS:
            return True
        if word in FALSE_WORDS:
            return False
        raise ValueError("Допустимо только «да» или «нет»")

    if _is_blank(raw):
        return None

    if ftype in (FieldType.TEXT, FieldType.TEXTAREA):
        text = str(raw).strip()
        limit = 5000 if ftype == FieldType.TEXTAREA else 500
        if len(text) > limit:
            raise ValueError(f"Слишком длинный текст (максимум {limit} символов)")
        return text

    if ftype == FieldType.PHONE:
        return normalize_phone(str(raw))

    if ftype == FieldType.EMAIL:
        return normalize_email(str(raw))

    if ftype == FieldType.URL:
        text = str(raw).strip()
        if len(text) > 500 or not URL_RE.match(text):
            raise ValueError("Ссылка должна начинаться с http:// или https://")
        return text

    if ftype == FieldType.SELECT:
        value = str(raw).strip()
        if value not in (field.options or []):
            raise ValueError("Выберите значение из списка")
        return value

    if ftype == FieldType.MULTISELECT:
        items = [raw] if isinstance(raw, str) else list(raw)
        values: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            if text not in (field.options or []):
                raise ValueError("Выберите значения из списка")
            if text not in values:
                values.append(text)
        return values or None

    if ftype == FieldType.INTEGER:
        if isinstance(raw, bool):
            raise ValueError("Введите целое число")
        number = parse_decimal(raw)
        if number != number.to_integral_value():
            raise ValueError("Введите целое число")
        return int(number)

    if ftype == FieldType.DECIMAL:
        number = parse_decimal(raw)
        return number.quantize(Decimal("0.000001"))

    if ftype == FieldType.DATE:
        return parse_date(raw)

    if ftype == FieldType.DATETIME:
        if isinstance(raw, datetime):
            return local_to_utc(raw)
        if isinstance(raw, date):
            return local_to_utc(datetime.combine(raw, datetime.min.time()))
        try:
            return local_to_utc(datetime.fromisoformat(str(raw).strip()))
        except ValueError:
            raise ValueError("Некорректные дата и время") from None

    raise ValueError("Неподдерживаемый тип поля")  # pragma: no cover


def coerce_values(
    fields: Sequence[CustomField],
    raw: Mapping[str, Any],
    *,
    partial: bool = False,
    strict_keys: bool = False,
) -> tuple[dict[int, Any], dict[str, str]]:
    """raw: {code: значение}. Возвращает ({field_id: значение|None}, {cf_<code>: ошибка}).

    partial=True — обрабатываются только присланные ключи (PATCH);
    strict_keys=True — неизвестные ключи считаются ошибкой (API)."""
    clean: dict[int, Any] = {}
    errors: dict[str, str] = {}
    active = [f for f in fields if f.is_active]

    if strict_keys:
        known = {f.code for f in active}
        for key in raw:
            if key not in known:
                errors[f"{FORM_PREFIX}{key}"] = "Неизвестное поле"

    for field in active:
        if partial and field.code not in raw:
            continue
        try:
            value = coerce_value(field, raw.get(field.code))
        except ValueError as e:
            errors[f"{FORM_PREFIX}{field.code}"] = str(e)
            continue
        if value is None and field.is_required and field.field_type != FieldType.BOOLEAN:
            errors[f"{FORM_PREFIX}{field.code}"] = "Обязательное поле"
            continue
        clean[field.id] = value
    return clean, errors


def raw_from_form(fields: Iterable[CustomField], form) -> dict[str, Any]:
    """HTML-форма -> {code: сырое значение}. Флажок без отметки в форме отсутствует — это False."""
    raw: dict[str, Any] = {}
    for field in fields:
        key = f"{FORM_PREFIX}{field.code}"
        if field.field_type == FieldType.BOOLEAN:
            raw[field.code] = key in form
        elif field.field_type == FieldType.MULTISELECT:
            raw[field.code] = [v for v in form.getlist(key) if isinstance(v, str)]
        else:
            value = form.get(key)
            raw[field.code] = value if isinstance(value, str) else None
    return raw


def apply_values(owner: Any, fields: Sequence[CustomField], clean: Mapping[int, Any]) -> None:
    """Создаёт/обновляет/удаляет CustomValue у клиента или сделки. Коммит — на вызывающем."""
    by_id = {f.id: f for f in fields}
    existing = {cv.field_id: cv for cv in owner.custom_values}
    for field_id, value in clean.items():
        current = existing.get(field_id)
        if value is None:
            if current is not None:
                owner.custom_values.remove(current)
            continue
        if current is None:
            current = CustomValue(field=by_id[field_id])
            owner.custom_values.append(current)
        current.set_value(value)


def values_by_field(owner: Any) -> dict[int, Any]:
    return {cv.field_id: cv.value for cv in owner.custom_values}


def format_number(value: Decimal | int) -> str:
    """12345.5 -> '12 345,5' (без хвостовых нулей, с неразрывными пробелами)."""
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
    else:
        text = str(value)
    integer, _, fraction = text.partition(".")
    sign = "-" if integer.startswith("-") else ""
    digits = integer.lstrip("-")
    grouped = f"{int(digits or 0):,}".replace(",", " ")
    return f"{sign}{grouped}" + (f",{fraction}" if fraction else "")


def form_value(field: CustomField, value: Any) -> Any:
    """Значение из БД -> то, что подставляется в input (строка / список / bool)."""
    ftype = field.field_type
    if ftype == FieldType.BOOLEAN:
        return bool(value)
    if ftype == FieldType.MULTISELECT:
        return list(value or [])
    if value is None:
        return ""
    if ftype == FieldType.DATE:
        return value.isoformat()
    if ftype == FieldType.DATETIME:
        return to_local(value).strftime("%Y-%m-%dT%H:%M")
    if ftype == FieldType.INTEGER:
        return str(int(value))
    if ftype == FieldType.DECIMAL:
        return format(Decimal(value).normalize(), "f")
    return str(value)


def form_values(owner: Any, fields: Iterable[CustomField]) -> dict[str, Any]:
    stored = values_by_field(owner)
    return {f.code: form_value(f, stored.get(f.id)) for f in fields}


def display_value(field: CustomField, value: Any) -> str:
    ftype = field.field_type
    if ftype == FieldType.BOOLEAN:
        return "—" if value is None else ("Да" if value else "Нет")
    if value is None or value == "" or value == []:
        return "—"
    if ftype == FieldType.MULTISELECT:
        return ", ".join(value)
    if ftype == FieldType.DATE:
        return value.strftime("%d.%m.%Y")
    if ftype == FieldType.DATETIME:
        return to_local(value).strftime("%d.%m.%Y %H:%M")
    if ftype in (FieldType.INTEGER, FieldType.DECIMAL):
        return format_number(value)
    return str(value)


def _owner_fk(model: type) -> Any:
    return CustomValue.client_id if model is Client else CustomValue.deal_id


def custom_text_search(model: type, text: str) -> ColumnElement[bool]:
    """Есть ли у записи текстовое/списочное значение, содержащее text (поиск по VIN, гос. номеру и т.п.)."""
    return exists().where(_owner_fk(model) == model.id, contains(CustomValue.value_text, text))


def _like_escape(text: str) -> str:
    return text.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def filter_param_names(field: CustomField) -> list[str]:
    base = f"{FORM_PREFIX}{field.code}"
    if field.field_type in (FieldType.INTEGER, FieldType.DECIMAL, FieldType.DATE, FieldType.DATETIME):
        return [f"{base}__from", f"{base}__to"]
    return [base]


def filterable_fields(fields: Iterable[CustomField]) -> list[CustomField]:
    return [f for f in fields if f.is_active and f.is_filterable]


def extract_custom_filters(fields: Iterable[CustomField], params: Mapping[str, str]) -> dict[str, str]:
    """Из query-параметров оставляет непустые параметры фильтров по кастомным полям."""
    result: dict[str, str] = {}
    for field in filterable_fields(fields):
        for name in filter_param_names(field):
            value = (params.get(name) or "").strip()
            if value:
                result[name] = value
    return result


def build_custom_conditions(
    model: type, fields: Iterable[CustomField], filters: Mapping[str, str]
) -> list[ColumnElement[bool]]:
    """SQL-условия (EXISTS по custom_values) для фильтров из extract_custom_filters.
    Некорректные значения (например, «abc» в числовом поле) молча игнорируются."""
    owner = _owner_fk(model)
    conditions: list[ColumnElement[bool]] = []

    def has(*extra: ColumnElement[bool], field: CustomField) -> ColumnElement[bool]:
        return exists().where(CustomValue.field_id == field.id, owner == model.id, *extra)

    for field in filterable_fields(fields):
        ftype = field.field_type
        base = f"{FORM_PREFIX}{field.code}"

        if ftype in TEXT_TYPES:
            if value := filters.get(base):
                conditions.append(has(contains(CustomValue.value_text, value), field=field))

        elif ftype == FieldType.SELECT:
            if value := filters.get(base):
                conditions.append(has(CustomValue.value_text == value, field=field))

        elif ftype == FieldType.MULTISELECT:
            if value := filters.get(base):
                as_text = cast(CustomValue.value_json, Text)
                escaped = json.dumps(value)
                plain = f'"{value}"'
                conditions.append(
                    has(
                        or_(
                            as_text.like(f"%{_like_escape(escaped)}%", escape="!"),
                            as_text.like(f"%{_like_escape(plain)}%", escape="!"),
                        ),
                        field=field,
                    )
                )

        elif ftype == FieldType.BOOLEAN:
            value = filters.get(base)
            if value == "1":
                conditions.append(has(CustomValue.value_bool.is_(True), field=field))
            elif value == "0":
                conditions.append(~has(CustomValue.value_bool.is_(True), field=field))

        elif ftype in (FieldType.INTEGER, FieldType.DECIMAL):
            for suffix, op in (("from", "ge"), ("to", "le")):
                if raw := filters.get(f"{base}__{suffix}"):
                    try:
                        number = parse_decimal(raw)
                    except ValueError:
                        continue
                    cond = CustomValue.value_number >= number if op == "ge" else CustomValue.value_number <= number
                    conditions.append(has(cond, field=field))

        elif ftype == FieldType.DATE:
            for suffix, op in (("from", "ge"), ("to", "le")):
                if raw := filters.get(f"{base}__{suffix}"):
                    try:
                        day = parse_date(raw)
                    except ValueError:
                        continue
                    cond = CustomValue.value_date >= day if op == "ge" else CustomValue.value_date <= day
                    conditions.append(has(cond, field=field))

        elif ftype == FieldType.DATETIME:
            if raw := filters.get(f"{base}__from"):
                try:
                    start, _ = local_day_bounds_utc(parse_date(raw))
                    conditions.append(has(CustomValue.value_datetime >= start, field=field))
                except ValueError:
                    pass
            if raw := filters.get(f"{base}__to"):
                try:
                    _, end = local_day_bounds_utc(parse_date(raw))
                    conditions.append(has(CustomValue.value_datetime < end, field=field))
                except ValueError:
                    pass
    return conditions
