from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.custom_value import CustomValue
    from app.models.deal_template import DealTemplate
    from app.models.status import Status
    from app.models.task import Task
    from app.models.user import User


class Deal(TimestampMixin, Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    deal_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status_id: Mapped[int] = mapped_column(ForeignKey("statuses.id", ondelete="RESTRICT"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    responsible_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("deal_templates.id", ondelete="SET NULL"), index=True
    )

    template: Mapped[DealTemplate | None] = relationship(back_populates="deals", lazy="joined")
    status: Mapped[Status] = relationship(back_populates="deals", lazy="joined")
    client: Mapped[Client] = relationship(back_populates="deals")
    responsible: Mapped[User | None] = relationship(back_populates="responsible_deals")
    tasks: Mapped[list[Task]] = relationship(back_populates="deal")
    custom_values: Mapped[list[CustomValue]] = relationship(
        back_populates="deal", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )

    @property
    def custom(self) -> dict[str, object]:
        return {
            v.field.code: v.value
            for v in self.custom_values
            if v.field.is_active and v.field.template_id in (None, self.template_id)
        }
