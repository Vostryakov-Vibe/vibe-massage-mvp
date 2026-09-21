"""Страницы админ-панели и аутентификация."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

import analytics
import config
import scheduling
from database import get_db
from models import Booking, Client, Master, Post, Review, Schedule, Service, User
from security import (
    client_ip,
    get_current_user,
    get_csrf_token,
    login_user,
    logout_user,
    rate_limit,
    require_csrf,
    validate_password_strength,
    verify_password,
)
from templating import templates

logger = logging.getLogger("salon.admin")
router = APIRouter(prefix="/admin")

MANAGER_ALLOWED = {"crm", "clients"}


def _render(request: Request, template: str, context: dict, status_code: int = 200) -> HTMLResponse:
    """Рендер страницы админки с общим контекстом."""
    user = context.get("user")
    context.setdefault("csrf_token", get_csrf_token(request))
    context.setdefault("active_page", "")
    context.setdefault("is_superadmin", bool(user and user.role == config.ROLE_SUPERADMIN))
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def _guard(request: Request, db: Session, page: str) -> tuple[User | None, RedirectResponse | None]:
    """Проверяет авторизацию и права на страницу."""
    user = get_current_user(request, db)
    if user is None:
        return None, RedirectResponse("/admin/login", status_code=303)
    if user.role != config.ROLE_SUPERADMIN and page not in MANAGER_ALLOWED:
        return None, RedirectResponse("/admin/crm?denied=1", status_code=303)
    return user, None


# --- Аутентификация --------------------------------------------------------


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, db: Session = Depends(get_db)):
    """Страница входа."""
    if get_current_user(request, db) is not None:
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        request, "admin/login.html", {"error": "", "username": "", "csrf_token": get_csrf_token(request)}
    )


@router.post("/login", include_in_schema=False)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Обработка формы входа."""
    ip = client_ip(request)
    if not rate_limit(f"login:{ip}", limit=10, window_seconds=900):
        logger.warning("Превышено число попыток входа с IP %s", ip)
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {
                "error": "Слишком много попыток входа. Попробуйте через 15 минут.",
                "username": username,
                "csrf_token": get_csrf_token(request),
            },
            status_code=429,
        )

    user = db.scalar(select(User).where(User.username == username.strip()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        logger.info("Неудачная попытка входа: %s (IP %s)", username, ip)
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {
                "error": "Неверный логин или пароль",
                "username": username,
                "csrf_token": get_csrf_token(request),
            },
            status_code=401,
        )

    login_user(request, user)
    logger.info("Вход выполнен: %s (%s)", user.username, user.role)
    return RedirectResponse("/admin", status_code=303)


@router.get("/logout", include_in_schema=False)
def logout(request: Request):
    """Выход из системы."""
    logout_user(request)
    return RedirectResponse("/admin/login", status_code=303)


@router.get("", include_in_schema=False)
def admin_root(request: Request, db: Session = Depends(get_db)):
    """Перенаправление на стартовую страницу по роли."""
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/admin/login", status_code=303)
    target = "/admin/dashboard" if user.role == config.ROLE_SUPERADMIN else "/admin/crm"
    return RedirectResponse(target, status_code=303)


# --- Страницы --------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    """Аналитический дашборд."""
    user, redirect = _guard(request, db, "dashboard")
    if redirect:
        return redirect
    return _render(
        request,
        "admin/dashboard.html",
        {"user": user, "active_page": "dashboard", "presets": analytics.period_presets()},
    )


@router.get("/crm", response_class=HTMLResponse, include_in_schema=False)
def crm_page(request: Request, db: Session = Depends(get_db)):
    """Канбан-доска записей."""
    user, redirect = _guard(request, db, "crm")
    if redirect:
        return redirect
    masters = db.scalars(
        select(Master).where(Master.is_system.is_(False)).order_by(Master.full_name)
    ).all()
    services = db.scalars(select(Service).order_by(Service.title)).all()
    return _render(
        request,
        "admin/crm.html",
        {
            "user": user,
            "active_page": "crm",
            "masters": masters,
            "services": services,
            "statuses": config.BOOKING_STATUSES,
            "denied": request.query_params.get("denied") == "1",
        },
    )


@router.get("/clients", response_class=HTMLResponse, include_in_schema=False)
def clients_page(request: Request, db: Session = Depends(get_db)):
    """База клиентов."""
    user, redirect = _guard(request, db, "clients")
    if redirect:
        return redirect
    clients = db.scalars(
        select(Client).options(selectinload(Client.bookings)).order_by(Client.full_name)
    ).all()
    return _render(
        request,
        "admin/clients.html",
        {"user": user, "active_page": "clients", "clients": clients},
    )


@router.get("/services", response_class=HTMLResponse, include_in_schema=False)
def services_page(request: Request, db: Session = Depends(get_db)):
    """Управление услугами."""
    user, redirect = _guard(request, db, "services")
    if redirect:
        return redirect
    services = db.scalars(select(Service).order_by(Service.sort_order, Service.title)).all()
    return _render(
        request,
        "admin/services.html",
        {"user": user, "active_page": "services", "services": services},
    )


@router.get("/masters", response_class=HTMLResponse, include_in_schema=False)
def masters_page(request: Request, db: Session = Depends(get_db)):
    """Управление мастерами и графиками смен."""
    user, redirect = _guard(request, db, "masters")
    if redirect:
        return redirect
    masters = db.scalars(
        select(Master).where(Master.is_system.is_(False)).order_by(Master.full_name)
    ).all()
    schedules = {master.id: scheduling.schedule_overview(db, master.id) for master in masters}
    return _render(
        request,
        "admin/masters.html",
        {"user": user, "active_page": "masters", "masters": masters, "schedules": schedules},
    )


@router.get("/marketing", response_class=HTMLResponse, include_in_schema=False)
def marketing_page(request: Request, db: Session = Depends(get_db)):
    """Генератор маркетинговых постов."""
    user, redirect = _guard(request, db, "marketing")
    if redirect:
        return redirect
    posts = db.scalars(select(Post).order_by(Post.created_at.desc()).limit(30)).all()
    return _render(
        request,
        "admin/marketing.html",
        {
            "user": user,
            "active_page": "marketing",
            "posts": posts,
            "tones": __import__("ai_marketing").TONES,
            "lengths": __import__("ai_marketing").LENGTHS,
            "retention_days": config.POSTS_RETENTION_DAYS,
            "telegram_ready": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID),
            "vk_ready": bool(config.VK_ACCESS_TOKEN and config.VK_GROUP_ID),
        },
    )


