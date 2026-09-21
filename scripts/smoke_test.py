"""Дымовые тесты API: онлайн-запись, авторизация, CRM, аналитика, ИИ-модуль.

Запуск (приложение должно быть уже запущено на http://127.0.0.1:8000):
    python scripts/smoke_test.py

Адрес можно переопределить, если приложение доступно по другому адресу:
    SMOKE_BASE=http://192.168.1.10:8000 python scripts/smoke_test.py
"""

from __future__ import annotations

import io
import os
import sys
import time
from datetime import date, timedelta

import requests

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8000").rstrip("/")
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Регистрирует результат проверки."""
    if condition:
        PASSED.append(name)
        print(f"  [ok]   {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  [FAIL] {name} — {detail}")


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * 62)


def main() -> int:
    # ---------------------------------------------------------------- публичное
    section("1. Публичная часть")
    response = requests.get(f"{BASE}/", timeout=10)
    check("Лендинг открывается", response.status_code == 200, f"HTTP {response.status_code}")
    check("Лендинг содержит блок записи", 'id="bookingForm"' in response.text)
    check("Локальный Tailwind подключён", "/static/vendor/tailwind.js" in response.text)
    check("Нет внешних CDN в разметке", "cdn.tailwindcss.com" not in response.text)

    services = requests.get(f"{BASE}/api/public/services", timeout=10).json()["items"]
    check("Каталог услуг не пуст", len(services) >= 5, f"{len(services)} услуг")

    masters = requests.get(f"{BASE}/api/public/masters", timeout=10).json()["items"]
    check("Список мастеров не пуст", len(masters) >= 4, f"{len(masters)} мастеров")

    # ---------------------------------------------------------------- запись
    section("2. Онлайн-запись и расчёт слотов")
    token = requests.get(f"{BASE}/api/public/form-token", timeout=10).json()["token"]
    check("Токен формы получен", bool(token))

    # Дата для проверки записи: берём ближайший день, где у мастера остались
    # свободные окна. Фиксированная дата не подходит — прошлые прогоны теста
    # оставляют в базе реальные записи и однажды занимают все слоты дня.
    target_date = ""
    slots: list[str] = []
    for offset in range(2, 15):
        candidate = (date.today() + timedelta(days=offset)).isoformat()
        candidate_slots = requests.get(
            f"{BASE}/api/public/slots",
            params={"service_id": services[0]["id"], "master_id": masters[0]["id"], "date_str": candidate},
            timeout=10,
        ).json().get("slots", [])
        if candidate_slots:
            target_date, slots = candidate, candidate_slots
            break
    check(
        "Свободные слоты рассчитаны",
        len(slots) > 0,
        f"{len(slots)} слотов на {target_date or '— нет свободных дней в ближайшие 2 недели'}",
    )

    payload = {
        "service_id": services[0]["id"],
        "master_id": masters[0]["id"],
        "date": target_date,
        "time": slots[0] if slots else "10:00",
        "full_name": "Тестовый Клиент",
        "phone": "+7 (999) 111-22-33",
        "contact": "@test_client",
        "comment": "Проверка онлайн-записи",
        "consent": True,
        "honeypot": "",
        "form_token": token,
        "turnstile_token": "",
    }

    fast = requests.post(f"{BASE}/api/public/bookings", json=payload, timeout=10)
    check("Слишком быстрая отправка отклонена", fast.status_code == 400, fast.json().get("detail", ""))

    time.sleep(3.2)
    no_consent = requests.post(
        f"{BASE}/api/public/bookings", json={**payload, "consent": False}, timeout=10
    )
    check("Запись без согласия 152-ФЗ отклонена", no_consent.status_code == 400)

    bot = requests.post(f"{BASE}/api/public/bookings", json={**payload, "honeypot": "spam"}, timeout=10)
    check("Honeypot-поле блокирует бота", bot.status_code == 400)

    booking = requests.post(f"{BASE}/api/public/bookings", json=payload, timeout=15)
    check("Запись создана", booking.status_code == 200, f"HTTP {booking.status_code}")
    ticket = booking.json().get("ticket", {}) if booking.status_code == 200 else {}
    check("Талон содержит код записи", bool(ticket.get("code")), ticket.get("code", ""))
    check("Стоимость зафиксирована", bool(ticket.get("price")), ticket.get("price", ""))

    if slots:
        duplicate = requests.post(f"{BASE}/api/public/bookings", json=payload, timeout=10)
        check("Повторная запись на занятый слот отклонена", duplicate.status_code == 409)

    # ---------------------------------------------------------------- авторизация
    section("3. Авторизация и роли")
    admin = requests.Session()
    bad_login = admin.post(
        f"{BASE}/admin/login", data={"username": "admin", "password": "wrong"}, timeout=10
    )
    check("Неверный пароль отклонён", bad_login.status_code == 401)

    good_login = admin.post(
        f"{BASE}/admin/login", data={"username": "admin", "password": "admin777"}, timeout=10
    )
    check("Суперадмин вошёл", good_login.status_code == 200, f"HTTP {good_login.status_code}")

    dashboard = admin.get(f"{BASE}/admin/dashboard", timeout=10)
    check("Дашборд доступен Суперадмину", dashboard.status_code == 200)
    check("CSRF-токен в разметке", 'name="csrf-token"' in dashboard.text)

    csrf = dashboard.text.split('name="csrf-token" content="')[1].split('"')[0]

    manager = requests.Session()
    manager.post(f"{BASE}/admin/login", data={"username": "manager", "password": "manager777"}, timeout=10)
    manager_crm = manager.get(f"{BASE}/admin/crm", timeout=10)
    check("Менеджер видит Канбан", manager_crm.status_code == 200)
    manager_dashboard = manager.get(f"{BASE}/admin/dashboard", allow_redirects=False, timeout=10)
    check(
        "Менеджер перенаправлен с дашборда",
        manager_dashboard.status_code in (302, 303),
        f"HTTP {manager_dashboard.status_code}",
    )
    manager_api = manager.get(f"{BASE}/api/admin/analytics", timeout=10)
    check("API аналитики закрыт для Менеджера", manager_api.status_code == 403)

    # ---------------------------------------------------------------- CRM
    section("4. CRM: Канбан-доска")
    board = admin.get(f"{BASE}/api/admin/bookings", timeout=10).json()
    check("Канбан вернул колонки", len(board["columns"]) == 7, f"{len(board['columns'])} колонок")
    check("Записи в базе есть", board["total"] > 0, f"{board['total']} записей")

    no_csrf = admin.post(
        f"{BASE}/api/admin/bookings/1/status", json={"status": "Подтверждена"}, timeout=10
    )
    check("Запрос без CSRF-токена отклонён", no_csrf.status_code == 403)

    first_id = None
    for column in board["columns"]:
        if column["bookings"]:
            first_id = column["bookings"][0]["id"]
            break

    moved = admin.post(
        f"{BASE}/api/admin/bookings/{first_id}/status",
        json={"status": "Подтверждена"},
        headers={"X-CSRF-Token": csrf},
        timeout=10,
    )
    check("Статус записи изменён", moved.status_code == 200, f"запись №{first_id}")

    priced = admin.patch(
        f"{BASE}/api/admin/bookings/{first_id}",
        json={"total_cost": 4321, "comment": "Гибкая цена из теста"},
        headers={"X-CSRF-Token": csrf},
        timeout=10,
    )
    check(
        "Гибкая цена сохранена",
        priced.status_code == 200 and priced.json()["booking"]["cost"] == 4321,
        priced.json().get("booking", {}).get("cost_label", ""),
    )

    notifications = admin.get(f"{BASE}/api/admin/notifications?after_id=0", timeout=10).json()
    check("Уведомления о новых записях работают", "max_id" in notifications)

    # ---------------------------------------------------------------- аналитика
    section("5. Аналитика и Excel")
    analytics = admin.get(f"{BASE}/api/admin/analytics", timeout=15).json()
    kpi = analytics["kpi"]
    check("Выручка рассчитана", kpi["revenue"] > 0, kpi["revenue_label"])
    check("Упущенная выгода рассчитана", kpi["lost_revenue"] > 0, kpi["lost_revenue_label"])
    check("Конверсия рассчитана", 0 <= kpi["conversion"] <= 100, f"{kpi['conversion']}%")
    check("Популярные услуги есть", len(analytics["popular_services"]) > 0)
    check("Загруженность мастеров посчитана", len(analytics["workload"]) > 0,
          f"лидер: {analytics['workload'][0]['master']} — {analytics['workload'][0]['load_percent']}%")
    check("Серия выручки по дням есть", len(analytics["day_series"]) > 0)
    check("Серия упущенной выгоды есть", len(analytics["lost_series"]) > 0)

    excel = admin.get(f"{BASE}/api/admin/analytics/export", timeout=30)
    check("Excel-отчёт сформирован", excel.status_code == 200 and len(excel.content) > 5000,
          f"{len(excel.content) / 1024:.0f} КБ")
    check(
        "Это действительно xlsx",
        excel.content[:2] == b"PK",
        excel.headers.get("content-type", ""),
    )

    # ---------------------------------------------------------------- маркетинг
    section("6. Маркетинговый ИИ-модуль")
    post = admin.post(
        f"{BASE}/api/admin/marketing/generate",
        json={
            "topic": "Массаж спины для офисных сотрудников",
            "tone": "Дружелюбный с юмором",
            "length": "Средний",
            "keywords": "шея, осанка, компьютер",
            "send_telegram": False,
            "send_vk": False,
        },
        headers={"X-CSRF-Token": csrf},
        timeout=40,
    )
    check("Пост сгенерирован", post.status_code == 200, f"HTTP {post.status_code}")
    if post.status_code == 200:
        data = post.json()["post"]
        content = data["content"]
        check("Источник определён", data["source"] in ("ai", "template"), data["source"])
        check("Текст поста содержательный", len(content) > 250, f"{len(content)} знаков")
        check("Есть призыв к действию с эмодзи", any(symbol in content for symbol in "😊🍵📩✨🔥"))
        check("Пост сохранён в архив", data["id"] > 0, f"id={data['id']}")

    posts = admin.get(f"{BASE}/api/admin/marketing/posts", timeout=10).json()
    check("Архив постов читается", posts["items"] and posts["retention_days"] == 30,
          f"{len(posts['items'])} постов, хранение {posts['retention_days']} дней")

    publish = admin.post(
        f"{BASE}/api/admin/marketing/publish",
        json={"post_id": posts["items"][0]["id"], "send_telegram": True, "send_vk": True},
        headers={"X-CSRF-Token": csrf},
        timeout=30,
    )
    check("Публикация без токенов не падает", publish.status_code == 200,
          str(publish.json().get("publish", {})))

    # ---------------------------------------------------------------- справочники
    section("7. Справочники и удаление")
    new_service = admin.post(
        f"{BASE}/api/admin/services",
        json={
            "title": "Тестовая услуга",
            "category": "Классический массаж",
            "duration_minutes": 30,
            "price": 1000,
            "short_description": "Проверка",
            "is_active": True,
            "sort_order": 999,
        },
        headers={"X-CSRF-Token": csrf},
        timeout=10,
    )
    check("Услуга создана", new_service.status_code == 200)
    service_id = new_service.json()["service"]["id"] if new_service.status_code == 200 else None

    if service_id:
        soft = admin.delete(f"{BASE}/api/admin/services/{service_id}",
                            headers={"X-CSRF-Token": csrf}, timeout=10)
        check("Мягкое удаление услуги", soft.status_code == 200 and soft.json()["mode"] == "soft")
        restore = admin.post(f"{BASE}/api/admin/services/{service_id}/restore",
                             headers={"X-CSRF-Token": csrf}, timeout=10)
        check("Услуга возвращена из архива", restore.status_code == 200)
        hard = admin.delete(f"{BASE}/api/admin/services/{service_id}/hard",
                            headers={"X-CSRF-Token": csrf}, timeout=10)
        check("Жёсткое удаление услуги", hard.status_code == 200,
              f"затронуто записей: {hard.json().get('affected_bookings')}")

    schedules = admin.get(f"{BASE}/api/admin/schedules?master_id={masters[0]['id']}", timeout=10).json()
    check("График смен читается", len(schedules["items"]) > 0, f"{len(schedules['items'])} смен")

    clients = admin.get(f"{BASE}/api/admin/clients?query=Тестовый", timeout=10).json()["items"]
    check("Клиент из онлайн-записи сохранён", len(clients) > 0)
    if clients:
        check("Согласие 152-ФЗ зафиксировано", clients[0]["consent_given"],
              f"IP {clients[0]['consent_ip']}")

    # ---------------------------------------------------------------- итог
    print("\n" + "=" * 62)
    print(f"Пройдено: {len(PASSED)} | Провалено: {len(FAILED)}")
    if FAILED:
        print("\nПроваленные проверки:")
        for item in FAILED:
            print(f"  - {item}")
    print("=" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except requests.RequestException as error:
        print(f"Сервер недоступен: {error}. Запустите `python app.py`.")
        sys.exit(2)
