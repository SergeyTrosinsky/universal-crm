from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import USERS_MANAGE
from app.db.session import get_db
from app.models import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services import user_service
from app.services.user_service import UserError

router = APIRouter(prefix="/users", tags=["users"])


def _get_or_404(db: Session, user_id: int) -> User:
    user = user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    return user


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db), _: User = Depends(require_permission(USERS_MANAGE))
) -> list[User]:
    return user_service.list_users(db)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(USERS_MANAGE)),
) -> User:
    try:
        return user_service.create_user(db, actor=actor, **payload.model_dump())
    except UserError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission(USERS_MANAGE))
) -> User:
    return _get_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(USERS_MANAGE)),
) -> User:
    user = _get_or_404(db, user_id)
    try:
        return user_service.update_user(
            db, user, actor=actor, **payload.model_dump(exclude_unset=True)
        )
    except UserError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
