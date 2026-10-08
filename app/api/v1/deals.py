from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.api.errors import to_http
from app.core.permissions import DEALS_DELETE, DEALS_READ, DEALS_WRITE
from app.db.session import get_db
from app.models import Deal, User
from app.schemas.activity import ActivityItemOut, NoteCreate
from app.schemas.deal import (
    DealCreate, DealPage, DealRead, DealStatusChange, DealTotal, DealUpdate,
)
from app.services import activity_service, deal_service, eav_service
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/deals", tags=["deals"])


def _get_or_404(db: Session, deal_id: int, viewer: User) -> Deal:
    deal = deal_service.get_deal(db, deal_id, viewer)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сделка не найдена")
    return deal


@router.get("", response_model=DealPage)
def list_deals(
    request: Request,
    q: str | None = Query(None, description="Поиск по названию, описанию, имени клиента и текстовым кастомным полям"),
    status_id: int | None = None,
    kind: str | None = Query(None, description="open | won | lost"),
    client_id: int | None = None,
    responsible_id: int | None = None,
    template: str | None = Query(None, description="id шаблона или none (стандартная форма)"),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    amount_min: str | None = None,
    amount_max: str | None = None,
    sort: str | None = Query(None, description="date | -date | amount | -amount | title | created | -created"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    viewer: User = Depends(require_permission(DEALS_READ)),
) -> DealPage:
    """Фильтры по кастомным полям: ?cf_<код>=значение, для чисел и дат — ?cf_<код>__from=..&cf_<код>__to=.."""
    fields = deal_service.active_fields(db)
    result = deal_service.list_deals(
        db,
        q=q,
        status_id=status_id,
        kind=kind,
        client_id=client_id,
        responsible_id=responsible_id,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        custom_filters=eav_service.extract_custom_filters(fields, request.query_params),
        fields=fields,
        template=template,
        sort=sort,
        page=page,
        per_page=per_page,
        viewer=viewer,
    )
    return DealPage(
        items=[DealRead.model_validate(d) for d in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
        totals=[DealTotal(currency=c, amount=a) for c, a in result.extra["totals"]],
    )


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
def create_deal(
    payload: DealCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(DEALS_WRITE)),
) -> Deal:
    data = payload.model_dump(exclude_unset=True, exclude={"custom"})
    try:
        return deal_service.create_deal(db, data=data, custom=payload.custom, actor=actor)
    except ValidationFailed as e:
        raise to_http(e) from e


@router.get("/{deal_id}", response_model=DealRead)
def get_deal(
    deal_id: int, db: Session = Depends(get_db), viewer: User = Depends(require_permission(DEALS_READ))
) -> Deal:
    return _get_or_404(db, deal_id, viewer)


@router.patch("/{deal_id}", response_model=DealRead)
def update_deal(
    deal_id: int,
    payload: DealUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(DEALS_WRITE)),
) -> Deal:
    deal = _get_or_404(db, deal_id, actor)
    data = payload.model_dump(exclude_unset=True, exclude={"custom"})
    try:
        return deal_service.update_deal(
            db, deal, data=data, custom=payload.custom or {}, actor=actor, partial=True
        )
    except ValidationFailed as e:
        raise to_http(e) from e


@router.post("/{deal_id}/status", response_model=DealRead)
def change_deal_status(
    deal_id: int,
    payload: DealStatusChange,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(DEALS_WRITE)),
) -> Deal:
    """Быстрая смена статуса (например, при перетаскивании карточки)."""
    deal = _get_or_404(db, deal_id, actor)
    try:
        return deal_service.change_status(db, deal, payload.status_id, actor)
    except ValidationFailed as e:
        raise to_http(e) from e


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(DEALS_DELETE)),
) -> Response:
    deal_service.delete_deal(db, _get_or_404(db, deal_id, actor))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{deal_id}/activity", response_model=list[ActivityItemOut])
def deal_activity(
    deal_id: int,
    db: Session = Depends(get_db),
    viewer: User = Depends(require_permission(DEALS_READ)),
) -> list[ActivityItemOut]:
    """История изменений и заметки карточки, новые сверху."""
    owner = _get_or_404(db, deal_id, viewer)
    return [ActivityItemOut.model_validate(i, from_attributes=True) for i in activity_service.feed(db, owner)]


@router.post("/{deal_id}/notes", response_model=ActivityItemOut, status_code=status.HTTP_201_CREATED)
def deal_add_note(
    deal_id: int,
    payload: NoteCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(DEALS_WRITE)),
) -> ActivityItemOut:
    owner = _get_or_404(db, deal_id, actor)
    try:
        note = activity_service.add_note(db, owner, author=actor, body=payload.body)
    except ValidationFailed as e:
        raise to_http(e) from e
    return ActivityItemOut(type="note", id=note.id, at=note.created_at, author=note.author_name, body=note.body)


@router.delete("/{deal_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def deal_delete_note(
    deal_id: int,
    note_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(DEALS_WRITE)),
) -> Response:
    owner = _get_or_404(db, deal_id, actor)
    note = activity_service.get_note(db, owner, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заметка не найдена")
    if not activity_service.can_delete_note(actor, note):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Удалить заметку может её автор или администратор")
    activity_service.delete_note(db, note)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
