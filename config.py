"""Конфигурация приложения.

Все параметры читаются из переменных окружения (.env), но каждое значение
имеет безопасный дефолт: приложение обязано запускаться «из коробки»,
локально и без интернета.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
TEMPLATES_DIR = BASE_DIR / "templates"
DATA_DIR = BASE_DIR / "data"

# .env читается из корня проекта; отсутствие файла — нормальная ситуация.
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    """Вернуть строковое значение переменной окружения."""
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_int(name: str, default: int) -> int:
    """Вернуть целочисленное значение переменной окружения."""
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    """Вернуть булево значение переменной окружения."""
    raw = _env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on", "да"}


# --- Основное --------------------------------------------------------------
def _secret_key() -> str:
    """Ключ подписи cookie: из .env либо сохранённый в instance/secret_key.

    Случайный ключ при каждом запуске ломал бы сессии админов при перезапуске
    и при нескольких процессах сервера, поэтому сгенерированный ключ храним.
    """
    path = INSTANCE_DIR / "secret_key"
    try:
        stored = path.read_text(encoding="utf-8").strip()
    except OSError:
        stored = ""
    if stored:
        return stored

    generated = secrets.token_urlsafe(48)
    try:
        INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(generated, encoding="utf-8")
        os.chmod(path, 0o600)  # на Windows вызов безвреден
    except OSError:
        pass
    return generated


SECRET_KEY = _env("SECRET_KEY") or _secret_key()
HOST = _env("HOST", "127.0.0.1")
PORT = _env_int("PORT", 8000)
DEBUG = _env_bool("DEBUG", False)
# При публикации за HTTPS-прокси включаем флаг Secure у cookie сессии.
SESSION_HTTPS_ONLY = _env_bool("SESSION_HTTPS_ONLY", False)

# --- База данных -----------------------------------------------------------
DATABASE_URL = _env("DATABASE_URL", f"sqlite:///{(INSTANCE_DIR / 'salon.db').as_posix()}")

# --- Контакты салона -------------------------------------------------------
SALON = {
    "name": _env("SALON_NAME", "Салон массажа «Гармония»"),
    "tagline": _env("SALON_TAGLINE", "Профессиональный оздоровительный массаж"),
    "address": _env("SALON_ADDRESS", "г. Москва, ул. Примерная, д. 10, офис 25"),
    "phone": _env("SALON_PHONE", "+7 (495) 123-45-67"),
    "email": _env("SALON_EMAIL", "info@harmony-massage.local"),
    "hours": _env("SALON_HOURS", "Ежедневно с 09:00 до 21:00"),
    "telegram": _env("SALON_TELEGRAM", "https://t.me/harmony_massage"),
    "vk": _env("SALON_VK", "https://vk.com/harmony_massage"),
    "whatsapp": _env("SALON_WHATSAPP", "https://wa.me/74951234567"),
}

# --- Учётные записи по умолчанию ------------------------------------------
DEFAULT_SUPERADMIN_LOGIN = _env("DEFAULT_SUPERADMIN_LOGIN", "admin")
DEFAULT_SUPERADMIN_PASSWORD = _env("DEFAULT_SUPERADMIN_PASSWORD", "admin777")
DEFAULT_MANAGER_LOGIN = _env("DEFAULT_MANAGER_LOGIN", "manager")
DEFAULT_MANAGER_PASSWORD = _env("DEFAULT_MANAGER_PASSWORD", "manager777")

# --- Интеграции ------------------------------------------------------------
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")
VK_ACCESS_TOKEN = _env("VK_ACCESS_TOKEN")
VK_GROUP_ID = _env("VK_GROUP_ID")

# --- Антиспам --------------------------------------------------------------
TURNSTILE_SITE_KEY = _env("TURNSTILE_SITE_KEY")
TURNSTILE_SECRET_KEY = _env("TURNSTILE_SECRET_KEY")
TURNSTILE_ENABLED = bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY)
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# --- Маркетинговый ИИ ------------------------------------------------------
AI_API_URL = _env("AI_API_URL", "https://text.pollinations.ai")
AI_API_TIMEOUT = _env_int("AI_API_TIMEOUT", 25)

# --- Прочее ----------------------------------------------------------------
POSTS_RETENTION_DAYS = _env_int("POSTS_RETENTION_DAYS", 30)
SLOT_STEP_MINUTES = _env_int("SLOT_STEP_MINUTES", 30)
MIN_LEAD_MINUTES = _env_int("MIN_LEAD_MINUTES", 60)

# Роли пользователей
ROLE_SUPERADMIN = "Superadmin"
ROLE_MANAGER = "Manager"

# Статусы записей (порядок = порядок колонок Канбан-доски)
STATUS_NEW = "Новая"
STATUS_INFORMING = "Информирование клиента"
STATUS_ADJUSTMENT = "Корректировка"
STATUS_CONFIRMED = "Подтверждена"
STATUS_DONE = "Выполнена"
STATUS_CANCELLED = "Отменена"
STATUS_NO_SHOW = "Не пришел"

BOOKING_STATUSES = [
    STATUS_NEW,
    STATUS_INFORMING,
    STATUS_ADJUSTMENT,
    STATUS_CONFIRMED,
    STATUS_DONE,
    STATUS_CANCELLED,
    STATUS_NO_SHOW,
]

# Статусы, при которых запись ещё занимает время мастера
ACTIVE_STATUSES = [STATUS_NEW, STATUS_INFORMING, STATUS_ADJUSTMENT, STATUS_CONFIRMED]
# Статусы «потерянной выгоды»
LOST_STATUSES = [STATUS_CANCELLED, STATUS_NO_SHOW]

SERVICE_CATEGORIES = [
    "Классический массаж",
    "Лечебный массаж",
    "Спортивный массаж",
    "Эстетический массаж",
    "Детокс и лимфодренаж",
]
