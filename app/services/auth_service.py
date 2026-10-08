"""Аутентификация."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import burn_password_check, verify_password
from app.models import User
from app.services.user_service import get_user_by_email


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Возвращает пользователя при верных данных. Одинаково отвечает на «нет такого»
    и «неверный пароль»; отключённый пользователь войти не может."""
    user = get_user_by_email(db, email or "")
    if user is None:
        burn_password_check(password or "")
        return None
    if not verify_password(password or "", user.hashed_password) or not user.is_active:
        return None
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return user
