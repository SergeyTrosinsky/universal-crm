from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.custom_field import CustomField
    from app.models.deal import Deal


class DealTemplate(TimestampMixin, Base):
    """Шаблон сделки («Автосервис», «Окрашивание»…): набор дополнительных полей, который
    выбирается при создании сделки. Поля без шаблона общие и показываются всегда."""

    __tablename__ = "deal_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    fields: Mapped[list[CustomField]] = relationship(back_populates="template")
    deals: Mapped[list[Deal]] = relationship(back_populates="template")
