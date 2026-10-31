"""Poller: vaxtı çatmış watch_key-ləri götürür (SKIP LOCKED lease), provayderə 1 sorğu göndərir,
bütün abunəçilər üçün alert qərarını verir və bildirişləri OUTBOX-a yazır (eyni transaksiyada).

Heç vaxt birbaşa Telegram-a yazmır. Çatdırılma broadcaster-in işidir.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flightbot import metrics
from flightbot.config import Settings
from flightbot.core.alert_engine import AlertInput, Verdict, decide
from flightbot.core.clock import utcnow
from flightbot.core.plans import effective_plan, limits_for
from flightbot.core.pricing import (
    PriceStats,
    is_anomalous_low,
    is_good_price,
    trend,
    vs_median_pct,
)
from flightbot.core.quiet import deliver_after
from flightbot.core.schedule import failure_backoff, next_check_delay
from flightbot.core.stats import load_price_stats
from flightbot.core.watch_key import DateMode, WatchKey
from flightbot.db.models import Notification, PricePoint, User, Watch
from flightbot.logging import get_logger
from flightbot.providers.base import (
    PriceProvider,
    PriceQuote,
    ProviderError,
    ProviderRateLimited,
    cheapest,
)

log = get_logger(__name__)

POINT_DEDUP_WINDOW = timedelta(hours=12)

_CLAIM_SQL = text(
    """
    WITH due AS (
        SELECT id FROM watch_keys
        WHERE active_watch_count > 0
          AND next_check_at <= now()
          AND (lease_until IS NULL OR lease_until < now())
        ORDER BY next_check_at
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE watch_keys wk
    SET lease_until = now() + make_interval(secs => CAST(:lease AS double precision))
    FROM due
    WHERE wk.id = due.id
    RETURNING wk.id, wk.origin, wk.destination, wk.date_mode, wk.depart_date, wk.return_date,
              wk.direct_only, wk.currency, wk.consecutive_failures
    """
)


@dataclass(slots=True)
class ClaimedKey:
    id: int
    key: WatchKey
    consecutive_failures: int


async def claim_due_keys(session: AsyncSession, *, limit: int, lease_s: int) -> list[ClaimedKey]:
    rows = (await session.execute(_CLAIM_SQL, {"limit": limit, "lease": lease_s})).all()
    return [
        ClaimedKey(
            id=r.id,
            key=WatchKey(
                origin=r.origin,
                destination=r.destination,
                date_mode=DateMode(r.date_mode),
                depart_date=r.depart_date,
                return_date=r.return_date,
                direct_only=r.direct_only,
                currency=r.currency,
            ),
            consecutive_failures=r.consecutive_failures,
        )
        for r in rows
    ]


def build_payload(
    *,
    key: WatchKey,
    quote: PriceQuote,
    target: Decimal,
    stats: PriceStats,
    previous_price: Decimal | None,
    watch_id: int | None = None,
) -> dict[str, Any]:
    return {
        "watch_id": watch_id,
        "origin": key.origin,
        "destination": key.destination,
        "date_mode": key.date_mode.value,
        "window_start": key.window_start.isoformat(),
        "currency": quote.currency,
        "price": str(quote.price),
        "depart_date": quote.depart_date.isoformat(),
        "return_date": quote.return_date.isoformat() if quote.return_date else None,
        "airline": quote.airline,
        "transfers": quote.transfers,
        "link": quote.link,
        "provider": quote.provider,
        "found_at": quote.found_at.isoformat() if quote.found_at else None,
        "target_price": str(target),
        "good_price": is_good_price(quote.price, stats),
        "median": str(stats.median) if stats.median is not None else None,
        "vs_median_pct": vs_median_pct(quote.price, stats),
        "trend": trend(quote.price, previous_price),
        "previous_price": str(previous_price) if previous_price is not None else None,
    }


class Poller:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        provider: PriceProvider,
        settings: Settings,
        *,
        clock=utcnow,
    ) -> None:
        self._sm = sessionmaker
        self._provider = provider
        self._settings = settings
        self._clock = clock
        self._sem = asyncio.Semaphore(settings.poller_concurrency)

    # ------------------------------------------------------------------ döngü
    async def run_once(self) -> int:
        async with self._sm.begin() as s:
            claimed = await claim_due_keys(
                s, limit=self._settings.poller_batch, lease_s=self._settings.poller_lease_s
            )
        if claimed:
            await asyncio.gather(*(self._guarded(c) for c in claimed))
        return len(claimed)

    async def refresh_metrics(self) -> None:
        """Vaxtı çatmış (geridə qalmış) açar sayı: poller ayaq tutmursa bu rəqəm artır."""
        async with self._sm() as s:
            due = await s.execute(
                text(
                    "SELECT count(*) FROM watch_keys WHERE active_watch_count > 0 AND next_check_at <= now()"
                )
            )
        metrics.DUE_KEYS.set(int(due.scalar() or 0))

    async def run_forever(self, stop: asyncio.Event) -> None:
        log.info("poller_started")
        while not stop.is_set():
            try:
                await self.refresh_metrics()
                processed = await self.run_once()
            except Exception:
                log.exception("poller_loop_error")
                processed = 0
                await _sleep(stop, 5.0)
            if processed == 0:
                await _sleep(stop, self._settings.poller_idle_s)
        log.info("poller_stopped")

    async def _guarded(self, c: ClaimedKey) -> None:
        async with self._sem:
            await self.process(c)

    # ----------------------------------------------------------------- emal
    async def process(self, c: ClaimedKey) -> None:
        started = time.monotonic()
        try:
            outcome = await self._process_inner(c, self._clock())
            metrics.POLLED_KEYS.labels(outcome).inc()
        except ProviderRateLimited as exc:
            await self._release(c.id, delay=timedelta(seconds=max(exc.retry_after, 30)), failure=False)
            metrics.POLLED_KEYS.labels("rate_limited").inc()
        except RedisError as exc:
            # Rate limiter/keş (Redis) əlçatmazdır: açarın günahı deyil, uğursuzluq sayğacını şişirmə
            await self._release(c.id, delay=timedelta(seconds=60), failure=False)
            log.error("poll_redis_error", key_id=c.id, error=repr(exc))
            metrics.POLLED_KEYS.labels("redis_error").inc()
        except ProviderError as exc:
            delay = failure_backoff(c.consecutive_failures + 1)
            await self._release(c.id, delay=delay, failure=True)
            log.warning("poll_provider_error", key_id=c.id, error=str(exc), retry_in_s=delay.seconds)
            metrics.POLLED_KEYS.labels("provider_error").inc()
        except Exception:
            delay = failure_backoff(c.consecutive_failures + 1)
            await self._release(c.id, delay=delay, failure=True)
            log.exception("poll_unexpected_error", key_id=c.id)
            metrics.POLLED_KEYS.labels("error").inc()
        finally:
            metrics.POLL_DURATION.observe(time.monotonic() - started)

    async def _process_inner(self, c: ClaimedKey, now: datetime) -> str:
        quote = await cheapest(self._provider, c.key)
        async with self._sm() as s:
            stats = await load_price_stats(s, c.id, now)

        confirmed = False
        if quote is not None and is_anomalous_low(quote.price, stats):
            # Şübhəli dərəcədə ucuz: keşi keçib ikinci müstəqil sorğu ilə təsdiqlə
            second = await cheapest(self._provider, c.key, fresh=True)
            if second is not None:
                quote = second
                confirmed = is_anomalous_low(second.price, stats)

        async with self._sm.begin() as s:
            await self._apply(s, c, quote, stats, confirmed, now)
        return "ok" if quote is not None else "no_offers"

    async def _apply(
        self,
        s: AsyncSession,
        c: ClaimedKey,
        quote: PriceQuote | None,
        stats: PriceStats,
        confirmed: bool,
        now: datetime,
    ) -> None:
        if quote is None:
            await self._finish_key(s, c, now, price=None)
            return

        unconfirmed_anomaly = is_anomalous_low(quote.price, stats) and not confirmed
        previous_price = await self._last_point_price(s, c.id)
        if not unconfirmed_anomaly:
            await self._record_point(s, c.id, quote, now)

        await self._evaluate_watchers(s, c, quote, stats, confirmed, previous_price, now)
        await self._finish_key(s, c, now, price=None if unconfirmed_anomaly else quote.price)

    # ------------------------------------------------------------ tarixçə
    async def _last_point_price(self, s: AsyncSession, key_id: int) -> Decimal | None:
        row = (
            await s.execute(
                select(PricePoint.price)
                .where(PricePoint.watch_key_id == key_id)
                .order_by(PricePoint.observed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row

    async def _record_point(self, s: AsyncSession, key_id: int, q: PriceQuote, now: datetime) -> None:
        last = (
            await s.execute(
                select(PricePoint.price, PricePoint.depart_date, PricePoint.observed_at)
                .where(PricePoint.watch_key_id == key_id)
                .order_by(PricePoint.observed_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if (
            last is not None
            and last.price == q.price
            and last.depart_date == q.depart_date
            and now - last.observed_at < POINT_DEDUP_WINDOW
        ):
            return  # dəyişməyib: tarixçəni şişirtmə
        s.add(
            PricePoint(
                watch_key_id=key_id,
                observed_at=now,
                price=q.price,
                currency=q.currency,
                depart_date=q.depart_date,
                return_date=q.return_date,
                airline=q.airline,
                transfers=q.transfers,
                link=q.link,
                found_at=q.found_at,
                provider=q.provider,
            )
        )

    # ---------------------------------------------------------- abunəçilər
    async def _evaluate_watchers(
        self,
        s: AsyncSession,
        c: ClaimedKey,
        quote: PriceQuote,
        stats: PriceStats,
        confirmed: bool,
        previous_price: Decimal | None,
        now: datetime,
    ) -> None:
        rows = (
            await s.execute(
                select(Watch, User.plan, User.plan_expires_at, User.quiet_hours)
                .join(User, User.id == Watch.user_id)
                .where(
                    Watch.watch_key_id == c.id,
                    Watch.status == "active",
                    User.is_blocked.is_(False),
                    # yalnız hədəfi ödəyənlər və re-arm gözləyənlər
                    or_(Watch.target_price >= quote.price, Watch.armed.is_(False)),
                )
                .with_for_update(of=Watch, skip_locked=True)
            )
        ).all()
        if not rows:
            return

        user_ids = {w.user_id for w, _, _, _ in rows}
        # Gündəlik limit race-i: eyni istifadəçinin FƏRQLİ açarları paralel yoxlananda hər tranzaksiya
        # sayğacı ayrıca görür və limit aşılır. İstifadəçi sətirlərini ID sırası ilə (deadlock yoxdur)
        # kilidləyirik: ikinci tranzaksiya birincinin commit-ini gözləyir və artıq yazılmış bildirişləri görür.
        # key_share=True -> FOR NO KEY UPDATE: bildiriş INSERT-lərinin FK yoxlamasını bloklamır.
        await s.execute(
            select(User.id).where(User.id.in_(user_ids)).order_by(User.id).with_for_update(key_share=True)
        )
        sent = await self._sent_last_24h(s, user_ids, now)

        for watch, plan, plan_expires_at, quiet_hours in rows:
            eff_plan = effective_plan(plan, plan_expires_at, now)
            decision = decide(
                AlertInput(
                    now=now,
                    price=quote.price,
                    target_price=watch.target_price,
                    armed=watch.armed,
                    last_notified_price=watch.last_notified_price,
                    last_notified_at=watch.last_notified_at,
                    notifications_last_24h=sent.get(watch.user_id, 0),
                    daily_limit=limits_for(eff_plan).daily_notifications,
                    stats=stats,
                    found_at=quote.found_at,
                    confirmed=confirmed,
                )
            )
            metrics.ALERT_DECISIONS.labels(decision.verdict.value).inc()

            if decision.rearm:
                watch.armed = True
                watch.last_notified_price = None

            if decision.verdict is not Verdict.NOTIFY:
                continue

            dedup_key = f"w{watch.id}:{quote.price}:{now:%Y%m%d}"
            # Sakit saatlarda bildiriş outbox-a yazılır, amma səhərə qədər göndərilmir
            available_at = (
                deliver_after(
                    now,
                    tz=self._settings.quiet_tz,
                    start_hour=self._settings.quiet_start_hour,
                    end_hour=self._settings.quiet_end_hour,
                )
                if quiet_hours
                else now
            )
            result = await s.execute(
                pg_insert(Notification)
                .values(
                    user_id=watch.user_id,
                    watch_id=watch.id,
                    dedup_key=dedup_key,
                    priority=0 if eff_plan == "pro" else 1,
                    available_at=available_at,
                    payload=build_payload(
                        key=c.key,
                        quote=quote,
                        target=watch.target_price,
                        stats=stats,
                        previous_price=previous_price,
                        watch_id=watch.id,
                    ),
                )
                .on_conflict_do_nothing(constraint="uq_notifications_dedup_key")
            )
            if result.rowcount:  # dublikat deyilsə state-i yenilə
                watch.armed = False
                watch.last_notified_price = quote.price
                watch.last_notified_at = now
                sent[watch.user_id] = sent.get(watch.user_id, 0) + 1

    async def _sent_last_24h(self, s: AsyncSession, user_ids: set[int], now: datetime) -> dict[int, int]:
        rows = await s.execute(
            select(Notification.user_id, func.count(Notification.id))
            .where(
                Notification.user_id.in_(user_ids),
                Notification.created_at > now - timedelta(hours=24),
                Notification.status.in_(("pending", "sending", "sent")),
            )
            .group_by(Notification.user_id)
        )
        return {uid: int(n) for uid, n in rows.all()}

    # ------------------------------------------------------ açarın bağlanması
    async def _has_pro_watcher(self, s: AsyncSession, key_id: int, now: datetime) -> bool:
        row = await s.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM watches w JOIN users u ON u.id = w.user_id "
                "WHERE w.watch_key_id = :k AND w.status = 'active' AND u.plan = 'pro' "
                "AND (u.plan_expires_at IS NULL OR u.plan_expires_at > :now))"
            ),
            {"k": key_id, "now": now},
        )
        return bool(row.scalar())

    async def _finish_key(
        self, s: AsyncSession, c: ClaimedKey, now: datetime, *, price: Decimal | None
    ) -> None:
        has_pro = await self._has_pro_watcher(s, c.id, now)
        delay = next_check_delay(c.key.horizon_days(_today(now)), has_pro)
        await s.execute(
            text(
                "UPDATE watch_keys SET last_checked_at = :now, next_check_at = :next, "
                "lease_until = NULL, consecutive_failures = 0, "
                "last_price = COALESCE(:price, last_price) WHERE id = :id"
            ),
            {"now": now, "next": now + delay, "price": price, "id": c.id},
        )

    async def _release(self, key_id: int, *, delay: timedelta, failure: bool) -> None:
        now = self._clock()
        async with self._sm.begin() as s:
            await s.execute(
                text(
                    "UPDATE watch_keys SET lease_until = NULL, last_checked_at = :now, "
                    "next_check_at = :next, "
                    "consecutive_failures = CASE WHEN :failure THEN consecutive_failures + 1 "
                    "ELSE consecutive_failures END WHERE id = :id"
                ),
                {"now": now, "next": now + delay, "failure": failure, "id": key_id},
            )


def _today(now: datetime) -> date:
    return now.date()


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
