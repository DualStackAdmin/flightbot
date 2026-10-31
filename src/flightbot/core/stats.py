"""Price history statistics (median, lowest 20%)."""

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.core.pricing import EMPTY_STATS, GOOD_PRICE_WINDOW_DAYS, PriceStats
from flightbot.core.watch_key import WatchKey
from flightbot.db.models import PricePoint
from flightbot.db.models import WatchKey as WatchKeyRow


async def load_price_stats(session: AsyncSession, key_id: int, now: datetime) -> PriceStats:
    since = now - timedelta(days=GOOD_PRICE_WINDOW_DAYS)
    row = (
        await session.execute(
            select(
                func.count(PricePoint.id),
                func.percentile_cont(0.5).within_group(PricePoint.price),
                func.percentile_cont(0.2).within_group(PricePoint.price),
            ).where(PricePoint.watch_key_id == key_id, PricePoint.observed_at >= since)
        )
    ).one()
    count, median, p20 = row
    if not count:
        return EMPTY_STATS
    return PriceStats(
        int(count),
        Decimal(str(round(median, 2))) if median is not None else None,
        Decimal(str(round(p20, 2))) if p20 is not None else None,
    )


async def key_price_stats(session: AsyncSession, key: WatchKey, now: datetime) -> PriceStats:
    """Stats for a key if it already exists in the database (empty for a new key). Does NOT create the key."""
    key_id = (
        await session.execute(
            select(WatchKeyRow.id).where(
                WatchKeyRow.origin == key.origin,
                WatchKeyRow.destination == key.destination,
                WatchKeyRow.date_mode == key.date_mode.value,
                WatchKeyRow.depart_date == key.depart_date,
                WatchKeyRow.return_date.is_(None)
                if key.return_date is None
                else WatchKeyRow.return_date == key.return_date,
                WatchKeyRow.direct_only == key.direct_only,
                WatchKeyRow.currency == key.currency,
            )
        )
    ).scalar_one_or_none()
    if key_id is None:
        return EMPTY_STATS
    return await load_price_stats(session, key_id, now)