@router.get("/users", response_class=HTMLResponse, include_in_schema=False)
def users_page(request: Request, db: Session = Depends(get_db)):
    """Пользователи и пароли (только Суперадмин)."""
    user, redirect = _guard(request, db, "users")
    if redirect:
        return redirect
    users = db.scalars(select(User).order_by(User.role, User.username)).all()
    return _render(request, "admin/users.html", {"user": user, "active_page": "users", "users": users})


@router.get("/archive", response_class=HTMLResponse, include_in_schema=False)
def archive_page(request: Request, db: Session = Depends(get_db)):
    """Архив: отзывы и удалённые (неактивные) сущности."""
    user, redirect = _guard(request, db, "archive")
    if redirect:
        return redirect
    inactive_services = db.scalars(select(Service).where(Service.is_active.is_(False))).all()
    inactive_masters = db.scalars(
        select(Master).where(Master.is_active.is_(False), Master.is_system.is_(False))
    ).all()
    reviews = db.scalars(select(Review).order_by(Review.created_at.desc())).all()
    bookings_total = db.scalar(select(func.count(Booking.id))) or 0
    return _render(
        request,
        "admin/archive.html",
        {
            "user": user,
            "active_page": "archive",
            "inactive_services": inactive_services,
            "inactive_masters": inactive_masters,
            "reviews": reviews,
            "bookings_total": bookings_total,
        },
    )


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_page(request: Request, db: Session = Depends(get_db)):
    """Настройки салона и интеграций."""
    user, redirect = _guard(request, db, "settings")
    if redirect:
        return redirect
    return _render(
        request,
        "admin/settings.html",
        {
            "user": user,
            "active_page": "settings",
            "telegram_ready": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID),
            "vk_ready": bool(config.VK_ACCESS_TOKEN and config.VK_GROUP_ID),
            "turnstile_enabled": config.TURNSTILE_ENABLED,
            "ai_api_url": config.AI_API_URL,
            "retention_days": config.POSTS_RETENTION_DAYS,
            "password_error": request.query_params.get("password_error", ""),
            "password_ok": request.query_params.get("password_ok", ""),
        },
    )


@router.post("/settings/password", include_in_schema=False)
def change_own_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
):
    """Смена собственного пароля из интерфейса."""
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/admin/login", status_code=303)

    if new_password != confirm_password:
        return RedirectResponse("/admin/settings?password_error=Пароли+не+совпадают", status_code=303)
    if not verify_password(current_password, user.password_hash):
        return RedirectResponse("/admin/settings?password_error=Неверный+текущий+пароль", status_code=303)
    problem = validate_password_strength(new_password)
    if problem:
        return RedirectResponse(f"/admin/settings?password_error={problem}", status_code=303)

    from security import hash_password

    user.password_hash = hash_password(new_password)
    db.commit()
    logger.info("Пользователь %s сменил пароль", user.username)
    return RedirectResponse("/admin/settings?password_ok=1", status_code=303)
