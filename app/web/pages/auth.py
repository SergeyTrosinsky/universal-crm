from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.api.deps import resolve_user
from app.core import csrf
from app.core.config import get_settings
from app.core.rate_limit import client_ip, login_limiter, wait_text
from app.core.security import clear_auth_cookie, create_access_token, set_auth_cookie
from app.db.session import get_db
from app.models import User
from app.services.auth_service import authenticate
from app.web.deps import get_web_user
from app.web.pages.dashboard import dashboard_page
from app.web.templating import redirect, render

router = APIRouter()


def safe_next(url: str | None) -> str:
    """Только локальные пути — защита от open redirect."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return "/"


@router.get("/")
def home(request: Request, db: Session = Depends(get_db), user: User = Depends(get_web_user)):
    if user.can("dashboard:read"):
        return dashboard_page(request, db, user)
    # Нет права на главную: ведём в первый доступный раздел.
    for permission, url in (("clients:read", "/clients"), ("deals:read", "/deals"), ("tasks:read", "/tasks")):
        if user.can(permission):
            return redirect(url, 302)
    return redirect("/profile", 302)


@router.get("/login")
def login_page(request: Request, next: str = "/", db: Session = Depends(get_db)):
    if resolve_user(db, request.cookies.get(get_settings().AUTH_COOKIE_NAME)):
        return redirect(safe_next(next))
    return render(request, "auth/login.html", {"next": safe_next(next), "email": "", "error": None})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    wait = login_limiter.retry_after(email, ip)
    if wait:
        response = render(
            request,
            "auth/login.html",
            {
                "next": safe_next(next), "email": email,
                "error": f"Слишком много неудачных попыток входа. Повторите через {wait_text(wait)}",
            },
            status_code=429,
        )
        response.headers["Retry-After"] = str(wait)
        return response
    user = authenticate(db, email, password)
    if user is None:
        login_limiter.register_failure(email, ip)
        return render(
            request,
            "auth/login.html",
            {"next": safe_next(next), "email": email, "error": "Неверный email или пароль"},
            status_code=401,
        )
    login_limiter.register_success(email, ip)
    csrf.reset_token(request)
    response = redirect(safe_next(next))
    set_auth_cookie(response, create_access_token(user.id, user.hashed_password))
    return response


@router.post("/logout")
def logout(request: Request):
    csrf.reset_token(request)
    response = redirect("/login")
    clear_auth_cookie(response)
    return response
