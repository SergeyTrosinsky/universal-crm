from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.core.security import create_access_token, set_auth_cookie, verify_password
from app.db.session import get_db
from app.models import User
from app.services import user_service
from app.services.user_service import UserError
from app.web.deps import get_web_user
from app.web.templating import flash, redirect, render

router = APIRouter()


def _profile_page(request: Request, user: User, error: str | None = None, status_code: int = 200):
    return render(request, "profile.html", {"error": error}, user=user, status_code=status_code)


@router.get("/profile")
def profile(request: Request, user: User = Depends(get_web_user)):
    return _profile_page(request, user)


@router.post("/profile")
def update_profile(
    request: Request,
    full_name: str = Form(""),
    user: User = Depends(get_web_user),
    db: Session = Depends(get_db),
):
    try:
        user_service.rename_self(db, user, full_name)
    except UserError as e:
        db.rollback()
        return _profile_page(request, user, str(e), 400)
    flash(request, "Профиль обновлён")
    return redirect("/profile")


@router.post("/profile/password")
def change_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    user: User = Depends(get_web_user),
    db: Session = Depends(get_db),
):
    if not verify_password(current_password, user.hashed_password):
        return _profile_page(request, user, "Текущий пароль указан неверно", 400)
    if new_password != confirm_password:
        return _profile_page(request, user, "Новый пароль и подтверждение не совпадают", 400)
    try:
        user_service.change_own_password(db, user, new_password)
    except UserError as e:
        db.rollback()
        return _profile_page(request, user, str(e), 400)

    flash(request, "Пароль изменён")
    response = redirect("/profile")
    # Отпечаток пароля в токене изменился — выдаём новый токен для текущей сессии.
    set_auth_cookie(response, create_access_token(user.id, user.hashed_password))
    return response
