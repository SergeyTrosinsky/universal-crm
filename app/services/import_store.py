"""Временное хранилище загруженных файлов между предпросмотром и подтверждением импорта.

Файл лежит во временной папке под случайным токеном и привязан к пользователю и виду данных,
поэтому подтвердить чужую загрузку нельзя. Старые файлы удаляются при каждой новой загрузке."""
from __future__ import annotations

import json
import re
import secrets
import tempfile
import time
from pathlib import Path

from app.core.config import get_settings

TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_AGE_SECONDS = 2 * 60 * 60


def _dir() -> Path:
    configured = get_settings().IMPORT_DIR
    path = Path(configured) if configured else Path(tempfile.gettempdir()) / "crm_imports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def purge_old() -> None:
    limit = time.time() - MAX_AGE_SECONDS
    for item in _dir().iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < limit:
                item.unlink()
        except OSError:
            continue


def save(user_id: int, kind: str, filename: str, data: bytes, duplicates: str) -> str:
    purge_old()
    token = secrets.token_hex(16)
    folder = _dir()
    (folder / f"{token}.bin").write_bytes(data)
    meta = {"user_id": user_id, "kind": kind, "filename": filename, "duplicates": duplicates}
    (folder / f"{token}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return token


def load(token: str, user_id: int, kind: str) -> tuple[bytes, dict] | None:
    """Файл и параметры загрузки или None, если токен не найден, просрочен или принадлежит другому."""
    if not TOKEN_RE.match(token or ""):
        return None
    folder = _dir()
    try:
        meta = json.loads((folder / f"{token}.json").read_text(encoding="utf-8"))
        data = (folder / f"{token}.bin").read_bytes()
    except (OSError, ValueError):
        return None
    if meta.get("user_id") != user_id or meta.get("kind") != kind:
        return None
    return data, meta


def discard(token: str) -> None:
    if not TOKEN_RE.match(token or ""):
        return
    for suffix in (".bin", ".json"):
        try:
            (_dir() / f"{token}{suffix}").unlink()
        except OSError:
            pass
