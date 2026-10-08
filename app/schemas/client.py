from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import ClientType


class ClientBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: ClientType
    name: str
    company_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    notes: str | None
    owner_id: int | None
    created_at: datetime
    updated_at: datetime
    custom: dict[str, Any] = Field(description="Значения кастомных полей: {код поля: значение}")


class ClientCreate(BaseModel):
    type: ClientType = ClientType.PERSON
    name: str = Field(min_length=1, max_length=255)
    company_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    notes: str | None = None
    owner_id: int | None = Field(default=None, description="По умолчанию — текущий пользователь")
    custom: dict[str, Any] = Field(default_factory=dict)


class ClientUpdate(BaseModel):
    """Меняются только присланные поля (PATCH). В custom — только присланные коды;
    null очищает значение."""

    type: ClientType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    company_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    notes: str | None = None
    owner_id: int | None = None
    custom: dict[str, Any] | None = None
