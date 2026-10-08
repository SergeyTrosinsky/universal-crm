from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import str_enum
from app.models.enums import ClientType
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.custom_value import CustomValue
    from app.models.deal import Deal
    from app.models.task import Task
    from app.models.user import User


class Client(TimestampMixin, Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[ClientType] = mapped_column(str_enum(ClientType, "client_type"), default=ClientType.PERSON)
    name: Mapped[str] = mapped_column(String(255), index=True)
    company_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50), index=True)
    address: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    owner: Mapped[User | None] = relationship(back_populates="owned_clients")

    deals: Mapped[list[Deal]] = relationship(
        back_populates="client", cascade="all, delete-orphan", passive_deletes=True
    )
    tasks: Mapped[list[Task]] = relationship(back_populates="client")
    custom_values: Mapped[list[CustomValue]] = relationship(
        back_populates="client", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )

    @property
    def custom(self) -> dict[str, object]:
        """{code поля: значение} — удобно для шаблонов."""
        return {v.field.code: v.value for v in self.custom_values if v.field.is_active}
