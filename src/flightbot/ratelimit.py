"""Distributed Token Bucket in Redis.

The problem with the earlier design: `aiolimiter.AsyncLimiter` is in-process, so N replicas = N x the limit.
Here the bucket lives in Redis and the time comes from the Redis server (TIME), so clock skew between
replicas does not affect the result.
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
        """Returns 0.0 if a token is granted, otherwise the wait time in seconds (no token is consumed)."""
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
        """Waits until a token is granted."""
        waited = 0.0
        while True:
            w = await self.acquire(name, rate=rate, capacity=capacity, cost=cost)
            if w <= 0:
                return
            if waited + w > max_wait:
                raise RateLimitTimeout(f"{name}: {waited + w:.1f}s > {max_wait}s")
            await asyncio.sleep(w)
            waited += w
