"""Помощники для поиска. LIKE экранируется символом «!», регистр сводится в нижний
(на SQLite lower() подменён на юникодную версию — см. db/session.py)."""
from sqlalchemy import ColumnElement, func

_ESC = "!"


def like_pattern(text: str) -> str:
    escaped = text.lower().replace(_ESC, _ESC * 2).replace("%", f"{_ESC}%").replace("_", f"{_ESC}_")
    return f"%{escaped}%"


def contains(column, text: str) -> ColumnElement[bool]:
    """Регистронезависимое «содержит» без спецсимволов LIKE."""
    return func.lower(column).like(like_pattern(text), escape=_ESC)


def digits_only(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def phone_digits(column):
    """Телефон без пробелов/скобок/дефисов/плюса — чтобы '9161234567' находил '+7 (916) 123-45-67'."""
    expr = column
    for ch in (" ", "-", "(", ")", "+", "."):
        expr = func.replace(expr, ch, "")
    return expr
