"""JSON API админ-панели: CRM, справочники, аналитика, маркетинг, пользователи.

Все изменяющие запросы защищены сессией + CSRF-токеном (заголовок X-CSRF-Token).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

import ai_marketing
import analytics
import config
import integrations
import scheduling
import seed
from database import get_db
from models import Booking, Client, Master, Post, Review, Schedule, Service, User
from security import (
    hash_password,
    require_csrf,
    require_superadmin,
    require_user,
    validate_password_strength,
)
from utils import money, normalize_phone, safe_filename, slugify

logger = logging.getLogger("salon.api")
router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_user)])


# --- Схемы запросов --------------------------------------------------------


class BookingUpdate(BaseModel):
    """Частичное обновление записи из карточки CRM."""

    status: str | None = None
    visit_date: str | None = None
    visit_time: str | None = None
    master_id: int | None = None
    total_cost: int | None = None
    comment: str | None = None


class StatusUpdate(BaseModel):
    """Смена статуса (drag&drop на Канбан-доске)."""

    status: str


class BookingCreate(BaseModel):
    """Создание записи администратором (звонок в салон)."""

    client_id: int | None = None
    full_name: str = ""
    phone: str = ""
    service_id: int
    master_id: int
    date: str
    time: str
    total_cost: int | None = None
    comment: str = ""
    force: bool = False


class ClientPayload(BaseModel):
    """Данные клиента."""

    full_name: str
    phone: str
    telegram_vk_contact: str = ""
    rating: int = 5
    admin_notes: str = ""


class ClientUpdate(BaseModel):
    """Частичное обновление клиента."""

    full_name: str | None = None
    phone: str | None = None
    telegram_vk_contact: str | None = None
    rating: int | None = None
    admin_notes: str | None = None


class ServicePayload(BaseModel):
    """Услуга."""

    title: str
    category: str = config.SERVICE_CATEGORIES[0]
    short_description: str = ""
    full_description: str = ""
    duration_minutes: int = 60
    price: int = 0
    indications: str = ""
    contraindications: str = ""
    is_active: bool = True
    sort_order: int = 100


class MasterPayload(BaseModel):
    """Мастер."""

    full_name: str
    specialization: str = ""
    experience_years: int = 0
    bio: str = ""
    is_active: bool = True


class SchedulePayload(BaseModel):
    """Массовое заполнение графика смен мастера."""

    master_id: int
    date_from: str
    date_to: str
    weekdays: list[int] = Field(default_factory=list)
    start_time: str = "10:00"
    end_time: str = "19:00"
    replace: bool = True


class MarketingRequest(BaseModel):
    """Параметры генерации маркетингового поста."""

    topic: str
    tone: str = ai_marketing.TONES[0]
    length: str = "Средний"
    keywords: str = ""
    send_telegram: bool = False
    send_vk: bool = False


class PublishRequest(BaseModel):
    """Публикация поста из архива."""

    post_id: int
    send_telegram: bool = False
    send_vk: bool = False


class UserPayload(BaseModel):
    """Создание пользователя."""

    username: str
    password: str
    role: str = config.ROLE_MANAGER
    full_name: str = ""


class UserUpdate(BaseModel):
    """Обновление пользователя."""

    password: str | None = None
    role: str | None = None
    full_name: str | None = None
    is_active: bool | None = None


class ReviewPayload(BaseModel):
    """Отзыв."""

    author_name: str
    rating: int = 5
    text: str = ""
    service_title: str = ""
    is_published: bool = True


# --- Сериализация ----------------------------------------------------------


def serialize_booking(booking: Booking) -> dict:
    """Карточка записи для Канбан-доски."""
    client = booking.client
    return {
        "id": booking.id,
        "client_id": booking.client_id,
        "client": client.full_name if client else "—",
        "phone": client.phone if client else "",
        "contact": client.telegram_vk_contact if client else "",
        "rating": client.rating if client else 0,
        "client_notes": client.admin_notes if client else "",
        "service_id": booking.service_id,
        "service": booking.service_title or "—",
        "master_id": booking.master_id,
        "master": booking.master_name or "—",
        "date": booking.visit_date.isoformat(),
        "date_label": booking.visit_date.strftime("%d.%m.%Y"),
        "weekday": booking.visit_date.strftime("%a"),
        "time": booking.visit_time.strftime("%H:%M"),
        "status": booking.status,
        "cost": booking.total_cost,
        "cost_label": money(booking.total_cost),
        "comment": booking.comment,
        "created_at": booking.created_at.strftime("%d.%m.%Y %H:%M"),
    }


def serialize_service(service: Service) -> dict:
    """Услуга для админки."""
    return {
        "id": service.id,
        "title": service.title,
        "slug": service.slug,
        "category": service.category,
        "short_description": service.short_description,
        "full_description": service.full_description,
        "duration_minutes": service.duration_minutes,
        "price": service.price,
        "price_label": money(service.price),
        "indications": service.indications,
        "contraindications": service.contraindications,
        "is_active": service.is_active,
        "sort_order": service.sort_order,
        "image_url": f"/static/uploads/{service.image_filename}" if service.image_filename else "",
    }


def serialize_master(master: Master) -> dict:
    """Мастер для админки."""
    return {
        "id": master.id,
        "full_name": master.full_name,
        "specialization": master.specialization,
        "experience_years": master.experience_years,
        "bio": master.bio,
        "is_active": master.is_active,
        "is_system": master.is_system,
        "avatar_url": f"/static/uploads/{master.avatar_filename}" if master.avatar_filename else "",
    }


# --- Записи (CRM) ----------------------------------------------------------


@router.get("/bookings")
def list_bookings(
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """Записи для Канбан-доски с фильтром по периоду и статусу."""
    query = select(Booking).options(selectinload(Booking.client))
    if date_from:
        query = query.where(Booking.visit_date >= _parse_date(date_from))
    if date_to:
        query = query.where(Booking.visit_date <= _parse_date(date_to))
    if status:
        query = query.where(Booking.status == status)

    bookings = db.scalars(query.order_by(Booking.visit_date, Booking.visit_time)).all()
    columns = {item: [] for item in config.BOOKING_STATUSES}
    for booking in bookings:
        columns.setdefault(booking.status, []).append(serialize_booking(booking))

    return {
        "columns": [{"status": item, "bookings": columns.get(item, [])} for item in config.BOOKING_STATUSES],
        "total": len(bookings),
    }


@router.get("/notifications")
def notifications(after_id: int = 0, db: Session = Depends(get_db)):
    """Новые записи для звукового уведомления в открытой CRM."""
    fresh = db.scalars(
        select(Booking)
        .options(selectinload(Booking.client))
        .where(Booking.id > after_id)
        .order_by(Booking.id.desc())
        .limit(10)
    ).all()
    max_id = db.scalar(select(func.max(Booking.id))) or after_id
    return {
        "max_id": max_id,
        "items": [serialize_booking(booking) for booking in fresh],
    }


@router.post("/bookings", dependencies=[Depends(require_csrf)])
def create_booking(payload: BookingCreate, db: Session = Depends(get_db)):
    """Создание записи администратором (клиент позвонил)."""
    service = db.get(Service, payload.service_id)
    master = db.get(Master, payload.master_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    if master is None:
        raise HTTPException(status_code=404, detail="Мастер не найден")

    day = _parse_date(payload.date)
    try:
        visit_time = datetime.strptime(payload.time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат времени") from None

    if not payload.force:
        available, reason = scheduling.is_slot_available(db, master, service, day, payload.time)
        if not available:
            raise HTTPException(status_code=409, detail=reason)

    if payload.total_cost is not None and payload.total_cost < 0:
        raise HTTPException(status_code=400, detail="Стоимость не может быть отрицательной")

    client = None
    if payload.client_id:
        client = db.get(Client, payload.client_id)
    if client is None and payload.phone:
        phone = normalize_phone(payload.phone)
        if phone:
            client = db.scalar(select(Client).where(Client.phone == phone))
        if client is None:
            if len(payload.full_name.strip()) < 2:
                raise HTTPException(status_code=400, detail="Укажите имя клиента")
            client = Client(
                full_name=payload.full_name.strip(),
                phone=phone or payload.phone.strip(),
                consent_given=False,
            )
            db.add(client)
            db.flush()
    if client is None:
        raise HTTPException(status_code=400, detail="Выберите клиента или укажите телефон")

    booking = Booking(
        client_id=client.id,
        service_id=service.id,
        master_id=master.id,
        service_title=service.title,
        master_name=master.full_name,
        visit_date=day,
        visit_time=visit_time,
        status=config.STATUS_NEW,
        total_cost=payload.total_cost if payload.total_cost is not None else service.price,
        comment=payload.comment,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return {"ok": True, "booking": serialize_booking(booking)}


@router.patch("/bookings/{booking_id}", dependencies=[Depends(require_csrf)])
def update_booking(booking_id: int, payload: BookingUpdate, db: Session = Depends(get_db)):
    """Обновление карточки записи: статус, время, мастер, гибкая цена."""
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    if payload.status is not None:
        if payload.status not in config.BOOKING_STATUSES:
            raise HTTPException(status_code=400, detail="Неизвестный статус")
        booking.status = payload.status

    if payload.visit_date is not None:
        booking.visit_date = _parse_date(payload.visit_date)

    if payload.visit_time is not None:
        try:
            booking.visit_time = datetime.strptime(payload.visit_time, "%H:%M").time()
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат времени") from None

    if payload.master_id is not None:
        master = db.get(Master, payload.master_id)
        if master is None:
            raise HTTPException(status_code=404, detail="Мастер не найден")
        booking.master_id = master.id
        booking.master_name = master.full_name

    if payload.total_cost is not None:
        if payload.total_cost < 0:
            raise HTTPException(status_code=400, detail="Стоимость не может быть отрицательной")
        booking.total_cost = payload.total_cost

    if payload.comment is not None:
        booking.comment = payload.comment

    booking.updated_at = datetime.now()
    db.commit()
    db.refresh(booking)
    return {"ok": True, "booking": serialize_booking(booking)}


@router.post("/bookings/{booking_id}/status", dependencies=[Depends(require_csrf)])
def set_status(booking_id: int, payload: StatusUpdate, db: Session = Depends(get_db)):
    """Смена статуса записи (drag&drop Канбан-доски)."""
    if payload.status not in config.BOOKING_STATUSES:
        raise HTTPException(status_code=400, detail="Неизвестный статус")
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    booking.status = payload.status
    booking.updated_at = datetime.now()
    db.commit()
    db.refresh(booking)
    return {"ok": True, "booking": serialize_booking(booking)}


@router.delete("/bookings/{booking_id}", dependencies=[Depends(require_csrf)])
def delete_booking(booking_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Жёсткое удаление записи (только Суперадмин)."""
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(booking)
    db.commit()
    logger.info("Запись #%s удалена Суперадмином", booking_id)
    return {"ok": True}


