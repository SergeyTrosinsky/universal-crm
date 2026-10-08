"""Импорт всех моделей нужен, чтобы Base.metadata знала обо всех таблицах (create_all / Alembic)."""
from app.models.activity import ActivityEvent, Note
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.custom_field import FIELD_STORAGE, CustomField
from app.models.custom_value import CustomValue
from app.models.deal import Deal
from app.models.deal_template import DealTemplate
from app.models.enums import (
    ClientType, EntityType, FieldType, StatusEntity, StatusKind, TaskPriority, TaskStatus,
)
from app.models.role import Role
from app.models.status import Status
from app.models.task import Task
from app.models.user import User

__all__ = [
    "ActivityEvent", "AppSetting", "Client", "ClientType", "CustomField", "CustomValue", "Deal", "DealTemplate", "EntityType", "FIELD_STORAGE",
    "FieldType", "Note", "Role", "Status", "StatusEntity", "StatusKind", "Task", "TaskPriority",
    "TaskStatus", "User",
]
