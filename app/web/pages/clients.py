"""Клиенты: список с поиском/фильтрами, карточка, форма с динамическими полями."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.core.permissions import CLIENTS_DELETE, CLIENTS_READ, CLIENTS_WRITE, DEALS_WRITE, TASKS_READ
from app.db.session import get_db
from app.models import Client, ClientType, User
from app.services import activity_service, client_service, eav_service, task_service
from app.services.errors import ValidationFailed
from app.web.deps import get_web_user, require_web_permission
from app.web.forms import fstr, get_form, optional_int, parse_page
from app.web.templating import flash, redirect, render

router = APIRouter(prefix="/clients")
PER_PAGE = 20
BASE_KEYS = ("type", "name", "company_name", "email", "phone", "address", "notes", "owner_id")


def _client_or_404(db: Session, client_id: int) -> Client:
    client = client_service.get_client(db, client_id)
    if client is None:
        raise HTTPException(404, "Клиент не найден")
    return client


def _active_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)))


@router.get("")
def clients_list(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(CLIENTS_READ))
):
    params = request.query_params
    fields = client_service.active_fields(db)
    filters = eav_service.extract_custom_filters(fields, params)
    page = client_service.list_clients(
        db,
        q=params.get("q"),
        client_type=params.get("type"),
        owner_id=optional_int(params.get("owner")),
        custom_filters=filters,
        fields=fields,
        sort=params.get("sort"),
        page=parse_page(params.get("page")),
        per_page=PER_PAGE,
    )
    ctx = {
        "page": page,
        "q": params.get("q", ""),
        "type_filter": params.get("type", ""),
        "owner_filter": params.get("owner", ""),
        "sort": params.get("sort") or client_service.DEFAULT_SORT,
        "owners": _active_users(db),
        "filter_fields": eav_service.filterable_fields(fields),
        "list_fields": [f for f in fields if f.show_in_list],
        "filters": filters,
        "has_filters": bool(params.get("q") or params.get("type") or params.get("owner") or filters),
        "client_types": [t.value for t in ClientType],
    }
    return render(request, "clients/list.html", ctx, user=user)


@router.get("/search")
def clients_search(request: Request, q: str = "", db: Session = Depends(get_db), user: User = Depends(get_web_user)):
    """Подсказки для выбора клиента в форме сделки."""
    if not (user.can(CLIENTS_READ) or user.can(DEALS_WRITE)):
        raise HTTPException(403, "Недостаточно прав")
    items = client_service.search_for_picker(db, q)
    return JSONResponse([{"id": c.id, "name": c.name, "phone": c.phone or "", "email": c.email or ""} for c in items])


def _form_page(request, user, db, *, client=None, form=None, cf_values=None, errors=None, status_code=200):
    fields = client_service.active_fields(db)
    ctx = {
        "client": client,
        "form": form or {},
        "fields": fields,
        "cf_values": cf_values or {},
        "errors": errors or {},
        "owners": _active_users(db),
        "client_types": [t.value for t in ClientType],
    }
    return render(request, "clients/form.html", ctx, user=user, status_code=status_code)


@router.get("/new")
def client_new_page(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(CLIENTS_WRITE))
):
    return _form_page(request, user, db, form={"type": "person", "owner_id": str(user.id)})


@router.post("/new")
def client_create(
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(CLIENTS_WRITE)),
):
    fields = client_service.active_fields(db)
    data = {key: fstr(form, key) for key in BASE_KEYS}
    custom = eav_service.raw_from_form(fields, form)
    try:
        client = client_service.create_client(db, data=data, custom=custom, actor=user)
    except ValidationFailed as e:
        db.rollback()
        return _form_page(request, user, db, form=data, cf_values=custom, errors=e.errors, status_code=400)
    flash(request, f"Клиент «{client.name}» создан")
    return redirect(f"/clients/{client.id}")


@router.get("/{client_id}")
def client_detail(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(CLIENTS_READ)),
):
    client = _client_or_404(db, client_id)
    deals = client_service.list_client_deals(db, client.id, user)
    totals: dict[str, object] = {}
    for deal in deals:
        totals[deal.currency] = totals.get(deal.currency, 0) + deal.amount
    ctx = {
        "client": client,
        "fields": client_service.active_fields(db),
        "deals": deals,
        "totals": list(totals.items()),
        "tasks": task_service.related_tasks(db, user, client_id=client.id) if user.can(TASKS_READ) else None,
        "feed": activity_service.feed(db, client),
        "can_note": user.can(CLIENTS_WRITE),
    }
    return render(request, "clients/detail.html", ctx, user=user)


@router.get("/{client_id}/edit")
def client_edit_page(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(CLIENTS_WRITE)),
):
    client = _client_or_404(db, client_id)
    fields = client_service.active_fields(db)
    form = {
        "type": client.type.value,
        "name": client.name,
        "company_name": client.company_name or "",
        "email": client.email or "",
        "phone": client.phone or "",
        "address": client.address or "",
        "notes": client.notes or "",
        "owner_id": str(client.owner_id or ""),
    }
    return _form_page(request, user, db, client=client, form=form, cf_values=eav_service.form_values(client, fields))


@router.post("/{client_id}/edit")
def client_update(
    client_id: int,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(CLIENTS_WRITE)),
):
    client = _client_or_404(db, client_id)
    fields = client_service.active_fields(db)
    data = {key: fstr(form, key) for key in BASE_KEYS}
    custom = eav_service.raw_from_form(fields, form)
    try:
        client_service.update_client(db, client, data=data, custom=custom, actor=user, partial=False)
    except ValidationFailed as e:
        db.rollback()
        db.refresh(client)
        return _form_page(
            request, user, db, client=client, form=data, cf_values=custom, errors=e.errors, status_code=400
        )
    flash(request, "Изменения сохранены")
    return redirect(f"/clients/{client.id}")


@router.post("/{client_id}/delete")
def client_delete(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(CLIENTS_DELETE)),
):
    client = _client_or_404(db, client_id)
    name = client.name
    removed = client_service.delete_client(db, client)
    flash(request, f"Клиент «{name}» удалён" + (f" вместе со связанными записями ({removed})" if removed else ""))
    return redirect("/clients")


@router.post("/{client_id}/notes")
def client_note_add(
    client_id: int,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(CLIENTS_WRITE)),
):
    client = _client_or_404(db, client_id)
    try:
        activity_service.add_note(db, client, author=user, body=fstr(form, "body"))
        flash(request, "Заметка добавлена")
    except ValidationFailed as e:
        db.rollback()
        flash(request, "; ".join(e.errors.values()), "error")
    return redirect(f"/clients/{client.id}#history")


@router.post("/{client_id}/notes/{note_id}/delete")
def client_note_delete(
    client_id: int,
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(CLIENTS_WRITE)),
):
    client = _client_or_404(db, client_id)
    note = activity_service.get_note(db, client, note_id)
    if note is None:
        raise HTTPException(404, "Заметка не найдена")
    if not activity_service.can_delete_note(user, note):
        raise HTTPException(403, "Удалить заметку может её автор или администратор")
    activity_service.delete_note(db, note)
    flash(request, "Заметка удалена")
    return redirect(f"/clients/{client.id}#history")
