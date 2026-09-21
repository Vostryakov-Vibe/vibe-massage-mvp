"""Точка входа приложения: салон массажа «Гармония».

Запуск:      python app.py
Docker:      docker compose -f docker/docker-compose.yml up --build

Приложение полностью автономно: все стили, скрипты и шрифты лежат локально
в /static, интернет нужен только для необязательных интеграций (Telegram, ВК,
Turnstile, ИИ-генерация постов) — без них система работает в офлайн-режиме.
"""

from __future__ import annotations

import logging
import socket
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

import config
import database
import seed
from routers import admin_pages, api_admin, public
from templating import templates

# Корректный вывод кириллицы в консоль Windows (в том числе при перенаправлении).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)-16s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("salon")


def _banner_hosts() -> list[str]:
    """Адреса для баннера.

    При HOST=0.0.0.0 приложение слушает все интерфейсы, и печатать
    «http://0.0.0.0» бессмысленно — показываем адреса, по которым
    сайт реально откроется: петлевой и локальный сетевой.
    """
    if config.HOST not in {"0.0.0.0", "::"}:
        return [config.HOST]

    hosts = ["127.0.0.1"]
    try:
        # UDP-сокет ничего не отправляет, но сообщает адрес основного интерфейса.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            local_ip = probe.getsockname()[0]
        if local_ip and local_ip not in hosts:
            hosts.append(local_ip)
    except OSError:
        pass
    return hosts


def print_banner() -> None:
    """Информация о запуске: адреса, учётные записи, статус интеграций."""
    offline_marks = {
        "Telegram": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID),
        "ВКонтакте": bool(config.VK_ACCESS_TOKEN and config.VK_GROUP_ID),
        "Turnstile": config.TURNSTILE_ENABLED,
    }
    hosts = _banner_hosts()
    local_only = hosts == ["127.0.0.1"]
    lines = [
        "",
        "=" * 68,
        f"  {config.SALON['name']} — CRM и онлайн-запись",
        "=" * 68,
    ]
    for index, host in enumerate(hosts):
        label = "Сайт:" if index == 0 else "Сеть:"
        lines.append(f"  {label:<12} http://{host}:{config.PORT}/")
    lines.append(f"  {'Админка:':<12} http://{hosts[0]}:{config.PORT}/admin")
    lines.append(f"  {'API-док:':<12} http://{hosts[0]}:{config.PORT}/api/docs")
    if not local_only:
        lines.append(f"  {' ':12} (адрес «Сеть» — для других устройств в этой же сети)")
    lines += [
        f"  База данных: {config.DATABASE_URL}",
        "",
        "  Учётные записи (созданы при первом запуске):",
        f"    Суперадмин: {config.DEFAULT_SUPERADMIN_LOGIN} / {config.DEFAULT_SUPERADMIN_PASSWORD}",
        f"    Менеджер:   {config.DEFAULT_MANAGER_LOGIN} / {config.DEFAULT_MANAGER_PASSWORD}",
        "",
        "  Внешние интеграции (необязательны, работают при наличии ключей в .env):",
    ]
    for name, ready in offline_marks.items():
        lines.append(f"    {'[+]' if ready else '[-]'} {name}: {'настроено' if ready else 'офлайн-режим'}")
    lines.append("=" * 68)
    lines.append("")
    # flush: при перенаправлении вывода в файл буфер иначе задержит баннер.
    print("\n".join(lines), flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация БД и демо-данных при старте."""
    database.init_db()
    session = database.SessionLocal()
    try:
        seed.initialize_database(session)
    finally:
        session.close()
    print_banner()
    yield
    logger.info("Приложение остановлено.")


def create_app() -> FastAPI:
    """Собирает приложение: middleware, статика, роутеры, обработчики ошибок."""
    app = FastAPI(
        title=f"{config.SALON['name']} — API",
        description="Онлайн-запись, CRM, аналитика и маркетинговый модуль салона массажа.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    # Сессия администратора: подписанная cookie (SameSite=Lax).
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.SECRET_KEY,
        session_cookie="salon_session",
        max_age=60 * 60 * 12,
        same_site="lax",
        # Локально работаем по http; при публикации за HTTPS включают
        # SESSION_HTTPS_ONLY=true, чтобы браузер не отправлял cookie по http.
        https_only=config.SESSION_HTTPS_ONLY,
    )

    # Вся статика (Tailwind, Chart.js, Sortable.js, шрифты, изображения) — локальная.
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

    @app.middleware("http")
    async def revalidate_uploads(request: Request, call_next):
        """Просим браузер перепроверять картинки из static/uploads.

        Их владелец салона может заменить своими файлами, а без заголовка
        браузер применяет эвристическое кэширование и показывает старую
        версию. no-cache не запрещает кэш: неизменённый файл отдаётся
        ответом 304 без повторной передачи картинки.
        """
        response = await call_next(request)
        if request.url.path.startswith("/static/uploads/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.include_router(public.router)
    app.include_router(admin_pages.router)
    app.include_router(api_admin.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        """Проверка живости для Docker."""
        return {"status": "ok", "app": config.SALON["name"]}

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        """JSON для API, красивая страница — для остальных маршрутов."""
        if request.url.path.startswith(("/api/", "/static/")):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"code": exc.status_code, "message": exc.detail},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        """Понятный текст ошибки валидации для фронтенда."""
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "данные"
        return JSONResponse(
            {"detail": f"Проверьте поле «{field}»: {first.get('msg', 'некорректное значение')}"},
            status_code=422,
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEBUG,
        log_level="debug" if config.DEBUG else "info",
    )
