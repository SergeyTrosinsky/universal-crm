from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import str_enum
from app.models.enums import StatusEntity, StatusKind
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.deal import Deal


class Status(TimestampMixin, Base):
    """Динамический статус (воронка). Пользователь создаёт/переименовывает/упорядочивает их в UI.

    `kind` (open/won/lost) задаёт смысл статуса для статистики и не зависит от названия.
    """

    __tablename__ = "statuses"
    __table_args__ = (UniqueConstraint("entity_type", "code", name="uq_statuses_entity_type_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[StatusEntity] = mapped_column(
        str_enum(StatusEntity, "status_entity"), default=StatusEntity.DEAL, index=True
    )
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(7), default="#6B7280")
    kind: Mapped[StatusKind] = mapped_column(str_enum(StatusKind, "status_kind"), default=StatusKind.OPEN)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    deals: Mapped[list[Deal]] = relationship(back_populates="status")
