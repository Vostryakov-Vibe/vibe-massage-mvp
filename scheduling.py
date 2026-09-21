"""Логика расписания: расчёт свободных таймслотов и проверка занятости.

Правила:
* слоты идут с шагом SLOT_STEP_MINUTES от начала смены мастера;
* слот валиден, если сеанс целиком укладывается в смену;
* слот занят, если пересекается с любой неотменённой записью мастера;
* на «сегодня» не показываем слоты раньше, чем через MIN_LEAD_MINUTES.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from models import Booking, Master, Schedule, Service


def _to_minutes(value: time) -> int:
    """Время → минуты от начала суток."""
    return value.hour * 60 + value.minute


def _to_time(minutes: int) -> time:
    """Минуты от начала суток → время."""
    return time(hour=(minutes // 60) % 24, minute=minutes % 60)


def get_shift(db: Session, master_id: int, day: date) -> Schedule | None:
    """Смена мастера на дату (None — мастер в этот день не работает)."""
    return db.scalar(
        select(Schedule).where(Schedule.master_id == master_id, Schedule.date == day)
    )


def _busy_intervals(db: Session, master_id: int, day: date) -> list[tuple[int, int]]:
    """Занятые интервалы мастера в минутах: (начало, конец)."""
    bookings = db.scalars(
        select(Booking).where(
            Booking.master_id == master_id,
            Booking.visit_date == day,
            Booking.status.notin_(config.LOST_STATUSES),
        )
    ).all()

    intervals: list[tuple[int, int]] = []
    for booking in bookings:
        duration = config.SLOT_STEP_MINUTES
        if booking.service is not None:
            duration = booking.service.duration_minutes
        start = _to_minutes(booking.visit_time)
        intervals.append((start, start + duration))
    return intervals


def available_slots(
    db: Session, master: Master, service: Service, day: date, now: datetime | None = None
) -> list[str]:
    """Список свободных слотов на дату в формате «HH:MM»."""
    now = now or datetime.now()
    if day < now.date():
        return []

    shift = get_shift(db, master.id, day)
    if shift is None:
        return []

    shift_start = _to_minutes(shift.start_time)
    shift_end = _to_minutes(shift.end_time)
    duration = service.duration_minutes
    busy = _busy_intervals(db, master.id, day)

    # Отсечка для сегодняшнего дня: запись минимум за MIN_LEAD_MINUTES.
    earliest = shift_start
    if day == now.date():
        earliest = max(earliest, now.hour * 60 + now.minute + config.MIN_LEAD_MINUTES)

    slots: list[str] = []
    for start in range(shift_start, shift_end - duration + 1, config.SLOT_STEP_MINUTES):
        if start < earliest:
            continue
        end = start + duration
        if any(start < busy_end and end > busy_start for busy_start, busy_end in busy):
            continue
        slots.append(_to_time(start).strftime("%H:%M"))
    return slots


def is_slot_available(
    db: Session, master: Master, service: Service, day: date, slot: str
) -> tuple[bool, str]:
    """Проверяет конкретный слот перед созданием записи.

    Возвращает (доступен, причина отказа).
    """
    try:
        parsed = datetime.strptime(slot, "%H:%M").time()
    except ValueError:
        return False, "Некорректный формат времени"

    shift = get_shift(db, master.id, day)
    if shift is None:
        return False, "Мастер не работает в выбранный день"

    start = _to_minutes(parsed)
    end = start + service.duration_minutes
    if start < _to_minutes(shift.start_time) or end > _to_minutes(shift.end_time):
        return False, "Сеанс не укладывается в рабочую смену мастера"

    if day == datetime.now().date():
        if start < datetime.now().hour * 60 + datetime.now().minute + config.MIN_LEAD_MINUTES:
            return False, (
                f"До начала сеанса осталось меньше {config.MIN_LEAD_MINUTES} минут — "
                "выберите время попозже или позвоните нам"
            )

    for busy_start, busy_end in _busy_intervals(db, master.id, day):
        if start < busy_end and end > busy_start:
            return False, "Это время уже занято — выберите другой слот"

    return True, ""


def schedule_overview(db: Session, master_id: int, days: int = 14) -> list[dict]:
    """Смены мастера на ближайшие N дней — для карточки в админке."""
    today = date.today()
    shifts = db.scalars(
        select(Schedule)
        .where(Schedule.master_id == master_id, Schedule.date >= today)
        .order_by(Schedule.date)
        .limit(days)
    ).all()
    return [
        {
            "id": shift.id,
            # date — объект date: шаблоны админки применяют к нему фильтры
            # (short_date/human_date), FastAPI сериализует его в ISO для JSON.
            "date": shift.date,
            "start_time": shift.start_time.strftime("%H:%M"),
            "end_time": shift.end_time.strftime("%H:%M"),
        }
        for shift in shifts
    ]


def build_shift_grid(days_ahead: int = 60) -> list[date]:
    """Даты, доступные для записи (сегодня … +N дней)."""
    today = date.today()
    return [today + timedelta(days=offset) for offset in range(days_ahead + 1)]
