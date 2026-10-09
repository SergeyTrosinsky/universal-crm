"""Готовые наборы полей и статусов: быстрый старт под разные виды бизнеса.
Применение идемпотентно — то, что уже есть (по названию), пропускается."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CustomField, EntityType, FieldType, Status
from app.services import custom_field_service, deal_template_service, status_service

PRESETS: dict[str, dict] = {
    "auto": {
        "title": "Автосервис",
        "description": "Шаблон заказа «Автосервис» с полями «Марка авто», «VIN», «Госномер». Статусы: приём → ремонт → выдача.",
        "template": "Автосервис",
        "fields": [
            (EntityType.DEAL, "Марка авто", FieldType.TEXT, []),
            (EntityType.DEAL, "VIN", FieldType.TEXT, []),
            (EntityType.DEAL, "Госномер", FieldType.TEXT, []),
        ],
        "terms": {"deal": ("Заказы", "Заказ", "заказ")},
        "statuses": [
            ("Приём", "#3B82F6", "open"),
            ("Диагностика", "#8B5CF6", "open"),
            ("В ремонте", "#F59E0B", "open"),
            ("Готово к выдаче", "#14B8A6", "open"),
            ("Выдан", "#10B981", "won"),
            ("Отказ", "#EF4444", "lost"),
        ],
    },
    "beauty": {
        "title": "Салон красоты",
        "description": "Шаблон записи «Салон красоты» с полями «Мастер», «Услуга», «Дата посещения». Статусы: запись → визит.",
        "template": "Салон красоты",
        "fields": [
            (EntityType.DEAL, "Мастер", FieldType.SELECT, ["Анна", "Мария", "Ольга"]),
            (
                EntityType.DEAL, "Услуга", FieldType.SELECT,
                ["Стрижка", "Окрашивание", "Маникюр", "Педикюр", "Макияж"],
            ),
            (EntityType.DEAL, "Дата посещения", FieldType.DATE, []),
        ],
        "terms": {"deal": ("Записи", "Запись", "запись")},
        "statuses": [
            ("Запись", "#3B82F6", "open"),
            ("Подтверждено", "#F59E0B", "open"),
            ("Визит состоялся", "#10B981", "won"),
            ("Отмена", "#EF4444", "lost"),
        ],
    },
}


def apply_preset(db: Session, key: str) -> tuple[int, int]:
    """Возвращает (создано полей, создано статусов)."""
    preset = PRESETS.get(key)
    if preset is None:
        raise KeyError(key)

    template = None
    if preset.get("template"):
        template = deal_template_service.find_by_name(db, preset["template"]) or deal_template_service.create_template(
            db, name=preset["template"]
        )

    new_fields = new_statuses = 0
    for entity, label, ftype, options in preset["fields"]:
        in_template = template is not None and entity == EntityType.DEAL
        existing = db.scalar(
            select(CustomField).where(
                CustomField.entity_type == entity, func.lower(CustomField.label) == label.lower()
            )
        )
        if existing is None:
            custom_field_service.create_field(
                db, entity_type=entity, label=label, field_type=ftype, options=options, show_in_list=True,
                template_id=template.id if in_template else None,
            )
            new_fields += 1
        elif in_template and existing.template_id is None:
            existing.template_id = template.id
            db.commit()

    existing_names = {name.lower() for name in db.scalars(select(Status.name))}
    for name, color, kind in preset["statuses"]:
        if name.lower() not in existing_names:
            status_service.create_status(db, name=name, color=color, kind=kind)
            new_statuses += 1
    return new_fields, new_statuses
