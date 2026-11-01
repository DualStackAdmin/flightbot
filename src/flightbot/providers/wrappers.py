"""Provider wrappers: distributed rate limit + Redis cache + singleflight.

The problem with the earlier design: `async with redis.lock(...) as acquired` doesn't return a bool and
raises LockError when blocking_timeout expires. Here SET NX + waiting + fallback is used:
a request that can't take the lock waits for the cache to fill and, if it doesn't, sends the request itself (never raises).
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import date

import orjson
from redis.asyncio import Redis

from flightbot import metrics
from flightbot.core.schedule import cache_ttl_seconds
from flightbot.core.watch_key import WatchKey
from flightbot.providers.base import PriceProvider, PriceQuote, quote_from_json, quote_to_json
from flightbot.ratelimit import TokenBucket

_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end
"""
NEGATIVE_TTL_CAP_S = 600
FETCH_LIMIT = 30  # the cache is always filled with the same limit so the key stays simple
EXPLORE_TTL_S = 3600  # the "anywhere" result is cached for one hour (a user-initiated request)
EXPLORE_FETCH_LIMIT = 40


class RateLimitedProvider:
    """Provider RPS limit shared across replicas."""

    def __init__(self, inner: PriceProvider, bucket: TokenBucket, *, rps: float) -> None:
        self._inner = inner
        self._bucket = bucket
        self._rps = rps
        self.name = inner.name

    async def _wait(self, cost: float = 1.0) -> None:
        await self._bucket.wait(
            f"provider:{self.name}",
            rate=self._rps,
            capacity=max(cost, self._rps),
            cost=cost,
            max_wait=120.0,
        )

    async def offers(self, key: WatchKey, *, limit: int = 30, fresh: bool = False) -> list[PriceQuote]:
        await self._wait(2.0 if key.has_stay else 1.0)  # stay-based round trips cost 2 requests
        return await self._inner.offers(key, limit=limit, fresh=fresh)

    async def explore(self, **kwargs) -> list[PriceQuote]:
        await self._wait(2.0 if kwargs.get("stay") else 1.0)
        return await self._inner.explore(**kwargs)


class CachedProvider:
    def __init__(
        self,
        inner: PriceProvider,
        redis: Redis,
        *,
        today_fn,
        lock_ttl_ms: int = 20_000,
        wait_for_peer_s: float = 5.0,
    ) -> None:
        self._inner = inner
        self._redis = redis
        self._today = today_fn
        self._lock_ttl_ms = lock_ttl_ms
        self._wait = wait_for_peer_s
        self._release = redis.register_script(_RELEASE_LUA)
        self.name = inner.name

    @staticmethod
    def _cache_key(key: WatchKey) -> str:
        return f"quote:{key.cache_id()}"

    async def _get(self, ck: str) -> list[PriceQuote] | None:
        raw = await self._redis.get(ck)
        if raw is None:
            return None
        return [quote_from_json(d) for d in orjson.loads(raw)]

    async def _set(self, ck: str, quotes: list[PriceQuote], ttl: int) -> None:
        if not quotes:
            ttl = min(ttl, NEGATIVE_TTL_CAP_S)  # keep an empty result short
        await self._redis.set(ck, orjson.dumps([quote_to_json(q) for q in quotes]), ex=ttl)

    async def _cached(
        self,
        ck: str,
        ttl: int,
        fetch: Callable[[], Awaitable[list[PriceQuote]]],
        *,
        fresh: bool,
    ) -> list[PriceQuote]:
        """Cache + singleflight: parallel requests for the same key collapse into one provider request."""
        if not fresh:
            hit = await self._get(ck)
            if hit is not None:
                metrics.PROVIDER_CACHE.labels("hit").inc()
                return hit
        metrics.PROVIDER_CACHE.labels("miss").inc()

        lock_key = f"lock:{ck}"
        token = uuid.uuid4().hex
        got_lock = bool(await self._redis.set(lock_key, token, nx=True, px=self._lock_ttl_ms))
        if not got_lock and not fresh:
            # Someone else is already requesting: wait for the cache to fill
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._wait
            while loop.time() < deadline:
                await asyncio.sleep(0.2)
                hit = await self._get(ck)
                if hit is not None:
                    metrics.PROVIDER_CACHE.labels("coalesced").inc()
                    return hit
            # the wait is over: we send the request ourselves (we don't raise)
        try:
            quotes = await fetch()
            await self._set(ck, quotes, ttl)
            return quotes
        finally:
            if got_lock:
                await self._release(keys=[lock_key], args=[token])

    async def offers(self, key: WatchKey, *, limit: int = 30, fresh: bool = False) -> list[PriceQuote]:
        ttl = cache_ttl_seconds(key.horizon_days(self._today()))
        quotes = await self._cached(
            self._cache_key(key),
            ttl,
            lambda: self._inner.offers(key, limit=FETCH_LIMIT, fresh=fresh),
            fresh=fresh,
        )
        return quotes[:limit]

    async def explore(
        self,
        *,
        origin: str,
        month: date,
        currency: str,
        direct_only: bool = False,
        limit: int = 20,
        fresh: bool = False,
        stay: tuple[int, int] | None = None,
    ) -> list[PriceQuote]:
        stay_id = f"{stay[0]}-{stay[1]}" if stay else "-"
        ck = f"explore:{origin}:{month:%Y-%m}:{currency}:{int(direct_only)}:{stay_id}"
        quotes = await self._cached(
            ck,
            EXPLORE_TTL_S,
            lambda: self._inner.explore(
                origin=origin,
                month=month,
                currency=currency,
                direct_only=direct_only,
                limit=EXPLORE_FETCH_LIMIT,
                fresh=fresh,
                stay=stay,
            ),
            fresh=fresh,
        )
        return quotes[:limit]
