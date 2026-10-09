from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import JSONType, str_enum
from app.models.enums import EntityType, FieldType
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.custom_value import CustomValue
    from app.models.deal_template import DealTemplate

FIELD_STORAGE: dict[FieldType, str] = {
    FieldType.TEXT: "value_text",
    FieldType.TEXTAREA: "value_text",
    FieldType.PHONE: "value_text",
    FieldType.EMAIL: "value_text",
    FieldType.URL: "value_text",
    FieldType.SELECT: "value_text",
    FieldType.MULTISELECT: "value_json",
    FieldType.INTEGER: "value_number",
    FieldType.DECIMAL: "value_number",
    FieldType.DATE: "value_date",
    FieldType.DATETIME: "value_datetime",
    FieldType.BOOLEAN: "value_bool",
}


class CustomField(TimestampMixin, Base):
    """EAV: определение (Attribute). Создаётся пользователем без правки кода."""

    __tablename__ = "custom_fields"
    __table_args__ = (UniqueConstraint("entity_type", "code", name="uq_custom_fields_entity_type_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(str_enum(EntityType, "custom_entity"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(150))
    field_type: Mapped[FieldType] = mapped_column(str_enum(FieldType, "custom_field_type"))
    options: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    placeholder: Mapped[str | None] = mapped_column(String(255))
    help_text: Mapped[str | None] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_filterable: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_list: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("deal_templates.id", ondelete="SET NULL"), index=True
    )

    template: Mapped[DealTemplate | None] = relationship(back_populates="fields")
    values: Mapped[list[CustomValue]] = relationship(
        back_populates="field", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def storage_column(self) -> str:
        return FIELD_STORAGE[self.field_type]
