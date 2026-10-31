"""Redis-də paylanmış Token Bucket.

Əvvəlki dizayndakı problem: `aiolimiter.AsyncLimiter` proses daxilidir, N replika = N x limit.
Burada bucket Redis-dədir və vaxt Redis serverindən (TIME) götürülür, ona görə replikalar
arasında saat sürüşməsi nəticəni pozmur.
"""

import asyncio

from redis.asyncio import Redis

_LUA = """
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now_ms
end
local delta = math.max(0, now_ms - ts)
tokens = math.min(capacity, tokens + delta * rate / 1000)
local wait_ms = 0
if tokens >= cost then
  tokens = tokens - cost
else
  wait_ms = math.ceil((cost - tokens) * 1000 / rate)
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now_ms))
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate * 1000) * 2 + 1000)
return wait_ms
"""


class RateLimitTimeout(Exception):
    pass


class TokenBucket:
    def __init__(self, redis: Redis, prefix: str = "rl") -> None:
        self._redis = redis
        self._prefix = prefix
        self._script = redis.register_script(_LUA)

    async def acquire(self, name: str, *, rate: float, capacity: float, cost: float = 1.0) -> float:
        """Token alırsa 0.0 qaytarır, əks halda gözləmə müddətini (saniyə) qaytarır (token sərf olunmur)."""
        wait_ms = await self._script(keys=[f"{self._prefix}:{name}"], args=[rate, capacity, cost])
        return int(wait_ms) / 1000.0

    async def wait(
        self,
        name: str,
        *,
        rate: float,
        capacity: float,
        cost: float = 1.0,
        max_wait: float = 30.0,
    ) -> None:
        """Token alınana qədər gözləyir."""
        waited = 0.0
        while True:
            w = await self.acquire(name, rate=rate, capacity=capacity, cost=cost)
            if w <= 0:
                return
            if waited + w > max_wait:
                raise RateLimitTimeout(f"{name}: {waited + w:.1f}s > {max_wait}s")
            await asyncio.sleep(w)
            waited += w
