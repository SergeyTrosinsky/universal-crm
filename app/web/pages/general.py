"""Общие настройки: название CRM, валюта по умолчанию, термины."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.core.labels import CURRENCIES
from app.core.permissions import SETTINGS_MANAGE
from app.db.session import get_db
from app.models import User
from app.services import settings_service
from app.services.errors import ValidationFailed
from app.web.deps import require_web_permission
from app.web.forms import fstr, get_form
from app.web.templating import flash, redirect, render

router = APIRouter(prefix="/settings/general")
guard = require_web_permission(SETTINGS_MANAGE)


def _page(request, user, *, form, errors=None, status_code=200):
    ctx = {
        "form": form,
        "errors": errors or {},
        "currency_options": [(code, f"{code} {symbol}") for code, symbol in CURRENCIES.items()],
        "labels": settings_service.LABELS,
        "env_name": request.state.ui["app_name"] if not form.get("app_name") else "",
    }
    return render(request, "settings/general.html", ctx, user=user, status_code=status_code)


@router.get("")
def general_page(request: Request, db: Session = Depends(get_db), user: User = Depends(guard)):
    return _page(request, user, form=settings_service.get_all(db))


@router.post("")
def general_save(
    request: Request, form: FormData = Depends(get_form), db: Session = Depends(get_db), user: User = Depends(guard)
):
    data = {key: fstr(form, key) for key in settings_service.DEFAULTS}
    try:
        settings_service.update(db, data)
    except ValidationFailed as e:
        db.rollback()
        return _page(request, user, form=data, errors=e.errors, status_code=400)
    flash(request, "Настройки сохранены")
    return redirect("/settings/general")


@router.post("/reset")
def general_reset(request: Request, db: Session = Depends(get_db), user: User = Depends(guard)):
    settings_service.reset(db)
    flash(request, "Настройки сброшены к значениям по умолчанию")
    return redirect("/settings/general")
