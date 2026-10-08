"""Зависимости API: текущий пользователь и проверка прав.
Токен берётся из заголовка Authorization: Bearer ... или из HttpOnly-cookie."""
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token, password_fingerprint
from app.db.session import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def resolve_user(db: Session, token: str | None) -> User | None:
    """Токен -> активный пользователь или None (подпись, срок, отпечаток пароля)."""
    if not token:
        return None
    data = decode_access_token(token)
    if data is None:
        return None
    user = db.get(User, data.user_id)
    if user is None or not user.is_active:
        return None
    if data.pwd_fingerprint != password_fingerprint(user.hashed_password):
        return None
    return user


def get_current_user(
    request: Request,
    bearer: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = bearer or request.cookies.get(get_settings().AUTH_COOKIE_NAME)
    user = resolve_user(db, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_permission(perm: str) -> Callable[..., User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if not user.can(perm):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return checker
