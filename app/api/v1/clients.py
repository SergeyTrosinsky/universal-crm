from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.api.errors import to_http
from app.core.permissions import CLIENTS_DELETE, CLIENTS_READ, CLIENTS_WRITE
from app.db.session import get_db
from app.models import Client, User
from app.schemas.activity import ActivityItemOut, NoteCreate
from app.schemas.client import ClientCreate, ClientRead, ClientUpdate
from app.schemas.common import PageOut
from app.services import activity_service, client_service, eav_service
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/clients", tags=["clients"])


def _get_or_404(db: Session, client_id: int) -> Client:
    client = client_service.get_client(db, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    return client


@router.get("", response_model=PageOut[ClientRead])
def list_clients(
    request: Request,
    q: str | None = Query(None, description="Поиск по имени, компании, email, телефону, адресу и текстовым кастомным полям"),
    type: str | None = Query(None, description="person | company"),
    owner_id: int | None = None,
    sort: str | None = Query(None, description="name | -name | created | -created"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(CLIENTS_READ)),
) -> PageOut[ClientRead]:
    """Фильтры по кастомным полям: ?cf_<код>=значение, для чисел и дат — ?cf_<код>__from=..&cf_<код>__to=.."""
    fields = client_service.active_fields(db)
    result = client_service.list_clients(
        db,
        q=q,
        client_type=type,
        owner_id=owner_id,
        custom_filters=eav_service.extract_custom_filters(fields, request.query_params),
        fields=fields,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    return PageOut[ClientRead](
        items=[ClientRead.model_validate(c) for c in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


@router.post("", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(CLIENTS_WRITE)),
) -> Client:
    data = payload.model_dump(exclude_unset=True, exclude={"custom"})
    try:
        return client_service.create_client(db, data=data, custom=payload.custom, actor=actor)
    except ValidationFailed as e:
        raise to_http(e) from e


@router.get("/{client_id}", response_model=ClientRead)
def get_client(
    client_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission(CLIENTS_READ))
) -> Client:
    return _get_or_404(db, client_id)


@router.patch("/{client_id}", response_model=ClientRead)
def update_client(
    client_id: int,
    payload: ClientUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(CLIENTS_WRITE)),
) -> Client:
    client = _get_or_404(db, client_id)
    data = payload.model_dump(exclude_unset=True, exclude={"custom"})
    try:
        return client_service.update_client(
            db, client, data=data, custom=payload.custom or {}, actor=actor, partial=True
        )
    except ValidationFailed as e:
        raise to_http(e) from e


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(CLIENTS_DELETE)),
) -> Response:
    """Удаляет клиента вместе с его сделками."""
    client_service.delete_client(db, _get_or_404(db, client_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{client_id}/activity", response_model=list[ActivityItemOut])
def client_activity(
    client_id: int,
    db: Session = Depends(get_db),
    viewer: User = Depends(require_permission(CLIENTS_READ)),
) -> list[ActivityItemOut]:
    """История изменений и заметки карточки, новые сверху."""
    owner = _get_or_404(db, client_id)
    return [ActivityItemOut.model_validate(i, from_attributes=True) for i in activity_service.feed(db, owner)]


@router.post("/{client_id}/notes", response_model=ActivityItemOut, status_code=status.HTTP_201_CREATED)
def client_add_note(
    client_id: int,
    payload: NoteCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(CLIENTS_WRITE)),
) -> ActivityItemOut:
    owner = _get_or_404(db, client_id)
    try:
        note = activity_service.add_note(db, owner, author=actor, body=payload.body)
    except ValidationFailed as e:
        raise to_http(e) from e
    return ActivityItemOut(type="note", id=note.id, at=note.created_at, author=note.author_name, body=note.body)


@router.delete("/{client_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def client_delete_note(
    client_id: int,
    note_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(CLIENTS_WRITE)),
) -> Response:
    owner = _get_or_404(db, client_id)
    note = activity_service.get_note(db, owner, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заметка не найдена")
    if not activity_service.can_delete_note(actor, note):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Удалить заметку может её автор или администратор")
    activity_service.delete_note(db, note)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
