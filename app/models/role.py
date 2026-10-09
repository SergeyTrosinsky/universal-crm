from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import JSONType
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Role(TimestampMixin, Base):
    """Роль = именованный набор прав (см. app/core/permissions.py)."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    users: Mapped[list[User]] = relationship(back_populates="role")

    def has_permission(self, perm: str) -> bool:
        perms = self.permissions or []
        return "*" in perms or perm in perms
