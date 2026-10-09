"""Роли: создание, редактирование набора прав, удаление."""
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import permissions as perms
from app.models import Role, User

CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")


class RoleError(ValueError):
    """Ошибка бизнес-правил; текст безопасно показывать пользователю."""


def list_roles(db: Session) -> list[Role]:
    return list(db.scalars(select(Role).order_by(Role.is_system.desc(), Role.name)))


def get_role(db: Session, role_id: int) -> Role | None:
    return db.get(Role, role_id)


def users_count_by_role(db: Session) -> dict[int, int]:
    rows = db.execute(select(User.role_id, func.count()).group_by(User.role_id)).all()
    return {role_id: count for role_id, count in rows}


def _clean_permissions(values: list[str]) -> list[str]:
    unknown = [v for v in values if v not in perms.ALL_PERMISSIONS]
    if unknown:
        raise RoleError(f"Неизвестные права: {', '.join(unknown)}")
    return [p for p in perms.ALL_PERMISSIONS if p in set(values)]


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise RoleError("Укажите название роли")
    if len(name) > 100:
        raise RoleError("Название слишком длинное")
    return name


def create_role(
    db: Session, *, code: str, name: str, description: str | None, permissions: list[str]
) -> Role:
    code = (code or "").strip().lower()
    if not CODE_RE.match(code):
        raise RoleError("Код: латиница, цифры и «_», начинается с буквы, 2–50 символов")
    if db.scalar(select(Role).where(Role.code == code)):
        raise RoleError("Роль с таким кодом уже существует")
    role = Role(
        code=code,
        name=_clean_name(name),
        description=(description or "").strip() or None,
        permissions=_clean_permissions(permissions),
        is_system=False,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def update_role(
    db: Session,
    role: Role,
    *,
    name: str | None = None,
    description: str | None = None,
    permissions: list[str] | None = None,
) -> Role:
    if name is not None:
        role.name = _clean_name(name)
    if description is not None:
        role.description = description.strip() or None
    if permissions is not None:
        if role.has_permission(perms.ALL):
            raise RoleError("Права роли администратора изменить нельзя")
        role.permissions = _clean_permissions(permissions)
    db.commit()
    db.refresh(role)
    return role


def delete_role(db: Session, role: Role) -> None:
    if role.is_system:
        raise RoleError("Системную роль удалить нельзя")
    if db.scalar(select(func.count()).select_from(User).where(User.role_id == role.id)):
        raise RoleError("Нельзя удалить роль, пока она назначена пользователям")
    db.delete(role)
    db.commit()
