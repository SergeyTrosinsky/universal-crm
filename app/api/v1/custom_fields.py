from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.errors import to_http
from app.core.permissions import SETTINGS_MANAGE
from app.db.session import get_db
from app.models import CustomField, EntityType, User
from app.schemas.custom_field import (
    CustomFieldCreate, CustomFieldRead, CustomFieldReorder, CustomFieldUpdate,
)
from app.services import custom_field_service
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/custom-fields", tags=["custom-fields"])


def _get_or_404(db: Session, field_id: int) -> CustomField:
    field = custom_field_service.get_field(db, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поле не найдено")
    return field


@router.get("", response_model=list[CustomFieldRead])
def list_fields(
    entity_type: EntityType | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[CustomField]:
    """Определения полей в порядке отображения. Нужны клиентам API, чтобы строить формы."""
    return custom_field_service.list_fields(db, entity_type, only_active=not include_inactive)


@router.post("", response_model=CustomFieldRead, status_code=status.HTTP_201_CREATED)
def create_field(
    payload: CustomFieldCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> CustomField:
    try:
        return custom_field_service.create_field(db, **payload.model_dump())
    except ValidationFailed as e:
        raise to_http(e) from e


@router.post("/reorder", response_model=list[CustomFieldRead])
def reorder_fields(
    payload: CustomFieldReorder,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> list[CustomField]:
    """Задаёт порядок: ids — id полей в желаемой последовательности."""
    try:
        return custom_field_service.reorder_fields(db, payload.entity_type, payload.ids)
    except ValidationFailed as e:
        raise to_http(e) from e


@router.get("/{field_id}", response_model=CustomFieldRead)
def get_field(
    field_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> CustomField:
    return _get_or_404(db, field_id)


@router.patch("/{field_id}", response_model=CustomFieldRead)
def update_field(
    field_id: int,
    payload: CustomFieldUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> CustomField:
    field = _get_or_404(db, field_id)
    try:
        return custom_field_service.update_field(db, field, **payload.model_dump(exclude_unset=True))
    except ValidationFailed as e:
        raise to_http(e) from e


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(
    field_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> Response:
    """Удаляет поле и все его значения. Чтобы только скрыть — PATCH {"is_active": false}."""
    custom_field_service.delete_field(db, _get_or_404(db, field_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
