"""Пользователи: создание, изменение, защита от потери доступа и повышения прав."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import permissions as perms
from app.core.config import get_settings
from app.core.security import hash_password, validate_password
from app.core.validators import normalize_email
from app.models import Role, User


class UserError(ValueError):
    """Ошибка бизнес-правил; текст безопасно показывать пользователю."""


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.full_name, User.id)))


def count_users(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


def _active_admin_count(db: Session) -> int:
    active = db.scalars(select(User).where(User.is_active.is_(True)))
    return sum(1 for u in active if u.role.has_permission(perms.ALL))


def _clean_name(full_name: str) -> str:
    name = (full_name or "").strip()
    if not name:
        raise UserError("Укажите имя")
    if len(name) > 255:
        raise UserError("Имя слишком длинное")
    return name


def _clean_password(password: str) -> str:
    try:
        return validate_password(password)
    except ValueError as e:
        raise UserError(str(e)) from e


def _get_role(db: Session, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise UserError("Роль не найдена")
    return role


def _check_admin_escalation(actor: User | None, role: Role) -> None:
    """Назначать роль с полным доступом может только тот, у кого он уже есть."""
    if actor is not None and role.has_permission(perms.ALL) and not actor.role.has_permission(perms.ALL):
        raise UserError("Только администратор может назначать роль администратора")


def create_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
    role_id: int,
    is_active: bool = True,
    actor: User | None = None,
) -> User:
    try:
        email = normalize_email(email)
    except ValueError as e:
        raise UserError(str(e)) from e
    full_name = _clean_name(full_name)
    password = _clean_password(password)
    role = _get_role(db, role_id)
    _check_admin_escalation(actor, role)
    if get_user_by_email(db, email):
        raise UserError("Пользователь с таким email уже существует")

    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
        role_id=role.id,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user: User,
    *,
    actor: User,
    full_name: str | None = None,
    role_id: int | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> User:
    is_self = actor.id == user.id
    was_admin = user.role.has_permission(perms.ALL)

    if was_admin and not actor.role.has_permission(perms.ALL):
        raise UserError("Только администратор может изменять администраторов")

    if full_name is not None:
        user.full_name = _clean_name(full_name)

    new_role = user.role
    if role_id is not None and role_id != user.role_id:
        if is_self:
            raise UserError("Нельзя изменить собственную роль")
        new_role = _get_role(db, role_id)
        _check_admin_escalation(actor, new_role)

    if is_active is not None and is_active != user.is_active and is_self:
        raise UserError("Нельзя отключить самого себя")

    final_active = user.is_active if is_active is None else is_active
    if was_admin and user.is_active and (not final_active or not new_role.has_permission(perms.ALL)):
        if _active_admin_count(db) <= 1:
            raise UserError("Нельзя отключить или понизить последнего администратора")

    if password:
        user.hashed_password = hash_password(_clean_password(password))

    user.role_id = new_role.id
    user.is_active = final_active
    db.commit()
    db.refresh(user)
    return user


def change_own_password(db: Session, user: User, new_password: str) -> User:
    user.hashed_password = hash_password(_clean_password(new_password))
    db.commit()
    return user


def rename_self(db: Session, user: User, full_name: str) -> User:
    user.full_name = _clean_name(full_name)
    db.commit()
    return user


def ensure_first_admin(db: Session) -> User | None:
    """Создаёт администратора из FIRST_ADMIN_* — только если в БД ещё нет пользователей."""
    settings = get_settings()
    if not settings.FIRST_ADMIN_EMAIL or not settings.FIRST_ADMIN_PASSWORD:
        return None
    if count_users(db) > 0:
        return None
    admin_role = db.scalar(select(Role).where(Role.code == "admin"))
    if admin_role is None:
        return None
    return create_user(
        db,
        email=settings.FIRST_ADMIN_EMAIL,
        full_name=settings.FIRST_ADMIN_NAME,
        password=settings.FIRST_ADMIN_PASSWORD,
        role_id=admin_role.id,
    )