# --- Клиенты ---------------------------------------------------------------


@router.get("/clients")
def list_clients(query: str = "", db: Session = Depends(get_db)):
    """Поиск по базе клиентов."""
    statement = select(Client).options(selectinload(Client.bookings))
    if query.strip():
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(Client.full_name.ilike(pattern), Client.phone.ilike(pattern))
        )
    clients = db.scalars(statement.order_by(Client.full_name).limit(200)).all()
    return {
        "items": [
            {
                "id": client.id,
                "full_name": client.full_name,
                "phone": client.phone,
                "contact": client.telegram_vk_contact,
                "rating": client.rating,
                "admin_notes": client.admin_notes,
                "consent_given": client.consent_given,
                "consent_date": client.consent_date.strftime("%d.%m.%Y") if client.consent_date else "",
                "consent_ip": client.consent_ip,
                "visits": client.visits_count,
                "created_at": client.created_at.strftime("%d.%m.%Y"),
            }
            for client in clients
        ]
    }


@router.post("/clients", dependencies=[Depends(require_csrf)])
def create_client(payload: ClientPayload, db: Session = Depends(get_db)):
    """Создание клиента вручную."""
    phone = normalize_phone(payload.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Укажите корректный телефон")
    if db.scalar(select(Client).where(Client.phone == phone)):
        raise HTTPException(status_code=409, detail="Клиент с таким телефоном уже есть")

    client = Client(
        full_name=payload.full_name.strip(),
        phone=phone,
        telegram_vk_contact=payload.telegram_vk_contact,
        rating=max(1, min(5, payload.rating)),
        admin_notes=payload.admin_notes,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return {"ok": True, "id": client.id}


@router.patch("/clients/{client_id}", dependencies=[Depends(require_csrf)])
def update_client(client_id: int, payload: ClientUpdate, db: Session = Depends(get_db)):
    """Обновление карточки клиента (рейтинг, заметки, контакты)."""
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")

    if payload.full_name is not None:
        client.full_name = payload.full_name.strip()
    if payload.phone is not None:
        phone = normalize_phone(payload.phone)
        if not phone:
            raise HTTPException(status_code=400, detail="Некорректный телефон")
        client.phone = phone
    if payload.telegram_vk_contact is not None:
        client.telegram_vk_contact = payload.telegram_vk_contact
    if payload.rating is not None:
        client.rating = max(1, min(5, payload.rating))
    if payload.admin_notes is not None:
        client.admin_notes = payload.admin_notes

    db.commit()
    return {"ok": True}


@router.delete("/clients/{client_id}", dependencies=[Depends(require_csrf)])
def delete_client(client_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Удаление клиента вместе с его записями (только Суперадмин)."""
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    db.delete(client)
    db.commit()
    return {"ok": True}


# --- Услуги ----------------------------------------------------------------


@router.get("/services")
def admin_services(db: Session = Depends(get_db)):
    """Все услуги, включая скрытые."""
    services = db.scalars(select(Service).order_by(Service.sort_order, Service.title)).all()
    return {"items": [serialize_service(service) for service in services]}


@router.post("/services", dependencies=[Depends(require_csrf)])
def create_service(payload: ServicePayload, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Создание услуги."""
    slug = _unique_slug(db, Service, slugify(payload.title))
    service = Service(
        title=payload.title.strip(),
        slug=slug,
        category=payload.category,
        short_description=payload.short_description,
        full_description=payload.full_description,
        duration_minutes=max(15, payload.duration_minutes),
        price=max(0, payload.price),
        indications=payload.indications,
        contraindications=payload.contraindications,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
    )
    db.add(service)
    db.commit()
    db.refresh(service)
    return {"ok": True, "service": serialize_service(service)}


@router.patch("/services/{service_id}", dependencies=[Depends(require_csrf)])
def update_service(
    service_id: int, payload: ServicePayload, db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Обновление услуги (в том числе мягкое скрытие через is_active)."""
    service = db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    service.title = payload.title.strip()
    service.category = payload.category
    service.short_description = payload.short_description
    service.full_description = payload.full_description
    service.duration_minutes = max(15, payload.duration_minutes)
    service.price = max(0, payload.price)
    service.indications = payload.indications
    service.contraindications = payload.contraindications
    service.is_active = payload.is_active
    service.sort_order = payload.sort_order
    db.commit()
    return {"ok": True, "service": serialize_service(service)}


@router.delete("/services/{service_id}", dependencies=[Depends(require_csrf)])
def soft_delete_service(
    service_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)
):
    """Мягкое удаление: услуга скрывается с сайта, история сохраняется."""
    service = db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    service.is_active = False
    db.commit()
    return {"ok": True, "mode": "soft"}


@router.post("/services/{service_id}/restore", dependencies=[Depends(require_csrf)])
def restore_service(
    service_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)
):
    """Возврат услуги из архива."""
    service = db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    service.is_active = True
    db.commit()
    return {"ok": True}


@router.delete("/services/{service_id}/hard", dependencies=[Depends(require_csrf)])
def hard_delete_service(
    service_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)
):
    """Жёсткое удаление: в записях обнуляется ссылка, снимок названия сохраняется."""
    service = db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    affected = db.scalars(select(Booking).where(Booking.service_id == service_id)).all()
    for booking in affected:
        booking.service_id = None
    db.flush()
    db.delete(service)
    db.commit()
    logger.info("Услуга #%s удалена физически, затронуто записей: %s", service_id, len(affected))
    return {"ok": True, "affected_bookings": len(affected)}


# --- Мастера ---------------------------------------------------------------


@router.get("/masters")
def admin_masters(db: Session = Depends(get_db)):
    """Все мастера, включая скрытых."""
    masters = db.scalars(
        select(Master).where(Master.is_system.is_(False)).order_by(Master.full_name)
    ).all()
    return {"items": [serialize_master(master) for master in masters]}


@router.post("/masters", dependencies=[Depends(require_csrf)])
def create_master(payload: MasterPayload, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Создание мастера + генерация локального аватара."""
    import assets

    # Имя файла аватара уникально, но само ФИО мастера менять не нужно.
    file_slug = f"{slugify(payload.full_name)}-{int(datetime.now().timestamp())}"
    avatar = assets.generate_master_avatar(file_slug, payload.full_name)
    master = Master(
        full_name=payload.full_name.strip(),
        specialization=payload.specialization,
        experience_years=max(0, payload.experience_years),
        bio=payload.bio,
        avatar_filename=avatar,
        is_active=payload.is_active,
    )
    db.add(master)
    db.commit()
    db.refresh(master)
    return {"ok": True, "master": serialize_master(master)}


@router.patch("/masters/{master_id}", dependencies=[Depends(require_csrf)])
def update_master(
    master_id: int, payload: MasterPayload, db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Обновление карточки мастера."""
    master = db.get(Master, master_id)
    if master is None or master.is_system:
        raise HTTPException(status_code=404, detail="Мастер не найден")
    master.full_name = payload.full_name.strip()
    master.specialization = payload.specialization
    master.experience_years = max(0, payload.experience_years)
    master.bio = payload.bio
    master.is_active = payload.is_active
    db.commit()
    return {"ok": True, "master": serialize_master(master)}


@router.delete("/masters/{master_id}", dependencies=[Depends(require_csrf)])
def soft_delete_master(master_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Мягкое удаление: мастер скрывается с сайта, записи сохраняются."""
    master = db.get(Master, master_id)
    if master is None or master.is_system:
        raise HTTPException(status_code=404, detail="Мастер не найден")
    master.is_active = False
    db.commit()
    return {"ok": True, "mode": "soft"}


@router.post("/masters/{master_id}/restore", dependencies=[Depends(require_csrf)])
def restore_master(master_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Возврат мастера из архива."""
    master = db.get(Master, master_id)
    if master is None:
        raise HTTPException(status_code=404, detail="Мастер не найден")
    master.is_active = True
    db.commit()
    return {"ok": True}


@router.delete("/masters/{master_id}/hard", dependencies=[Depends(require_csrf)])
def hard_delete_master(master_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Жёсткое удаление: записи переводятся на системного мастера «Уволенный сотрудник»."""
    master = db.get(Master, master_id)
    if master is None or master.is_system:
        raise HTTPException(status_code=404, detail="Мастер не найден")

    system_master = seed.ensure_system_master(db)
    affected = db.scalars(select(Booking).where(Booking.master_id == master_id)).all()
    for booking in affected:
        booking.master_id = system_master.id  # снимок master_name остаётся историческим

    for shift in db.scalars(select(Schedule).where(Schedule.master_id == master_id)).all():
        db.delete(shift)

    db.flush()
    db.delete(master)
    db.commit()
    logger.info(
        "Мастер #%s удалён физически, записи переведены на «%s»: %s",
        master_id, seed.SYSTEM_MASTER_NAME, len(affected),
    )
    return {"ok": True, "affected_bookings": len(affected), "reassigned_to": seed.SYSTEM_MASTER_NAME}


# --- Графики смен ----------------------------------------------------------


@router.get("/schedules")
def list_schedules(master_id: int, db: Session = Depends(get_db)):
    """Смены мастера на ближайшие 30 дней."""
    return {"items": scheduling.schedule_overview(db, master_id, days=30)}


@router.post("/schedules", dependencies=[Depends(require_csrf)])
def create_schedules(payload: SchedulePayload, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Заполняет график смен на диапазон дат по выбранным дням недели."""
    master = db.get(Master, payload.master_id)
    if master is None or master.is_system:
        raise HTTPException(status_code=404, detail="Мастер не найден")

    start_day = _parse_date(payload.date_from)
    end_day = _parse_date(payload.date_to)
    if end_day < start_day:
        raise HTTPException(status_code=400, detail="Дата окончания раньше даты начала")
    if (end_day - start_day).days > 180:
        raise HTTPException(status_code=400, detail="Слишком длинный период (максимум 180 дней)")

    try:
        start_time = datetime.strptime(payload.start_time, "%H:%M").time()
        end_time = datetime.strptime(payload.end_time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат времени") from None
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="Время окончания должно быть позже начала")

    if payload.replace:
        existing = db.scalars(
            select(Schedule).where(
                Schedule.master_id == master.id,
                Schedule.date >= start_day,
                Schedule.date <= end_day,
            )
        ).all()
        for shift in existing:
            db.delete(shift)
        db.flush()

    created = 0
    day = start_day
    while day <= end_day:
        if not payload.weekdays or day.weekday() in payload.weekdays:
            db.add(
                Schedule(
                    master_id=master.id, date=day, start_time=start_time, end_time=end_time
                )
            )
            created += 1
        day += timedelta(days=1)

    db.commit()
    return {"ok": True, "created": created}


@router.delete("/schedules/{schedule_id}", dependencies=[Depends(require_csrf)])
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Удаляет смену из графика."""
    shift = db.get(Schedule, schedule_id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Смена не найдена")
    db.delete(shift)
    db.commit()
    return {"ok": True}


# --- Аналитика -------------------------------------------------------------


@router.get("/analytics")
def analytics_data(
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Метрики дашборда за период."""
    start, end = _resolve_period(date_from, date_to)
    report = analytics.build_report(db, start, end)
    return {
        "period": report["period"],
        "kpi": report["kpi"],
        "status_stats": report["status_stats"],
        "popular_services": report["popular_services"],
        "day_series": report["day_series"],
        "lost_series": report["lost_series"],
        "workload": report["workload"],
        "lost_bookings": report["lost_bookings"][:50],
        "presets": analytics.period_presets(),
    }


@router.get("/analytics/export")
def analytics_export(
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Выгрузка отчёта в Excel (.xlsx)."""
    start, end = _resolve_period(date_from, date_to)
    payload = analytics.export_to_excel(db, start, end)
    filename = f"salon-report-{start.isoformat()}_{end.isoformat()}.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Маркетинговый ИИ ------------------------------------------------------


@router.post("/marketing/generate", dependencies=[Depends(require_csrf)])
def marketing_generate(
    payload: MarketingRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Генерирует пост и (опционально) публикует его в ВК/ТГ."""
    if not payload.topic.strip():
        raise HTTPException(status_code=400, detail="Укажите тему поста")

    result = ai_marketing.generate_post(
        payload.topic, payload.tone, payload.length, payload.keywords
    )

    post = Post(
        topic=payload.topic.strip(),
        tone=payload.tone,
        length=payload.length,
        keywords=payload.keywords,
        content=result["content"],
        source=result["source"],
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    publish_results = _publish_post(post, payload.send_telegram, payload.send_vk, db)
    return {
        "ok": True,
        "post": {
            "id": post.id,
            "topic": post.topic,
            "tone": post.tone,
            "length": post.length,
            "content": post.content,
            "source": post.source,
            "created_at": post.created_at.strftime("%d.%m.%Y %H:%M"),
        },
        "publish": publish_results,
    }


@router.post("/marketing/publish", dependencies=[Depends(require_csrf)])
def marketing_publish(
    payload: PublishRequest, db: Session = Depends(get_db), _: User = Depends(require_superadmin)
):
    """Публикует ранее сгенерированный пост из архива."""
    post = db.get(Post, payload.post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Пост не найден")
    results = _publish_post(post, payload.send_telegram, payload.send_vk, db)
    return {"ok": True, "publish": results}


@router.get("/marketing/posts")
def marketing_posts(db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Архив постов."""
    posts = db.scalars(select(Post).order_by(Post.created_at.desc()).limit(100)).all()
    return {
        "items": [
            {
                "id": post.id,
                "topic": post.topic,
                "tone": post.tone,
                "length": post.length,
                "keywords": post.keywords,
                "content": post.content,
                "source": post.source,
                "sent_telegram": post.sent_telegram,
                "sent_vk": post.sent_vk,
                "created_at": post.created_at.strftime("%d.%m.%Y %H:%M"),
            }
            for post in posts
        ],
        "retention_days": config.POSTS_RETENTION_DAYS,
    }


@router.post("/marketing/cleanup", dependencies=[Depends(require_csrf)])
def marketing_cleanup(db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Мгновенная ручная очистка архива постов."""
    removed = seed.cleanup_old_posts(db, retention_days=config.POSTS_RETENTION_DAYS)
    return {"ok": True, "removed": removed}


def _publish_post(post: Post, to_telegram: bool, to_vk: bool, db: Session) -> dict:
    """Отправляет пост в выбранные соцсети, фиксирует результат в БД."""
    results: dict[str, dict] = {}
    log_lines: list[str] = []

    if to_telegram:
        outcome = integrations.send_telegram_message(integrations.format_post_for_channel(post))
        results["telegram"] = outcome
        if outcome.get("ok"):
            post.sent_telegram = True
        log_lines.append(f"TG: {outcome.get('detail', '')}")

    if to_vk:
        outcome = integrations.send_vk_post(integrations.format_post_for_channel(post))
        results["vk"] = outcome
        if outcome.get("ok"):
            post.sent_vk = True
        log_lines.append(f"VK: {outcome.get('detail', '')}")

    if log_lines:
        post.publish_log = "; ".join(log_lines)
        db.commit()
    return results


# --- Пользователи ----------------------------------------------------------


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Список пользователей админки."""
    users = db.scalars(select(User).order_by(User.role, User.username)).all()
    return {
        "items": [
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at.strftime("%d.%m.%Y"),
            }
            for user in users
        ]
    }


@router.post("/users", dependencies=[Depends(require_csrf)])
def create_user(payload: UserPayload, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Создание пользователя админки."""
    username = payload.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Логин минимум 3 символа")
    if payload.role not in {config.ROLE_SUPERADMIN, config.ROLE_MANAGER}:
        raise HTTPException(status_code=400, detail="Неизвестная роль")
    problem = validate_password_strength(payload.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail="Такой логин уже занят")

    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        full_name=payload.full_name,
    )
    db.add(user)
    db.commit()
    return {"ok": True, "id": user.id}


@router.patch("/users/{user_id}", dependencies=[Depends(require_csrf)])
def update_user(
    user_id: int, payload: UserUpdate, db: Session = Depends(get_db),
    admin: User = Depends(require_superadmin),
):
    """Смена пароля, роли или блокировка пользователя."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if payload.password:
        problem = validate_password_strength(payload.password)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        user.password_hash = hash_password(payload.password)

    if payload.full_name is not None:
        user.full_name = payload.full_name

    if payload.role is not None:
        if payload.role not in {config.ROLE_SUPERADMIN, config.ROLE_MANAGER}:
            raise HTTPException(status_code=400, detail="Неизвестная роль")
        if user.id == admin.id and payload.role != config.ROLE_SUPERADMIN:
            raise HTTPException(status_code=400, detail="Нельзя понизить собственную роль")
        user.role = payload.role

    if payload.is_active is not None:
        if user.id == admin.id and not payload.is_active:
            raise HTTPException(status_code=400, detail="Нельзя заблокировать себя")
        user.is_active = payload.is_active

    db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}", dependencies=[Depends(require_csrf)])
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_superadmin)):
    """Удаление пользователя админки."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить себя")
    db.delete(user)
    db.commit()
    return {"ok": True}


# --- Отзывы ----------------------------------------------------------------


@router.get("/reviews")
def list_reviews(db: Session = Depends(get_db)):
    """Отзывы для модерации."""
    reviews = db.scalars(select(Review).order_by(Review.created_at.desc())).all()
    return {
        "items": [
            {
                "id": review.id,
                "author_name": review.author_name,
                "rating": review.rating,
                "text": review.text,
                "service_title": review.service_title,
                "is_published": review.is_published,
                "created_at": review.created_at.strftime("%d.%m.%Y"),
            }
            for review in reviews
        ]
    }


@router.post("/reviews", dependencies=[Depends(require_csrf)])
def create_review(payload: ReviewPayload, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Добавление отзыва."""
    review = Review(
        author_name=payload.author_name.strip(),
        rating=max(1, min(5, payload.rating)),
        text=payload.text,
        service_title=payload.service_title,
        is_published=payload.is_published,
    )
    db.add(review)
    db.commit()
    return {"ok": True, "id": review.id}


@router.patch("/reviews/{review_id}", dependencies=[Depends(require_csrf)])
def update_review(
    review_id: int, payload: ReviewPayload, db: Session = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Правка/публикация отзыва."""
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Отзыв не найден")
    review.author_name = payload.author_name.strip()
    review.rating = max(1, min(5, payload.rating))
    review.text = payload.text
    review.service_title = payload.service_title
    review.is_published = payload.is_published
    db.commit()
    return {"ok": True}


@router.delete("/reviews/{review_id}", dependencies=[Depends(require_csrf)])
def delete_review(review_id: int, db: Session = Depends(get_db), _: User = Depends(require_superadmin)):
    """Удаление отзыва."""
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Отзыв не найден")
    db.delete(review)
    db.commit()
    return {"ok": True}


# --- Вспомогательное -------------------------------------------------------


def _parse_date(value: str) -> date:
    """«2026-09-21» → date."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Неверный формат даты: {value}") from None


def _resolve_period(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """Период отчёта: по умолчанию — текущий месяц."""
    today = date.today()
    start = _parse_date(date_from) if date_from else today.replace(day=1)
    end = _parse_date(date_to) if date_to else today
    if end < start:
        raise HTTPException(status_code=400, detail="Дата окончания раньше даты начала")
    return start, end


def _unique_slug(db: Session, model, base: str, column: str = "slug") -> str:
    """Подбирает свободный slug/имя."""
    candidate = base
    index = 2
    field = getattr(model, column)
    while db.scalar(select(model).where(field == candidate)):
        candidate = f"{base}-{index}"
        index += 1
    return candidate
