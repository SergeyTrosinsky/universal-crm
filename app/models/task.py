from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import str_enum
from app.models.enums import TaskPriority, TaskStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.deal import Deal
    from app.models.user import User


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_assignee_status", "assignee_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(str_enum(TaskStatus, "task_status"), default=TaskStatus.TODO)
    priority: Mapped[TaskPriority] = mapped_column(
        str_enum(TaskPriority, "task_priority"), default=TaskPriority.NORMAL
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"), index=True)

    assignee: Mapped[User | None] = relationship(back_populates="assigned_tasks", foreign_keys=[assignee_id])
    creator: Mapped[User | None] = relationship(foreign_keys=[creator_id])
    client: Mapped[Client | None] = relationship(back_populates="tasks")
    deal: Mapped[Deal | None] = relationship(back_populates="tasks")

    @property
    def is_overdue(self) -> bool:
        """Не закрыта и срок уже прошёл."""
        if self.due_at is None or self.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
            return False
        due = self.due_at if self.due_at.tzinfo else self.due_at.replace(tzinfo=timezone.utc)
        return due < datetime.now(timezone.utc)
