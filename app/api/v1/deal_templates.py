from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.errors import to_http
from app.core.permissions import SETTINGS_MANAGE
from app.db.session import get_db
from app.models import DealTemplate, User
from app.schemas.deal_template import DealTemplateCreate, DealTemplateRead, DealTemplateUpdate
from app.services import deal_template_service
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/deal-templates", tags=["deal-templates"])


def _get_or_404(db: Session, template_id: int) -> DealTemplate:
    template = deal_template_service.get_template(db, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаблон не найден")
    return template


@router.get("", response_model=list[DealTemplateRead])
def list_templates(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DealTemplate]:
    """Шаблоны сделок в порядке отображения. Поля шаблона — GET /custom-fields (поле template_id)."""
    return deal_template_service.list_templates(db, only_active=not include_inactive)


@router.post("", response_model=DealTemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: DealTemplateCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> DealTemplate:
    try:
        return deal_template_service.create_template(db, **payload.model_dump())
    except ValidationFailed as e:
        raise to_http(e) from e


@router.patch("/{template_id}", response_model=DealTemplateRead)
def update_template(
    template_id: int,
    payload: DealTemplateUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> DealTemplate:
    template = _get_or_404(db, template_id)
    try:
        return deal_template_service.update_template(db, template, **payload.model_dump(exclude_unset=True))
    except ValidationFailed as e:
        db.rollback()
        raise to_http(e) from e


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_MANAGE)),
) -> Response:
    """Удаляет только неиспользуемый шаблон; иначе 422 — скройте его (is_active=false)."""
    try:
        deal_template_service.delete_template(db, _get_or_404(db, template_id))
    except ValidationFailed as e:
        raise to_http(e) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)
