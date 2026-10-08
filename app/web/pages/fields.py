"""Настройки CRM: пользовательские поля клиентов и сделок."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.core.permissions import SETTINGS_MANAGE
from app.db.session import get_db
from app.models import CustomField, FieldType, User
from app.services import custom_field_service, deal_template_service, presets, settings_service
from app.services.errors import ValidationFailed
from app.web.deps import require_web_permission
from app.web.forms import fbool, fstr, get_form, parse_entity, parse_options_text
from app.web.templating import flash, redirect, render

router = APIRouter(prefix="/settings/fields")
guard = require_web_permission(SETTINGS_MANAGE)


def _field_or_404(db: Session, field_id: int) -> CustomField:
    field = custom_field_service.get_field(db, field_id)
    if field is None:
        raise HTTPException(404, "Поле не найдено")
    return field


def _back(entity: str) -> str:
    return f"/settings/fields?entity={entity}"


@router.get("")
def fields_page(
    request: Request,
    entity: str = "client",
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    ent = parse_entity(entity)
    ctx = {
        "entity": ent.value,
        "fields": custom_field_service.list_fields(db, ent),
        "counts": custom_field_service.value_counts(db),
        "presets": presets.PRESETS,
        "template_names": {t.id: t.name for t in deal_template_service.list_templates(db)},
    }
    return render(request, "settings/fields.html", ctx, user=user)


def _form_page(
    request, user, db, *, entity, field=None, form=None, errors=None, values_count=0, status_code=200
):
    ctx = {
        "templates": deal_template_service.list_templates(db) if entity == "deal" else [],
        "entity": entity,
        "field": field,
        "form": form or {},
        "errors": errors or {},
        "field_types": [t.value for t in FieldType],
        "values_count": values_count,
    }
    return render(request, "settings/field_form.html", ctx, user=user, status_code=status_code)


def _form_dict(form: FormData) -> dict:
    return {
        "label": fstr(form, "label"),
        "code": fstr(form, "code"),
        "field_type": fstr(form, "field_type", "text"),
        "options": fstr(form, "options"),
        "placeholder": fstr(form, "placeholder"),
        "help_text": fstr(form, "help_text"),
        "is_required": fbool(form, "is_required"),
        "is_filterable": fbool(form, "is_filterable"),
        "show_in_list": fbool(form, "show_in_list"),
        "is_active": fbool(form, "is_active"),
        "template_id": fstr(form, "template_id"),
    }


@router.get("/new")
def field_new_page(
    request: Request,
    entity: str = "client",
    template: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    ent = parse_entity(entity)
    defaults = {"field_type": "text", "is_filterable": True, "is_active": True, "template_id": template}
    return _form_page(request, user, db, entity=ent.value, form=defaults)


@router.post("/new")
def field_create(
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    entity = parse_entity(fstr(form, "entity_type")).value
    values = _form_dict(form)
    try:
        field = custom_field_service.create_field(
            db,
            entity_type=entity,
            label=values["label"],
            field_type=values["field_type"],
            code=values["code"] or None,
            options=parse_options_text(values["options"]),
            placeholder=values["placeholder"],
            help_text=values["help_text"],
            is_required=values["is_required"],
            is_filterable=values["is_filterable"],
            show_in_list=values["show_in_list"],
            is_active=values["is_active"],
            template_id=values["template_id"] or None,
        )
    except ValidationFailed as e:
        db.rollback()
        return _form_page(request, user, db, entity=entity, form=values, errors=e.errors, status_code=400)
    flash(request, f"Поле «{field.label}» создано")
    return redirect(_back(entity))


@router.get("/{field_id}/edit")
def field_edit_page(
    field_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    field = _field_or_404(db, field_id)
    form = {
        "label": field.label,
        "code": field.code,
        "field_type": field.field_type.value,
        "options": "\n".join(field.options or []),
        "placeholder": field.placeholder or "",
        "help_text": field.help_text or "",
        "is_required": field.is_required,
        "is_filterable": field.is_filterable,
        "show_in_list": field.show_in_list,
        "is_active": field.is_active,
        "template_id": str(field.template_id or ""),
    }
    return _form_page(
        request,
        user,
        db,
        entity=field.entity_type.value,
        field=field,
        form=form,
        values_count=custom_field_service.value_counts(db).get(field.id, 0),
    )


@router.post("/{field_id}/edit")
def field_update(
    field_id: int,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    field = _field_or_404(db, field_id)
    entity = field.entity_type.value
    values = _form_dict(form)
    values.update(code=field.code, field_type=field.field_type.value)
    try:
        custom_field_service.update_field(
            db,
            field,
            label=values["label"],
            options=parse_options_text(values["options"]),
            placeholder=values["placeholder"],
            help_text=values["help_text"],
            is_required=values["is_required"],
            is_filterable=values["is_filterable"],
            show_in_list=values["show_in_list"],
            is_active=values["is_active"],
            **({"template_id": values["template_id"] or None} if entity == "deal" else {}),
        )
    except ValidationFailed as e:
        db.rollback()
        db.refresh(field)
        return _form_page(
            request,
            user,
            db,
            entity=entity,
            field=field,
            form=values,
            errors=e.errors,
            values_count=custom_field_service.value_counts(db).get(field.id, 0),
            status_code=400,
        )
    flash(request, "Поле сохранено")
    return redirect(_back(entity))


@router.post("/{field_id}/move")
def field_move(
    field_id: int,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(guard),
):
    field = _field_or_404(db, field_id)
    try:
        custom_field_service.move_field(db, field, fstr(form, "direction"))
    except ValidationFailed:
        pass
    return redirect(_back(field.entity_type.value))


@router.post("/{field_id}/toggle")
def field_toggle(
    field_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    field = _field_or_404(db, field_id)
    custom_field_service.update_field(db, field, is_active=not field.is_active)
    flash(request, f"Поле «{field.label}» {'показано' if field.is_active else 'скрыто'}")
    return redirect(_back(field.entity_type.value))


@router.post("/{field_id}/delete")
def field_delete(
    field_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    field = _field_or_404(db, field_id)
    entity, label = field.entity_type.value, field.label
    removed = custom_field_service.delete_field(db, field)
    flash(request, f"Поле «{label}» удалено" + (f" вместе с {removed} значениями" if removed else ""))
    return redirect(_back(entity))


@router.post("/preset/{key}")
def field_preset(
    key: str, request: Request, db: Session = Depends(get_db), user: User = Depends(guard)
):
    try:
        new_fields, new_statuses = presets.apply_preset(db, key)
    except KeyError:
        raise HTTPException(404, "Набор не найден") from None
    renamed = [
        entity
        for entity, (pl, sg, acc) in presets.PRESETS[key].get("terms", {}).items()
        if settings_service.apply_terms(db, entity, pl, sg, acc)
    ]
    message = f"Набор «{presets.PRESETS[key]['title']}»: добавлено полей — {new_fields}, статусов — {new_statuses}"
    if presets.PRESETS[key].get("template"):
        message += f". Шаблон «{presets.PRESETS[key]['template']}» доступен при создании записи"
    if renamed:
        message += ". Термины обновлены (Настройки → Общие)"
    flash(request, message)
    return redirect("/settings/fields?entity=deal")
