"""Creating/managing watches. The quota check is atomic via FOR UPDATE on the user row:
even 10 parallel requests from the same user cannot exceed the limit."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.core.plans import effective_plan, limits_for
from flightbot.core.watch_key import WatchKey
from flightbot.db.models import Notification, User, Watch
from flightbot.db.models import WatchKey as WatchKeyRow


class QuotaExceeded(Exception):
    def __init__(self, code: str, limit: int) -> None:
        super().__init__(code)
        self.code = code  # 'max_watches' | 'max_flexible'
        self.limit = limit


async def _lock_user_limits(session: AsyncSession, user_id: int, now: datetime):
    row = (
        await session.execute(
            select(User.plan, User.plan_expires_at).where(User.id == user_id).with_for_update()
        )
    ).one()
    return limits_for(effective_plan(row.plan, row.plan_expires_at, now))


async def _active_counts(session: AsyncSession, user_id: int) -> tuple[int, int]:
    row = (
        await session.execute(
            select(
                func.count(Watch.id),
                func.count(Watch.id).filter(WatchKeyRow.date_mode == "month"),
            )
            .join(WatchKeyRow, WatchKeyRow.id == Watch.watch_key_id)
            .where(Watch.user_id == user_id, Watch.status == "active")
        )
    ).one()
    return int(row[0]), int(row[1])


async def count_active(session: AsyncSession, user_id: int) -> int:
    return (await _active_counts(session, user_id))[0]


def _check_quota(limits, active: int, flexible: int, is_flexible: bool) -> None:
    if active >= limits.max_active_watches:
        raise QuotaExceeded("max_watches", limits.max_active_watches)
    if is_flexible and limits.max_flexible_watches is not None and flexible >= limits.max_flexible_watches:
        raise QuotaExceeded("max_flexible", limits.max_flexible_watches)


def _stay_conditions(key: WatchKey) -> list:
    if not key.has_stay:
        return [WatchKeyRow.stay_min.is_(None), WatchKeyRow.stay_max.is_(None)]
    return [WatchKeyRow.stay_min == key.stay_min, WatchKeyRow.stay_max == key.stay_max]


async def get_or_create_key_id(session: AsyncSession, key: WatchKey) -> int:
    values = dict(
        origin=key.origin,
        destination=key.destination,
        date_mode=key.date_mode.value,
        depart_date=key.depart_date,
        return_date=key.return_date,
        direct_only=key.direct_only,
        currency=key.currency,
        stay_min=key.stay_min,
        stay_max=key.stay_max,
        expires_on=key.window_end,
    )
    stmt = (
        pg_insert(WatchKeyRow)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_watch_keys_signature")
        .returning(WatchKeyRow.id)
    )
    key_id = (await session.execute(stmt)).scalar_one_or_none()
    if key_id is not None:
        return key_id
    ret_cond = (
        WatchKeyRow.return_date.is_(None)
        if key.return_date is None
        else WatchKeyRow.return_date == key.return_date
    )
    return (
        await session.execute(
            select(WatchKeyRow.id).where(
                WatchKeyRow.origin == key.origin,
                WatchKeyRow.destination == key.destination,
                WatchKeyRow.date_mode == key.date_mode.value,
                WatchKeyRow.depart_date == key.depart_date,
                ret_cond,
                WatchKeyRow.direct_only == key.direct_only,
                WatchKeyRow.currency == key.currency,
                *_stay_conditions(key),
            )
        )
    ).scalar_one()


async def create_or_update_watch(
    session: AsyncSession,
    *,
    user_id: int,
    key: WatchKey,
    target_price: Decimal,
    now: datetime,
) -> tuple[Watch, bool]:
    """(watch, created). For an existing (user, key) it updates the target and re-arms."""
    limits = await _lock_user_limits(session, user_id, now)
    key_id = await get_or_create_key_id(session, key)

    existing = (
        await session.execute(select(Watch).where(Watch.user_id == user_id, Watch.watch_key_id == key_id))
    ).scalar_one_or_none()

    if existing is None or existing.status != "active":
        active, flexible = await _active_counts(session, user_id)
        _check_quota(limits, active, flexible, key.is_flexible)

    if existing is not None:
        existing.target_price = target_price
        existing.armed = True
        existing.last_notified_price = None
        existing.status = "active"
        existing.pause_reason = None
        watch, created = existing, False
    else:
        watch = Watch(user_id=user_id, watch_key_id=key_id, target_price=target_price)
        session.add(watch)
        created = True
    await session.flush()

    # If the key was already checked and the price is below the target, check it now instead of waiting for the next cycle.
    await session.execute(
        text(
            "UPDATE watch_keys SET next_check_at = LEAST(next_check_at, now()) "
            "WHERE id = :k AND last_price IS NOT NULL AND last_price <= :t"
        ),
        {"k": key_id, "t": target_price},
    )
    return watch, created


async def list_watches(session: AsyncSession, user_id: int) -> list[tuple[Watch, WatchKeyRow]]:
    rows = await session.execute(
        select(Watch, WatchKeyRow)
        .join(WatchKeyRow, WatchKeyRow.id == Watch.watch_key_id)
        .where(Watch.user_id == user_id, Watch.status.in_(("active", "paused")))
        .order_by(Watch.created_at, Watch.id)
    )
    return [(w, k) for w, k in rows.all()]


async def get_watch_with_key(
    session: AsyncSession, *, user_id: int, watch_id: int
) -> tuple[Watch, WatchKeyRow] | None:
    row = (
        await session.execute(
            select(Watch, WatchKeyRow)
            .join(WatchKeyRow, WatchKeyRow.id == Watch.watch_key_id)
            .where(Watch.id == watch_id, Watch.user_id == user_id)
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None


async def set_paused(
    session: AsyncSession, *, user_id: int, watch_id: int, paused: bool, now: datetime
) -> bool:
    """Pause/resume. The quota is re-checked on resume. False if not found."""
    limits = await _lock_user_limits(session, user_id, now)
    row = (
        await session.execute(
            select(Watch, WatchKeyRow.date_mode)
            .join(WatchKeyRow, WatchKeyRow.id == Watch.watch_key_id)
            .where(Watch.id == watch_id, Watch.user_id == user_id)
        )
    ).one_or_none()
    if row is None:
        return False
    watch, mode = row
    if paused:
        if watch.status == "active":
            watch.status = "paused"
            watch.pause_reason = "user"
    elif watch.status == "paused":
        active, flexible = await _active_counts(session, user_id)
        _check_quota(limits, active, flexible, mode == "month")
        watch.status = "active"
        watch.pause_reason = None
    await session.flush()
    return True


async def delete_watch(session: AsyncSession, *, user_id: int, watch_id: int) -> bool:
    res = await session.execute(
        text("DELETE FROM watches WHERE id = :w AND user_id = :u"), {"w": watch_id, "u": user_id}
    )
    return (res.rowcount or 0) > 0


async def record_feedback(session: AsyncSession, *, notification_id: int, user_id: int, vote: int) -> bool:
    if vote not in (-1, 1):
        raise ValueError(vote)
    res = await session.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user_id)
        .values(feedback=vote)
    )
    return (res.rowcount or 0) > 0


async def update_target(session: AsyncSession, *, user_id: int, watch_id: int, target_price: Decimal) -> bool:
    """Change the target and re-arm the watch. Checked immediately if the price is already below the target."""
    res = await session.execute(
        text(
            "UPDATE watches SET target_price = :t, armed = true, last_notified_price = NULL, "
            "updated_at = now() WHERE id = :w AND user_id = :u RETURNING watch_key_id"
        ),
        {"t": target_price, "w": watch_id, "u": user_id},
    )
    row = res.one_or_none()
    if row is None:
        return False
    await session.execute(
        text(
            "UPDATE watch_keys SET next_check_at = LEAST(next_check_at, now()) "
            "WHERE id = :k AND last_price IS NOT NULL AND last_price <= :t"
        ),
        {"k": row[0], "t": target_price},
    )
    return True


async def set_quiet_hours(session: AsyncSession, user_id: int, enabled: bool) -> None:
    await session.execute(update(User).where(User.id == user_id).values(quiet_hours=enabled))
