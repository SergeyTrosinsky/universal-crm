"""Зависимости HTML-страниц: вместо JSON-401 — редирект на /login."""
from collections.abc import Callable
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import resolve_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models import User
from app.services import settings_service


class LoginRequired(Exception):
    def __init__(self, next_url: str):
        self.next_url = next_url


def login_redirect_url(next_url: str) -> str:
    return f"/login?next={quote(next_url, safe='')}"


def get_web_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = resolve_user(db, request.cookies.get(get_settings().AUTH_COOKIE_NAME))
    if user is None:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise LoginRequired(target)
    request.state.ui = settings_service.ui(db)  # название CRM и термины для шаблонов
    return user


def require_web_permission(perm: str) -> Callable[..., User]:
    def checker(user: User = Depends(get_web_user)) -> User:
        if not user.can(perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для этого раздела")
        return user

    return checker
