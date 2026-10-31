import random
from datetime import timedelta

from flightbot.core import schedule as sch


def test_free_intervals_grow_with_horizon():
    d = [sch.check_interval(h, False) for h in (1, 20, 60, 200)]
    assert d == sorted(d) and d[0] == timedelta(hours=3) and d[-1] == timedelta(hours=24)


def test_pro_is_always_at_least_as_fast_as_free():
    for h in (0, 5, 29, 31, 89, 91, 300):
        assert sch.check_interval(h, True) <= sch.check_interval(h, False)


def test_pro_near_term_is_hourly():
    assert sch.check_interval(10, True) == timedelta(hours=1)


def test_jitter_within_ten_percent():
    rng = random.Random(1)
    base = sch.check_interval(10, False).total_seconds()
    for _ in range(200):
        s = sch.next_check_delay(10, False, rng).total_seconds()
        assert base * 0.9 <= s <= base * 1.1


def test_jitter_actually_spreads_values():
    rng = random.Random(2)
    values = {round(sch.next_check_delay(10, False, rng).total_seconds()) for _ in range(50)}
    assert len(values) > 10  # eyni anda yaranan açarlar eyni saniyədə yoxlanmır


def test_failure_backoff_exponential_and_capped():
    rng = random.Random(3)
    b = [sch.failure_backoff(n, rng).total_seconds() for n in (1, 2, 3, 20)]
    assert b[0] < b[1] < b[2]
    assert b[3] <= sch.MAX_BACKOFF_S * 1.1


def test_cache_ttl_tiers():
    rng = random.Random(4)
    assert 270 <= sch.cache_ttl_seconds(1, rng) <= 330
    assert 1080 <= sch.cache_ttl_seconds(10, rng) <= 1320
    assert 12_960 <= sch.cache_ttl_seconds(100, rng) <= 15_840
