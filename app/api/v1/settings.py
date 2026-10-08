from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.errors import to_http
from app.core.permissions import SETTINGS_MANAGE
from app.db.session import get_db
from app.models import User
from app.services import settings_service
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/settings", tags=["settings"])


class GeneralSettings(BaseModel):
    app_name: str = Field(description="Пусто — название из APP_NAME")
    default_currency: str
    client_pl: str
    client_sg: str
    client_acc: str
    deal_pl: str
    deal_sg: str
    deal_acc: str


class GeneralSettingsUpdate(BaseModel):
    app_name: str | None = None
    default_currency: str | None = None
    client_pl: str | None = None
    client_sg: str | None = None
    client_acc: str | None = None
    deal_pl: str | None = None
    deal_sg: str | None = None
    deal_acc: str | None = None


@router.get("/general", response_model=GeneralSettings)
def get_general(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    return settings_service.get_all(db)


@router.patch("/general", response_model=GeneralSettings)
def update_general(
    payload: GeneralSettingsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> dict:
    """Меняются только присланные ключи."""
    try:
        return settings_service.update(db, payload.model_dump(exclude_unset=True))
    except ValidationFailed as e:
        raise to_http(e) from e


@router.post("/general/reset", response_model=GeneralSettings)
def reset_general(db: Session = Depends(get_db), _: User = Depends(require_permission(SETTINGS_MANAGE))) -> dict:
    settings_service.reset(db)
    return settings_service.get_all(db)
