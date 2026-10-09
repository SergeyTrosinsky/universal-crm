"""Задачи сотрудников: видимость по правам, фильтры, создание/изменение, смена статуса."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.permissions import TASKS_ASSIGN, TASKS_READ_ALL
from app.core.timezone import app_tz, local_day_bounds_utc, local_to_utc, today_local
from app.core.validators import parse_optional_int
from app.models import Client, Deal, Task, TaskPriority, TaskStatus, User
from app.services.errors import ValidationFailed
from app.services.pagination import Page, clamp_page
from app.services.query_utils import contains

OPEN_STATUSES = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)
CLOSED_STATUSES = (TaskStatus.DONE, TaskStatus.CANCELLED)
VIEWS = ("open", "overdue", "today", "done", "all")
DEFAULT_VIEW = "open"

_PRIORITY_RANK = case(
    (Task.priority == TaskPriority.URGENT, 0),
    (Task.priority == TaskPriority.HIGH, 1),
    (Task.priority == TaskPriority.NORMAL, 2),
    else_=3,
)
_NO_DUE_LAST = case((Task.due_at.is_(None), 1), else_=0)
_CLOSED_LAST = case((Task.status.in_(OPEN_STATUSES), 0), else_=1)

SORTS = {
    "due": (_CLOSED_LAST.asc(), _NO_DUE_LAST.asc(), Task.due_at.asc(), _PRIORITY_RANK.asc(), Task.id.asc()),
    "-due": (_CLOSED_LAST.asc(), _NO_DUE_LAST.asc(), Task.due_at.desc(), Task.id.desc()),
    "priority": (_CLOSED_LAST.asc(), _PRIORITY_RANK.asc(), _NO_DUE_LAST.asc(), Task.due_at.asc(), Task.id.asc()),
    "title": (func.lower(Task.title).asc(), Task.id.asc()),
    "created": (Task.created_at.asc(), Task.id.asc()),
    "-created": (Task.created_at.desc(), Task.id.desc()),
}
DEFAULT_SORT = "due"


def can_see_all(viewer: User) -> bool:
    return viewer.can(TASKS_READ_ALL)


def visibility(viewer: User):
    """Условие SQL: что именно пользователь вправе видеть. None — без ограничений."""
    if can_see_all(viewer):
        return None
    return or_(Task.assignee_id == viewer.id, Task.creator_id == viewer.id)


def has_access(viewer: User, task: Task) -> bool:
    return can_see_all(viewer) or viewer.id in (task.assignee_id, task.creator_id)


def get_task(db: Session, task_id: int) -> Task | None:
    return db.get(Task, task_id)


def _opt_int(value: Any) -> int | None:
    try:
        return parse_optional_int(value)
    except ValueError:
        return None


def _opt_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value.strip()) if value and value.strip() else None
    except ValueError:
        return None


def _conditions(
    viewer: User, *, q, view, status, priority, assignee, client_id, deal_id, due_from, due_to
) -> list:
    conds: list = []
    vis = visibility(viewer)
    if vis is not None:
        conds.append(vis)

    if q and q.strip():
        text = q.strip()
        conds.append(
            or_(
                contains(Task.title, text),
                contains(Task.description, text),
                Task.client_id.in_(select(Client.id).where(contains(Client.name, text))),
                Task.deal_id.in_(select(Deal.id).where(contains(Deal.title, text))),
            )
        )

    status_value = None
    if status:
        try:
            status_value = TaskStatus(status)
        except ValueError:
            status_value = None
    if status_value is not None:
        conds.append(Task.status == status_value)
    else:
        now = datetime.now(timezone.utc)
        if view == "open":
            conds.append(Task.status.in_(OPEN_STATUSES))
        elif view == "overdue":
            conds.append(Task.status.in_(OPEN_STATUSES))
            conds.append(Task.due_at.is_not(None))
            conds.append(Task.due_at < now)
        elif view == "today":
            start, end = local_day_bounds_utc(today_local())
            conds.append(Task.status.in_(OPEN_STATUSES))
            conds.append(Task.due_at >= start)
            conds.append(Task.due_at < end)
        elif view == "done":
            conds.append(Task.status.in_(CLOSED_STATUSES))

    if priority:
        try:
            conds.append(Task.priority == TaskPriority(priority))
        except ValueError:
            pass
    if assignee == "me":
        conds.append(Task.assignee_id == viewer.id)
    elif assignee and assignee != "all":
        aid = _opt_int(assignee)
        if aid is not None:
            conds.append(Task.assignee_id == aid)
    if client_id is not None:
        conds.append(Task.client_id == client_id)
    if deal_id is not None:
        conds.append(Task.deal_id == deal_id)
    if due_from:
        conds.append(Task.due_at >= local_day_bounds_utc(due_from)[0])
    if due_to:
        conds.append(Task.due_at < local_day_bounds_utc(due_to)[1])
    return conds


def list_tasks(
    db: Session,
    viewer: User,
    *,
    q: str | None = None,
    view: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    client_id: Any = None,
    deal_id: Any = None,
    due_from: str | None = None,
    due_to: str | None = None,
    sort: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> Page[Task]:
    """Параметры — «сырые» строки из URL; некорректные значения игнорируются.
    assignee: 'me' | 'all' | id. view: open | overdue | today | done | all."""
    view = view if view in VIEWS else DEFAULT_VIEW
    conds = _conditions(
        viewer,
        q=q, view=view, status=status, priority=priority, assignee=assignee,
        client_id=_opt_int(client_id), deal_id=_opt_int(deal_id),
        due_from=_opt_date(due_from), due_to=_opt_date(due_to),
    )
    total = db.scalar(select(func.count()).select_from(Task).where(*conds)) or 0
    page = clamp_page(page, total, per_page)
    stmt = (
        select(Task)
        .where(*conds)
        .order_by(*SORTS.get(sort or "", SORTS[DEFAULT_SORT]))
        .limit(per_page)
        .offset((page - 1) * per_page)
        .options(selectinload(Task.assignee), selectinload(Task.client), selectinload(Task.deal))
    )
    return Page(items=list(db.scalars(stmt)), total=total, page=page, per_page=per_page)


def view_counts(db: Session, viewer: User, *, assignee: str | None = None) -> dict[str, int]:
    """Счётчики для вкладок списка (с теми же правами видимости)."""
    out = {}
    for view in VIEWS:
        conds = _conditions(
            viewer, q=None, view=view, status=None, priority=None, assignee=assignee,
            client_id=None, deal_id=None, due_from=None, due_to=None,
        )
        out[view] = db.scalar(select(func.count()).select_from(Task).where(*conds)) or 0
    return out


def related_tasks(
    db: Session, viewer: User, *, client_id: int | None = None, deal_id: int | None = None, limit: int = 20
) -> list[Task]:
    """Задачи, привязанные к клиенту или сделке (открытые первыми)."""
    conds = []
    vis = visibility(viewer)
    if vis is not None:
        conds.append(vis)
    if client_id is not None:
        conds.append(Task.client_id == client_id)
    if deal_id is not None:
        conds.append(Task.deal_id == deal_id)
    stmt = (
        select(Task).where(*conds).order_by(*SORTS[DEFAULT_SORT]).limit(limit)
        .options(selectinload(Task.assignee))
    )
    return list(db.scalars(stmt))


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parse_due(raw: Any) -> datetime | None:
    """datetime / 'YYYY-MM-DDTHH:MM' / 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD' / 'DD.MM.YYYY [HH:MM]'.
    Наивное значение — время в часовом поясе приложения; только дата = конец дня (23:59)."""
    if _is_blank(raw):
        return None
    if isinstance(raw, datetime):
        return local_to_utc(raw)
    if isinstance(raw, date):
        return local_to_utc(datetime.combine(raw, time(23, 59)))
    text = str(raw).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return local_to_utc(datetime.strptime(text, fmt))
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return local_to_utc(datetime.combine(datetime.strptime(text, fmt).date(), time(23, 59)))
        except ValueError:
            pass
    try:
        return local_to_utc(datetime.fromisoformat(str(raw).strip()))
    except ValueError:
        raise ValueError("Некорректная дата и время (пример: 2025-03-09 14:30)") from None


def due_form_value(task: Task | None) -> str:
    """Значение для <input type=datetime-local> в часовом поясе приложения."""
    if task is None or task.due_at is None:
        return ""
    due = task.due_at if task.due_at.tzinfo else task.due_at.replace(tzinfo=timezone.utc)
    return due.astimezone(app_tz()).strftime("%Y-%m-%dT%H:%M")


def _enum(enum_cls, raw: Any, message: str):
    try:
        return enum_cls(str(raw).strip())
    except ValueError:
        raise ValueError(message) from None


def _clean(
    db: Session, data: Mapping[str, Any], *, partial: bool, creating: bool, actor: User, current: Task | None
) -> tuple[dict[str, Any], dict[str, str]]:
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}

    if "title" in data or not partial:
        title = str(data.get("title") or "").strip()
        if not title:
            errors["title"] = "Укажите название задачи"
        elif len(title) > 255:
            errors["title"] = "Слишком длинное название (максимум 255 символов)"
        else:
            out["title"] = title

    if "description" in data:
        text = str(data.get("description") or "").strip() or None
        if text and len(text) > 10000:
            errors["description"] = "Слишком длинное описание"
        else:
            out["description"] = text

    if "priority" in data and not _is_blank(data.get("priority")):
        try:
            out["priority"] = _enum(TaskPriority, data["priority"], "Выберите приоритет из списка")
        except ValueError as e:
            errors["priority"] = str(e)
    elif creating:
        out["priority"] = TaskPriority.NORMAL

    if "status" in data and not _is_blank(data.get("status")):
        try:
            out["status"] = _enum(TaskStatus, data["status"], "Выберите статус из списка")
        except ValueError as e:
            errors["status"] = str(e)
    elif creating:
        out["status"] = TaskStatus.TODO

    if "due_at" in data:
        try:
            out["due_at"] = parse_due(data.get("due_at"))
        except ValueError as e:
            errors["due_at"] = str(e)

    if not actor.can(TASKS_ASSIGN):
        allowed = {actor.id} | ({current.assignee_id} if current is not None and current.assignee_id else set())
        if "assignee_id" in data and not _is_blank(data.get("assignee_id")):
            try:
                requested = parse_optional_int(data.get("assignee_id"))
            except ValueError:
                requested = -1
            if requested not in allowed:
                errors["assignee_id"] = "Нет права назначать задачи другим сотрудникам"
        if creating:
            out["assignee_id"] = actor.id
    elif "assignee_id" in data:
        try:
            aid = parse_optional_int(data.get("assignee_id"))
        except ValueError:
            aid, errors["assignee_id"] = None, "Исполнитель не найден"
        if aid is not None and "assignee_id" not in errors:
            user = db.get(User, aid)
            keeps = current is not None and current.assignee_id == aid
            if user is None or (not user.is_active and not keeps):
                errors["assignee_id"] = "Исполнитель не найден"
        if "assignee_id" not in errors:
            out["assignee_id"] = aid
    elif creating:
        out["assignee_id"] = actor.id

    deal = None
    if "deal_id" in data:
        try:
            did = parse_optional_int(data.get("deal_id"))
        except ValueError:
            did, errors["deal_id"] = None, "Сделка не найдена"
        if did is not None and "deal_id" not in errors:
            deal = db.get(Deal, did)
            if deal is None:
                errors["deal_id"] = "Сделка не найдена"
        if "deal_id" not in errors:
            out["deal_id"] = did

    if "client_id" in data:
        try:
            cid = parse_optional_int(data.get("client_id"))
        except ValueError:
            cid, errors["client_id"] = None, "Клиент не найден"
        if cid is not None and "client_id" not in errors and db.get(Client, cid) is None:
            errors["client_id"] = "Клиент не найден"
        if "client_id" not in errors:
            out["client_id"] = cid

    if deal is not None and "deal_id" not in errors and "client_id" not in errors:
        if out.get("client_id") is None:
            out["client_id"] = deal.client_id
        elif out["client_id"] != deal.client_id:
            errors["deal_id"] = "Сделка принадлежит другому клиенту"
    return out, errors


def _apply_status(task: Task, status: TaskStatus) -> None:
    task.status = status
    if status == TaskStatus.DONE:
        if task.completed_at is None:
            task.completed_at = datetime.now(timezone.utc)
    else:
        task.completed_at = None


def create_task(db: Session, *, data: Mapping[str, Any], actor: User) -> Task:
    clean, errors = _clean(db, data, partial=False, creating=True, actor=actor, current=None)
    if errors:
        raise ValidationFailed(errors)
    status = clean.pop("status")
    task = Task(**clean, creator_id=actor.id)
    _apply_status(task, status)
    db.add(task)
    db.commit()
    return task


def update_task(db: Session, task: Task, *, data: Mapping[str, Any], actor: User, partial: bool) -> Task:
    clean, errors = _clean(db, data, partial=partial, creating=False, actor=actor, current=task)
    if errors:
        raise ValidationFailed(errors)
    status = clean.pop("status", None)
    for key, value in clean.items():
        setattr(task, key, value)
    if status is not None and status != task.status:
        _apply_status(task, status)
    db.commit()
    db.refresh(task)
    return task


def change_status(db: Session, task: Task, status: Any) -> Task:
    try:
        new = _enum(TaskStatus, status, "Выберите статус из списка")
    except ValueError as e:
        raise ValidationFailed({"status": str(e)}) from None
    if new != task.status:
        _apply_status(task, new)
        db.commit()
        db.refresh(task)
    return task


def delete_task(db: Session, task: Task) -> None:
    db.delete(task)
    db.commit()
