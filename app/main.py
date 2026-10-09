import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.init_db import ensure_schema, seed_defaults
from app.db.session import SessionLocal
from app.services.user_service import ensure_first_admin
from app.web.deps import LoginRequired, login_redirect_url
from app.web.router import web_router
from app.web.templating import render

BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("crm")

DEFAULT_SECRET = "change-me-in-production"


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema()
    with SessionLocal() as db:
        seed_defaults(db)
        admin = ensure_first_admin(db)
        if admin:
            log.warning("Создан первый администратор: %s", admin.email)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.SECRET_KEY == DEFAULT_SECRET and not settings.DEBUG:
        log.warning("SECRET_KEY не задан — используется небезопасное значение по умолчанию!")

    app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        session_cookie="crm_session",
        same_site="lax",
        https_only=settings.AUTH_COOKIE_SECURE,
        max_age=None,
    )
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(web_router)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(LoginRequired)
    async def login_required_handler(_: Request, exc: LoginRequired):
        return RedirectResponse(login_redirect_url(exc.next_url), status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        wants_html = "text/html" in request.headers.get("accept", "")
        if request.url.path.startswith("/api") or not wants_html:
            return await http_exception_handler(request, exc)
        return render(
            request, "error.html", {"code": exc.status_code, "message": exc.detail}, status_code=exc.status_code
        )

    return app


app = create_app()
