"""Сделки: список с фильтрами и итогами, карточка, форма с динамическими полями."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.core.permissions import DEALS_DELETE, DEALS_READ, DEALS_WRITE, TASKS_READ, TASKS_WRITE
from app.core.timezone import today_local
from app.db.session import get_db
from app.models import Client, Deal, StatusKind, User
from app.services import (
    activity_service, client_service, deal_service, deal_template_service, eav_service, status_service, task_service,
)
from app.services.errors import ValidationFailed
from app.web.deps import get_web_user, require_web_permission
from app.web.forms import fstr, get_form, optional_int, parse_page
from app.web.templating import flash, redirect, render

router = APIRouter(prefix="/deals")
PER_PAGE = 20
BASE_KEYS = (
    "title", "client_id", "amount", "currency", "deal_date", "status_id", "responsible_id", "description", "template_id",
)


def _deal_or_404(db: Session, deal_id: int, user: User) -> Deal:
    deal = deal_service.get_deal(db, deal_id, user)
    if deal is None:
        raise HTTPException(404, "Запись не найдена")
    return deal


def _active_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)))


@router.get("")
def deals_list(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(DEALS_READ))
):
    params = request.query_params
    fields = deal_service.active_fields(db)
    filters = eav_service.extract_custom_filters(fields, params)
    page = deal_service.list_deals(
        db,
        q=params.get("q"),
        status_id=params.get("status"),
        kind=params.get("kind"),
        client_id=params.get("client"),
        responsible_id=params.get("responsible"),
        date_from=params.get("date_from"),
        date_to=params.get("date_to"),
        amount_min=params.get("amount_min"),
        amount_max=params.get("amount_max"),
        custom_filters=filters,
        fields=fields,
        template=params.get("template"),
        sort=params.get("sort"),
        page=parse_page(params.get("page")),
        per_page=PER_PAGE,
        viewer=user,
    )
    client_id = optional_int(params.get("client"))
    simple = (
        "q", "status", "kind", "client", "responsible", "date_from", "date_to", "amount_min", "amount_max", "template",
    )
    ctx = {
        "page": page,
        "p": {key: params.get(key, "") for key in simple},
        "sort": params.get("sort") or deal_service.DEFAULT_SORT,
        "statuses": status_service.list_statuses(db),
        "users": _active_users(db),
        "templates": deal_template_service.list_templates(db),
        "kinds": [k.value for k in StatusKind],
        "client_filter": db.get(Client, client_id) if client_id else None,
        "filter_fields": eav_service.filterable_fields(fields),
        "filters": filters,
        "has_filters": any(params.get(key) for key in simple) or bool(filters),
    }
    return render(request, "deals/list.html", ctx, user=user)


@router.get("/board")
def deals_board(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(DEALS_READ))
):
    params = request.query_params
    client_id = optional_int(params.get("client"))
    columns = deal_service.board(
        db, q=params.get("q"), responsible_id=params.get("responsible"), client_id=client_id, viewer=user
    )
    ctx = {
        "columns": columns,
        "p": {"q": params.get("q", ""), "responsible": params.get("responsible", "")},
        "users": _active_users(db),
        "client_filter": db.get(Client, client_id) if client_id else None,
        "has_filters": bool(params.get("q") or params.get("responsible") or client_id),
        "movable": user.can(DEALS_WRITE),
        "all_statuses": [(c["status"].id, c["status"].name) for c in columns],
        "total_deals": sum(c["count"] for c in columns),
    }
    return render(request, "deals/board.html", ctx, user=user)


@router.get("/search")
def deals_search(request: Request, q: str = "", db: Session = Depends(get_db), user: User = Depends(get_web_user)):
    """Подсказки для выбора сделки (например, в форме задачи)."""
    if not (user.can(DEALS_READ) or user.can(TASKS_WRITE)):
        raise HTTPException(403, "Недостаточно прав")
    items = deal_service.search_for_picker(db, q, viewer=user)
    return JSONResponse([{"id": d.id, "name": d.title, "sub": d.client.name} for d in items])


def _applicable_fields(db: Session, template_raw: str):
    """Поля, которые реально пришли из формы: общие + поля выбранного шаблона."""
    return deal_template_service.fields_for_template(
        deal_service.active_fields(db), optional_int(template_raw)
    )


def _form_page(request, user, db, *, deal=None, form=None, cf_values=None, errors=None, status_code=200):
    form = dict(form or {})
    statuses = [s for s in status_service.list_statuses(db) if s.is_active or (deal and s.id == deal.status_id)]
    client_id = optional_int(str(form.get("client_id", "")))
    picked = db.get(Client, client_id) if client_id else None
    templates = [
        t for t in deal_template_service.list_templates(db)
        if t.is_active or (deal is not None and deal.template_id == t.id)
    ]
    template_ids = {t.id for t in templates}
    ctx = {
        "deal": deal,
        "form": form,
        "fields": [f for f in deal_service.active_fields(db) if f.template_id is None or f.template_id in template_ids],
        "templates": templates,
        "cf_values": cf_values or {},
        "errors": errors or {},
        "statuses": statuses,
        "users": _active_users(db),
        "picked_client": picked,
    }
    return render(request, "deals/form.html", ctx, user=user, status_code=status_code)


@router.get("/new")
def deal_new_page(
    request: Request,
    client_id: str = "",
    template_id: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(DEALS_WRITE)),
):
    default = status_service.get_default_status(db)
    form = {
        "client_id": client_id,
        "template_id": template_id,
        "currency": request.state.ui["default_currency"],
        "deal_date": today_local().isoformat(),
        "status_id": str(default.id) if default else "",
        "responsible_id": str(user.id),
        "amount": "",
    }
    return _form_page(request, user, db, form=form)


@router.post("/new")
def deal_create(
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(DEALS_WRITE)),
):
    data = {key: fstr(form, key) for key in BASE_KEYS}
    custom = eav_service.raw_from_form(_applicable_fields(db, data["template_id"]), form)
    try:
        deal = deal_service.create_deal(db, data=data, custom=custom, actor=user)
    except ValidationFailed as e:
        db.rollback()
        return _form_page(request, user, db, form=data, cf_values=custom, errors=e.errors, status_code=400)
    flash(request, f"Создано: «{deal.title}»")
    return redirect(f"/deals/{deal.id}")


@router.get("/{deal_id}")
def deal_detail(
    deal_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(DEALS_READ)),
):
    deal = _deal_or_404(db, deal_id, user)
    ctx = {
        "deal": deal,
        "fields": deal_template_service.fields_for_template(deal_service.active_fields(db), deal.template_id),
        "statuses": [s for s in status_service.list_statuses(db) if s.is_active or s.id == deal.status_id],
        "tasks": task_service.related_tasks(db, user, deal_id=deal.id) if user.can(TASKS_READ) else None,
        "feed": activity_service.feed(db, deal),
        "can_note": user.can(DEALS_WRITE),
    }
    return render(request, "deals/detail.html", ctx, user=user)


@router.get("/{deal_id}/edit")
def deal_edit_page(
    deal_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(DEALS_WRITE)),
):
    deal = _deal_or_404(db, deal_id, user)
    fields = deal_service.active_fields(db)
    form = {
        "title": deal.title,
        "client_id": str(deal.client_id),
        "amount": f"{deal.amount:.2f}",
        "currency": deal.currency,
        "deal_date": deal.deal_date.isoformat(),
        "status_id": str(deal.status_id),
        "responsible_id": str(deal.responsible_id or ""),
        "description": deal.description or "",
        "template_id": str(deal.template_id or ""),
    }
    return _form_page(request, user, db, deal=deal, form=form, cf_values=eav_service.form_values(deal, fields))


@router.post("/{deal_id}/edit")
def deal_update(
    deal_id: int,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(DEALS_WRITE)),
):
    deal = _deal_or_404(db, deal_id, user)
    data = {key: fstr(form, key) for key in BASE_KEYS}
    custom = eav_service.raw_from_form(_applicable_fields(db, data["template_id"]), form)
    try:
        deal_service.update_deal(db, deal, data=data, custom=custom, actor=user, partial=False)
    except ValidationFailed as e:
        db.rollback()
        db.refresh(deal)
        return _form_page(
            request, user, db, deal=deal, form=data, cf_values=custom, errors=e.errors, status_code=400
        )
    flash(request, "Изменения сохранены")
    return redirect(f"/deals/{deal.id}")


@router.post("/{deal_id}/status")
def deal_change_status(
    deal_id: int,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(DEALS_WRITE)),
):
    deal = _deal_or_404(db, deal_id, user)
    try:
        deal_service.change_status(db, deal, fstr(form, "status_id"), user)
        flash(request, f"Статус изменён на «{deal.status.name}»")
    except ValidationFailed as e:
        db.rollback()
        flash(request, "; ".join(e.errors.values()), "error")
    return redirect(f"/deals/{deal.id}")


@router.post("/{deal_id}/delete")
def deal_delete(
    deal_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(DEALS_DELETE)),
):
    deal = _deal_or_404(db, deal_id, user)
    title, client_id = deal.title, deal.client_id
    deal_service.delete_deal(db, deal)
    flash(request, f"Удалено: «{title}»")
    return redirect(f"/clients/{client_id}")


@router.post("/{deal_id}/notes")
def deal_note_add(
    deal_id: int,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(DEALS_WRITE)),
):
    deal = _deal_or_404(db, deal_id, user)
    try:
        activity_service.add_note(db, deal, author=user, body=fstr(form, "body"))
        flash(request, "Заметка добавлена")
    except ValidationFailed as e:
        db.rollback()
        flash(request, "; ".join(e.errors.values()), "error")
    return redirect(f"/deals/{deal.id}#history")


@router.post("/{deal_id}/notes/{note_id}/delete")
def deal_note_delete(
    deal_id: int,
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(DEALS_WRITE)),
):
    deal = _deal_or_404(db, deal_id, user)
    note = activity_service.get_note(db, deal, note_id)
    if note is None:
        raise HTTPException(404, "Заметка не найдена")
    if not activity_service.can_delete_note(user, note):
        raise HTTPException(403, "Удалить заметку может её автор или администратор")
    activity_service.delete_note(db, note)
    flash(request, "Заметка удалена")
    return redirect(f"/deals/{deal.id}#history")
