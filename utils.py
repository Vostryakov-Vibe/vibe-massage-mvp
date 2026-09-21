"""Мелкие утилиты: форматирование, телефоны, безопасные имена файлов."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time

import config

MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def money(value: int | float | None) -> str:
    """12345 → «12 345 ₽»."""
    if value is None:
        return "—"
    return f"{int(round(value)):,}".replace(",", " ") + " ₽"


def human_date(value: date | datetime | None) -> str:
    """2026-09-21 → «21 сентября 2026»."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.day} {MONTHS_GENITIVE[value.month - 1]} {value.year}"


def short_date(value: date | datetime | None) -> str:
    """2026-09-21 → «21.09.2026»."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d.%m.%Y")


def human_time(value: time | str | None) -> str:
    """Время → «HH:MM»."""
    if value is None:
        return "—"
    if isinstance(value, str):
        return value[:5]
    return value.strftime("%H:%M")


def weekday_name(value: date | datetime | None) -> str:
    """Название дня недели."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    return WEEKDAYS[value.weekday()]


def normalize_phone(raw: str) -> str:
    """Приводит телефон к виду +7XXXXXXXXXX.

    Возвращает пустую строку, если номер не похож на российский.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:  # 9991234567
        digits = "7" + digits
    elif len(digits) == 11 and digits[0] == "8":  # 89991234567
        digits = "7" + digits[1:]
    if len(digits) != 11 or not digits.startswith("7"):
        return ""
    return f"+{digits}"


def tel_href(value: str) -> str:
    """Телефон → значение для ссылки tel: (только цифры и ведущий плюс)."""
    digits = re.sub(r"\D", "", value or "")
    return f"+{digits}" if digits else ""


def slugify(value: str) -> str:
    """Транслитерация в slug для URL (кириллица → латиница)."""
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya",
    }
    text = unicodedata.normalize("NFKD", (value or "").lower())
    result = "".join(table.get(char, char) for char in text)
    result = re.sub(r"[^a-z0-9]+", "-", result).strip("-")
    return result or "item"


def safe_filename(value: str, fallback: str = "file") -> str:
    """Безопасное имя файла без путей и спецсимволов."""
    name = (value or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")
    return name or fallback


def status_tone(status: str) -> str:
    """CSS-класс Tailwind для бейджа статуса."""
    return {
        config.STATUS_NEW: "bg-sky-100 text-sky-800 border-sky-200",
        config.STATUS_INFORMING: "bg-indigo-100 text-indigo-800 border-indigo-200",
        config.STATUS_ADJUSTMENT: "bg-amber-100 text-amber-900 border-amber-200",
        config.STATUS_CONFIRMED: "bg-emerald-100 text-emerald-900 border-emerald-200",
        config.STATUS_DONE: "bg-teal-600 text-white border-teal-700",
        config.STATUS_CANCELLED: "bg-rose-100 text-rose-800 border-rose-200",
        config.STATUS_NO_SHOW: "bg-slate-200 text-slate-700 border-slate-300",
    }.get(status, "bg-slate-100 text-slate-700 border-slate-200")


def plural_ru(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение: 1 запись / 2 записи / 5 записей."""
    count = abs(count) % 100
    if 11 <= count <= 19:
        return many
    count %= 10
    if count == 1:
        return one
    if 2 <= count <= 4:
        return few
    return many
