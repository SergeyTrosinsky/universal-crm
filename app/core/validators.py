"""Общие валидаторы и парсеры пользовательского ввода.

Все функции бросают ValueError с текстом, который можно показать пользователю.
Email проверяем мягко (без DNS и списка спец-доменов), чтобы работали адреса вида admin@company.local.
"""
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[\d\s().\-]{5,50}$")
_SPACES_RE = re.compile(r"[\s  ]")


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 255 or not EMAIL_RE.match(email):
        raise ValueError("Некорректный email")
    return email


def normalize_phone(value: str) -> str:
    phone = (value or "").strip()
    if not PHONE_RE.match(phone) or sum(ch.isdigit() for ch in phone) < 5:
        raise ValueError("Некорректный телефон")
    return phone


def parse_optional_int(raw: Any) -> int | None:
    """'' / None -> None; '12' -> 12; всё остальное — ValueError."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError("Некорректное значение")
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError("Некорректное значение") from None


def parse_decimal(raw: Any, *, max_abs: Decimal = Decimal("1e13")) -> Decimal:
    """Принимает 1500.5, '1 500,50', Decimal. Запятая = десятичный разделитель."""
    if isinstance(raw, bool):
        raise ValueError("Введите число")
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, (int, float)):
        value = Decimal(str(raw))
    else:
        text = _SPACES_RE.sub("", str(raw)).replace(",", ".")
        try:
            value = Decimal(text)
        except InvalidOperation:
            raise ValueError("Введите число") from None
    if not value.is_finite():
        raise ValueError("Введите число")
    if abs(value) >= max_abs:
        raise ValueError("Слишком большое число")
    return value


def parse_money(raw: Any) -> Decimal:
    value = parse_decimal(raw, max_abs=Decimal("1e12"))
    if value < 0:
        raise ValueError("Сумма не может быть отрицательной")
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_date(raw: Any) -> date:
    """date / datetime / 'YYYY-MM-DD' / 'DD.MM.YYYY'."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("Некорректная дата")
