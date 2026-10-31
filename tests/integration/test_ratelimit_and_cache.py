import asyncio
import time
from decimal import Decimal

import pytest

from flightbot.providers.base import PriceQuote, ProviderError
from flightbot.providers.wrappers import CachedProvider, RateLimitedProvider
from flightbot.ratelimit import RateLimitTimeout, TokenBucket
from tests.helpers import ScriptedProvider, key, today


async def test_bucket_allows_burst_then_throttles(redis):
    b = TokenBucket(redis)
    waits = [await b.acquire("t1", rate=2, capacity=3) for _ in range(5)]
    assert waits[:3] == [0, 0, 0]
    assert waits[3] > 0 and waits[4] > 0


async def test_bucket_refills_over_time(redis):
    b = TokenBucket(redis)
    for _ in range(2):
        await b.acquire("t2", rate=20, capacity=2)
    assert await b.acquire("t2", rate=20, capacity=2) > 0
    await asyncio.sleep(0.12)
    assert await b.acquire("t2", rate=20, capacity=2) == 0


async def test_wait_blocks_until_token_available(redis):
    b = TokenBucket(redis)
    await b.acquire("t3", rate=10, capacity=1)
    t0 = time.monotonic()
    await b.wait("t3", rate=10, capacity=1)
    assert 0.05 < time.monotonic() - t0 < 0.5


async def test_wait_raises_when_wait_exceeds_max(redis):
    b = TokenBucket(redis)
    await b.acquire("t4", rate=0.1, capacity=1)
    with pytest.raises(RateLimitTimeout):
        await b.wait("t4", rate=0.1, capacity=1, max_wait=0.5)


async def test_bucket_is_shared_across_instances(redis):
    """Fərqli proses/replikalar eyni bucket-ı paylaşır (əvvəlki in-process limiter problemi)."""
    b1, b2 = TokenBucket(redis), TokenBucket(redis)
    assert await b1.acquire("shared", rate=1, capacity=1) == 0
    assert await b2.acquire("shared", rate=1, capacity=1) > 0


async def test_bucket_total_throughput_across_concurrent_workers(redis):
    b = TokenBucket(redis)
    granted = 0

    async def worker():
        nonlocal granted
        for _ in range(20):
            if await b.acquire("burst", rate=5, capacity=5) == 0:
                granted += 1

    await asyncio.gather(*(worker() for _ in range(5)))  # 100 cəhd
    assert granted == 5  # yalnız capacity qədər keçir


class SlowCountingProvider(ScriptedProvider):
    async def offers(self, k, *, limit=30, fresh=False):
        await asyncio.sleep(0.3)
        return await super().offers(k, limit=limit, fresh=fresh)


async def test_cache_hit_avoids_second_provider_call(redis):
    inner = ScriptedProvider(100)
    cp = CachedProvider(inner, redis, today_fn=today)
    k = key()
    a, b = await cp.offers(k), await cp.offers(k)
    assert inner.calls == 1 and a == b


async def test_fresh_bypasses_cache_and_updates_it(redis):
    inner = ScriptedProvider(100, 80)
    cp = CachedProvider(inner, redis, today_fn=today)
    k = key()
    await cp.offers(k)
    fresh = await cp.offers(k, fresh=True)
    assert inner.calls == 2 and fresh[0].price == Decimal("80")
    assert (await cp.offers(k))[0].price == Decimal("80")  # keş yeniləndi


async def test_concurrent_requests_are_coalesced_into_one_call(redis):
    """Singleflight: 10 paralel sorğu = 1 provayder sorğusu (keş stampede mühafizəsi)."""
    inner = SlowCountingProvider(100)
    cp = CachedProvider(inner, redis, today_fn=today)
    k = key()
    results = await asyncio.gather(*(cp.offers(k) for _ in range(10)))
    assert inner.calls == 1
    assert all(r[0].price == Decimal("100") for r in results)


async def test_lock_timeout_never_raises_and_falls_back_to_own_fetch(redis):
    """Əvvəlki dizayndakı LockError problemi: kilid tutulubsa və keş dolmursa, xəta yox, fallback."""
    inner = ScriptedProvider(100)
    cp = CachedProvider(inner, redis, today_fn=today, wait_for_peer_s=0.4)
    k = key()
    await redis.set(f"lock:quote:{k.cache_id()}", "someone-else", px=5000)  # ölü kilid
    out = await cp.offers(k)
    assert out[0].price == Decimal("100") and inner.calls == 1
    # başqasının kilidi silinməməlidir (token yoxlaması)
    assert await redis.get(f"lock:quote:{k.cache_id()}") == b"someone-else"


async def test_empty_result_is_negatively_cached_briefly(redis):
    inner = ScriptedProvider(None)
    cp = CachedProvider(inner, redis, today_fn=today)
    k = key()
    assert await cp.offers(k) == [] and await cp.offers(k) == []
    assert inner.calls == 1
    ttl = await redis.ttl(f"quote:{k.cache_id()}")
    assert 0 < ttl <= 600


async def test_provider_error_is_not_cached_and_lock_released(redis):
    inner = ScriptedProvider(ProviderError("boom"), 100)
    cp = CachedProvider(inner, redis, today_fn=today)
    k = key()
    with pytest.raises(ProviderError):
        await cp.offers(k)
    assert await redis.get(f"lock:quote:{k.cache_id()}") is None
    assert (await cp.offers(k))[0].price == Decimal("100")


async def test_rate_limited_provider_waits_for_shared_bucket(redis):
    inner = ScriptedProvider(100)
    rl = RateLimitedProvider(inner, TokenBucket(redis), rps=20)
    k = key()
    t0 = time.monotonic()
    await asyncio.gather(*(rl.offers(k) for _ in range(6)))  # capacity 20 -> hamısı dərhal
    assert time.monotonic() - t0 < 0.5 and inner.calls == 6
    assert isinstance(PriceQuote, type)
