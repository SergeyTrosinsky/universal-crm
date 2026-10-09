"""Создание схемы (dev) и идемпотентное наполнение справочников.
В продакшене схему ведёт Alembic, здесь остаётся только seed_defaults()."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import permissions as p
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine
from app.models import AppSetting, Role, Status, StatusEntity, StatusKind

DEFAULT_ROLES = [
    {"code": "admin", "name": "Администратор", "permissions": [p.ALL], "is_system": True},
    {
        "code": "manager", "name": "Менеджер", "is_system": True,
        "permissions": [
            p.CLIENTS_READ, p.CLIENTS_WRITE, p.CLIENTS_DELETE, p.DEALS_READ, p.DEALS_WRITE,
            p.DEALS_DELETE, p.DEALS_READ_ALL, p.DEALS_ASSIGN, p.TASKS_READ, p.TASKS_WRITE,
            p.TASKS_READ_ALL, p.TASKS_ASSIGN, p.DASHBOARD_READ,
        ],
    },
    {
        "code": "employee", "name": "Сотрудник", "is_system": True,
        "permissions": [
            p.CLIENTS_READ, p.CLIENTS_WRITE, p.DEALS_READ, p.DEALS_WRITE,
            p.TASKS_READ, p.TASKS_WRITE, p.DASHBOARD_READ,
        ],
    },
]

DEFAULT_DEAL_STATUSES = [
    {"code": "new", "name": "Новая", "color": "#3B82F6", "kind": StatusKind.OPEN, "is_default": True},
    {"code": "in_progress", "name": "В работе", "color": "#F59E0B", "kind": StatusKind.OPEN},
    {"code": "won", "name": "Выиграна", "color": "#10B981", "kind": StatusKind.WON},
    {"code": "lost", "name": "Проиграна", "color": "#EF4444", "kind": StatusKind.LOST},
]


def create_schema() -> None:
    Base.metadata.create_all(bind=engine)


def ensure_schema() -> None:
    """Dev-режим: создаёт таблицы напрямую. При AUTO_CREATE_SCHEMA=false схему ведёт Alembic."""
    if get_settings().AUTO_CREATE_SCHEMA:
        create_schema()


ROLES_REV_KEY = "_roles_rev"
ROLES_REV = 2
ROLE_UPGRADES = [
    (2, "manager", [p.DEALS_READ_ALL, p.DEALS_ASSIGN, p.TASKS_ASSIGN]),
]


def upgrade_system_roles(db: Session) -> None:
    """Однократно (по метке в app_settings) докладывает новые права в системные роли уже
    работающей базы. Дальнейшие правки ролей администратором не затрагиваются."""
    row = db.get(AppSetting, ROLES_REV_KEY)
    current = int(row.value) if row and row.value.isdigit() else 1
    if current >= ROLES_REV:
        return
    for rev, code, perms in ROLE_UPGRADES:
        if rev <= current:
            continue
        role = db.scalar(select(Role).where(Role.code == code))
        if role is not None and p.ALL not in (role.permissions or []):
            role.permissions = list(role.permissions or []) + [x for x in perms if x not in (role.permissions or [])]
    if row is None:
        db.add(AppSetting(key=ROLES_REV_KEY, value=str(ROLES_REV)))
    else:
        row.value = str(ROLES_REV)
    db.commit()


def seed_defaults(db: Session) -> None:
    for data in DEFAULT_ROLES:
        if not db.scalar(select(Role).where(Role.code == data["code"])):
            db.add(Role(**data))
    for order, data in enumerate(DEFAULT_DEAL_STATUSES):
        exists = db.scalar(
            select(Status).where(Status.entity_type == StatusEntity.DEAL, Status.code == data["code"])
        )
        if not exists:
            db.add(Status(entity_type=StatusEntity.DEAL, sort_order=order, **data))
    db.commit()
    upgrade_system_roles(db)
