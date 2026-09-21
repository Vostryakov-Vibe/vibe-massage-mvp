"""Аналитика: расчёт метрик и выгрузка отчёта в Excel.

Все метрики считаются по «снимку» записи (service_title, master_name,
total_cost), поэтому корректны даже после удаления услуги или мастера.
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

import config
from models import Booking, Master, Schedule
from utils import human_time, money

# Фирменные цвета для Excel
EMERALD = "044A42"
EMERALD_LIGHT = "0B6B5F"
GOLD = "D4AF37"
GOLD_LIGHT = "F3E3B3"
GREY = "F1F5F4"

THIN = Side(style="thin", color="BFCED0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _booking_minutes(booking: Booking) -> int:
    """Длительность сеанса в минутах (по услуге, иначе шаг сетки)."""
    if booking.service is not None:
        return booking.service.duration_minutes
    return config.SLOT_STEP_MINUTES


def load_bookings(db: Session, date_from: date, date_to: date) -> list[Booking]:
    """Записи за период с подгруженными связями."""
    return list(
        db.scalars(
            select(Booking)
            .options(selectinload(Booking.service), selectinload(Booking.master),
                     selectinload(Booking.client))
            .where(Booking.visit_date >= date_from, Booking.visit_date <= date_to)
            .order_by(Booking.visit_date, Booking.visit_time)
        ).all()
    )


def build_report(db: Session, date_from: date, date_to: date) -> dict:
    """Считает все метрики дашборда за период.

    Возвращает словарь, пригодный и для JSON-ответа, и для Excel-отчёта.
    """
    bookings = load_bookings(db, date_from, date_to)

    total_bookings = len(bookings)
    done = [b for b in bookings if b.status == config.STATUS_DONE]
    lost = [b for b in bookings if b.status in config.LOST_STATUSES]

    revenue = sum(b.total_cost for b in done)
    lost_revenue = sum(b.total_cost for b in lost)
    potential_revenue = revenue + lost_revenue

    # --- Выручка и количество по дням -------------------------------------
    revenue_by_day: dict[date, int] = defaultdict(int)
    count_by_day: dict[date, int] = defaultdict(int)
    for booking in bookings:
        count_by_day[booking.visit_date] += 1
        if booking.status == config.STATUS_DONE:
            revenue_by_day[booking.visit_date] += booking.total_cost

    lost_by_day: dict[date, int] = defaultdict(int)
    for booking in lost:
        lost_by_day[booking.visit_date] += booking.total_cost

    day_series = []
    lost_series = []
    cursor = date_from
    while cursor <= date_to:
        label = cursor.strftime("%d.%m")
        day_series.append(
            {
                "date": cursor.isoformat(),
                "label": label,
                "revenue": revenue_by_day.get(cursor, 0),
                "bookings": count_by_day.get(cursor, 0),
            }
        )
        lost_series.append(
            {
                "date": cursor.isoformat(),
                "label": label,
                "lost": lost_by_day.get(cursor, 0),
            }
        )
        cursor += timedelta(days=1)

    # --- Популярные услуги -------------------------------------------------
    services_stats: dict[str, dict] = {}
    for booking in bookings:
        title = booking.service_title or "Услуга удалена"
        stats = services_stats.setdefault(
            title, {"title": title, "count": 0, "revenue": 0, "minutes": 0}
        )
        stats["count"] += 1
        stats["minutes"] += _booking_minutes(booking)
        if booking.status == config.STATUS_DONE:
            stats["revenue"] += booking.total_cost

    popular_services = sorted(services_stats.values(), key=lambda item: item["count"], reverse=True)

    # --- Статусы -----------------------------------------------------------
    status_stats = {status: 0 for status in config.BOOKING_STATUSES}
    for booking in bookings:
        status_stats[booking.status] = status_stats.get(booking.status, 0) + 1

    # --- Загруженность мастеров -------------------------------------------
    workload = build_workload(db, bookings, date_from, date_to)

    # --- Клиенты -----------------------------------------------------------
    unique_clients = {b.client_id for b in bookings}
    new_clients = {
        b.client_id
        for b in bookings
        if b.client and date_from <= b.client.created_at.date() <= date_to
    }

    conversion = round(len(done) / total_bookings * 100, 1) if total_bookings else 0.0
    avg_check = round(revenue / len(done)) if done else 0
    # Рейтинг считаем по уникальным клиентам, иначе частые гости искажают среднее.
    client_ratings = {b.client_id: b.client.rating for b in bookings if b.client}
    avg_rating = round(sum(client_ratings.values()) / len(client_ratings), 2) if client_ratings else 0

    return {
        "period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "kpi": {
            "revenue": revenue,
            "revenue_label": money(revenue),
            "bookings_total": total_bookings,
            "bookings_done": len(done),
            "bookings_lost": len(lost),
            "lost_revenue": lost_revenue,
            "lost_revenue_label": money(lost_revenue),
            "potential_revenue": potential_revenue,
            "conversion": conversion,
            "avg_check": avg_check,
            "avg_check_label": money(avg_check),
            "clients_total": len(unique_clients),
            "clients_new": len(new_clients),
            "avg_rating": avg_rating,
        },
        "status_stats": status_stats,
        "popular_services": popular_services,
        "day_series": day_series,
        "lost_series": lost_series,
        "workload": workload,
        "bookings": [
            {
                "id": booking.id,
                "date": booking.visit_date.isoformat(),
                "date_label": booking.visit_date.strftime("%d.%m.%Y"),
                "time": human_time(booking.visit_time),
                "client": booking.client.full_name if booking.client else "—",
                "phone": booking.client.phone if booking.client else "—",
                "service": booking.service_title or "—",
                "master": booking.master_name or "—",
                "status": booking.status,
                "cost": booking.total_cost,
                "comment": booking.comment,
            }
            for booking in bookings
        ],
        "lost_bookings": [
            {
                "id": booking.id,
                "date_label": booking.visit_date.strftime("%d.%m.%Y"),
                "time": human_time(booking.visit_time),
                "client": booking.client.full_name if booking.client else "—",
                "service": booking.service_title or "—",
                "master": booking.master_name or "—",
                "status": booking.status,
                "cost": booking.total_cost,
                "comment": booking.comment,
            }
            for booking in lost
        ],
    }


def build_workload(
    db: Session, bookings: list[Booking], date_from: date, date_to: date
) -> list[dict]:
    """Загруженность мастеров: часы на сеансах / часы по графику смен.

    В числитель идут только «живые» записи (не отменённые и не «не пришёл»):
    они реально занимают время мастера.
    """
    masters = db.scalars(
        select(Master).where(Master.is_active.is_(True), Master.is_system.is_(False))
    ).all()

    shifts = db.scalars(
        select(Schedule).where(Schedule.date >= date_from, Schedule.date <= date_to)
    ).all()
    scheduled_minutes: dict[int, int] = defaultdict(int)
    shifts_count: dict[int, int] = defaultdict(int)
    for shift in shifts:
        start = shift.start_time.hour * 60 + shift.start_time.minute
        end = shift.end_time.hour * 60 + shift.end_time.minute
        scheduled_minutes[shift.master_id] += max(0, end - start)
        shifts_count[shift.master_id] += 1

    booked_minutes: dict[int, int] = defaultdict(int)
    done_revenue: dict[int, int] = defaultdict(int)
    for booking in bookings:
        if booking.status in config.LOST_STATUSES or booking.master_id is None:
            continue
        booked_minutes[booking.master_id] += _booking_minutes(booking)
        if booking.status == config.STATUS_DONE:
            done_revenue[booking.master_id] += booking.total_cost

    result = []
    for master in masters:
        scheduled = scheduled_minutes.get(master.id, 0)
        booked = booked_minutes.get(master.id, 0)
        result.append(
            {
                "master_id": master.id,
                "master": master.full_name,
                "specialization": master.specialization,
                "shifts": shifts_count.get(master.id, 0),
                "scheduled_hours": round(scheduled / 60, 1),
                "booked_hours": round(booked / 60, 1),
                "load_percent": round(booked / scheduled * 100, 1) if scheduled else 0.0,
                "revenue": done_revenue.get(master.id, 0),
                "revenue_label": money(done_revenue.get(master.id, 0)),
            }
        )
    return sorted(result, key=lambda item: item["load_percent"], reverse=True)


# --- Excel -----------------------------------------------------------------


def _style_header(sheet, row: int, columns: int, fill_color: str = EMERALD) -> None:
    """Оформляет строку заголовков."""
    fill = PatternFill("solid", fgColor=fill_color)
    for column in range(1, columns + 1):
        cell = sheet.cell(row=row, column=column)
        cell.fill = fill
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    sheet.row_dimensions[row].height = 26


def _autosize(sheet, min_width: int = 10, max_width: int = 46) -> None:
    """Подгоняет ширину колонок под содержимое."""
    for column_cells in sheet.columns:
        length = max((len(str(cell.value)) for cell in column_cells if cell.value is not None), default=0)
        letter = get_column_letter(column_cells[0].column)
        sheet.column_dimensions[letter].width = min(max(length + 3, min_width), max_width)


def _title(sheet, row: int, text: str, columns: int, subtitle: str = "") -> int:
    """Пишет заголовок листа и возвращает следующую свободную строку."""
    sheet.cell(row=row, column=1, value=text).font = Font(bold=True, size=15, color=EMERALD)
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(columns, 2))
    row += 1
    if subtitle:
        sheet.cell(row=row, column=1, value=subtitle).font = Font(size=10, italic=True, color="6B7B7A")
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(columns, 2))
        row += 1
    return row + 1


def export_to_excel(db: Session, date_from: date, date_to: date) -> bytes:
    """Формирует .xlsx-отчёт с цветными тематическими листами."""
    report = build_report(db, date_from, date_to)
    period_label = f"Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}"

    workbook = Workbook()

    # --- Лист 1. Сводка ----------------------------------------------------
    summary = workbook.active
    summary.title = "Сводка"
    row = _title(summary, 1, f"Отчёт {config.SALON['name']}", 4, period_label)

    kpi = report["kpi"]
    summary.cell(row=row, column=1, value="Ключевые показатели").font = Font(bold=True, size=12, color=EMERALD_LIGHT)
    row += 1
    summary.cell(row=row, column=1, value="Показатель")
    summary.cell(row=row, column=2, value="Значение")
    _style_header(summary, row, 2, EMERALD)
    row += 1

    kpi_rows = [
        ("Фактическая выручка (выполненные записи)", money(kpi["revenue"])),
        ("Упущенная выгода (отмены и неявки)", money(kpi["lost_revenue"])),
        ("Потенциальная выручка периода", money(kpi["potential_revenue"])),
        ("Конверсия записей в выполненные", f"{kpi['conversion']} %"),
        ("Средний чек", money(kpi["avg_check"])),
        ("Всего записей", kpi["bookings_total"]),
        ("Выполнено", kpi["bookings_done"]),
        ("Отменено / не пришли", kpi["bookings_lost"]),
        ("Уникальных клиентов", kpi["clients_total"]),
        ("Новых клиентов за период", kpi["clients_new"]),
        ("Средний рейтинг клиентов", kpi["avg_rating"]),
    ]
    for index, (label, value) in enumerate(kpi_rows):
        summary.cell(row=row, column=1, value=label).border = BORDER
        cell = summary.cell(row=row, column=2, value=value)
        cell.border = BORDER
        cell.font = Font(bold=True, color=EMERALD if index < 5 else "1F2937")
        cell.alignment = Alignment(horizontal="right")
        if index % 2:
            summary.cell(row=row, column=1).fill = PatternFill("solid", fgColor=GREY)
            cell.fill = PatternFill("solid", fgColor=GREY)
        row += 1

    row += 1
    summary.cell(row=row, column=1, value="Распределение по статусам").font = Font(bold=True, size=12, color=EMERALD_LIGHT)
    row += 1
    summary.cell(row=row, column=1, value="Статус")
    summary.cell(row=row, column=2, value="Записей")
    _style_header(summary, row, 2, GOLD)
    row += 1
    for status, count in report["status_stats"].items():
        summary.cell(row=row, column=1, value=status).border = BORDER
        cell = summary.cell(row=row, column=2, value=count)
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="right")
        row += 1
    _autosize(summary, min_width=14, max_width=52)

    # --- Лист 2. Выручка по дням ------------------------------------------
    daily = workbook.create_sheet("Выручка по дням")
    row = _title(daily, 1, "Динамика выручки по дням", 3, period_label)
    headers = ["Дата", "Выручка, ₽", "Записей"]
    for index, header in enumerate(headers, start=1):
        daily.cell(row=row, column=index, value=header)
    _style_header(daily, row, len(headers), EMERALD)
    row += 1
    for point in report["day_series"]:
        daily.cell(row=row, column=1, value=point["label"]).border = BORDER
        revenue_cell = daily.cell(row=row, column=2, value=point["revenue"])
        revenue_cell.border = BORDER
        revenue_cell.number_format = "#,##0 ₽"
        count_cell = daily.cell(row=row, column=3, value=point["bookings"])
        count_cell.border = BORDER
        count_cell.alignment = Alignment(horizontal="right")
        if point["revenue"]:
            revenue_cell.fill = PatternFill("solid", fgColor=GOLD_LIGHT)
        row += 1
    _autosize(daily)

    # --- Лист 3. Услуги ----------------------------------------------------
    services_sheet = workbook.create_sheet("Услуги")
    row = _title(services_sheet, 1, "Популярность услуг", 5, period_label)
    headers = ["Услуга", "Записей", "Выручка, ₽", "Средний чек, ₽", "Часов на сеансах"]
    for index, header in enumerate(headers, start=1):
        services_sheet.cell(row=row, column=index, value=header)
    _style_header(services_sheet, row, len(headers), EMERALD)
    row += 1
    for item in report["popular_services"]:
        services_sheet.cell(row=row, column=1, value=item["title"]).border = BORDER
        services_sheet.cell(row=row, column=2, value=item["count"]).border = BORDER
        revenue_cell = services_sheet.cell(row=row, column=3, value=item["revenue"])
        revenue_cell.border = BORDER
        revenue_cell.number_format = "#,##0 ₽"
        avg_cell = services_sheet.cell(
            row=row, column=4, value=round(item["revenue"] / item["count"]) if item["count"] else 0
        )
        avg_cell.border = BORDER
        avg_cell.number_format = "#,##0 ₽"
        hours_cell = services_sheet.cell(row=row, column=5, value=round(item["minutes"] / 60, 1))
        hours_cell.border = BORDER
        row += 1
    _autosize(services_sheet, min_width=22)

    # --- Лист 4. Мастера ---------------------------------------------------
    masters_sheet = workbook.create_sheet("Мастера")
    row = _title(masters_sheet, 1, "Загруженность мастеров", 7, period_label)
    headers = ["Мастер", "Специализация", "Смен", "Часов по графику", "Часов на сеансах", "Загруженность, %", "Выручка, ₽"]
    for index, header in enumerate(headers, start=1):
        masters_sheet.cell(row=row, column=index, value=header)
    _style_header(masters_sheet, row, len(headers), EMERALD)
    row += 1
    for item in report["workload"]:
        masters_sheet.cell(row=row, column=1, value=item["master"]).border = BORDER
        masters_sheet.cell(row=row, column=2, value=item["specialization"]).border = BORDER
        masters_sheet.cell(row=row, column=3, value=item["shifts"]).border = BORDER
        masters_sheet.cell(row=row, column=4, value=item["scheduled_hours"]).border = BORDER
        masters_sheet.cell(row=row, column=5, value=item["booked_hours"]).border = BORDER
        load_cell = masters_sheet.cell(row=row, column=6, value=item["load_percent"])
        load_cell.border = BORDER
        load_cell.font = Font(bold=True, color=EMERALD if item["load_percent"] >= 40 else "9A3412")
        revenue_cell = masters_sheet.cell(row=row, column=7, value=item["revenue"])
        revenue_cell.border = BORDER
        revenue_cell.number_format = "#,##0 ₽"
        row += 1
    _autosize(masters_sheet, min_width=16)

    # --- Лист 5. Записи ----------------------------------------------------
    bookings_sheet = workbook.create_sheet("Записи")
    row = _title(bookings_sheet, 1, "Детализация записей", 9, period_label)
    headers = ["№", "Дата", "Время", "Клиент", "Телефон", "Услуга", "Мастер", "Статус", "Стоимость, ₽"]
    for index, header in enumerate(headers, start=1):
        bookings_sheet.cell(row=row, column=index, value=header)
    _style_header(bookings_sheet, row, len(headers), EMERALD)
    bookings_sheet.freeze_panes = bookings_sheet.cell(row=row + 1, column=1)
    row += 1
    for item in report["bookings"]:
        values = [
            item["id"], item["date_label"], item["time"], item["client"], item["phone"],
            item["service"], item["master"], item["status"], item["cost"],
        ]
        for index, value in enumerate(values, start=1):
            cell = bookings_sheet.cell(row=row, column=index, value=value)
            cell.border = BORDER
        cost_cell = bookings_sheet.cell(row=row, column=9)
        cost_cell.number_format = "#,##0 ₽"
        if item["status"] == config.STATUS_DONE:
            cost_cell.fill = PatternFill("solid", fgColor="D7F0E4")
        elif item["status"] in config.LOST_STATUSES:
            cost_cell.fill = PatternFill("solid", fgColor="FBDDDD")
        row += 1
    _autosize(bookings_sheet, min_width=12)

    # --- Лист 6. Упущенная выгода -----------------------------------------
    lost_sheet = workbook.create_sheet("Упущенная выгода")
    row = _title(lost_sheet, 1, "Отменённые записи и неявки", 7, period_label)
    headers = ["Дата", "Время", "Клиент", "Услуга", "Мастер", "Статус", "Потеряно, ₽"]
    for index, header in enumerate(headers, start=1):
        lost_sheet.cell(row=row, column=index, value=header)
    _style_header(lost_sheet, row, len(headers), "9B1C1C")
    row += 1
    for item in report["lost_bookings"]:
        values = [
            item["date_label"], item["time"], item["client"], item["service"],
            item["master"], item["status"], item["cost"],
        ]
        for index, value in enumerate(values, start=1):
            cell = lost_sheet.cell(row=row, column=index, value=value)
            cell.border = BORDER
        lost_sheet.cell(row=row, column=7).number_format = "#,##0 ₽"
        row += 1
    if report["lost_bookings"]:
        total_cell = lost_sheet.cell(row=row, column=6, value="Итого")
        total_cell.font = Font(bold=True)
        total_cell.fill = PatternFill("solid", fgColor=GOLD_LIGHT)
        sum_cell = lost_sheet.cell(row=row, column=7, value=report["kpi"]["lost_revenue"])
        sum_cell.font = Font(bold=True)
        sum_cell.number_format = "#,##0 ₽"
        sum_cell.fill = PatternFill("solid", fgColor=GOLD_LIGHT)
    _autosize(lost_sheet, min_width=12)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def period_presets(today: date | None = None) -> dict[str, dict[str, str]]:
    """Быстрые фильтры дашборда: сегодня / неделя / месяц."""
    today = today or date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    return {
        "today": {"date_from": today.isoformat(), "date_to": today.isoformat(), "label": "Сегодня"},
        "week": {"date_from": week_start.isoformat(), "date_to": today.isoformat(), "label": "Неделя"},
        "month": {"date_from": month_start.isoformat(), "date_to": today.isoformat(), "label": "Месяц"},
    }
