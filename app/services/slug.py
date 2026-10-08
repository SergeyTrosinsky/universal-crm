"""Транслитерация названий в коды (slug): «Марка авто» -> «marka_avto»."""
import re

_RU = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text: str, fallback: str = "item", max_length: int = 50) -> str:
    result = "".join(_RU.get(ch, ch) for ch in (text or "").lower())
    result = re.sub(r"[^a-z0-9]+", "_", result).strip("_")
    if not result:
        result = fallback
    if result[0].isdigit():
        result = f"{fallback[0]}_{result}"
    return result[:max_length].strip("_") or fallback
