"""Общие настройки CRM, редактируемые в интерфейсе: название, валюта по умолчанию и термины
(«Клиенты» → «Пациенты», «Сделки» → «Заказы»…). Хранятся в таблице app_settings; чего нет — берётся из DEFAULTS."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.labels import CURRENCIES
from app.models import AppSetting
from app.services.errors import ValidationFailed

TERM_KEYS = ("pl", "sg", "acc")
MAX_LEN = 60

DEFAULTS: dict[str, str] = {
    "app_name": "",
    "default_currency": "RUB",
    "client_pl": "Клиенты",
    "client_sg": "Клиент",
    "client_acc": "клиента",
    "deal_pl": "Сделки",
    "deal_sg": "Сделка",
    "deal_acc": "сделку",
}

LABELS = {
    "app_name": "Название CRM",
    "default_currency": "Валюта по умолчанию",
    "client_pl": "Клиенты (множественное число)",
    "client_sg": "Клиент (единственное число)",
    "client_acc": "клиента (кого? — для «Добавить …»)",
    "deal_pl": "Сделки (множественное число)",
    "deal_sg": "Сделка (единственное число)",
    "deal_acc": "сделку (что? — для «Добавить …»)",
}


def get_all(db: Session | None) -> dict[str, str]:
    values = dict(DEFAULTS)
    if db is not None:
        for row in db.scalars(select(AppSetting)):
            if row.key in DEFAULTS and row.value.strip():
                values[row.key] = row.value
    return values


def build_ui(values: Mapping[str, str]) -> dict[str, Any]:
    """Структура для шаблонов: ui.app_name, ui.default_currency, ui.client.pl / .sg / .acc, ui.deal…"""
    return {
        "app_name": values.get("app_name") or get_settings().APP_NAME,
        "default_currency": values.get("default_currency") or DEFAULTS["default_currency"],
        "client": {k: values[f"client_{k}"] for k in TERM_KEYS},
        "deal": {k: values[f"deal_{k}"] for k in TERM_KEYS},
    }


def ui(db: Session | None) -> dict[str, Any]:
    return build_ui(get_all(db))


def default_currency(db: Session) -> str:
    return get_all(db)["default_currency"]


def validate(data: Mapping[str, Any]) -> dict[str, str]:
    """Проверяет присланные ключи и возвращает очищенные значения; ошибки — ValidationFailed."""
    clean: dict[str, str] = {}
    errors: dict[str, str] = {}
    for key, raw in data.items():
        if key not in DEFAULTS:
            errors[key] = "Неизвестная настройка"
            continue
        value = " ".join(str(raw if raw is not None else "").split())
        if key == "app_name":
            if len(value) > MAX_LEN:
                errors[key] = f"Слишком длинное название (максимум {MAX_LEN} символов)"
            else:
                clean[key] = value
        elif key == "default_currency":
            value = value.upper()
            if value not in CURRENCIES:
                errors[key] = "Выберите валюту из списка"
            else:
                clean[key] = value
        else:
            if not value:
                errors[key] = "Заполните поле"
            elif len(value) > MAX_LEN:
                errors[key] = f"Слишком длинный текст (максимум {MAX_LEN} символов)"
            else:
                clean[key] = value
    if errors:
        raise ValidationFailed(errors)
    return clean


def update(db: Session, data: Mapping[str, Any]) -> dict[str, str]:
    clean = validate(data)
    existing = {row.key: row for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(list(clean))))}
    for key, value in clean.items():
        if value == DEFAULTS[key]:
            if key in existing:
                db.delete(existing[key])
        elif key in existing:
            existing[key].value = value
        else:
            db.add(AppSetting(key=key, value=value))
    db.commit()
    return get_all(db)


def reset(db: Session) -> None:
    for row in db.scalars(select(AppSetting)):
        if not row.key.startswith("_"):
            db.delete(row)
    db.commit()


def apply_terms(db: Session, entity: str, pl: str, sg: str, acc: str) -> bool:
    """Подставляет термины набора (например, «Заказы» для автосервиса), только если админ
    ещё не менял эту сущность. Возвращает True, если применено."""
    current = get_all(db)
    if any(current[f"{entity}_{k}"] != DEFAULTS[f"{entity}_{k}"] for k in TERM_KEYS):
        return False
    update(db, {f"{entity}_pl": pl, f"{entity}_sg": sg, f"{entity}_acc": acc})
    return True
