from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.deal import Deal
    from app.models.role import Role
    from app.models.task import Task


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), index=True)
    role: Mapped[Role] = relationship(back_populates="users", lazy="joined")

    owned_clients: Mapped[list[Client]] = relationship(back_populates="owner")
    responsible_deals: Mapped[list[Deal]] = relationship(back_populates="responsible")
    assigned_tasks: Mapped[list[Task]] = relationship(
        back_populates="assignee", foreign_keys="Task.assignee_id"
    )

    @property
    def label(self) -> str:
        """«Имя (Роль)» — для списков выбора, чтобы не назначить не того: на странице видны только имена."""
        return f"{self.full_name} ({self.role.name})" if self.role is not None else self.full_name

    def can(self, perm: str) -> bool:
        return self.is_active and self.role.has_permission(perm)
