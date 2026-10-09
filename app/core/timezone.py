"""Часовой пояс приложения. В БД всё хранится в UTC (SQLite отдаёт значения без tzinfo —
считаем их UTC), пользователь видит и вводит время в APP_TIMEZONE."""
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings


@lru_cache
def app_tz() -> tzinfo:
    try:
        return ZoneInfo(get_settings().APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        return timezone.utc


def to_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(app_tz())


def local_to_utc(value: datetime) -> datetime:
    """Наивное время трактуется как локальное; aware — просто приводится к UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=app_tz())
    return value.astimezone(timezone.utc)


def local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """[начало дня, начало следующего дня) в UTC."""
    start = datetime.combine(day, time.min).replace(tzinfo=app_tz())
    end = datetime.combine(day + timedelta(days=1), time.min).replace(tzinfo=app_tz())
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def today_local() -> date:
    return datetime.now(app_tz()).date()
