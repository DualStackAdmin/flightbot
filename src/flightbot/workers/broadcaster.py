"""Broadcaster: takes notifications from the outbox (priority: Pro first) and sends them while respecting
Telegram limits.

- The global limit (25 msg/s) and 1 msg/s per user live in a Redis token bucket, shared across replicas.
- RetryAfter: a global pause for all replicas (a Redis key) + the message is returned to the queue.
- Forbidden / chat not found: the user counts as blocked and their watches are frozen.
- Delivery is "at-least-once": if a worker crashes after sending but before writing the status,
  the message may be re-sent once the lease expires (rare; the window is milliseconds).
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import LinkPreviewOptions
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flightbot import metrics
from flightbot.bot.render import render_notification
from flightbot.config import Settings
from flightbot.core.clock import utcnow
from flightbot.core.users import mark_blocked
from flightbot.db.models import User
from flightbot.logging import get_logger
from flightbot.ratelimit import RateLimitTimeout, TokenBucket

log = get_logger(__name__)

PAUSE_KEY = "tg:pause_until"
_BLOCKED_HINTS = ("chat not found", "user is deactivated", "bot was blocked", "peer_id_invalid")

_CLAIM_SQL = text(
    """
    WITH due AS (
        SELECT id FROM notifications
        WHERE (status = 'pending' AND available_at <= now())
           OR (status = 'sending' AND lease_until < now())
        ORDER BY priority, available_at, id
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE notifications n
    SET status = 'sending',
        attempts = n.attempts + 1,
        lease_until = now() + make_interval(secs => CAST(:lease AS double precision))
    FROM due
    WHERE n.id = due.id
    RETURNING n.id, n.user_id, n.payload, n.attempts
    """
)


@dataclass(slots=True)
class Outgoing:
    id: int
    user_id: int
    chat_id: int
    language: str
    payload: dict[str, Any]
    attempts: int


def retry_backoff_seconds(attempts: int) -> float:
    return float(min(30 * (2 ** max(0, attempts - 1)), 1800))


class Broadcaster:
    def __init__(
        self,
        bot,
        sessionmaker: async_sessionmaker[AsyncSession],
        redis: Redis,
        settings: Settings,
        *,
        marker: str = "",
        clock=utcnow,
    ) -> None:
        self._bot = bot
        self._sm = sessionmaker
        self._redis = redis
        self._bucket = TokenBucket(redis)
        self._settings = settings
        self._marker = marker
        self._clock = clock
        self._sem = asyncio.Semaphore(settings.broadcaster_concurrency)

    # ------------------------------------------------------------------ loop
    async def run_once(self) -> int:
        outgoing = await self.claim()
        if outgoing:
            await asyncio.gather(*(self._guarded(n) for n in outgoing))
        return len(outgoing)

    async def run_forever(self, stop: asyncio.Event) -> None:
        log.info("broadcaster_started")
        while not stop.is_set():
            try:
                processed = await self.run_once()
                await self.refresh_metrics()
            except Exception:
                log.exception("broadcaster_loop_error")
                processed = 0
                await _sleep(stop, 5.0)
            if processed == 0:
                await _sleep(stop, self._settings.broadcaster_idle_s)
        log.info("broadcaster_stopped")

    async def _guarded(self, n: Outgoing) -> None:
        async with self._sem:
            try:
                await self.deliver(n)
            except Exception:
                log.exception("deliver_unexpected_error", notification_id=n.id)
                await self._fail_or_retry(n, "unexpected")

    # ------------------------------------------------------------------ claim
    # Invariant: all exit transitions are allowed only from the 'sending' state (WHERE status='sending').
    # If another worker/process has already changed the row (skipped/sent), a late write does not corrupt it.
    async def claim(self) -> list[Outgoing]:
        async with self._sm.begin() as s:
            rows = (
                await s.execute(
                    _CLAIM_SQL,
                    {
                        "limit": self._settings.broadcaster_batch,
                        "lease": self._settings.broadcaster_lease_s,
                    },
                )
            ).all()
            if not rows:
                return []
            users = {
                u.id: u
                for u in (
                    await s.execute(
                        select(User.id, User.telegram_id, User.language, User.is_blocked).where(
                            User.id.in_({r.user_id for r in rows})
                        )
                    )
                ).all()
            }
        out: list[Outgoing] = []
        for r in rows:
            u = users.get(r.user_id)
            if u is None or u.is_blocked:
                await self._finish(r.id, "skipped", error="user_blocked_or_missing")
                continue
            out.append(Outgoing(r.id, r.user_id, u.telegram_id, u.language, r.payload, r.attempts))
        return out

    # ---------------------------------------------------------------- delivery
    async def deliver(self, n: Outgoing) -> str:
        if n.attempts > self._settings.broadcaster_max_attempts:
            await self._finish(n.id, "failed", error="max_attempts_exceeded")
            return "failed"
        try:
            return await self._deliver(n)
        except RedisError as exc:
            # Redis is down: this is not the notification's fault. Put it back to waiting without burning an attempt,
            # so a long Redis outage doesn't turn notifications into 'failed'.
            metrics.TELEGRAM_ERRORS.labels("redis_down").inc()
            log.error("broadcaster_redis_error", notification_id=n.id, error=repr(exc))
            await self._reschedule(n.id, delay=10.0, undo_attempt=True)
            return "deferred"

    async def _deliver(self, n: Outgoing) -> str:

        now_ts = time.time()
        pause_raw = await self._redis.get(PAUSE_KEY)
        if pause_raw is not None and float(pause_raw) > now_ts:
            await self._reschedule(n.id, delay=float(pause_raw) - now_ts, undo_attempt=True)
            return "deferred"

        user_wait = await self._bucket.acquire(
            f"tg:user:{n.chat_id}", rate=self._settings.telegram_user_rps, capacity=1
        )
        if user_wait > 0:
            await self._reschedule(n.id, delay=user_wait, undo_attempt=True)
            return "deferred"

        rps = self._settings.telegram_global_rps
        try:
            await self._bucket.wait("tg:global", rate=rps, capacity=rps, max_wait=30.0)
        except RateLimitTimeout:
            await self._reschedule(n.id, delay=1.0, undo_attempt=True)
            return "deferred"

        text_, markup = render_notification(n.payload, n.language, marker=self._marker, notification_id=n.id)
        try:
            msg = await self._bot.send_message(
                chat_id=n.chat_id,
                text=text_,
                reply_markup=markup,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except TelegramRetryAfter as exc:
            metrics.TELEGRAM_ERRORS.labels("retry_after").inc()
            pause = float(exc.retry_after) + 1.0
            await self._redis.set(PAUSE_KEY, str(time.time() + pause), ex=int(pause) + 5)
            await self._reschedule(n.id, delay=pause, undo_attempt=True)
            log.warning("telegram_retry_after", seconds=exc.retry_after)
            return "deferred"
        except TelegramForbiddenError:
            metrics.TELEGRAM_ERRORS.labels("forbidden").inc()
            await self._block_user(n)
            return "blocked"
        except TelegramBadRequest as exc:
            metrics.TELEGRAM_ERRORS.labels("bad_request").inc()
            if any(h in str(exc).lower() for h in _BLOCKED_HINTS):
                await self._block_user(n)
                return "blocked"
            # Our side's mistake (e.g. invalid HTML): retrying is pointless
            log.error("telegram_bad_request", notification_id=n.id, error=str(exc))
            await self._finish(n.id, "failed", error=f"bad_request: {exc}"[:500])
            return "failed"
        except TelegramAPIError as exc:  # network / 5xx etc.
            metrics.TELEGRAM_ERRORS.labels("api_error").inc()
            return await self._fail_or_retry(n, repr(exc)[:500])

        await self._finish(n.id, "sent", message_id=msg.message_id)
        return "sent"

    # -------------------------------------------------------- state transitions
    async def _finish(
        self,
        notification_id: int,
        status: str,
        *,
        error: str | None = None,
        message_id: int | None = None,
    ) -> None:
        async with self._sm.begin() as s:
            await s.execute(
                text(
                    "UPDATE notifications SET status = :st, lease_until = NULL, last_error = :err, "
                    "telegram_message_id = COALESCE(:mid, telegram_message_id), "
                    "sent_at = CASE WHEN :is_sent THEN CAST(:now AS timestamptz) ELSE sent_at END "
                    "WHERE id = :id AND status = 'sending'"
                ),
                {
                    "st": status,
                    "is_sent": status
                    == "sent",  # separate parameter: asyncpg cannot infer 2 types for the same $n
                    "err": error,
                    "mid": message_id,
                    "now": self._clock(),
                    "id": notification_id,
                },
            )
        metrics.NOTIFICATIONS.labels(status).inc()

    async def _reschedule(self, notification_id: int, *, delay: float, undo_attempt: bool) -> None:
        async with self._sm.begin() as s:
            await s.execute(
                text(
                    "UPDATE notifications SET status = 'pending', lease_until = NULL, "
                    "available_at = now() + make_interval(secs => CAST(:d AS double precision)), "
                    "attempts = GREATEST(attempts - :undo, 0) WHERE id = :id AND status = 'sending'"
                ),
                {"d": max(delay, 0.0), "undo": 1 if undo_attempt else 0, "id": notification_id},
            )

    async def _fail_or_retry(self, n: Outgoing, error: str) -> str:
        if n.attempts >= self._settings.broadcaster_max_attempts:
            await self._finish(n.id, "failed", error=error)
            return "failed"
        async with self._sm.begin() as s:
            await s.execute(
                text(
                    "UPDATE notifications SET status = 'pending', lease_until = NULL, last_error = :err, "
                    "available_at = now() + make_interval(secs => CAST(:d AS double precision)) "
                    "WHERE id = :id AND status = 'sending'"
                ),
                {"err": error, "d": retry_backoff_seconds(n.attempts), "id": n.id},
            )
        return "retry"

    async def _block_user(self, n: Outgoing) -> None:
        log.info("user_blocked_bot", user_id=n.user_id)
        async with self._sm.begin() as s:
            await mark_blocked(s, n.user_id)
        # mark_blocked sets pending notifications to 'skipped'; the current one is included
        metrics.NOTIFICATIONS.labels("skipped").inc()

    # ------------------------------------------------------------------ metrika
    async def refresh_metrics(self) -> None:
        async with self._sm() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT count(*) AS depth, "
                        "COALESCE(EXTRACT(EPOCH FROM (now() - min(available_at))), 0) AS lag "
                        "FROM notifications WHERE status = 'pending' AND available_at <= now()"
                    )
                )
            ).one()
        metrics.QUEUE_DEPTH.set(int(row.depth))
        metrics.QUEUE_LAG.set(max(0.0, float(row.lag)))


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
