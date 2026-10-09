from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONType

ONE_OWNER = "(client_id IS NOT NULL AND deal_id IS NULL) OR (client_id IS NULL AND deal_id IS NOT NULL)"


class ActivityEvent(Base):
    """Запись журнала: кто и что изменил в клиенте или сделке.

    Владелец — клиент ИЛИ сделка (реальные FK с каскадом: удалили карточку — удалился и её журнал).
    Имя автора хранится отдельно, чтобы запись не «осиротела» после удаления пользователя.
    changes — список {"label": "Сумма", "old": "1 000 RUB", "new": "1 500 RUB"} (значения уже в читаемом виде)."""

    __tablename__ = "activity_events"
    __table_args__ = (
        CheckConstraint(ONE_OWNER, name="exactly_one_owner"),
        Index("ix_activity_events_client", "client_id", "created_at"),
        Index("ix_activity_events_deal", "deal_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    kind: Mapped[str] = mapped_column(String(20))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_name: Mapped[str | None] = mapped_column(String(255))
    changes: Mapped[Any | None] = mapped_column(JSONType)


class Note(Base):
    """Заметка (комментарий) сотрудника в карточке клиента или сделки."""

    __tablename__ = "notes"
    __table_args__ = (
        CheckConstraint(ONE_OWNER, name="exactly_one_owner"),
        Index("ix_notes_client", "client_id", "created_at"),
        Index("ix_notes_deal", "deal_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    body: Mapped[str] = mapped_column(Text)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_name: Mapped[str | None] = mapped_column(String(255))
