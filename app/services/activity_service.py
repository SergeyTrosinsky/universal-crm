"""История изменений и заметки в карточках клиентов и сделок.

Идея: перед изменением снимаем «снимок» читаемых значений (в том числе кастомных полей),
после изменения — второй, и в журнал пишем только то, что отличается. Так в записи попадают
и поля формы, и ответственный, и статус, и значения ваших полей, а пустое сохранение
формы ничего не добавляет."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.labels import CLIENT_TYPE_LABELS
from app.core.permissions import SETTINGS_MANAGE
from app.models import ActivityEvent, Client, CustomField, Deal, DealTemplate, Note, Status, User
from app.services import eav_service
from app.services.errors import ValidationFailed

CREATED = "created"
UPDATED = "updated"
EMPTY = "—"
MAX_VALUE_LEN = 200
MAX_NOTE_LEN = 5000
FEED_LIMIT = 100

Snapshot = dict[str, tuple[str, str]]  # ключ -> (подпись, значение для показа)


# ------------------------------------------------------------------ снимки
def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_VALUE_LEN else text[: MAX_VALUE_LEN - 1] + "…"


def _text(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return EMPTY
    return _clip(value)


def _user_name(db: Session, user_id: int | None) -> str:
    user = db.get(User, user_id) if user_id else None
    return user.full_name if user else EMPTY


def _custom_snapshot(owner: Any, fields: Iterable[CustomField]) -> Snapshot:
    stored = {cv.field_id: cv.value for cv in owner.custom_values}
    return {
        f"cf:{f.id}": (f.label, _clip(eav_service.display_value(f, stored.get(f.id))))
        for f in fields
        if f.is_active
    }


def client_snapshot(db: Session, client: Client, fields: Iterable[CustomField]) -> Snapshot:
    ctype = client.type.value if hasattr(client.type, "value") else str(client.type)
    snap: Snapshot = {
        "name": ("Имя / название", _text(client.name)),
        "type": ("Тип", CLIENT_TYPE_LABELS.get(ctype, ctype)),
        "company_name": ("Компания", _text(client.company_name)),
        "phone": ("Телефон", _text(client.phone)),
        "email": ("Email", _text(client.email)),
        "address": ("Адрес", _text(client.address)),
        "owner": ("Ответственный", _user_name(db, client.owner_id)),
        "notes": ("Заметки в карточке", _text(client.notes)),
    }
    snap.update(_custom_snapshot(client, fields))
    return snap


def deal_snapshot(db: Session, deal: Deal, fields: Iterable[CustomField]) -> Snapshot:
    status = db.get(Status, deal.status_id) if deal.status_id else None
    client = db.get(Client, deal.client_id) if deal.client_id else None
    template = db.get(DealTemplate, deal.template_id) if deal.template_id else None
    amount = f"{eav_service.format_number(deal.amount)} {deal.currency}" if deal.amount is not None else EMPTY
    snap: Snapshot = {
        "title": ("Название", _text(deal.title)),
        "status": ("Статус", status.name if status else EMPTY),
        "amount": ("Сумма", amount),
        "deal_date": ("Дата", deal.deal_date.strftime("%d.%m.%Y") if deal.deal_date else EMPTY),
        "responsible": ("Ответственный", _user_name(db, deal.responsible_id)),
        "client": ("Клиент", client.name if client else EMPTY),
        "template": ("Шаблон", template.name if template else EMPTY),
        "description": ("Описание", _text(deal.description)),
    }
    snap.update(_custom_snapshot(deal, fields))
    return snap


def snapshot(db: Session, owner: Client | Deal, fields: Iterable[CustomField]) -> Snapshot:
    return client_snapshot(db, owner, fields) if isinstance(owner, Client) else deal_snapshot(db, owner, fields)


def diff(before: Mapping[str, tuple[str, str]], after: Mapping[str, tuple[str, str]]) -> list[dict[str, str]]:
    changes = []
    for key, (label, new) in after.items():
        old = before.get(key, (label, EMPTY))[1]
        if old != new:
            changes.append({"label": label, "old": old, "new": new})
    return changes


# ------------------------------------------------------------------ запись
def record(
    db: Session,
    owner: Client | Deal,
    *,
    kind: str,
    actor: User | None,
    changes: list[dict[str, str]] | None = None,
) -> ActivityEvent | None:
    """Добавляет запись в журнал (без коммита). Пустое «изменение» не записывается.
    owner должен иметь id (после flush)."""
    if kind == UPDATED and not changes:
        return None
    event = ActivityEvent(
        kind=kind,
        actor_id=actor.id if actor else None,
        actor_name=actor.full_name if actor else None,
        changes=changes or None,
    )
    if isinstance(owner, Deal):
        event.deal_id = owner.id
    else:
        event.client_id = owner.id
    db.add(event)
    return event


def _owner_condition(model: type, owner: Client | Deal):
    return model.deal_id == owner.id if isinstance(owner, Deal) else model.client_id == owner.id


# ----------------------------------------------------------------- заметки
def clean_note_body(raw: Any) -> str:
    body = str(raw or "").strip()
    if not body:
        raise ValidationFailed({"body": "Напишите текст заметки"})
    if len(body) > MAX_NOTE_LEN:
        raise ValidationFailed({"body": f"Слишком длинная заметка (максимум {MAX_NOTE_LEN} символов)"})
    return body


def add_note(db: Session, owner: Client | Deal, *, author: User, body: Any) -> Note:
    note = Note(body=clean_note_body(body), author_id=author.id, author_name=author.full_name)
    if isinstance(owner, Deal):
        note.deal_id = owner.id
    else:
        note.client_id = owner.id
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def get_note(db: Session, owner: Client | Deal, note_id: int) -> Note | None:
    """Заметка именно этой карточки (чужой карточки — как будто её нет)."""
    return db.scalar(select(Note).where(Note.id == note_id, _owner_condition(Note, owner)))


def can_delete_note(user: User, note: Note) -> bool:
    """Свою заметку удаляет автор; чужие — только тот, кто управляет настройками (администратор)."""
    return note.author_id == user.id or user.can(SETTINGS_MANAGE)


def delete_note(db: Session, note: Note) -> None:
    db.delete(note)
    db.commit()


# -------------------------------------------------------------------- лента
@dataclass
class FeedItem:
    type: str                      # "event" | "note"
    at: datetime
    id: int
    author: str | None
    kind: str | None = None        # для события: created | updated
    changes: list[dict[str, str]] | None = None
    body: str | None = None        # для заметки
    author_id: int | None = None


def feed(db: Session, owner: Client | Deal, limit: int = FEED_LIMIT) -> list[FeedItem]:
    """События и заметки одной карточки, новые сверху."""
    events = db.scalars(
        select(ActivityEvent)
        .where(_owner_condition(ActivityEvent, owner))
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
        .limit(limit)
    )
    notes = db.scalars(
        select(Note)
        .where(_owner_condition(Note, owner))
        .order_by(Note.created_at.desc(), Note.id.desc())
        .limit(limit)
    )
    items = [
        FeedItem("event", e.created_at, e.id, e.actor_name, kind=e.kind, changes=e.changes or [], author_id=e.actor_id)
        for e in events
    ] + [FeedItem("note", n.created_at, n.id, n.author_name, body=n.body, author_id=n.author_id) for n in notes]
    # у событий и заметок отдельные счётчики id, поэтому при равном времени заметка идёт выше события
    items.sort(key=lambda i: (i.at, 1 if i.type == "note" else 0, i.id), reverse=True)
    return items[:limit]
