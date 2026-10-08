"""Помощники для HTML-форм. Тело формы читает async-зависимость, а сами обработчики
остаются обычными (sync) функциями и выполняются в пуле потоков."""
from fastapi import Request
from starlette.datastructures import FormData

from app.models import EntityType


async def get_form(request: Request) -> FormData:
    return await request.form()


def fstr(form: FormData, key: str, default: str = "") -> str:
    value = form.get(key)
    return value if isinstance(value, str) else default


def fbool(form: FormData, key: str) -> bool:
    """Флажок: есть в форме — значит отмечен."""
    return key in form


def parse_page(value: str | None) -> int:
    try:
        return max(1, int(value or 1))
    except ValueError:
        return 1


def parse_options_text(text: str) -> list[str]:
    """Варианты списка: по одному в строке."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def parse_entity(value: str | None) -> EntityType:
    try:
        return EntityType(value or "")
    except ValueError:
        return EntityType.CLIENT


def optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value and value.strip() else None
    except ValueError:
        return None
