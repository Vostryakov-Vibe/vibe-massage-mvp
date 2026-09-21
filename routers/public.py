"""Публичная часть: лендинг, юридические страницы и API онлайн-записи."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
import integrations
import scheduling
from database import get_db
from models import Booking, Client, Master, Review, Service
from security import client_ip, rate_limit
from templating import templates
from utils import human_date, human_time, money, normalize_phone

logger = logging.getLogger("salon.public")
router = APIRouter()

# Подписанный токен формы: защищает от «мгновенных» ботов-скриптов.
form_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="booking-form")
FORM_MIN_SECONDS = 3
FORM_MAX_SECONDS = 7200


# --- Страницы --------------------------------------------------------------


@router.get("/", include_in_schema=False)
def landing(request: Request, db: Session = Depends(get_db)):
    """Главная страница салона."""
    services = db.scalars(
        select(Service).where(Service.is_active.is_(True)).order_by(Service.sort_order, Service.title)
    ).all()
    masters = db.scalars(
        select(Master)
        .where(Master.is_active.is_(True), Master.is_system.is_(False))
        .order_by(Master.experience_years.desc())
    ).all()
    reviews = db.scalars(
        select(Review).where(Review.is_published.is_(True)).order_by(Review.created_at.desc()).limit(9)
    ).all()

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "services": services,
            "masters": masters,
            "reviews": reviews,
            "categories": sorted({service.category for service in services}),
            "today": date.today(),
        },
    )


@router.get("/policy/privacy", include_in_schema=False)
def privacy_policy(request: Request):
    """Политика конфиденциальности (152-ФЗ)."""
    return templates.TemplateResponse(request, "policy_privacy.html", {"updated": date.today()})


@router.get("/policy/consent", include_in_schema=False)
def consent_page(request: Request):
    """Согласие на обработку персональных данных."""
    return templates.TemplateResponse(request, "policy_consent.html", {"updated": date.today()})


# --- API онлайн-записи -----------------------------------------------------


@router.get("/api/public/config")
def public_config():
    """Настройки для фронтенда: антиспам и контакты."""
    return {
        "turnstile_enabled": config.TURNSTILE_ENABLED,
        "turnstile_site_key": config.TURNSTILE_SITE_KEY,
        "min_lead_minutes": config.MIN_LEAD_MINUTES,
        "salon": config.SALON,
    }


@router.get("/api/public/form-token")
def form_token():
    """Выдаёт подписанный токен формы (антиспам-проверка по времени)."""
    issued_at = int(datetime.now().timestamp())
    return {"token": form_serializer.dumps({"ts": issued_at})}


@router.get("/api/public/services")
def public_services(db: Session = Depends(get_db)):
    """Список активных услуг."""
    services = db.scalars(
        select(Service).where(Service.is_active.is_(True)).order_by(Service.sort_order, Service.title)
    ).all()
    return {
        "items": [
            {
                "id": service.id,
                "title": service.title,
                "slug": service.slug,
                "category": service.category,
                "duration_minutes": service.duration_minutes,
                "duration_label": service.duration_label,
                "price": service.price,
                "price_label": money(service.price),
                "short_description": service.short_description,
            }
            for service in services
        ]
    }


@router.get("/api/public/masters")
def public_masters(service_id: int | None = None, db: Session = Depends(get_db)):
    """Список активных мастеров (для формы записи)."""
    masters = db.scalars(
        select(Master)
        .where(Master.is_active.is_(True), Master.is_system.is_(False))
        .order_by(Master.full_name)
    ).all()
    return {
        "items": [
            {
                "id": master.id,
                "full_name": master.full_name,
                "specialization": master.specialization,
                "experience_years": master.experience_years,
                "avatar_url": f"/static/uploads/{master.avatar_filename}" if master.avatar_filename else "",
            }
            for master in masters
        ]
    }


@router.get("/api/public/slots")
def public_slots(
    service_id: int,
    master_id: int,
    date_str: str,
    db: Session = Depends(get_db),
):
    """Свободные таймслоты мастера на дату с учётом длительности услуги."""
    service = db.get(Service, service_id)
    master = db.get(Master, master_id)
    if service is None or not service.is_active:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    if master is None or not master.is_active:
        raise HTTPException(status_code=404, detail="Мастер не найден")

    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты") from None

    if day < date.today():
        return {"slots": [], "message": "Дата уже прошла"}
    if day > date.today() + timedelta(days=60):
        return {"slots": [], "message": "Запись открыта на 60 дней вперёд"}

    shift = scheduling.get_shift(db, master.id, day)
    slots = scheduling.available_slots(db, master, service, day)
    return {
        "slots": slots,
        "date": day.isoformat(),
        "date_label": f"{human_date(day)}, {human_time(shift.start_time) if shift else ''}",
        "shift": (
            f"{human_time(shift.start_time)}–{human_time(shift.end_time)}" if shift else ""
        ),
        "message": "" if slots else "На этот день свободных окон нет — выберите другую дату",
    }


class BookingRequest(BaseModel):
    """Данные формы онлайн-записи (имена полей совпадают с JSON фронтенда)."""

    service_id: int
    master_id: int
    date: str
    time: str
    full_name: str
    phone: str
    contact: str = ""
    comment: str = ""
    consent: bool = False
    honeypot: str = ""
    form_token: str = ""
    turnstile_token: str = ""


def _verify_turnstile(token: str, ip: str) -> tuple[bool, str]:
    """Проверка Cloudflare Turnstile (только если ключи заданы в .env)."""
    if not config.TURNSTILE_ENABLED:
        return True, ""

    import requests  # локальный импорт: при офлайн-режиме библиотека не нужна

    try:
        response = requests.post(
            config.TURNSTILE_VERIFY_URL,
            data={
                "secret": config.TURNSTILE_SECRET_KEY,
                "response": token,
                "remoteip": ip,
            },
            timeout=10,
        )
        payload = response.json()
    except Exception as error:  # noqa: BLE001 — сеть может быть недоступна
        logger.warning("Turnstile недоступен: %s", error)
        return False, "Не удалось проверить капчу. Попробуйте ещё раз или позвоните нам."

    if payload.get("success"):
        return True, ""
    return False, "Проверка «я не робот» не пройдена"


@router.post("/api/public/bookings")
def create_booking(
    payload: BookingRequest,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Создаёт запись на массаж с полным набором антиспам-проверок."""
    ip = client_ip(request)

    # 1. Honeypot: скрытое поле заполняют только боты.
    if payload.honeypot.strip():
        logger.info("Заявка отклонена: заполнено honeypot-поле (IP %s)", ip)
        raise HTTPException(status_code=400, detail="Заявка отклонена")

    # 2. Токен формы: отсекает мгновенные отправки и «просроченные» страницы.
    try:
        data = form_serializer.loads(payload.form_token, max_age=FORM_MAX_SECONDS)
    except SignatureExpired:
        raise HTTPException(status_code=400, detail="Форма устарела — обновите страницу") from None
    except BadSignature:
        raise HTTPException(status_code=400, detail="Некорректный токен формы") from None

    age = datetime.now().timestamp() - float(data.get("ts", 0))
    if age < FORM_MIN_SECONDS:
        raise HTTPException(status_code=400, detail="Слишком быстрая отправка формы")

    # 3. Turnstile (если настроен).
    ok, reason = _verify_turnstile(payload.turnstile_token, ip)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    # 4. Согласие на обработку персональных данных (152-ФЗ).
    if not payload.consent:
        raise HTTPException(
            status_code=400, detail="Отметьте согласие на обработку персональных данных"
        )

    # 5. Валидация данных клиента.
    full_name = payload.full_name.strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Укажите имя")
    phone = normalize_phone(payload.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Укажите корректный телефон")

    service = db.get(Service, payload.service_id)
    master = db.get(Master, payload.master_id)
    if service is None or not service.is_active:
        raise HTTPException(status_code=404, detail="Услуга недоступна")
    if master is None or not master.is_active:
        raise HTTPException(status_code=404, detail="Мастер недоступен")

    try:
        day = datetime.strptime(payload.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты") from None

    available, reason = scheduling.is_slot_available(db, master, service, day, payload.time)
    if not available:
        raise HTTPException(status_code=409, detail=reason)

    visit_time = datetime.strptime(payload.time, "%H:%M").time()

    # 6. Лимит заявок с одного IP. Считаем только заявки, прошедшие проверки выше:
    #    иначе отклонённые попытки (быстрая отправка, нет согласия, занятый слот)
    #    расходовали бы квоту и реальная запись получала бы 429 вместо своего ответа.
    if not rate_limit(f"booking:{ip}", limit=5, window_seconds=600):
        raise HTTPException(
            status_code=429, detail="Слишком много заявок с одного адреса. Позвоните нам, пожалуйста."
        )

    # 7. Клиент: ищем по телефону, иначе создаём. Согласие фиксируем всегда.
    client = db.scalar(select(Client).where(Client.phone == phone))
    if client is None:
        client = Client(full_name=full_name, phone=phone)
        db.add(client)
        db.flush()
    client.full_name = full_name
    if payload.contact.strip():
        client.telegram_vk_contact = payload.contact.strip()
    client.consent_given = True
    client.consent_date = datetime.now()
    client.consent_ip = ip

    # 8. Запись. Стоимость фиксируется на момент бронирования.
    booking = Booking(
        client_id=client.id,
        service_id=service.id,
        master_id=master.id,
        service_title=service.title,
        master_name=master.full_name,
        visit_date=day,
        visit_time=visit_time,
        status=config.STATUS_NEW,
        total_cost=service.price,
        comment=payload.comment.strip(),
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    logger.info(
        "Новая запись #%s: %s, %s в %s (%s)",
        booking.id, service.title, human_date(day), human_time(visit_time), master.full_name,
    )

    # 9. Уведомление сотрудникам (не блокирует ответ клиенту).
    #    Передаём id: фоновая задача работает уже после закрытия сессии запроса.
    background.add_task(integrations.notify_new_booking, booking.id)

    return {
        "ok": True,
        "ticket": {
            "code": f"ГРМ-{booking.id:06d}",
            "booking_id": booking.id,
            "service": service.title,
            "master": master.full_name,
            "date": human_date(day),
            "weekday": day.strftime("%d.%m.%Y"),
            "time": human_time(visit_time),
            "duration": service.duration_label,
            "price": money(booking.total_cost),
            "address": config.SALON["address"],
            "phone": config.SALON["phone"],
            "client": client.full_name,
        },
    }
