from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.client import ClientBrief
from app.schemas.deal_template import DealTemplateBrief
from app.schemas.status import StatusRead
from app.schemas.user import UserBrief


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    amount: Decimal
    currency: str
    deal_date: date
    closed_at: datetime | None
    status: StatusRead
    client: ClientBrief
    responsible: UserBrief | None
    template: DealTemplateBrief | None = None
    created_at: datetime
    updated_at: datetime
    custom: dict[str, Any]


class DealCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    client_id: int
    description: str | None = None
    amount: Decimal = Decimal("0")
    currency: str | None = Field(default=None, description="Код валюты; по умолчанию — из общих настроек")
    deal_date: date | None = Field(default=None, description="По умолчанию — сегодня")
    status_id: int | None = Field(default=None, description="По умолчанию — основной статус")
    responsible_id: int | None = Field(default=None, description="По умолчанию — текущий пользователь")
    template_id: int | None = Field(default=None, description="Шаблон сделки; пусто — стандартная форма")
    custom: dict[str, Any] = Field(default_factory=dict)


class DealUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    client_id: int | None = None
    description: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    deal_date: date | None = None
    status_id: int | None = None
    responsible_id: int | None = None
    template_id: int | None = None
    custom: dict[str, Any] | None = None


class DealStatusChange(BaseModel):
    status_id: int


class DealTotal(BaseModel):
    currency: str
    amount: Decimal


class DealPage(BaseModel):
    items: list[DealRead]
    total: int
    page: int
    per_page: int
    pages: int
    totals: list[DealTotal]
