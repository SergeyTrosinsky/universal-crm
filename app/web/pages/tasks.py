"""Задачи: список с вкладками и фильтрами, карточка, форма, быстрая смена статуса."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.core.labels import TASK_PRIORITY_LABELS, TASK_STATUS_LABELS
from app.core.permissions import TASKS_READ, TASKS_WRITE
from app.db.session import get_db
from app.models import Client, Deal, Task, User
from app.services import task_service
from app.services.errors import ValidationFailed
from app.web.deps import require_web_permission
from app.web.forms import fstr, get_form, optional_int, parse_page
from app.web.pages.auth import safe_next
from app.web.templating import flash, redirect, render

router = APIRouter(prefix="/tasks")
PER_PAGE = 20
BASE_KEYS = ("title", "description", "priority", "status", "due_at", "assignee_id", "client_id", "deal_id")

VIEW_LABELS = [
    ("open", "Открытые"),
    ("overdue", "Просроченные"),
    ("today", "На сегодня"),
    ("done", "Закрытые"),
    ("all", "Все"),
]


def _task_or_404(db: Session, task_id: int, user: User) -> Task:
    task = task_service.get_task(db, task_id)
    if task is None or not task_service.has_access(user, task):
        raise HTTPException(404, "Задача не найдена")
    return task


def _active_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)))


@router.get("")
def tasks_list(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(TASKS_READ))
):
    params = request.query_params
    view = params.get("view") if params.get("view") in task_service.VIEWS else task_service.DEFAULT_VIEW
    assignee = params.get("assignee") or "me"
    simple = ("q", "status", "priority", "due_from", "due_to")
    page = task_service.list_tasks(
        db, user,
        q=params.get("q"), view=view, status=params.get("status"), priority=params.get("priority"),
        assignee=assignee, client_id=params.get("client"), deal_id=params.get("deal"),
        due_from=params.get("due_from"), due_to=params.get("due_to"),
        sort=params.get("sort"), page=parse_page(params.get("page")), per_page=PER_PAGE,
    )
    client_id, deal_id = optional_int(params.get("client")), optional_int(params.get("deal"))
    ctx = {
        "page": page,
        "view": view,
        "views": VIEW_LABELS,
        "counts": task_service.view_counts(db, user, assignee=assignee),
        "p": {key: params.get(key, "") for key in simple},
        "assignee": assignee,
        "sort": params.get("sort") or task_service.DEFAULT_SORT,
        "users": _active_users(db),
        "task_statuses": list(TASK_STATUS_LABELS.items()),
        "task_priorities": list(TASK_PRIORITY_LABELS.items()),
        "client_filter": db.get(Client, client_id) if client_id else None,
        "deal_filter": db.get(Deal, deal_id) if deal_id else None,
        "has_filters": any(params.get(key) for key in simple) or assignee != "me"
        or bool(client_id or deal_id),
    }
    return render(request, "tasks/list.html", ctx, user=user)


def _form_page(request, user, db, *, task=None, form=None, errors=None, status_code=200):
    form = dict(form or {})
    client_id, deal_id = optional_int(str(form.get("client_id", ""))), optional_int(str(form.get("deal_id", "")))
    ctx = {
        "task": task,
        "form": form,
        "errors": errors or {},
        "users": _active_users(db),
        "task_statuses": list(TASK_STATUS_LABELS.items()),
        "task_priorities": list(TASK_PRIORITY_LABELS.items()),
        "picked_client": db.get(Client, client_id) if client_id else None,
        "picked_deal": db.get(Deal, deal_id) if deal_id else None,
    }
    return render(request, "tasks/form.html", ctx, user=user, status_code=status_code)


@router.get("/new")
def task_new_page(
    request: Request,
    client_id: str = "",
    deal_id: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(TASKS_WRITE)),
):
    form = {
        "priority": "normal", "status": "todo", "assignee_id": str(user.id),
        "client_id": client_id, "deal_id": deal_id, "due_at": "",
    }
    deal = db.get(Deal, optional_int(deal_id) or 0) if deal_id else None
    if deal is not None:
        form["client_id"] = str(deal.client_id)
    return _form_page(request, user, db, form=form)


@router.post("/new")
def task_create(
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(TASKS_WRITE)),
):
    data = {key: fstr(form, key) for key in BASE_KEYS}
    try:
        task = task_service.create_task(db, data=data, actor=user)
    except ValidationFailed as e:
        db.rollback()
        return _form_page(request, user, db, form=data, errors=e.errors, status_code=400)
    flash(request, f"Задача «{task.title}» создана")
    return redirect(f"/tasks/{task.id}")


@router.get("/{task_id}")
def task_detail(
    task_id: int, request: Request, db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(TASKS_READ)),
):
    task = _task_or_404(db, task_id, user)
    ctx = {"task": task, "task_statuses": list(TASK_STATUS_LABELS.items())}
    return render(request, "tasks/detail.html", ctx, user=user)


@router.get("/{task_id}/edit")
def task_edit_page(
    task_id: int, request: Request, db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(TASKS_WRITE)),
):
    task = _task_or_404(db, task_id, user)
    form = {
        "title": task.title,
        "description": task.description or "",
        "priority": task.priority.value,
        "status": task.status.value,
        "due_at": task_service.due_form_value(task),
        "assignee_id": str(task.assignee_id or ""),
        "client_id": str(task.client_id or ""),
        "deal_id": str(task.deal_id or ""),
    }
    return _form_page(request, user, db, task=task, form=form)


@router.post("/{task_id}/edit")
def task_update(
    task_id: int, request: Request, form: FormData = Depends(get_form), db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(TASKS_WRITE)),
):
    task = _task_or_404(db, task_id, user)
    data = {key: fstr(form, key) for key in BASE_KEYS}
    try:
        task_service.update_task(db, task, data=data, actor=user, partial=False)
    except ValidationFailed as e:
        db.rollback()
        db.refresh(task)
        return _form_page(request, user, db, task=task, form=data, errors=e.errors, status_code=400)
    flash(request, "Изменения сохранены")
    return redirect(f"/tasks/{task.id}")


@router.post("/{task_id}/status")
def task_change_status(
    task_id: int, request: Request, form: FormData = Depends(get_form), db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(TASKS_WRITE)),
):
    task = _task_or_404(db, task_id, user)
    try:
        task_service.change_status(db, task, fstr(form, "status"))
        flash(request, f"Статус задачи: «{TASK_STATUS_LABELS[task.status.value]}»")
    except ValidationFailed as e:
        db.rollback()
        flash(request, "; ".join(e.errors.values()), "error")
    target = fstr(form, "next")
    return redirect(safe_next(target) if target else f"/tasks/{task.id}")


@router.post("/{task_id}/delete")
def task_delete(
    task_id: int, request: Request, db: Session = Depends(get_db),
    user: User = Depends(require_web_permission(TASKS_WRITE)),
):
    task = _task_or_404(db, task_id, user)
    title = task.title
    task_service.delete_task(db, task)
    flash(request, f"Задача «{title}» удалена")
    return redirect("/tasks")
