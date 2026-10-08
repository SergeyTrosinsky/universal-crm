from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.security import validate_password
from app.core.validators import normalize_email
from app.schemas.role import RoleRead

Email = Annotated[str, AfterValidator(normalize_email)]
Password = Annotated[str, AfterValidator(validate_password)]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    is_active: bool
    role: RoleRead
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    email: Email
    full_name: str = Field(min_length=1, max_length=255)
    password: Password
    role_id: int
    is_active: bool = True


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role_id: int | None = None
    is_active: bool | None = None
    password: Password | None = None


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
