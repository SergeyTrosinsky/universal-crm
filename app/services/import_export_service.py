"""Импорт и экспорт клиентов и сделок (CSV / XLSX), включая пользовательские поля.

Импорт: файл -> Table (tabular.py) -> построчная проверка и запись теми же сервисами, что и формы
(client_service / deal_service), поэтому правила (обязательные поля, права на назначение, статусы,
шаблоны) везде одни и те же. Предпросмотр — это тот же прогон в транзакции, которая откатывается;
загрузка — тот же прогон с подтверждением. Колонки находятся по заголовкам, порядок не важен."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.labels import CLIENT_TYPE_LABELS, CURRENCIES
from app.core.timezone import to_local, today_local
from app.core.validators import normalize_email, normalize_phone
from app.models import Client, CustomField, Deal, FieldType, User
from app.services import (
    client_service, deal_service, deal_template_service, eav_service, status_service,
)
from app.services.errors import ValidationFailed
from app.services.pagination import Page
from app.services.tabular import (
    CSV_MIME, XLSX_MIME, ListValidation, Table, XlsxSpec, normalize_header, write_csv, write_xlsx,
)

CLIENTS = "clients"
DEALS = "deals"
KINDS = (CLIENTS, DEALS)
DUPLICATES = ("skip", "update", "allow")
MAX_EXPORT_ROWS = 50000
AMBIGUOUS = -1

ACTION_LABELS = {"create": "Будет создано", "update": "Будет обновлено", "skip": "Пропущено", "error": "Ошибка"}


@dataclass(frozen=True)
class BaseColumn:
    key: str
    header: str
    aliases: tuple[str, ...] = ()
    required: bool = False
    hint: str = ""


CLIENT_COLUMNS: tuple[BaseColumn, ...] = (
    BaseColumn("type", "Тип", ("type", "вид"), hint="Физлицо или Компания. Пусто — Физлицо."),
    BaseColumn("name", "Имя", ("название", "фио", "наименование", "name", "имя или название"), True,
               "Имя человека или название компании."),
    BaseColumn("company_name", "Компания", ("организация", "company", "название компании"),
               hint="Для физлица — место работы, необязательно."),
    BaseColumn("email", "Email", ("e-mail", "почта", "эл. почта", "электронная почта", "mail"),
               hint="Адрес электронной почты. По нему ищутся повторы."),
    BaseColumn("phone", "Телефон", ("phone", "тел", "тел.", "номер телефона", "мобильный"),
               hint="Любой формат, например +7 (916) 123-45-67. По нему ищутся повторы."),
    BaseColumn("address", "Адрес", ("address",), hint="Свободный текст."),
    BaseColumn("notes", "Заметки", ("примечание", "комментарий", "notes", "заметка"), hint="Свободный текст."),
    BaseColumn("owner", "Ответственный", ("менеджер", "owner", "ответственный сотрудник"),
               hint="Email или ФИО сотрудника из CRM. Пусто — тот, кто загружает файл."),
)

DEAL_COLUMNS: tuple[BaseColumn, ...] = (
    BaseColumn("title", "Название", ("название заказа", "название сделки", "заказ", "сделка", "title"), True,
               "Короткое название записи."),
    BaseColumn("client_name", "Клиент", ("имя клиента", "заказчик", "client"),
               hint="Имя — только если нет телефона и email. Найдётся, если совпадает ровно с одним клиентом."),
    BaseColumn("client_phone", "Телефон клиента", ("телефон заказчика", "client phone"),
               hint="По телефону находится клиент. Клиент должен уже быть в CRM."),
    BaseColumn("client_email", "Email клиента", ("email заказчика", "client email", "почта клиента"),
               hint="По email находится клиент. Клиент должен уже быть в CRM."),
    BaseColumn("amount", "Сумма", ("стоимость", "цена", "amount", "сумма заказа"),
               hint="Число, например 15000 или 1 500,50. Пусто — 0."),
    BaseColumn("currency", "Валюта", ("currency",), hint="RUB, USD, EUR… Пусто — валюта по умолчанию."),
    BaseColumn("deal_date", "Дата", ("дата заказа", "дата сделки", "date"),
               hint="ДД.ММ.ГГГГ или ГГГГ-ММ-ДД. Пусто — сегодня."),
    BaseColumn("status", "Статус", ("status", "этап"),
               hint="Название статуса из настроек. Пусто — статус по умолчанию."),
    BaseColumn("responsible", "Ответственный", ("менеджер", "исполнитель", "responsible"),
               hint="Email или ФИО сотрудника. Пусто — тот, кто загружает файл."),
    BaseColumn("template", "Шаблон", ("template", "тип заказа"),
               hint="Название шаблона. Пусто или «Стандартная форма» — без шаблона."),
    BaseColumn("description", "Описание", ("комментарий", "примечание", "description"), hint="Свободный текст."),
)

COLUMNS = {CLIENTS: CLIENT_COLUMNS, DEALS: DEAL_COLUMNS}
DEAL_AMOUNT_COLUMN = 1 + [c.key for c in DEAL_COLUMNS].index("amount")

ERROR_LABELS = {
    "type": "Тип", "name": "Имя", "company_name": "Компания", "email": "Email", "phone": "Телефон",
    "address": "Адрес", "notes": "Заметки", "owner_id": "Ответственный", "title": "Название",
    "client_id": "Клиент", "amount": "Сумма", "currency": "Валюта", "deal_date": "Дата",
    "status_id": "Статус", "responsible_id": "Ответственный", "template_id": "Шаблон",
    "description": "Описание",
}
STANDARD_TEMPLATE_WORDS = {
    normalize_header(w)
    for w in ("Стандартная форма", "Стандартная", "Без шаблона", "Нет", "-", "—", "none")
}
TYPE_WORDS: dict[str, str] = {
    **{normalize_header(code): code for code in CLIENT_TYPE_LABELS},
    **{normalize_header(label): code for code, label in CLIENT_TYPE_LABELS.items()},
    **{normalize_header(w): "person" for w in ("Физическое лицо", "Физ. лицо", "Физ лицо", "Человек", "Частное лицо")},
    **{normalize_header(w): "company" for w in ("Юрлицо", "Юридическое лицо", "Юр. лицо", "Юр лицо", "Организация")},
}


@dataclass
class ColumnMap:
    base: dict[str, int] = field(default_factory=dict)
    custom: dict[int, int] = field(default_factory=dict)
    headers: dict[int, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def cell(self, cells: Sequence[Any], key: str) -> Any:
        index = self.base.get(key)
        return cells[index] if index is not None and index < len(cells) else None


def field_headers(fields: Sequence[CustomField], reserved: set[str]) -> dict[int, str]:
    """Заголовки колонок для пользовательских полей. Если подпись повторяется или совпадает с
    обычной колонкой, добавляется код: «Мастер (master)»."""
    counts = Counter(normalize_header(f.label) for f in fields)
    result: dict[int, str] = {}
    for f in fields:
        norm = normalize_header(f.label)
        result[f.id] = f.label if counts[norm] == 1 and norm not in reserved else f"{f.label} ({f.code})"
    return result


def _reserved(columns: Sequence[BaseColumn]) -> set[str]:
    return {normalize_header(n) for c in columns for n in (c.header, *c.aliases)}


def map_columns(headers: Sequence[str], columns: Sequence[BaseColumn], fields: Sequence[CustomField]) -> ColumnMap:
    reserved = _reserved(columns)
    names = field_headers(fields, reserved)
    labels = Counter(normalize_header(f.label) for f in fields)
    lookup: dict[str, tuple[str, Any]] = {}
    for column in columns:
        for name in (column.header, *column.aliases):
            lookup.setdefault(normalize_header(name), ("base", column.key))
    for f in fields:
        candidates = [names[f.id], f.code]
        norm_label = normalize_header(f.label)
        if labels[norm_label] == 1 and norm_label not in reserved:
            candidates.append(f.label)
        for name in candidates:
            lookup.setdefault(normalize_header(name), ("field", f.id))

    result = ColumnMap(headers=dict(names))
    for index, header in enumerate(headers):
        if not header:
            continue
        found = lookup.get(normalize_header(header))
        if found is None:
            result.warnings.append(f"Колонка «{header}» не распознана и будет пропущена")
            continue
        kind, key = found
        target = result.base if kind == "base" else result.custom
        if key in target:
            result.warnings.append(f"Колонка «{header}» повторяется — используется первая")
            continue
        target[key] = index
    return result


@dataclass
class RowResult:
    row: int
    action: str
    title: str
    messages: list[str] = field(default_factory=list)


@dataclass
class Report:
    kind: str
    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    rows: list[RowResult] = field(default_factory=list)
    file_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def loadable(self) -> int:
        return self.created + self.updated

    def add(self, result: RowResult) -> None:
        self.rows.append(result)
        self.total += 1
        if result.action == "create":
            self.created += 1
        elif result.action == "update":
            self.updated += 1
        elif result.action == "skip":
            self.skipped += 1
        else:
            self.failed += 1


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return str(value).strip()


def _split_multi(field_: CustomField, text: str) -> list[str]:
    options = field_.options or []
    parts = [p.strip() for p in text.split(";") if p.strip()]
    if len(parts) == 1 and "," in text and text.strip() not in options:
        parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts


def _parse_datetime_text(text: str) -> datetime | str:
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return text


def _custom_raw(field_: CustomField, value: Any) -> Any:
    """Значение ячейки -> то, что принимает eav_service.coerce_value."""
    if value is None:
        return None
    if field_.field_type == FieldType.MULTISELECT:
        return _split_multi(field_, _text(value))
    if field_.field_type == FieldType.DATETIME and isinstance(value, str):
        return _parse_datetime_text(value)
    return value


def _format_errors(errors: dict[str, str], label_for: Callable[[str], str]) -> list[str]:
    return [f"{label_for(key)}: {message}" for key, message in errors.items()]


def _label_resolver(cmap: ColumnMap, fields: dict[int, CustomField]) -> Callable[[str], str]:
    by_code = {f.code: cmap.headers.get(f.id, f.label) for f in fields.values()}

    def label_for(key: str) -> str:
        if key.startswith(eav_service.FORM_PREFIX):
            code = key[len(eav_service.FORM_PREFIX):]
            return by_code.get(code, code)
        return ERROR_LABELS.get(key, key)

    return label_for


def email_key(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        return normalize_email(text)
    except ValueError:
        return None


def phone_key(value: Any) -> str | None:
    """Телефон для сравнения: только цифры, последние 10 (8 916… и +7 916… — один номер)."""
    text = _text(value)
    if not text:
        return None
    try:
        normalize_phone(text)
    except ValueError:
        return None
    digits = re.sub(r"\D", "", text)
    return digits[-10:] if len(digits) >= 5 else None


def _put(mapping: dict[str, int], key: str | None, client_id: int) -> None:
    if key is None:
        return
    mapping[key] = client_id if mapping.get(key, client_id) == client_id else AMBIGUOUS


class ClientIndex:
    """Поиск клиентов по email, телефону и имени без запросов на каждую строку."""

    def __init__(self, db: Session):
        self.email: dict[str, int] = {}
        self.phone: dict[str, int] = {}
        self.name: dict[str, int] = {}
        for cid, name, email, phone in db.execute(select(Client.id, Client.name, Client.email, Client.phone)):
            self.add(cid, name, email, phone)

    def add(self, client_id: int, name: Any, email: Any, phone: Any) -> None:
        _put(self.email, email_key(email), client_id)
        _put(self.phone, phone_key(phone), client_id)
        norm = normalize_header(name)
        if norm:
            _put(self.name, norm, client_id)

    def match(self, email: Any, phone: Any) -> tuple[set[int], bool]:
        """(найденные id, были ли неоднозначные совпадения)."""
        found: set[int] = set()
        ambiguous = False
        for mapping, key in ((self.email, email_key(email)), (self.phone, phone_key(phone))):
            if key is None or key not in mapping:
                continue
            if mapping[key] == AMBIGUOUS:
                ambiguous = True
            else:
                found.add(mapping[key])
        return found, ambiguous

    def find_for_deal(self, email: Any, phone: Any, name: Any) -> int:
        """id клиента для сделки; ValueError — понятное пользователю объяснение."""
        has_contact = bool(_text(email) or _text(phone))
        if has_contact:
            found, ambiguous = self.match(email, phone)
            if ambiguous:
                raise ValueError("Под этот телефон или email подходит несколько клиентов — уточните данные")
            if len(found) > 1:
                raise ValueError("Телефон и email принадлежат разным клиентам")
            if found:
                return next(iter(found))
            raise ValueError("Клиент с таким телефоном или email не найден — сначала загрузите клиентов")
        label = _text(name)
        if not label:
            raise ValueError("Укажите телефон или email клиента")
        mapped = self.name.get(normalize_header(label))
        if mapped is None:
            raise ValueError(f"Клиент «{label}» не найден — укажите его телефон или email")
        if mapped == AMBIGUOUS:
            raise ValueError(f"Клиентов с именем «{label}» несколько — укажите телефон или email")
        return mapped


class UserIndex:
    """Сотрудник по email или ФИО."""

    def __init__(self, db: Session):
        self.email: dict[str, int] = {}
        self.name: dict[str, int] = {}
        for user in db.scalars(select(User).where(User.is_active.is_(True))):
            self.email[user.email.lower()] = user.id
            key = normalize_header(user.full_name)
            self.name[key] = AMBIGUOUS if key in self.name else user.id

    def find(self, value: Any) -> int:
        text = _text(value)
        if text.lower() in self.email:
            return self.email[text.lower()]
        mapped = self.name.get(normalize_header(text))
        if mapped is None:
            raise ValueError(f"Сотрудник «{text}» не найден")
        if mapped == AMBIGUOUS:
            raise ValueError(f"Сотрудников с именем «{text}» несколько — укажите email")
        return mapped


def _missing_required(cmap: ColumnMap, columns: Sequence[BaseColumn], fields: Sequence[CustomField]) -> list[str]:
    missing = [c.header for c in columns if c.required and c.key not in cmap.base]
    for f in fields:
        if f.is_required and f.field_type != FieldType.BOOLEAN and f.id not in cmap.custom:
            missing.append(cmap.headers.get(f.id, f.label))
    return missing


def import_clients(db: Session, table: Table, actor: User, *, duplicates: str = "skip") -> Report:
    report = Report(kind=CLIENTS)
    fields = client_service.active_fields(db)
    by_id = {f.id: f for f in fields}
    cmap = map_columns(table.headers, CLIENT_COLUMNS, fields)
    report.warnings = list(cmap.warnings)
    missing = _missing_required(cmap, CLIENT_COLUMNS, fields)
    if missing:
        report.file_errors.append("В файле нет обязательных колонок: " + ", ".join(f"«{m}»" for m in missing))
        return report

    label_for = _label_resolver(cmap, by_id)
    users = UserIndex(db)
    index = ClientIndex(db)
    update_mode = duplicates == "update"

    for number, cells in table.rows:
        data: dict[str, Any] = {}
        problems: list[str] = []
        for key in ("name", "company_name", "email", "phone", "address", "notes"):
            if key in cmap.base:
                data[key] = _text(cmap.cell(cells, key))
        title = data.get("name") or "(без имени)"

        type_text = _text(cmap.cell(cells, "type"))
        if type_text:
            code = TYPE_WORDS.get(normalize_header(type_text))
            if code is None:
                problems.append(f"Тип: «{type_text}» — допустимо «Физлицо» или «Компания»")
            else:
                data["type"] = code
        owner_text = _text(cmap.cell(cells, "owner"))
        if owner_text:
            try:
                data["owner_id"] = users.find(owner_text)
            except ValueError as e:
                problems.append(f"Ответственный: {e}")
        custom = {
            by_id[fid].code: _custom_raw(by_id[fid], cells[idx] if idx < len(cells) else None)
            for fid, idx in cmap.custom.items()
        }
        if problems:
            report.add(RowResult(number, "error", title, problems))
            continue

        found, ambiguous = index.match(data.get("email"), data.get("phone"))
        try:
            if not found and not ambiguous:
                client = client_service.create_client(db, data=data, custom=custom, actor=actor, commit=False)
                index.add(client.id, client.name, client.email, client.phone)
                report.add(RowResult(number, "create", title))
            elif not update_mode:
                report.add(RowResult(number, "skip", title, ["Такой клиент уже есть (совпал email или телефон)"]))
            elif ambiguous or len(found) > 1:
                report.add(RowResult(number, "error", title, ["Email или телефон подходят нескольким клиентам"]))
            else:
                client = db.get(Client, next(iter(found)))
                payload = {k: v for k, v in data.items() if v not in (None, "")}
                filled = {k: v for k, v in custom.items() if v not in (None, [])}
                client_service.update_client(
                    db, client, data=payload, custom=filled, actor=actor, partial=True, commit=False
                )
                index.add(client.id, client.name, client.email, client.phone)
                report.add(RowResult(number, "update", client.name, ["Обновлены заполненные поля"]))
        except ValidationFailed as e:
            report.add(RowResult(number, "error", title, _format_errors(e.errors, label_for)))
    return report


def import_deals(db: Session, table: Table, actor: User, *, duplicates: str = "skip") -> Report:
    report = Report(kind=DEALS)
    fields = deal_service.active_fields(db)
    by_id = {f.id: f for f in fields}
    cmap = map_columns(table.headers, DEAL_COLUMNS, fields)
    report.warnings = list(cmap.warnings)

    missing = [c.header for c in DEAL_COLUMNS if c.required and c.key not in cmap.base]
    missing += [
        cmap.headers.get(f.id, f.label)
        for f in fields
        if f.template_id is None and f.is_required and f.field_type != FieldType.BOOLEAN and f.id not in cmap.custom
    ]
    if missing:
        report.file_errors.append("В файле нет обязательных колонок: " + ", ".join(f"«{m}»" for m in missing))
    if not any(k in cmap.base for k in ("client_phone", "client_email", "client_name")):
        report.file_errors.append(
            "Нужна колонка, по которой находится клиент: «Телефон клиента» или «Email клиента»"
        )
    if report.file_errors:
        return report

    label_for = _label_resolver(cmap, by_id)
    users = UserIndex(db)
    clients = ClientIndex(db)
    statuses = {normalize_header(s.name): s.id for s in status_service.list_statuses(db)}
    templates = {normalize_header(t.name): t for t in deal_template_service.list_templates(db)}

    for number, cells in table.rows:
        title = _text(cmap.cell(cells, "title")) or "(без названия)"
        data: dict[str, Any] = {"title": _text(cmap.cell(cells, "title"))}
        problems: list[str] = []

        try:
            data["client_id"] = clients.find_for_deal(
                cmap.cell(cells, "client_email"), cmap.cell(cells, "client_phone"), cmap.cell(cells, "client_name")
            )
        except ValueError as e:
            problems.append(f"Клиент: {e}")

        for key in ("amount", "currency", "deal_date", "description"):
            if key in cmap.base:
                data[key] = cmap.cell(cells, key)

        status_text = _text(cmap.cell(cells, "status"))
        if status_text:
            if normalize_header(status_text) in statuses:
                data["status_id"] = statuses[normalize_header(status_text)]
            else:
                problems.append(f"Статус: «{status_text}» не найден в настройках")

        responsible_text = _text(cmap.cell(cells, "responsible"))
        if responsible_text:
            try:
                data["responsible_id"] = users.find(responsible_text)
            except ValueError as e:
                problems.append(f"Ответственный: {e}")

        template = None
        template_text = _text(cmap.cell(cells, "template"))
        if template_text and normalize_header(template_text) not in STANDARD_TEMPLATE_WORDS:
            template = templates.get(normalize_header(template_text))
            if template is None:
                problems.append(f"Шаблон: «{template_text}» не найден в настройках")
            else:
                data["template_id"] = template.id

        applicable = {f.id for f in deal_template_service.fields_for_template(fields, template.id if template else None)}
        custom: dict[str, Any] = {}
        for fid, idx in cmap.custom.items():
            f = by_id[fid]
            value = cells[idx] if idx < len(cells) else None
            if fid in applicable:
                custom[f.code] = _custom_raw(f, value)
            elif value is not None:
                owner_name = f.template.name if f.template else "другого шаблона"
                problems.append(
                    f"{cmap.headers.get(fid, f.label)}: поле есть только у шаблона «{owner_name}» — укажите его в колонке «Шаблон»"
                )

        if problems:
            report.add(RowResult(number, "error", title, problems))
            continue
        try:
            if duplicates != "allow":
                base, base_errors = deal_service.check_new(db, data, actor)
                if not base_errors and deal_service.find_duplicate(db, base) is not None:
                    report.add(RowResult(
                        number, "skip", title,
                        ["Такая запись уже есть (совпали клиент, название, сумма и дата)"],
                    ))
                    continue
            deal_service.create_deal(db, data=data, custom=custom, actor=actor, commit=False)
            report.add(RowResult(number, "create", title))
        except ValidationFailed as e:
            report.add(RowResult(number, "error", title, _format_errors(e.errors, label_for)))
    return report


def run_import(
    db: Session, kind: str, table: Table, actor: User, *, duplicates: str = "skip", commit: bool
) -> Report:
    """Один и тот же прогон для предпросмотра (commit=False, всё откатывается) и для загрузки."""
    if duplicates not in DUPLICATES or (kind == CLIENTS and duplicates == "allow") or (kind == DEALS and duplicates == "update"):
        duplicates = "skip"
    try:
        if kind == CLIENTS:
            report = import_clients(db, table, actor, duplicates=duplicates)
        else:
            report = import_deals(db, table, actor, duplicates=duplicates)
        if commit and not report.file_errors and report.loadable:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    return report


def collect(fetch: Callable[[int, int], Page], *, batch: int = 500, limit: int = MAX_EXPORT_ROWS) -> list:
    """Забирает все страницы выборки (fetch(page, per_page) -> Page)."""
    items: list = []
    page = 1
    while True:
        result = fetch(page, batch)
        items.extend(result.items)
        if not result.has_next or len(items) >= limit:
            return items[:limit]
        page += 1


def _export_value(field_: CustomField, value: Any) -> Any:
    ftype = field_.field_type
    if value is None or value == [] or value == "":
        return None
    if ftype == FieldType.BOOLEAN:
        return "Да" if value else "Нет"
    if ftype == FieldType.MULTISELECT:
        return "; ".join(str(v) for v in value)
    if ftype == FieldType.INTEGER:
        return int(value)
    if ftype == FieldType.DECIMAL:
        return Decimal(value).normalize() if Decimal(value) != Decimal(value).to_integral_value() else int(value)
    if ftype == FieldType.DATETIME:
        return to_local(value).replace(tzinfo=None)
    return value


def _file(fmt: str, headers: list[str], rows: list[list[Any]], **xlsx_options: Any) -> tuple[bytes, str]:
    if fmt == "csv":
        return write_csv(headers, rows), CSV_MIME
    return write_xlsx(XlsxSpec(headers=headers, rows=rows, **xlsx_options)), XLSX_MIME


def export_clients(db: Session, clients: Sequence[Client], fmt: str) -> tuple[bytes, str]:
    fields = client_service.active_fields(db)
    names = field_headers(fields, _reserved(CLIENT_COLUMNS))
    headers = [c.header for c in CLIENT_COLUMNS] + [names[f.id] for f in fields]
    rows = []
    for c in clients:
        stored = eav_service.values_by_field(c)
        rows.append(
            [
                CLIENT_TYPE_LABELS.get(c.type.value, c.type.value), c.name, c.company_name, c.email, c.phone,
                c.address, c.notes, c.owner.full_name if c.owner else None,
                *[_export_value(f, stored.get(f.id)) for f in fields],
            ]
        )
    return _file(fmt, headers, rows)


def export_deals(db: Session, deals: Sequence[Deal], fmt: str) -> tuple[bytes, str]:
    fields = deal_service.active_fields(db)
    names = field_headers(fields, _reserved(DEAL_COLUMNS))
    headers = [c.header for c in DEAL_COLUMNS] + [names[f.id] for f in fields]
    rows = []
    for d in deals:
        stored = d.custom
        rows.append(
            [
                d.title, d.client.name, d.client.phone, d.client.email, d.amount, d.currency, d.deal_date,
                d.status.name, d.responsible.full_name if d.responsible else None,
                d.template.name if d.template else None, d.description,
                *[_export_value(f, stored.get(f.code)) for f in fields],
            ]
        )
    return _file(fmt, headers, rows, money_columns={DEAL_AMOUNT_COLUMN})


def export_filename(kind: str, fmt: str) -> str:
    return f"{kind}-{today_local():%Y-%m-%d}.{fmt}"


def _field_hint(f: CustomField) -> str:
    ftype = f.field_type
    parts: list[str] = []
    if ftype == FieldType.SELECT:
        parts.append("Одно значение из списка: " + "; ".join(f.options or []))
    elif ftype == FieldType.MULTISELECT:
        parts.append("Несколько значений из списка через «;»: " + "; ".join(f.options or []))
    elif ftype == FieldType.BOOLEAN:
        parts.append("Да или Нет")
    elif ftype in (FieldType.INTEGER, FieldType.DECIMAL):
        parts.append("Целое число" if ftype == FieldType.INTEGER else "Число, дробная часть через запятую или точку")
    elif ftype == FieldType.DATE:
        parts.append("Дата: ДД.ММ.ГГГГ")
    elif ftype == FieldType.DATETIME:
        parts.append("Дата и время: ДД.ММ.ГГГГ ЧЧ:ММ")
    elif ftype == FieldType.PHONE:
        parts.append("Телефон")
    elif ftype == FieldType.EMAIL:
        parts.append("Email")
    elif ftype == FieldType.URL:
        parts.append("Ссылка, начинается с http:// или https://")
    else:
        parts.append("Текст")
    if f.help_text:
        parts.append(f.help_text)
    if f.template is not None:
        parts.append(f"Только для шаблона «{f.template.name}»")
    return ". ".join(parts)


def build_template(db: Session, kind: str, fmt: str) -> tuple[bytes, str]:
    """Пустой файл-образец: заголовки совпадают с вашими полями. В Excel — ещё подсказки и выпадающие списки."""
    columns = COLUMNS[kind]
    fields = client_service.active_fields(db) if kind == CLIENTS else deal_service.active_fields(db)
    names = field_headers(fields, _reserved(columns))
    headers = [c.header for c in columns] + [names[f.id] for f in fields]
    if fmt == "csv":
        return write_csv(headers, []), CSV_MIME

    hints: list[tuple[str, str, str]] = []
    for c in columns:
        required = "да"
        if not c.required:
            required = "один из двух" if c.key in ("client_phone", "client_email") else "нет"
        hints.append((c.header, required, c.hint))
    for f in fields:
        hints.append((names[f.id], "да" if f.is_required and f.field_type != FieldType.BOOLEAN else "нет", _field_hint(f)))

    lists: list[ListValidation] = []
    position = {h: i for i, h in enumerate(headers, start=1)}
    if kind == CLIENTS:
        lists.append(ListValidation(position["Тип"], list(CLIENT_TYPE_LABELS.values())))
    else:
        lists.append(ListValidation(position["Статус"], [s.name for s in status_service.list_statuses(db, only_active=True)]))
        lists.append(ListValidation(position["Шаблон"], [t.name for t in deal_template_service.list_templates(db, only_active=True)]))
        lists.append(ListValidation(position["Валюта"], list(CURRENCIES)))
    for f in fields:
        if f.field_type == FieldType.SELECT and f.options:
            lists.append(ListValidation(position[names[f.id]], [str(o) for o in f.options]))
        elif f.field_type == FieldType.BOOLEAN:
            lists.append(ListValidation(position[names[f.id]], ["Да", "Нет"]))
    lists = [item for item in lists if item.values]

    money = {DEAL_AMOUNT_COLUMN} if kind == DEALS else set()
    return write_xlsx(XlsxSpec(headers=headers, hints=hints, lists=lists, money_columns=money)), XLSX_MIME


def template_filename(kind: str, fmt: str) -> str:
    return f"{kind}-import-template.{fmt}"
