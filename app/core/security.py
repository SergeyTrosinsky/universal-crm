"""Пароли (passlib/bcrypt) и JWT (python-jose)."""
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from jose import JWTError, jwt
from passlib.context import CryptContext
from starlette.responses import Response

from app.core.config import get_settings

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def validate_password(password: str) -> str:
    """Проверка требований к новому паролю. Бросает ValueError с понятным текстом."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Пароль слишком длинный (максимум {MAX_PASSWORD_BYTES} байт)")
    return password


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        return False


@lru_cache
def _dummy_hash() -> str:
    return _pwd_context.hash("timing-equalizer-password")


def burn_password_check(plain: str) -> None:
    """Выравнивает время ответа, когда пользователь не найден (защита от перебора email)."""
    verify_password(plain, _dummy_hash())


def password_fingerprint(hashed_password: str) -> str:
    """Короткий отпечаток хеша. Лежит в токене: после смены пароля старые токены перестают работать."""
    return hashlib.sha256(hashed_password.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class TokenData:
    user_id: int
    pwd_fingerprint: str


def create_access_token(user_id: int, hashed_password: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "pv": password_fingerprint(hashed_password),
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> TokenData | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return TokenData(user_id=int(payload["sub"]), pwd_fingerprint=str(payload["pv"]))
    except (JWTError, KeyError, ValueError, TypeError):
        return None


def set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=settings.AUTH_COOKIE_SECURE,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(get_settings().AUTH_COOKIE_NAME, path="/")
