from datetime import datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.db.models import User

SUPPORTED_LANGUAGES = ("az", "ru", "en")
SUPPORTED_CURRENCIES = ("USD", "AZN", "EUR")
LAST_SEEN_THROTTLE = timedelta(minutes=10)


def pick_language(hint: str | None, default: str) -> str:
    """Telegram language_code -> a supported language. Unsupported = default (az)."""
    if hint:
        code = hint.split("-")[0].lower()
        if code in SUPPORTED_LANGUAGES:
            return code
    return default


async def get_or_create_user(
    session: AsyncSession,
    *,
    tenant_id: int,
    telegram_id: int,
    language_hint: str | None,
    default_language: str,
    default_home_iata: str | None,
    now: datetime,
) -> tuple[User, bool]:
    """Race-safe: INSERT ... ON CONFLICT DO NOTHING + SELECT. Returns (user, created)."""
    stmt = (
        pg_insert(User)
        .values(
            tenant_id=tenant_id,
            telegram_id=telegram_id,
            language=pick_language(language_hint, default_language),
            home_iata=default_home_iata,
        )
        .on_conflict_do_nothing(constraint="uq_users_tenant_telegram")
        .returning(User.id)
    )
    created = (await session.execute(stmt)).scalar_one_or_none() is not None
    user = (
        await session.execute(
            select(User).where(User.tenant_id == tenant_id, User.telegram_id == telegram_id)
        )
    ).scalar_one()
    if now - user.last_seen_at > LAST_SEEN_THROTTLE:
        user.last_seen_at = now
    return user, created


async def set_language(session: AsyncSession, user_id: int, language: str) -> None:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(language)
    await session.execute(update(User).where(User.id == user_id).values(language=language))


async def set_currency(session: AsyncSession, user_id: int, currency: str) -> None:
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(currency)
    await session.execute(update(User).where(User.id == user_id).values(currency=currency))


async def mark_blocked(session: AsyncSession, user_id: int) -> None:
    """The user blocked the bot: freeze their watches and cancel pending notifications.

    active_watch_count is fixed automatically by a trigger; no manual counter update is needed.
    """
    await session.execute(update(User).where(User.id == user_id).values(is_blocked=True))
    await session.execute(
        text(
            "UPDATE watches SET status='paused', pause_reason='blocked', updated_at=now() "
            "WHERE user_id=:u AND status='active'"
        ),
        {"u": user_id},
    )
    await session.execute(
        text(
            "UPDATE notifications SET status='skipped', last_error='user_blocked', lease_until=NULL "
            "WHERE user_id=:u AND status IN ('pending','sending')"
        ),
        {"u": user_id},
    )


async def mark_unblocked(session: AsyncSession, user_id: int) -> None:
    """The user restarted the bot: restore the watches that were frozen because of the block."""
    await session.execute(update(User).where(User.id == user_id).values(is_blocked=False))
    await session.execute(
        text(
            "UPDATE watches SET status='active', pause_reason=NULL, updated_at=now() "
            "WHERE user_id=:u AND status='paused' AND pause_reason='blocked'"
        ),
        {"u": user_id},
    )


async def delete_user_data(session: AsyncSession, user_id: int) -> None:
    """Delete the user and everything tied to them (watches, notifications) (FK ON DELETE CASCADE).

    active_watch_count is fixed automatically by a trigger. Price history (price_points) belongs to the route,
    not the user, carries no personal data and is kept.
    """
    await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})


async def set_home(session: AsyncSession, user_id: int, iata: str) -> None:
    await session.execute(update(User).where(User.id == user_id).values(home_iata=iata.upper()))
