from pydantic import BaseModel, ConfigDict, Field

from app.models import StatusEntity, StatusKind


class StatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type: StatusEntity
    code: str
    name: str
    color: str
    kind: StatusKind
    sort_order: int
    is_default: bool
    is_active: bool


class StatusCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = "#6B7280"
    kind: StatusKind = StatusKind.OPEN
    is_default: bool = False
    is_active: bool = True


class StatusUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = None
    kind: StatusKind | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class StatusReorder(BaseModel):
    ids: list[int]
