from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import EntityType, FieldType


class CustomFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type: EntityType
    code: str
    label: str
    field_type: FieldType
    options: list[Any]
    placeholder: str | None
    help_text: str | None
    is_required: bool
    is_filterable: bool
    show_in_list: bool
    is_active: bool
    sort_order: int
    template_id: int | None = None


class CustomFieldCreate(BaseModel):
    entity_type: EntityType
    label: str = Field(min_length=1, max_length=150)
    field_type: FieldType
    code: str | None = Field(default=None, max_length=64, description="Если не задан — формируется из названия")
    options: list[str] = Field(default_factory=list, description="Варианты для select / multiselect")
    placeholder: str | None = None
    help_text: str | None = None
    is_required: bool = False
    is_filterable: bool = True
    show_in_list: bool = False
    is_active: bool = True
    template_id: int | None = Field(default=None, description="Только для полей сделок; пусто — общее поле")


class CustomFieldUpdate(BaseModel):
    """Код и тип поля после создания не меняются."""

    label: str | None = Field(default=None, min_length=1, max_length=150)
    options: list[str] | None = None
    placeholder: str | None = None
    help_text: str | None = None
    is_required: bool | None = None
    is_filterable: bool | None = None
    show_in_list: bool | None = None
    is_active: bool | None = None
    template_id: int | None = Field(default=None, description="Шаблон сделки; null — сделать поле общим")


class CustomFieldReorder(BaseModel):
    entity_type: EntityType
    ids: list[int]
