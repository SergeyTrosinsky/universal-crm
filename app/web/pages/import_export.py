"""Импорт и экспорт клиентов и сделок: скачать шаблон, загрузить файл, проверить, подтвердить, выгрузить список.

Роутер подключается в web/router.py РАНЬШЕ clients и deals: иначе «/clients/export»
попадёт под «/clients/{client_id}»."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from starlette.datastructures import FormData, UploadFile

from app.core.config import get_settings
from app.core.permissions import CLIENTS_READ, CLIENTS_WRITE, DEALS_READ, DEALS_WRITE
from app.db.session import get_db
from app.models import User
from app.services import client_service, deal_service, eav_service, import_export_service as ie, import_store
from app.services.tabular import FORMATS, FileError, read_table
from app.web.deps import get_web_user, require_web_permission
from app.web.forms import fstr, get_form, optional_int
from app.web.templating import flash, redirect, render

router = APIRouter()
PREVIEW_ERROR_ROWS = 200
PREVIEW_OK_ROWS = 100
WRITE_PERMISSION = {ie.CLIENTS: CLIENTS_WRITE, ie.DEALS: DEALS_WRITE}
LIST_URL = {ie.CLIENTS: "/clients", ie.DEALS: "/deals"}


def _fmt(value: str | None) -> str:
    return value if value in FORMATS else "xlsx"


def _download(content: bytes, mime: str, filename: str) -> Response:
    return Response(
        content,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


def _kind_for(kind: str, user: User) -> str:
    if kind not in ie.KINDS:
        raise HTTPException(404, "Страница не найдена")
    if not user.can(WRITE_PERMISSION[kind]):
        raise HTTPException(403, "Недостаточно прав для этого раздела")
    return kind


@router.get("/clients/export")
def clients_export(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(CLIENTS_READ))
):
    params = request.query_params
    fields = client_service.active_fields(db)
    filters = eav_service.extract_custom_filters(fields, params)

    def fetch(page: int, per_page: int):
        return client_service.list_clients(
            db, q=params.get("q"), client_type=params.get("type"), owner_id=optional_int(params.get("owner")),
            custom_filters=filters, fields=fields, sort=params.get("sort"), page=page, per_page=per_page,
        )

    fmt = _fmt(params.get("format"))
    content, mime = ie.export_clients(db, ie.collect(fetch), fmt)
    return _download(content, mime, ie.export_filename(ie.CLIENTS, fmt))


@router.get("/deals/export")
def deals_export(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_web_permission(DEALS_READ))
):
    params = request.query_params
    fields = deal_service.active_fields(db)
    filters = eav_service.extract_custom_filters(fields, params)

    def fetch(page: int, per_page: int):
        return deal_service.list_deals(
            db, q=params.get("q"), status_id=params.get("status"), kind=params.get("kind"),
            client_id=params.get("client"), responsible_id=params.get("responsible"),
            date_from=params.get("date_from"), date_to=params.get("date_to"),
            amount_min=params.get("amount_min"), amount_max=params.get("amount_max"),
            custom_filters=filters, fields=fields, template=params.get("template"), sort=params.get("sort"),
            page=page, per_page=per_page, viewer=user,
        )

    fmt = _fmt(params.get("format"))
    content, mime = ie.export_deals(db, ie.collect(fetch), fmt)
    return _download(content, mime, ie.export_filename(ie.DEALS, fmt))


def _upload_page(request, user, kind, *, error="", status_code=200):
    ctx = {
        "kind": kind,
        "error": error,
        "max_mb": get_settings().IMPORT_MAX_FILE_MB,
        "max_rows": get_settings().IMPORT_MAX_ROWS,
    }
    return render(request, "import/upload.html", ctx, user=user, status_code=status_code)


@router.get("/import/{kind}")
def import_page(kind: str, request: Request, user: User = Depends(get_web_user)):
    return _upload_page(request, user, _kind_for(kind, user))


@router.get("/import/{kind}/template")
def import_template(kind: str, request: Request, db: Session = Depends(get_db), user: User = Depends(get_web_user)):
    _kind_for(kind, user)
    fmt = _fmt(request.query_params.get("format"))
    content, mime = ie.build_template(db, kind, fmt)
    return _download(content, mime, ie.template_filename(kind, fmt))


@router.post("/import/{kind}")
def import_preview(
    kind: str,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(get_web_user),
):
    _kind_for(kind, user)
    settings = get_settings()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return _upload_page(request, user, kind, error="Выберите файл .xlsx или .csv", status_code=400)
    limit = settings.IMPORT_MAX_FILE_MB * 1024 * 1024
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        return _upload_page(
            request, user, kind, error=f"Файл слишком большой: максимум {settings.IMPORT_MAX_FILE_MB} МБ", status_code=400
        )
    duplicates = fstr(form, "duplicates")
    duplicates = duplicates if duplicates in ie.DUPLICATES else "skip"
    try:
        table = read_table(data, upload.filename, max_rows=settings.IMPORT_MAX_ROWS)
    except FileError as e:
        return _upload_page(request, user, kind, error=str(e), status_code=400)

    report = ie.run_import(db, kind, table, user, duplicates=duplicates, commit=False)
    token = ""
    if not report.file_errors and report.loadable:
        token = import_store.save(user.id, kind, upload.filename, data, duplicates)
    errors = [r for r in report.rows if r.action == "error"]
    others = [r for r in report.rows if r.action != "error"]
    ctx = {
        "kind": kind,
        "report": report,
        "filename": upload.filename,
        "token": token,
        "duplicates": duplicates,
        "error_rows": errors[:PREVIEW_ERROR_ROWS],
        "more_errors": max(0, len(errors) - PREVIEW_ERROR_ROWS),
        "ok_rows": others[:PREVIEW_OK_ROWS],
        "more_ok": max(0, len(others) - PREVIEW_OK_ROWS),
        "action_labels": ie.ACTION_LABELS,
    }
    return render(request, "import/preview.html", ctx, user=user)


@router.post("/import/{kind}/confirm")
def import_confirm(
    kind: str,
    request: Request,
    form: FormData = Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(get_web_user),
):
    _kind_for(kind, user)
    token = fstr(form, "token")
    loaded = import_store.load(token, user.id, kind)
    if loaded is None:
        flash(request, "Загрузка устарела или не найдена — загрузите файл ещё раз", "error")
        return redirect(f"/import/{kind}")
    data, meta = loaded
    try:
        table = read_table(data, meta["filename"], max_rows=get_settings().IMPORT_MAX_ROWS)
    except FileError as e:
        import_store.discard(token)
        flash(request, str(e), "error")
        return redirect(f"/import/{kind}")
    report = ie.run_import(db, kind, table, user, duplicates=meta.get("duplicates", "skip"), commit=True)
    import_store.discard(token)

    parts = [
        f"{label}: {count}"
        for label, count in (
            ("создано", report.created), ("обновлено", report.updated),
            ("пропущено", report.skipped), ("с ошибками", report.failed),
        )
        if count
    ]
    if report.loadable:
        flash(request, "Импорт завершён — " + ", ".join(parts))
    else:
        flash(request, "Ничего не загружено" + (f" — {', '.join(parts)}" if parts else ""), "error")
    return redirect(LIST_URL[kind])
