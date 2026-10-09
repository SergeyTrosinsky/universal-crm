"""Ограничение числа неудачных попыток входа (скользящее окно, в памяти процесса).

Считаются только неудачные попытки: по email (защита учётной записи от подбора) и по IP
(защита от перебора многих адресов). Успешный вход обнуляет счётчик email.
При нескольких процессах/серверах каждый считает отдельно — для небольшой CRM этого достаточно;
для кластера счётчики стоит вынести в Redis."""
from __future__ import annotations

import time
from collections import deque
from threading import Lock

from fastapi import Request

from app.core.config import get_settings

MAX_KEYS = 20000


def client_ip(request: Request) -> str:
    if get_settings().TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


class LoginLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._now = time.monotonic

    @staticmethod
    def _keys(email: str, ip: str) -> tuple[str, str]:
        return f"acct:{(email or '').strip().lower()[:254]}", f"ip:{ip}"

    def _live(self, key: str, now: float, window: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and now - hits[0] >= window:
            hits.popleft()
        if not hits:
            self._hits.pop(key, None)
        return hits

    def retry_after(self, email: str, ip: str) -> int:
        """0 — можно пробовать; иначе через сколько секунд снимется блокировка."""
        cfg = get_settings()
        window = cfg.LOGIN_WINDOW_SECONDS
        acct, ip_key = self._keys(email, ip)
        now = self._now()
        wait = 0.0
        with self._lock:
            for key, limit in ((acct, cfg.LOGIN_MAX_ATTEMPTS), (ip_key, cfg.LOGIN_MAX_ATTEMPTS_PER_IP)):
                hits = self._live(key, now, window)
                if limit > 0 and len(hits) >= limit:
                    wait = max(wait, hits[0] + window - now)
        return int(wait) + 1 if wait > 0 else 0

    def register_failure(self, email: str, ip: str) -> None:
        window = get_settings().LOGIN_WINDOW_SECONDS
        now = self._now()
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                for key in list(self._hits):
                    self._live(key, now, window)
                if len(self._hits) > MAX_KEYS:
                    self._hits.clear()
            for key in self._keys(email, ip):
                self._hits.setdefault(key, deque()).append(now)

    def register_success(self, email: str, ip: str) -> None:
        with self._lock:
            self._hits.pop(self._keys(email, ip)[0], None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = LoginLimiter()


def wait_text(seconds: int) -> str:
    minutes = (seconds + 59) // 60
    return f"{minutes} мин." if minutes > 1 else "минуту"
