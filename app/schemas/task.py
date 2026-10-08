from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import TaskPriority, TaskStatus
from app.schemas.client import ClientBrief
from app.schemas.user import UserBrief


class DealBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    completed_at: datetime | None
    is_overdue: bool
    assignee: UserBrief | None
    creator_id: int | None
    client: ClientBrief | None
    deal: DealBrief | None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.NORMAL
    due_at: datetime | None = Field(default=None, description="Без часового пояса — время APP_TIMEZONE")
    assignee_id: int | None = Field(default=None, description="По умолчанию — текущий пользователь")
    client_id: int | None = None
    deal_id: int | None = Field(default=None, description="Клиент подставится из сделки")


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    assignee_id: int | None = None
    client_id: int | None = None
    deal_id: int | None = None


class TaskStatusChange(BaseModel):
    status: TaskStatus
