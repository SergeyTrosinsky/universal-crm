"""Настройки CRM: шаблоны сделок (наборы дополнительных полей)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.core.permissions import SETTINGS_MANAGE
from app.db.session import get_db
from app.models import DealTemplate, EntityType, User
from app.services import custom_field_service, deal_template_service
from app.services.errors import ValidationFailed
from app.web.deps import require_web_permission
from app.web.forms import fbool, fstr, get_form
from app.web.templating import flash, redirect, render

router = APIRouter(prefix="/settings/templates")
guard = require_web_permission(SETTINGS_MANAGE)


def _template_or_404(db: Session, template_id: int) -> DealTemplate:
    template = deal_template_service.get_template(db, template_id)
    if template is None:
        raise HTTPException(404, "Шаблон не найден")
    return template


@router.get("")
def templates_page(request: Request, db: Session = Depends(get_db), user: User = Depends(guard)):
    templates = deal_template_service.list_templates(db)
    fields = custom_field_service.list_fields(db, EntityType.DEAL)
    ctx = {
        "templates": templates,
        "usage": deal_template_service.usage(db),
        "common_fields": [f for f in fields if f.template_id is None],
        "fields_by_template": {t.id: [f for f in fields if f.template_id == t.id] for t in templates},
    }
    return render(request, "settings/deal_templates.html", ctx, user=user)


def _form_page(request, user, *, template=None, form=None, errors=None, used=None, status_code=200):
    ctx = {"item": template, "form": form or {}, "errors": errors or {}, "used": used or {"fields": 0, "deals": 0}}
    return render(request, "settings/deal_template_form.html", ctx, user=user, status_code=status_code)


@router.get("/new")
def template_new_page(request: Request, user: User = Depends(guard)):
    return _form_page(request, user, form={"is_active": True})


@router.post("/new")
def template_create(
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    values = {
        "name": fstr(form, "name"),
        "description": fstr(form, "description"),
        "is_active": fbool(form, "is_active"),
    }
    try:
        template = deal_template_service.create_template(db, **values)
    except ValidationFailed as e:
        db.rollback()
        return _form_page(request, user, form=values, errors=e.errors, status_code=400)
    flash(request, f"Шаблон «{template.name}» создан. Теперь добавьте ему поля")
    return redirect(f"/settings/fields/new?entity=deal&template={template.id}")


@router.get("/{template_id}/edit")
def template_edit_page(
    template_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    template = _template_or_404(db, template_id)
    form = {"name": template.name, "description": template.description or "", "is_active": template.is_active}
    used = deal_template_service.usage(db).get(template.id, {"fields": 0, "deals": 0})
    return _form_page(request, user, template=template, form=form, used=used)


@router.post("/{template_id}/edit")
def template_update(
    template_id: int,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    template = _template_or_404(db, template_id)
    values = {
        "name": fstr(form, "name"),
        "description": fstr(form, "description"),
        "is_active": fbool(form, "is_active"),
    }
    try:
        deal_template_service.update_template(db, template, **values)
    except ValidationFailed as e:
        db.rollback()
        db.refresh(template)
        used = deal_template_service.usage(db).get(template.id, {"fields": 0, "deals": 0})
        return _form_page(
            request, user, template=template, form=values, errors=e.errors, used=used, status_code=400
        )
    flash(request, "Шаблон сохранён")
    return redirect("/settings/templates")


@router.post("/{template_id}/move")
def template_move(
    template_id: int,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    template = _template_or_404(db, template_id)
    try:
        deal_template_service.move_template(db, template, fstr(form, "direction"))
    except ValidationFailed:
        pass
    return redirect("/settings/templates")


@router.post("/{template_id}/toggle")
def template_toggle(
    template_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    template = _template_or_404(db, template_id)
    deal_template_service.update_template(db, template, is_active=not template.is_active)
    flash(request, f"Шаблон «{template.name}» {'показан' if template.is_active else 'скрыт'}")
    return redirect("/settings/templates")


@router.post("/{template_id}/delete")
def template_delete(
    template_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    template = _template_or_404(db, template_id)
    name = template.name
    try:
        deal_template_service.delete_template(db, template)
    except ValidationFailed as e:
        db.rollback()
        flash(request, "; ".join(e.errors.values()), "error")
        return redirect(f"/settings/templates/{template_id}/edit")
    flash(request, f"Шаблон «{name}» удалён")
    return redirect("/settings/templates")
