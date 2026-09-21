"""Модели базы данных (SQLAlchemy 2.0, декларативный стиль).

Денежные значения хранятся целыми числами в рублях — это исключает
ошибки округления при расчётах в аналитике.
"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

import config
from database import Base


def _now() -> datetime:
    """Локальное «сейчас» (приложение работает офлайн, часовой пояс — системный)."""
    return datetime.now()


class User(Base):
    """Пользователь админки: Superadmin (полный доступ) или Manager (записи)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(32), default=config.ROLE_MANAGER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - отладочное
        return f"<User {self.username} ({self.role})>"


class Service(Base):
    """Услуга салона. Удаление — мягкое (is_active=False)."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    short_description: Mapped[str] = mapped_column(String(400), default="")
    full_description: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    image_filename: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(80), default="Классический массаж")
    indications: Mapped[str] = mapped_column(Text, default="")
    contraindications: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    bookings: Mapped[list["Booking"]] = relationship(back_populates="service")

    @property
    def duration_label(self) -> str:
        """Человекочитаемая длительность: 90 мин → «1 ч 30 мин»."""
        hours, minutes = divmod(self.duration_minutes, 60)
        if hours and minutes:
            return f"{hours} ч {minutes} мин"
        if hours:
            return f"{hours} ч"
        return f"{minutes} мин"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Service {self.title}>"


class Master(Base):
    """Мастер (специалист) салона. Удаление — мягкое (is_active=False)."""

    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    specialization: Mapped[str] = mapped_column(String(200), default="")
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    bio: Mapped[str] = mapped_column(Text, default="")
    avatar_filename: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    bookings: Mapped[list["Booking"]] = relationship(back_populates="master")
    schedules: Mapped[list["Schedule"]] = relationship(
        back_populates="master", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Master {self.full_name}>"


class Schedule(Base):
    """Смена мастера: конкретная дата и рабочий интервал."""

    __tablename__ = "schedules"
    __table_args__ = (UniqueConstraint("master_id", "date", name="uq_schedule_master_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(
        ForeignKey("masters.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    master: Mapped["Master"] = relationship(back_populates="schedules")

    @property
    def duration_hours(self) -> float:
        """Длительность смены в часах (для расчёта загруженности)."""
        start_minutes = self.start_time.hour * 60 + self.start_time.minute
        end_minutes = self.end_time.hour * 60 + self.end_time.minute
        return max(0, end_minutes - start_minutes) / 60

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Schedule master={self.master_id} {self.date} {self.start_time}-{self.end_time}>"


class Client(Base):
    """Клиент салона + согласие на обработку персональных данных (152-ФЗ)."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    telegram_vk_contact: Mapped[str] = mapped_column(String(160), default="")
    rating: Mapped[int] = mapped_column(Integer, default=5)
    admin_notes: Mapped[str] = mapped_column(Text, default="")
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    bookings: Mapped[list["Booking"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    @property
    def visits_count(self) -> int:
        """Количество завершённых визитов."""
        return len([b for b in self.bookings if b.status == config.STATUS_DONE])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Client {self.full_name} {self.phone}>"


class Booking(Base):
    """Запись на массаж.

    Поля ``service_title`` и ``master_name`` — снимок на момент визита:
    если услугу или мастера удалят физически, история и аналитика
    останутся корректными.
    """

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True, nullable=True
    )
    master_id: Mapped[int | None] = mapped_column(
        ForeignKey("masters.id", ondelete="SET NULL"), index=True, nullable=True
    )
    service_title: Mapped[str] = mapped_column(String(160), default="")
    master_name: Mapped[str] = mapped_column(String(160), default="")
    visit_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    visit_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), default=config.STATUS_NEW, index=True, nullable=False
    )
    total_cost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    client: Mapped["Client"] = relationship(back_populates="bookings")
    service: Mapped["Service | None"] = relationship(back_populates="bookings")
    master: Mapped["Master | None"] = relationship(back_populates="bookings")

    @property
    def visit_datetime(self) -> datetime:
        """Дата и время визита одним объектом."""
        return datetime.combine(self.visit_date, self.visit_time)

    @property
    def is_lost(self) -> bool:
        """Запись попала в «упущенную выгоду»."""
        return self.status in config.LOST_STATUSES

    @property
    def is_revenue(self) -> bool:
        """Запись принесла фактическую выручку."""
        return self.status == config.STATUS_DONE

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Booking #{self.id} {self.visit_date} {self.visit_time} {self.status}>"


class Review(Base):
    """Отзыв для блока «Отзывы» на лендинге."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_name: Mapped[str] = mapped_column(String(120), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, default=5)
    text: Mapped[str] = mapped_column(Text, default="")
    service_title: Mapped[str] = mapped_column(String(160), default="")
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Review {self.author_name} {self.rating}★>"


class Post(Base):
    """Пост, сгенерированный маркетинговым ИИ-модулем (архив)."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(200), default="")
    tone: Mapped[str] = mapped_column(String(60), default="")
    length: Mapped[str] = mapped_column(String(30), default="")
    keywords: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="template")
    sent_telegram: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_vk: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Post #{self.id} {self.topic!r} ({self.source})>"
