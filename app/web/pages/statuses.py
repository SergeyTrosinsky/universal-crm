"""Настройки CRM: статусы сделок."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.core.permissions import SETTINGS_MANAGE
from app.db.session import get_db
from app.models import Status, StatusKind, User
from app.services import status_service
from app.services.errors import ValidationFailed
from app.web.deps import require_web_permission
from app.web.forms import fbool, fstr, get_form
from app.web.templating import flash, redirect, render

router = APIRouter(prefix="/settings/statuses")
guard = require_web_permission(SETTINGS_MANAGE)
KINDS = [k.value for k in StatusKind]


def _status_or_404(db: Session, status_id: int) -> Status:
    item = status_service.get_status(db, status_id)
    if item is None:
        raise HTTPException(404, "Статус не найден")
    return item


def _form_page(request, user, *, item=None, form=None, errors=None, deals_count=0, status_code=200):
    ctx = {
        "item": item,
        "form": form or {},
        "errors": errors or {},
        "kinds": KINDS,
        "deals_count": deals_count,
    }
    return render(request, "settings/status_form.html", ctx, user=user, status_code=status_code)


def _form_dict(form: FormData) -> dict:
    return {
        "name": fstr(form, "name"),
        "color": fstr(form, "color", "#6B7280"),
        "kind": fstr(form, "kind", "open"),
        "is_default": fbool(form, "is_default"),
        "is_active": fbool(form, "is_active"),
    }


@router.get("")
def statuses_page(request: Request, db: Session = Depends(get_db), user: User = Depends(guard)):
    ctx = {"statuses": status_service.list_statuses(db), "counts": status_service.deal_counts(db)}
    return render(request, "settings/statuses.html", ctx, user=user)


@router.get("/new")
def status_new_page(request: Request, user: User = Depends(guard)):
    return _form_page(request, user, form={"color": "#6B7280", "kind": "open", "is_active": True})


@router.post("/new")
def status_create(
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    values = _form_dict(form)
    try:
        item = status_service.create_status(db, **values)
    except ValidationFailed as e:
        db.rollback()
        return _form_page(request, user, form=values, errors=e.errors, status_code=400)
    flash(request, f"Статус «{item.name}» создан")
    return redirect("/settings/statuses")


@router.get("/{status_id}/edit")
def status_edit_page(
    status_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    item = _status_or_404(db, status_id)
    form = {
        "name": item.name,
        "color": item.color,
        "kind": item.kind.value,
        "is_default": item.is_default,
        "is_active": item.is_active,
    }
    return _form_page(
        request, user, item=item, form=form, deals_count=status_service.deal_counts(db).get(item.id, 0)
    )


@router.post("/{status_id}/edit")
def status_update(
    status_id: int,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    item = _status_or_404(db, status_id)
    values = _form_dict(form)
    try:
        status_service.update_status(db, item, **values)
    except ValidationFailed as e:
        db.rollback()
        db.refresh(item)
        return _form_page(
            request,
            user,
            item=item,
            form=values,
            errors=e.errors,
            deals_count=status_service.deal_counts(db).get(item.id, 0),
            status_code=400,
        )
    flash(request, "Статус сохранён")
    return redirect("/settings/statuses")


@router.post("/{status_id}/move")
def status_move(
    status_id: int,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    item = _status_or_404(db, status_id)
    try:
        status_service.move_status(db, item, fstr(form, "direction"))
    except ValidationFailed:
        pass
    return redirect("/settings/statuses")


@router.post("/{status_id}/default")
def status_make_default(
    status_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    item = _status_or_404(db, status_id)
    try:
        status_service.update_status(db, item, is_default=True)
        flash(request, f"«{item.name}» теперь основной статус для новых сделок")
    except ValidationFailed as e:
        flash(request, "; ".join(e.errors.values()), "error")
    return redirect("/settings/statuses")


@router.post("/{status_id}/delete")
def status_delete(
    status_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    item = _status_or_404(db, status_id)
    name = item.name
    try:
        status_service.delete_status(db, item)
    except ValidationFailed as e:
        db.rollback()
        flash(request, "; ".join(e.errors.values()), "error")
        return redirect("/settings/statuses")
    flash(request, f"Статус «{name}» удалён")
    return redirect("/settings/statuses")
