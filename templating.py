"""Общий экземпляр Jinja2-шаблонов, фильтры и глобальные переменные."""

from __future__ import annotations

from fastapi.templating import Jinja2Templates

import config
import utils

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

# Фильтры шаблонов
templates.env.filters["money"] = utils.money
templates.env.filters["human_date"] = utils.human_date
templates.env.filters["short_date"] = utils.short_date
templates.env.filters["human_time"] = utils.human_time
templates.env.filters["weekday"] = utils.weekday_name
templates.env.filters["status_tone"] = utils.status_tone
templates.env.filters["plural"] = utils.plural_ru
templates.env.filters["tel"] = utils.tel_href

# Глобальные значения, доступные в любом шаблоне
templates.env.globals.update(
    salon=config.SALON,
    app_statuses=config.BOOKING_STATUSES,
    app_categories=config.SERVICE_CATEGORIES,
    turnstile_enabled=config.TURNSTILE_ENABLED,
    turnstile_site_key=config.TURNSTILE_SITE_KEY,
    role_superadmin=config.ROLE_SUPERADMIN,
    role_manager=config.ROLE_MANAGER,
    status_new=config.STATUS_NEW,
    status_informing=config.STATUS_INFORMING,
    status_adjustment=config.STATUS_ADJUSTMENT,
    status_confirmed=config.STATUS_CONFIRMED,
    status_done=config.STATUS_DONE,
    status_cancelled=config.STATUS_CANCELLED,
    status_no_show=config.STATUS_NO_SHOW,
    lost_statuses=config.LOST_STATUSES,
)
