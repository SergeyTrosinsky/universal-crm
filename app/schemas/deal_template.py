from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DealTemplateBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class DealTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DealTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    is_active: bool = True


class DealTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    is_active: bool | None = None
