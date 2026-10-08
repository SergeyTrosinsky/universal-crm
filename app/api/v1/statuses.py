from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.errors import to_http
from app.core.permissions import SETTINGS_MANAGE
from app.db.session import get_db
from app.models import Status, User
from app.schemas.status import StatusCreate, StatusRead, StatusReorder, StatusUpdate
from app.services import status_service
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/statuses", tags=["statuses"])


def _get_or_404(db: Session, status_id: int) -> Status:
    item = status_service.get_status(db, status_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Статус не найден")
    return item


@router.get("", response_model=list[StatusRead])
def list_statuses(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Status]:
    return status_service.list_statuses(db, only_active=not include_inactive)


@router.post("", response_model=StatusRead, status_code=status.HTTP_201_CREATED)
def create_status(
    payload: StatusCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> Status:
    try:
        return status_service.create_status(db, **payload.model_dump())
    except ValidationFailed as e:
        raise to_http(e) from e


@router.post("/reorder", response_model=list[StatusRead])
def reorder_statuses(
    payload: StatusReorder,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> list[Status]:
    try:
        return status_service.reorder_statuses(db, payload.ids)
    except ValidationFailed as e:
        raise to_http(e) from e


@router.patch("/{status_id}", response_model=StatusRead)
def update_status(
    status_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> Status:
    item = _get_or_404(db, status_id)
    try:
        return status_service.update_status(db, item, **payload.model_dump(exclude_unset=True))
    except ValidationFailed as e:
        raise to_http(e) from e


@router.delete("/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_status(
    status_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> Response:
    try:
        status_service.delete_status(db, _get_or_404(db, status_id))
    except ValidationFailed as e:
        raise to_http(e) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)
