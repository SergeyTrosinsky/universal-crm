from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.permissions import ALL_PERMISSIONS, USERS_MANAGE
from app.db.session import get_db
from app.models import Role, User
from app.schemas.role import RoleCreate, RoleRead, RoleUpdate
from app.services import role_service
from app.services.role_service import RoleError

router = APIRouter(prefix="/roles", tags=["roles"])


def _get_or_404(db: Session, role_id: int) -> Role:
    role = role_service.get_role(db, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Роль не найдена")
    return role


@router.get("", response_model=list[RoleRead])
def list_roles(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Role]:
    return role_service.list_roles(db)


@router.get("/permissions", response_model=list[str])
def list_permissions(_: User = Depends(get_current_user)) -> list[str]:
    """Каталог прав, которые можно выдавать ролям."""
    return ALL_PERMISSIONS


@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(USERS_MANAGE)),
) -> Role:
    try:
        return role_service.create_role(db, **payload.model_dump())
    except RoleError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.patch("/{role_id}", response_model=RoleRead)
def update_role(
    role_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(USERS_MANAGE)),
) -> Role:
    role = _get_or_404(db, role_id)
    try:
        return role_service.update_role(db, role, **payload.model_dump(exclude_unset=True))
    except RoleError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(USERS_MANAGE)),
) -> Response:
    role = _get_or_404(db, role_id)
    try:
        role_service.delete_role(db, role)
    except RoleError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)
