from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import JSONType
from app.models.custom_field import FIELD_STORAGE, CustomField
from app.models.enums import FieldType

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.deal import Deal


class CustomValue(Base):
    """EAV: значение. Ровно один владелец (клиент ИЛИ сделка) — реальные FK, поэтому
    значения каскадно удаляются вместе с владельцем, а типизированные колонки
    позволяют фильтровать и сортировать на уровне SQL (>, <, BETWEEN, LIKE)."""

    __tablename__ = "custom_values"
    __table_args__ = (
        CheckConstraint(
            "(client_id IS NOT NULL AND deal_id IS NULL) OR (client_id IS NULL AND deal_id IS NOT NULL)",
            name="exactly_one_owner",
        ),
        UniqueConstraint("field_id", "client_id", name="uq_custom_values_field_client"),
        UniqueConstraint("field_id", "deal_id", name="uq_custom_values_field_deal"),
        Index("ix_custom_values_client", "client_id"),
        Index("ix_custom_values_deal", "deal_id"),
        Index("ix_custom_values_field_number", "field_id", "value_number"),
        Index("ix_custom_values_field_date", "field_id", "value_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("custom_fields.id", ondelete="CASCADE"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"))

    value_text: Mapped[str | None] = mapped_column(Text)
    value_number: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    value_date: Mapped[date | None] = mapped_column(Date)
    value_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_json: Mapped[Any | None] = mapped_column(JSONType)

    field: Mapped[CustomField] = relationship(back_populates="values", lazy="joined")
    client: Mapped[Client | None] = relationship(back_populates="custom_values")
    deal: Mapped[Deal | None] = relationship(back_populates="custom_values")

    @property
    def value(self) -> Any:
        value = getattr(self, FIELD_STORAGE[self.field.field_type])
        if value is not None and self.field.field_type == FieldType.INTEGER:
            return int(value)
        return value

    def set_value(self, raw: Any) -> None:
        """Пишет значение в нужную колонку и обнуляет остальные (при смене типа поля)."""
        for col in set(FIELD_STORAGE.values()):
            setattr(self, col, None)
        setattr(self, FIELD_STORAGE[self.field.field_type], raw)
