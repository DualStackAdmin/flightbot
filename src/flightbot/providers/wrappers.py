"""Provayder sarğıları: paylanmış rate limit + Redis keşi + singleflight.

Əvvəlki dizayndakı problem: `async with redis.lock(...) as acquired` bool qaytarmır və
blocking_timeout bitəndə LockError atır. Burada SET NX + gözləmə + fallback işlədilir:
kilidi tuta bilməyən sorğu keşin dolmasını gözləyir, dolmasa özü sorğu göndərir (heç vaxt xəta atmır).
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
FETCH_LIMIT = 30  # keş həmişə eyni limitlə doldurulur ki, açar sadə qalsın
EXPLORE_TTL_S = 3600  # "hər yerə" nəticəsi bir saat keşlənir (istifadəçi tərəfindən başladılan sorğu)
EXPLORE_FETCH_LIMIT = 40


class RateLimitedProvider:
    """Replikalar arası paylaşılan provayder RPS limiti."""

    def __init__(self, inner: PriceProvider, bucket: TokenBucket, *, rps: float) -> None:
        self._inner = inner
        self._bucket = bucket
        self._rps = rps
        self.name = inner.name

    async def _wait(self) -> None:
        await self._bucket.wait(
            f"provider:{self.name}", rate=self._rps, capacity=max(1.0, self._rps), max_wait=120.0
        )

    async def offers(self, key: WatchKey, *, limit: int = 30, fresh: bool = False) -> list[PriceQuote]:
        await self._wait()
        return await self._inner.offers(key, limit=limit, fresh=fresh)

    async def explore(self, **kwargs) -> list[PriceQuote]:
        await self._wait()
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
            ttl = min(ttl, NEGATIVE_TTL_CAP_S)  # boş nəticəni qısa saxla
        await self._redis.set(ck, orjson.dumps([quote_to_json(q) for q in quotes]), ex=ttl)

    async def _cached(
        self,
        ck: str,
        ttl: int,
        fetch: Callable[[], Awaitable[list[PriceQuote]]],
        *,
        fresh: bool,
    ) -> list[PriceQuote]:
        """Keş + singleflight: eyni açar üçün paralel sorğular 1 provayder sorğusuna birləşir."""
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
            # Başqası artıq sorğu göndərir: keşin dolmasını gözlə
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._wait
            while loop.time() < deadline:
                await asyncio.sleep(0.2)
                hit = await self._get(ck)
                if hit is not None:
                    metrics.PROVIDER_CACHE.labels("coalesced").inc()
                    return hit
            # gözləmə bitdi: özümüz sorğu göndəririk (xəta atmırıq)
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
    ) -> list[PriceQuote]:
        ck = f"explore:{origin}:{month:%Y-%m}:{currency}:{int(direct_only)}"
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
            ),
            fresh=fresh,
        )
        return quotes[:limit]
