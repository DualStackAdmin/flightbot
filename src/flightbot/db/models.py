"""Schema v2.

Key design decisions:
- `watch_keys` = the unique unit of an API request (dedup). `watches` = a user's subscription.
- `watch_keys.active_watch_count` is maintained by a DB trigger (never updated by hand -> no drift).
- `notifications` = transactional outbox. A notification is written in the poller's transaction and
  sent separately by the broadcaster. It survives a Redis loss.
- `tenant_id` exists from day one (cheap insurance for future B2B / white-label).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from flightbot.db.base import Base

TZDateTime = DateTime(timezone=True)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "telegram_id", name="uq_users_tenant_telegram"),
        CheckConstraint("plan IN ('free','pro')", name="plan"),
        CheckConstraint("language IN ('az','ru','en')", name="language"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), server_default=text("1"), nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    language: Mapped[str] = mapped_column(String(2), server_default="az")
    currency: Mapped[str] = mapped_column(String(3), server_default="USD")
    home_iata: Mapped[str | None] = mapped_column(String(3), nullable=True)
    plan: Mapped[str] = mapped_column(String(8), server_default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    quiet_hours: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class WatchKey(Base):
    """The unique signature of a provider request. Same signature = 1 request, however many users subscribe."""

    __tablename__ = "watch_keys"
    __table_args__ = (
        UniqueConstraint(
            "origin",
            "destination",
            "date_mode",
            "depart_date",
            "return_date",
            "direct_only",
            "currency",
            "stay_min",
            "stay_max",
            name="uq_watch_keys_signature",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("date_mode IN ('exact','month')", name="date_mode"),
        CheckConstraint("char_length(origin) = 3 AND char_length(destination) = 3", name="iata"),
        CheckConstraint("active_watch_count >= 0", name="count_nonneg"),
        CheckConstraint(
            "(stay_min IS NULL AND stay_max IS NULL) OR "
            "(stay_min BETWEEN 1 AND 30 AND stay_max BETWEEN stay_min AND 30)",
            name="stay_range",
        ),
        # The scheduler only looks at keys that are due and have an active subscriber.
        Index(
            "ix_watch_keys_due",
            "next_check_at",
            postgresql_where=text("active_watch_count > 0"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    origin: Mapped[str] = mapped_column(String(3))
    destination: Mapped[str] = mapped_column(String(3))
    date_mode: Mapped[str] = mapped_column(String(8))
    depart_date: Mapped[date] = mapped_column(Date)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    direct_only: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    currency: Mapped[str] = mapped_column(String(3))
    stay_min: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    stay_max: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    expires_on: Mapped[date] = mapped_column(Date)

    next_check_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active_watch_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class Watch(Base):
    """A user's subscription."""

    __tablename__ = "watches"
    __table_args__ = (
        UniqueConstraint("user_id", "watch_key_id", name="uq_watches_user_key"),
        CheckConstraint("status IN ('active','paused','expired')", name="status"),
        CheckConstraint("target_price > 0", name="target_positive"),
        Index(
            "ix_watches_key_active",
            "watch_key_id",
            "target_price",
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_watches_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    watch_key_id: Mapped[int] = mapped_column(ForeignKey("watch_keys.id", ondelete="CASCADE"))
    target_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(8), server_default="active")
    pause_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 'user' | 'blocked'
    # armed=False: a notification was sent; not re-armed until the price rises above the target
    armed: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_notified_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())


class PricePoint(Base):
    """Price history. Written from day one for the future 'good price' badge and charts."""

    __tablename__ = "price_points"
    __table_args__ = (Index("ix_price_points_key_time", "watch_key_id", text("observed_at DESC")),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    watch_key_id: Mapped[int] = mapped_column(ForeignKey("watch_keys.id", ondelete="CASCADE"))
    observed_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3))
    depart_date: Mapped[date] = mapped_column(Date)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    airline: Mapped[str | None] = mapped_column(String(8), nullable=True)
    transfers: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    found_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    provider: Mapped[str] = mapped_column(String(32))


class Notification(Base):
    """Transactional outbox. status: pending -> sending -> sent | failed | skipped."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_notifications_dedup_key"),
        CheckConstraint("status IN ('pending','sending','sent','failed','skipped')", name="status"),
        CheckConstraint("feedback IN (-1, 1)", name="feedback"),
        Index(
            "ix_notifications_queue",
            "priority",
            "available_at",
            "id",
            postgresql_where=text("status IN ('pending','sending')"),
        ),
        Index("ix_notifications_user_created", "user_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    watch_id: Mapped[int | None] = mapped_column(ForeignKey("watches.id", ondelete="SET NULL"), nullable=True)
    dedup_key: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))  # 0=pro, 1=free
    status: Mapped[str] = mapped_column(String(8), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    lease_until: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    feedback: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
