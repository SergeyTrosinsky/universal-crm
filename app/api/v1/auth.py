from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.rate_limit import client_ip, login_limiter, wait_text
from app.core.security import clear_auth_cookie, create_access_token, set_auth_cookie
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, Token
from app.schemas.user import UserRead
from app.services.auth_service import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])

_BAD_CREDENTIALS = "Неверный email или пароль"


def _guarded_login(db: Session, request: Request, email: str, password: str) -> User:
    """Проверка пароля с ограничением числа неудачных попыток (429 + Retry-After)."""
    ip = client_ip(request)
    wait = login_limiter.retry_after(email, ip)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Слишком много неудачных попыток входа. Повторите через {wait_text(wait)}",
            headers={"Retry-After": str(wait)},
        )
    user = authenticate(db, email, password)
    if user is None:
        login_limiter.register_failure(email, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_CREDENTIALS)
    login_limiter.register_success(email, ip)
    return user


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> Token:
    """Вход по JSON. Токен возвращается в теле и ставится в HttpOnly-cookie."""
    user = _guarded_login(db, request, payload.email, payload.password)
    token = create_access_token(user.id, user.hashed_password)
    set_auth_cookie(response, token)
    return Token(access_token=token)


@router.post("/token", response_model=Token)
def token_for_swagger(
    request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    """OAuth2 password flow для кнопки Authorize в /docs (username = email)."""
    user = _guarded_login(db, request, form.username, form.password)
    return Token(access_token=create_access_token(user.id, user.hashed_password))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    clear_auth_cookie(response)


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user
