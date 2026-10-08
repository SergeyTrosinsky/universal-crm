"""Перечисления домена. Хранятся в БД как VARCHAR (переносимо между SQLite и PostgreSQL)."""
from enum import StrEnum


class EntityType(StrEnum):
    """К какой сущности привязано кастомное поле (EAV)."""
    CLIENT = "client"
    DEAL = "deal"


class StatusEntity(StrEnum):
    """Для какой сущности существует справочник статусов (пока только сделки)."""
    DEAL = "deal"


class StatusKind(StrEnum):
    """Семантика статуса — нужна статистике, даже если пользователь переименовал статусы."""
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class ClientType(StrEnum):
    PERSON = "person"
    COMPANY = "company"


class FieldType(StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    SELECT = "select"
    MULTISELECT = "multiselect"
    PHONE = "phone"
    EMAIL = "email"
    URL = "url"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
