"""Защита от подделки межсайтовых запросов (CSRF).

Токен хранится в подписанной сессии (cookie crm_session) и должен приходить с каждым
изменяющим запросом: в поле формы `csrf_token` или в заголовке `X-CSRF-Token`.
Поле автоматически добавляется во все HTML-формы с method="post" при отрисовке страницы
(см. web/templating.render), а JavaScript берёт токен из <meta name="csrf-token">.

API с заголовком Authorization: Bearer ... от CSRF не страдает (браузер не подставляет
такой заголовок сам), поэтому проверяется только вход по cookie."""
from __future__ import annotations

import re
import secrets
from html import escape

from fastapi import HTTPException, Request

from app.core.config import get_settings

SESSION_KEY = "csrf"
FIELD_NAME = "csrf_token"
HEADER_NAME = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
FORM_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")
API_EXEMPT = ("/api/v1/auth/login", "/api/v1/auth/token")
FORM_RE = re.compile(r"(<form\b[^>]*\bmethod=[\"']post[\"'][^>]*>)", re.IGNORECASE)
FAILED = "Сессия устарела или запрос не прошёл проверку безопасности. Обновите страницу и повторите."


def get_token(request: Request) -> str:
    token = request.session.get(SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_KEY] = token
    return token


def reset_token(request: Request) -> None:
    """Сбрасывается при входе и выходе, чтобы старый токен не пережил смену пользователя."""
    request.session.pop(SESSION_KEY, None)


def inject(html: str, token: str) -> str:
    """Добавляет скрытое поле с токеном во все POST-формы."""
    field = f'<input type="hidden" name="{FIELD_NAME}" value="{escape(token, quote=True)}">'
    return FORM_RE.sub(lambda m: m.group(1) + field, html)


def _matches(request: Request, sent: str | None) -> bool:
    expected = request.session.get(SESSION_KEY)
    return bool(expected and sent) and secrets.compare_digest(str(expected).encode(), str(sent).encode())


def _forbidden() -> HTTPException:
    return HTTPException(403, FAILED)


async def verify_web(request: Request) -> None:
    """Зависимость HTML-страниц: все POST/PUT/PATCH/DELETE должны нести токен."""
    if request.method in SAFE_METHODS or not get_settings().CSRF_ENABLED:
        return
    sent = request.headers.get(HEADER_NAME)
    if not sent and request.headers.get("content-type", "").lower().startswith(FORM_TYPES):
        form = await request.form()
        value = form.get(FIELD_NAME)
        sent = value if isinstance(value, str) else None
    if not _matches(request, sent):
        raise _forbidden()


async def verify_api(request: Request) -> None:
    """Зависимость API: токен нужен только если пользователь авторизован cookie, а не Bearer."""
    if request.method in SAFE_METHODS or not get_settings().CSRF_ENABLED:
        return
    if request.headers.get("authorization") or request.url.path in API_EXEMPT:
        return
    if not request.cookies.get(get_settings().AUTH_COOKIE_NAME):
        return
    if not _matches(request, request.headers.get(HEADER_NAME)):
        raise _forbidden()
