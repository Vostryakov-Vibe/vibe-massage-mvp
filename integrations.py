"""Интеграции с внешними сервисами: Telegram Bot API и VK API.

Ключевое требование: приложение работает офлайн и НЕ падает, если токенов нет.
Любая ошибка отправки логируется в консоль и возвращается вызывающему коду
в виде словаря {"ok": False, "detail": "..."}.
"""

from __future__ import annotations

import logging

import requests
from sqlalchemy import select
from sqlalchemy.orm import selectinload

import config
from database import SessionLocal
from models import Booking, Post
from utils import human_date, human_time, money

logger = logging.getLogger("salon.integrations")

REQUEST_TIMEOUT = 12


# --- Telegram --------------------------------------------------------------


def telegram_configured() -> bool:
    """Настроены ли токен и чат для уведомлений."""
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def send_telegram_message(text: str, *, parse_mode: str = "HTML") -> dict:
    """Отправляет сообщение в Telegram-чат сотрудников."""
    if not telegram_configured():
        logger.warning(
            "Telegram не настроен (нет TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID) — "
            "сообщение не отправлено, работа продолжается."
        )
        return {"ok": False, "detail": "Telegram не настроен: заполните .env", "skipped": True}

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        data = response.json()
    except requests.RequestException as error:
        logger.warning("Telegram недоступен: %s", error)
        return {"ok": False, "detail": f"Сеть недоступна: {error}"}
    except ValueError:
        return {"ok": False, "detail": "Некорректный ответ Telegram"}

    if not data.get("ok"):
        description = data.get("description", "неизвестная ошибка")
        logger.warning("Telegram отклонил запрос: %s", description)
        return {"ok": False, "detail": description}
    return {"ok": True, "detail": "Отправлено в Telegram"}


def format_booking_card(booking: Booking) -> str:
    """Карточка записи для чата сотрудников (HTML)."""
    client = booking.client
    lines = [
        "🟢 <b>НОВАЯ ЗАПИСЬ</b>",
        f"<b>Услуга:</b> {booking.service_title or '—'}",
        f"<b>Мастер:</b> {booking.master_name or 'любой свободный'}",
        f"<b>Дата:</b> {human_date(booking.visit_date)} в {human_time(booking.visit_time)}",
        f"<b>Стоимость:</b> {money(booking.total_cost)}",
        "",
        f"<b>Клиент:</b> {client.full_name if client else '—'}",
        f"<b>Телефон:</b> {client.phone if client else '—'}",
    ]
    if client and client.telegram_vk_contact:
        lines.append(f"<b>Мессенджер:</b> {client.telegram_vk_contact}")
    if booking.comment:
        lines.append(f"<b>Комментарий:</b> {booking.comment}")
    lines.append(f"\n<i>Запись №{booking.id} · {config.SALON['name']}</i>")
    return "\n".join(lines)


def notify_new_booking(booking_id: int) -> dict:
    """Отправляет карточку новой записи в Telegram.

    Задача выполняется в фоне, когда сессия запроса уже закрыта, поэтому
    открываем собственную сессию и заранее подгружаем клиента записи —
    иначе обращение к booking.client падает с DetachedInstanceError.
    """
    with SessionLocal() as session:
        booking = session.scalar(
            select(Booking).options(selectinload(Booking.client)).where(Booking.id == booking_id)
        )
        if booking is None:
            logger.warning("Уведомление не отправлено: запись #%s не найдена.", booking_id)
            return {"ok": False, "detail": f"Запись #{booking_id} не найдена"}
        card = format_booking_card(booking)

    return send_telegram_message(card)


def format_post_for_channel(post: Post) -> str:
    """Текст поста для публикации."""
    return post.content.strip()


# --- VK --------------------------------------------------------------------


def vk_configured() -> bool:
    """Настроены ли токен и идентификатор группы ВК."""
    return bool(config.VK_ACCESS_TOKEN and config.VK_GROUP_ID)


def send_vk_post(message: str) -> dict:
    """Публикует запись на стене группы ВК (метод wall.post)."""
    if not vk_configured():
        logger.warning(
            "ВК не настроен (нет VK_ACCESS_TOKEN/VK_GROUP_ID) — публикация пропущена."
        )
        return {"ok": False, "detail": "ВК не настроен: заполните .env", "skipped": True}

    group_id = config.VK_GROUP_ID.lstrip("-")
    payload = {
        "access_token": config.VK_ACCESS_TOKEN,
        "owner_id": f"-{group_id}",
        "from_group": 1,
        "message": message,
        "v": "5.199",
    }
    try:
        response = requests.post(
            "https://api.vk.com/method/wall.post", data=payload, timeout=REQUEST_TIMEOUT
        )
        data = response.json()
    except requests.RequestException as error:
        logger.warning("ВК недоступен: %s", error)
        return {"ok": False, "detail": f"Сеть недоступна: {error}"}
    except ValueError:
        return {"ok": False, "detail": "Некорректный ответ ВК"}

    if "error" in data:
        message_text = data["error"].get("error_msg", "неизвестная ошибка")
        logger.warning("ВК отклонил публикацию: %s", message_text)
        return {"ok": False, "detail": message_text}
    post_id = data.get("response", {}).get("post_id")
    return {"ok": True, "detail": f"Опубликовано в ВК (post_id={post_id})"}
