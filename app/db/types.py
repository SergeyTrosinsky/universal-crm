"""Переносимые типы колонок."""
from enum import Enum
from typing import Type

from sqlalchemy import JSON, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB

JSONType = JSON().with_variant(JSONB(), "postgresql")


def str_enum(enum_cls: Type[Enum], name: str) -> SAEnum:
    """Enum как VARCHAR без нативного ENUM: миграции проще, значения — .value, а не имена."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )
