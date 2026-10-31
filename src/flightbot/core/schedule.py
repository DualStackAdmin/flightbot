"""Check frequency and cache TTL. All values are tunable tables.

Free: ~3-24 hours (depending on time to departure), Pro: ~1-6 hours.
Note: the Travelpayouts Data API serves cached data, so checking more often than hourly is pointless.
"""

import random
from datetime import timedelta

H = 3600

# (max days to departure, interval in seconds)
FREE_TIERS: tuple[tuple[int, int], ...] = ((7, 3 * H), (30, 6 * H), (90, 12 * H), (10_000, 24 * H))
PRO_TIERS: tuple[tuple[int, int], ...] = ((30, 1 * H), (90, 3 * H), (10_000, 6 * H))

# Provider cache (for user-initiated /search and repeated requests)
CACHE_TIERS: tuple[tuple[int, int], ...] = ((3, 300), (14, 1200), (60, 3600), (10_000, 14_400))

JITTER = 0.10
MAX_BACKOFF_S = 6 * H
BASE_BACKOFF_S = 5 * 60


def _pick(tiers: tuple[tuple[int, int], ...], horizon_days: int) -> int:
    for max_days, seconds in tiers:
        if horizon_days <= max_days:
            return seconds
    return tiers[-1][1]


def _jitter(seconds: float, rng: random.Random | None) -> float:
    r = rng or random
    return seconds * (1 + r.uniform(-JITTER, JITTER))


def check_interval(horizon_days: int, has_pro_watcher: bool) -> timedelta:
    tiers = PRO_TIERS if has_pro_watcher else FREE_TIERS
    return timedelta(seconds=_pick(tiers, horizon_days))


def next_check_delay(horizon_days: int, has_pro_watcher: bool, rng: random.Random | None = None) -> timedelta:
    """±10% jitter: keys created at the same moment must not be checked in the same second (thundering herd)."""
    base = check_interval(horizon_days, has_pro_watcher).total_seconds()
    return timedelta(seconds=_jitter(base, rng))


def failure_backoff(consecutive_failures: int, rng: random.Random | None = None) -> timedelta:
    n = max(1, consecutive_failures)
    seconds = min(BASE_BACKOFF_S * (2 ** (n - 1)), MAX_BACKOFF_S)
    return timedelta(seconds=_jitter(seconds, rng))


def cache_ttl_seconds(horizon_days: int, rng: random.Random | None = None) -> int:
    return max(30, int(_jitter(_pick(CACHE_TIERS, horizon_days), rng)))
