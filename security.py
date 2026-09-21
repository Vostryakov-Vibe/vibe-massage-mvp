"""Аутентификация, роли, CSRF и защита от перебора паролей."""

from __future__ import annotations

import secrets
import time
from collections import defaultdict

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from database import get_db
from models import User

# --- Пароли ----------------------------------------------------------------


def hash_password(password: str) -> str:
    """Хэширует пароль алгоритмом bcrypt (cost=12).

    bcrypt учитывает только первые 72 байта — обрезаем явно, чтобы
    длинный пароль не приводил к неожиданному поведению.
    """
    payload = password.encode("utf-8")[:72]
    return bcrypt.hashpw(payload, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль против сохранённого хэша."""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> str | None:
    """Возвращает текст ошибки или None, если пароль достаточно надёжен."""
    if len(password) < 6:
        return "Пароль должен содержать минимум 6 символов"
    if password.isdigit():
        return "Пароль не должен состоять только из цифр"
    return None


# --- Сессия -----------------------------------------------------------------

SESSION_USER_KEY = "user_id"
SESSION_CSRF_KEY = "csrf_token"


def login_user(request: Request, user: User) -> None:
    """Записывает пользователя в сессию и обновляет CSRF-токен."""
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    request.session[SESSION_CSRF_KEY] = secrets.token_urlsafe(32)


def logout_user(request: Request) -> None:
    """Очищает сессию."""
    request.session.clear()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Возвращает текущего пользователя или None."""
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


def require_user(user: User | None = Depends(get_current_user)) -> User:
    """Зависимость: доступ только авторизованным."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход")
    return user


def require_superadmin(user: User = Depends(require_user)) -> User:
    """Зависимость: доступ только Суперадмину."""
    if user.role != config.ROLE_SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав: действие доступно только Суперадмину",
        )
    return user


def get_csrf_token(request: Request) -> str:
    """Возвращает (при необходимости создаёт) CSRF-токен сессии."""
    token = request.session.get(SESSION_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_CSRF_KEY] = token
    return token


async def require_csrf(request: Request) -> None:
    """Зависимость: проверка CSRF-токена для изменяющих запросов админки.

    Токен приходит либо заголовком X-CSRF-Token (fetch-запросы из JS),
    либо скрытым полем csrf_token (обычные HTML-формы).
    """
    expected = request.session.get(SESSION_CSRF_KEY)
    provided = request.headers.get("X-CSRF-Token") or request.headers.get("X-CSRF-TOKEN")
    if not provided:
        form = await request.form()
        provided = str(form.get("csrf_token") or "")

    # Сравниваем байты: compare_digest со str падает на не-ASCII входе.
    if (
        not expected
        or not provided
        or not secrets.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ошибка CSRF-токена")


# --- Ограничение частоты запросов ------------------------------------------

_attempts: dict[str, list[float]] = defaultdict(list)


def _prune(bucket: list[float], window: float, now: float) -> list[float]:
    """Убирает из истории метки старше окна."""
    return [stamp for stamp in bucket if now - stamp < window]


def rate_limit(key: str, limit: int, window_seconds: float) -> bool:
    """Регистрирует попытку. False — лимит исчерпан (действие отклоняется)."""
    now = time.time()
    bucket = _prune(_attempts[key], window_seconds, now)
    if len(bucket) >= limit:
        _attempts[key] = bucket
        return False
    bucket.append(now)
    _attempts[key] = bucket
    return True


def rate_limit_peek(key: str, limit: int, window_seconds: float) -> bool:
    """Проверяет лимит без регистрации попытки."""
    now = time.time()
    return len(_prune(_attempts.get(key, []), window_seconds, now)) < limit


def client_ip(request: Request) -> str:
    """IP клиента с учётом обратного прокси (X-Forwarded-For)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
