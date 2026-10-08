from datetime import datetime

from pydantic import BaseModel, Field


class ChangeOut(BaseModel):
    label: str
    old: str
    new: str


class ActivityItemOut(BaseModel):
    type: str = Field(description="event (изменение) | note (заметка)")
    id: int
    at: datetime
    author: str | None
    kind: str | None = Field(None, description="Для события: created | updated")
    changes: list[ChangeOut] | None = None
    body: str | None = Field(None, description="Для заметки: текст")


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
