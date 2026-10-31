"""Housekeeping: expired watches, counter drift check, purging old data."""

import asyncio
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flightbot import metrics
from flightbot.logging import get_logger

log = get_logger(__name__)

NOTIFICATION_RETENTION_DAYS = 30
PRICE_POINT_RETENTION_DAYS = 400


async def expire_past_watches(s: AsyncSession, today: date) -> int:
    res = await s.execute(
        text(
            "UPDATE watches w SET status = 'expired', pause_reason = NULL, updated_at = now() "
            "FROM watch_keys k WHERE w.watch_key_id = k.id "
            "AND w.status IN ('active', 'paused') AND k.expires_on < :today"
        ),
        {"today": today},
    )
    return res.rowcount or 0


async def reconcile_counts(s: AsyncSession) -> int:
    """The trigger should never be wrong, but as extra insurance: fix any drift and record it in the metrics."""
    res = await s.execute(
        text(
            """
            WITH actual AS (
                SELECT k.id, COALESCE(count(w.id) FILTER (WHERE w.status = 'active'), 0) AS c
                FROM watch_keys k LEFT JOIN watches w ON w.watch_key_id = k.id
                GROUP BY k.id
            )
            UPDATE watch_keys k SET active_watch_count = a.c
            FROM actual a WHERE k.id = a.id AND k.active_watch_count <> a.c
            """
        )
    )
    fixed = res.rowcount or 0
    if fixed:
        metrics.COUNT_DRIFT.inc(fixed)
        log.error("active_watch_count_drift_fixed", rows=fixed)
    return fixed


async def purge_old(s: AsyncSession, today: date) -> dict[str, int]:
    n = await s.execute(
        text(
            "DELETE FROM notifications WHERE status IN ('sent','failed','skipped') "
            "AND created_at < now() - make_interval(days => :d)"
        ),
        {"d": NOTIFICATION_RETENTION_DAYS},
    )
    p = await s.execute(
        text("DELETE FROM price_points WHERE observed_at < now() - make_interval(days => :d)"),
        {"d": PRICE_POINT_RETENTION_DAYS},
    )
    k = await s.execute(
        text(
            "DELETE FROM watch_keys k WHERE k.active_watch_count = 0 AND k.expires_on < :today "
            "AND NOT EXISTS (SELECT 1 FROM watches w WHERE w.watch_key_id = k.id)"
        ),
        {"today": today},
    )
    return {
        "notifications": n.rowcount or 0,
        "price_points": p.rowcount or 0,
        "watch_keys": k.rowcount or 0,
    }


async def run_janitor_once(sessionmaker: async_sessionmaker[AsyncSession], today: date) -> dict[str, int]:
    async with sessionmaker.begin() as s:
        expired = await expire_past_watches(s, today)
        drift = await reconcile_counts(s)
        purged = await purge_old(s, today)
    result = {"expired": expired, "drift_fixed": drift, **purged}
    log.info("janitor_done", **result)
    return result


async def run_forever(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event, interval_s: int, today_fn
) -> None:
    log.info("janitor_started")
    while not stop.is_set():
        try:
            await run_janitor_once(sessionmaker, today_fn())
        except Exception:
            log.exception("janitor_error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            pass
    log.info("janitor_stopped")
