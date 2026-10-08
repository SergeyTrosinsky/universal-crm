"""Jinja2: окружение, фильтры, флеш-сообщения и общий render()."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core import csrf
from app.core.config import get_settings
from app.core.labels import (
    CLIENT_TYPE_LABELS, CURRENCIES, ENTITY_LABELS, ENTITY_LABELS_SINGULAR,
    FIELD_TYPE_LABELS, STATUS_KIND_LABELS, TASK_PRIORITY_LABELS, TASK_STATUS_LABELS,
)
from app.core.permissions import PERMISSION_GROUPS, PERMISSION_LABELS
from app.core.timezone import to_local
from app.services import eav_service, settings_service

BASE_DIR = Path(__file__).resolve().parent.parent
FLASH_KEY = "_flashes"

_settings = get_settings()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def format_dt(value: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Значения в БД — UTC (SQLite отдаёт их без tzinfo); показываем в APP_TIMEZONE."""
    return "—" if value is None else to_local(value).strftime(fmt)


def format_date(value: date | None) -> str:
    return "—" if value is None else value.strftime("%d.%m.%Y")


def money(value: Decimal | int | float | None, currency: str | None = None) -> str:
    """1234.5 -> '1 234,50 ₽'"""
    if value is None:
        return "—"
    text = f"{Decimal(str(value)):,.2f}".replace(",", " ").replace(".", ",")
    if currency:
        text += f" {CURRENCIES.get(currency, currency)}"
    return text


def can(user, perm: str) -> bool:
    return bool(user and user.can(perm))


def url_with(request: Request, **overrides) -> str:
    """Текущий URL с изменёнными query-параметрами; значение None/'' удаляет параметр."""
    items = [(k, v) for k, v in request.query_params.multi_items() if k not in overrides]
    for key, value in overrides.items():
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple)):
            items.extend((key, str(v)) for v in value)
        else:
            items.append((key, str(value)))
    query = urlencode(items)
    return f"{request.url.path}?{query}" if query else request.url.path


def export_href(request: Request, path: str, fmt: str) -> str:
    """Ссылка на выгрузку с теми же фильтрами и сортировкой, что в текущем списке (без номера страницы)."""
    items = [(k, v) for k, v in request.query_params.multi_items() if k not in ("page", "format")]
    items.append(("format", fmt))
    return f"{path}?{urlencode(items)}"


def options_of(items, value_attr: str = "id", label_attr: str = "name") -> list[tuple]:
    """Список объектов -> пары (значение, подпись) для <select>."""
    return [(getattr(item, value_attr), getattr(item, label_attr)) for item in items]


def cf_map(owner) -> dict[int, object]:
    return eav_service.values_by_field(owner)


templates.env.globals.update(
    app_name=_settings.APP_NAME,
    can=can,
    url_with=url_with,
    export_href=export_href,
    options_of=options_of,
    cf_map=cf_map,
    cf_display=eav_service.display_value,
    cf_filter_names=eav_service.filter_param_names,
    permission_groups=PERMISSION_GROUPS,
    permission_labels=PERMISSION_LABELS,
    entity_labels=ENTITY_LABELS,
    entity_labels_singular=ENTITY_LABELS_SINGULAR,
    field_type_labels=FIELD_TYPE_LABELS,
    status_kind_labels=STATUS_KIND_LABELS,
    client_type_labels=CLIENT_TYPE_LABELS,
    currencies=CURRENCIES,
    task_status_labels=TASK_STATUS_LABELS,
    task_priority_labels=TASK_PRIORITY_LABELS,
)
templates.env.filters["dt"] = format_dt
templates.env.filters["date"] = format_date
templates.env.filters["money"] = money


def flash(request: Request, message: str, category: str = "success") -> None:
    """category: success | error | info"""
    flashes = request.session.get(FLASH_KEY, [])
    flashes.append({"message": message, "category": category})
    request.session[FLASH_KEY] = flashes


def render(
    request: Request,
    name: str,
    context: dict | None = None,
    *,
    user=None,
    status_code: int = 200,
):
    ctx = dict(context or {})
    ui = getattr(request.state, "ui", None) or settings_service.ui(None)
    ctx["ui"] = ui
    ctx["app_name"] = ui["app_name"]  # перекрывает глобальное имя из окружения
    ctx["user"] = user
    ctx["flashes"] = request.session.pop(FLASH_KEY, [])
    token = csrf.get_token(request)
    ctx["csrf_token"] = token
    ctx["request"] = request
    html = csrf.inject(templates.get_template(name).render(ctx), token)  # токен — во все POST-формы
    return HTMLResponse(html, status_code=status_code)


def redirect(url: str, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(url, status_code=status_code)
