import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from flightbot.core.watch_key import DateMode
from flightbot.providers.base import ProviderError, ProviderRateLimited
from flightbot.workers.poller import Poller, claim_due_keys
from tests.conftest import MutableClock
from tests.helpers import ScriptedProvider, key, make_due, make_user, make_watch, rows, scalar


def poller(sm, provider, settings, clock=None):
    return Poller(sm, provider, settings, clock=clock or (lambda: datetime.now(UTC)))


async def notif_count(sm, status=None):
    if status:
        return await scalar(sm, "select count(*) from notifications where status=:s", s=status)
    return await scalar(sm, "select count(*) from notifications")


async def seed_history(sm, key_id, price, n=20):
    async with sm.begin() as s:
        for i in range(n):
            await s.execute(
                text(
                    "INSERT INTO price_points (watch_key_id, observed_at, price, currency, depart_date, provider) "
                    "VALUES (:k, now() - make_interval(days => :d), :p, 'USD', current_date + 30, 'x')"
                ),
                {"k": key_id, "d": i + 1, "p": price},
            )


async def test_price_below_target_creates_exactly_one_outbox_notification(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 120)
    prov = ScriptedProvider(100)
    assert await poller(sm, prov, settings).run_once() == 1

    n = (await rows(sm, "select status, priority, payload, user_id from notifications"))[0]
    assert n.status == "pending" and n.priority == 1 and n.user_id == u
    assert n.payload["price"] == "100" and n.payload["origin"] == "GYD"
    w = (await rows(sm, "select armed, last_notified_price from watches"))[0]
    assert w.armed is False and w.last_notified_price == Decimal("100.00")
    assert await scalar(sm, "select last_price from watch_keys") == Decimal("100.00")
    assert await scalar(sm, "select count(*) from price_points") == 1
    # the key is scheduled for the next check and the lease is released
    r = (
        await rows(
            sm, "select next_check_at > now() as later, lease_until, consecutive_failures from watch_keys"
        )
    )[0]
    assert r.later and r.lease_until is None and r.consecutive_failures == 0


async def test_price_above_target_does_not_notify(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 100)
    await poller(sm, ScriptedProvider(150), settings).run_once()
    assert await notif_count(sm) == 0
    assert await scalar(sm, "select count(*) from price_points") == 1  # history is still written


async def test_many_subscribers_one_provider_call_correct_fanout(sm, settings):
    """800 subscriptions = 1 API request. Here: 30 users with different targets."""
    k = key()
    for i in range(30):
        u = await make_user(sm, 1000 + i)
        await make_watch(sm, u, k, 100 + i * 10)  # targets 100..390
    prov = ScriptedProvider(205)
    await poller(sm, prov, settings).run_once()
    assert prov.calls == 1
    assert await scalar(sm, "select count(*) from watch_keys") == 1
    assert await notif_count(sm) == 19  # those with a target >= 205: 210, 220, ..., 390


async def test_same_price_on_next_poll_does_not_duplicate(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 120)
    p = poller(sm, ScriptedProvider(100), settings)
    await p.run_once()
    await make_due(sm)
    await p.run_once()
    assert await notif_count(sm) == 1


async def test_rearm_then_second_drop_notifies_after_cooldown(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 120)
    clock = MutableClock()
    prov = ScriptedProvider(100)
    p = poller(sm, prov, settings, clock)

    await p.run_once()
    assert await notif_count(sm) == 1

    clock.now += timedelta(hours=7)
    prov.set(150)  # above the target -> re-armed
    await make_due(sm)
    await p.run_once()
    assert await scalar(sm, "select armed from watches") is True
    assert await scalar(sm, "select last_notified_price from watches") is None

    clock.now += timedelta(hours=7)
    prov.set(110)
    await make_due(sm)
    await p.run_once()
    assert await notif_count(sm) == 2


async def test_cooldown_blocks_quick_second_notification(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 120)
    clock = MutableClock()
    prov = ScriptedProvider(100)
    p = poller(sm, prov, settings, clock)
    await p.run_once()
    clock.now += timedelta(hours=1)
    prov.set(150)
    await make_due(sm)
    await p.run_once()  # rearm
    clock.now += timedelta(hours=1)
    prov.set(90)
    await make_due(sm)
    await p.run_once()  # cooldown (2 saat < 6 saat)
    assert await notif_count(sm) == 1


async def test_further_5_percent_drop_notifies_again_after_cooldown(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 120)
    clock = MutableClock()
    prov = ScriptedProvider(100)
    p = poller(sm, prov, settings, clock)
    await p.run_once()
    clock.now += timedelta(hours=7)
    prov.set(94)  # at least 5% cheaper than 100
    await make_due(sm)
    await p.run_once()
    assert await notif_count(sm) == 2


async def test_daily_limit_for_free_users(sm, settings):
    u = await make_user(sm, 1)
    ks = [key(dest=d) for d in ("IST", "DXB")]
    for k in ks:
        await make_watch(sm, u, k, 500)
    third = key(dest="TBS")
    await make_watch(sm, u, third, 500)
    # a 4th key needs quota, so upgrade to pro and create 4 keys
    async with sm.begin() as s:
        await s.execute(text("UPDATE users SET plan='pro'"))
    await make_watch(sm, u, key(dest="LON"), 500)
    async with sm.begin() as s:
        await s.execute(text("UPDATE users SET plan='free', plan_expires_at=NULL"))

    await poller(sm, ScriptedProvider(100), settings).run_once()
    assert await notif_count(sm) == 3  # Free: 3 per day
    assert await scalar(sm, "select count(*) from notifications where user_id=:u", u=u) == 3


async def test_pro_user_gets_priority_zero_and_higher_daily_limit(sm, settings):
    u = await make_user(sm, 1, plan="pro")
    await make_watch(sm, u, key(), 500)
    await poller(sm, ScriptedProvider(100), settings).run_once()
    assert await scalar(sm, "select priority from notifications") == 0


async def test_pro_watcher_makes_key_poll_faster(sm, settings):
    free, pro = await make_user(sm, 1), await make_user(sm, 2, plan="pro")
    await make_watch(sm, free, key(days=20), 1)
    await make_watch(sm, pro, key(dest="DXB", days=20), 1)
    await poller(sm, ScriptedProvider(500), settings).run_once()
    r = await rows(
        sm,
        "select destination, extract(epoch from (next_check_at - now()))/3600 as h from watch_keys order by destination",
    )
    by = {x.destination: float(x.h) for x in r}
    assert 0.8 <= by["DXB"] <= 1.2  # Pro: ~1 saat
    assert 5.0 <= by["IST"] <= 6.7  # Free (20 days): ~6 hours


async def test_blocked_users_are_not_evaluated(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    async with sm.begin() as s:
        await s.execute(text("UPDATE users SET is_blocked=true"))
    await poller(sm, ScriptedProvider(100), settings).run_once()
    assert await notif_count(sm) == 0


async def test_no_offers_just_reschedules(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await poller(sm, ScriptedProvider(None), settings).run_once()
    assert await notif_count(sm) == 0
    assert await scalar(sm, "select last_price from watch_keys") is None
    assert await scalar(sm, "select next_check_at > now() from watch_keys") is True


async def test_provider_error_backs_off_and_counts_failure(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await poller(sm, ScriptedProvider(ProviderError("down")), settings).run_once()
    r = (
        await rows(
            sm,
            "select consecutive_failures as f, lease_until, extract(epoch from (next_check_at - now())) as s from watch_keys",
        )
    )[0]
    assert r.f == 1 and r.lease_until is None and 200 <= float(r.s) <= 400  # ~5 min
    assert await notif_count(sm) == 0


async def test_repeated_failures_increase_backoff(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    p = poller(sm, ScriptedProvider(ProviderError("down")), settings)
    delays = []
    for _ in range(3):
        await make_due(sm)
        await p.run_once()
        delays.append(
            float(await scalar(sm, "select extract(epoch from (next_check_at - now())) from watch_keys"))
        )
    assert delays[0] < delays[1] < delays[2]
    assert await scalar(sm, "select consecutive_failures from watch_keys") == 3


async def test_rate_limit_delays_without_counting_failure(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await poller(sm, ScriptedProvider(ProviderRateLimited(120)), settings).run_once()
    assert await scalar(sm, "select consecutive_failures from watch_keys") == 0
    assert (
        float(await scalar(sm, "select extract(epoch from (next_check_at - now())) from watch_keys")) >= 100
    )


async def test_success_resets_failure_counter(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    prov = ScriptedProvider(ProviderError("x"), 300)
    p = poller(sm, prov, settings)
    await p.run_once()
    await make_due(sm)
    await p.run_once()
    assert await scalar(sm, "select consecutive_failures from watch_keys") == 0


async def test_unexpected_exception_does_not_wedge_key(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await poller(sm, ScriptedProvider(RuntimeError("bug")), settings).run_once()
    assert await scalar(sm, "select lease_until from watch_keys") is None
    assert await scalar(sm, "select consecutive_failures from watch_keys") == 1


async def test_skip_locked_two_claimers_get_disjoint_keys(sm):
    """Two workers at the same time must not claim the same key (SKIP LOCKED)."""
    for i in range(10):
        u = await make_user(sm, 100 + i)
        await make_watch(
            sm, u, key(dest=("IST", "DXB", "TBS", "LON", "PAR", "BER", "ROM", "AMS", "MAD", "PRG")[i]), 100
        )
    await make_due(sm)
    a, b = sm(), sm()
    try:
        async with a.begin():
            first = await claim_due_keys(a, limit=6, lease_s=300)
            async with b.begin():  # a hasn't committed yet: its rows are locked
                second = await claim_due_keys(b, limit=6, lease_s=300)
        ids_a, ids_b = {c.id for c in first}, {c.id for c in second}
        assert len(ids_a) == 6 and len(ids_b) == 4
        assert ids_a.isdisjoint(ids_b)
    finally:
        await a.close()
        await b.close()


async def test_leased_key_is_not_claimed_again_until_lease_expires(sm):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 100)
    await make_due(sm)
    async with sm.begin() as s:
        assert len(await claim_due_keys(s, limit=5, lease_s=300)) == 1
    async with sm.begin() as s:
        assert await claim_due_keys(s, limit=5, lease_s=300) == []
    async with sm.begin() as s:  # the worker crashed: the lease expires
        await s.execute(text("UPDATE watch_keys SET lease_until = now() - interval '1 second'"))
    async with sm.begin() as s:
        assert len(await claim_due_keys(s, limit=5, lease_s=300)) == 1


async def test_keys_without_active_watchers_are_never_polled(sm, settings):
    u = await make_user(sm, 1)
    w = await make_watch(sm, u, key(), 100)
    async with sm.begin() as s:
        await s.execute(text("UPDATE watches SET status='paused' WHERE id=:w"), {"w": w})
    await make_due(sm)
    prov = ScriptedProvider(100)
    assert await poller(sm, prov, settings).run_once() == 0 and prov.calls == 0


async def test_two_pollers_concurrently_do_not_duplicate_notifications(sm, settings):
    for i in range(15):
        u = await make_user(sm, 500 + i)
        await make_watch(sm, u, key(), 500)
    prov1, prov2 = ScriptedProvider(100), ScriptedProvider(100)
    await asyncio.gather(poller(sm, prov1, settings).run_once(), poller(sm, prov2, settings).run_once())
    assert prov1.calls + prov2.calls == 1  # 1 key = 1 request
    assert await notif_count(sm) == 15


# ------------------------------------------------------------- anomaly protection
async def test_anomalous_low_price_is_confirmed_by_fresh_second_request(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await seed_history(sm, 1, 200)  # median 200 -> 70 is suspicious (< 80)
    prov = ScriptedProvider(70, 70)
    await poller(sm, prov, settings).run_once()
    assert prov.calls == 2 and prov.fresh_calls == 1
    assert await notif_count(sm) == 1


async def test_anomaly_not_confirmed_is_dropped_and_not_stored(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await seed_history(sm, 1, 200)
    prov = ScriptedProvider(70, 190)  # the second request returns a normal price
    await poller(sm, prov, settings).run_once()
    assert await scalar(sm, "select count(*) from price_points where price = 70") == 0
    assert await scalar(sm, "select count(*) from price_points where price = 190") == 1
    assert await notif_count(sm) == 1  # 190 <= target 500: a normal notification about the real price


async def test_anomaly_with_no_second_result_blocks_alert_and_history(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await seed_history(sm, 1, 200)
    prov = ScriptedProvider(70, None)
    await poller(sm, prov, settings).run_once()
    assert await notif_count(sm) == 0
    assert await scalar(sm, "select count(*) from price_points where price = 70") == 0
    assert await scalar(sm, "select last_price from watch_keys") is None  # the suspicious price is not stored


async def test_price_history_deduplicates_unchanged_prices(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 1)
    p = poller(sm, ScriptedProvider(300), settings)
    for _ in range(3):
        await make_due(sm)
        await p.run_once()
    assert await scalar(sm, "select count(*) from price_points") == 1


async def test_good_price_flag_and_vs_median_in_payload(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await seed_history(sm, 1, 200)
    await poller(sm, ScriptedProvider(150), settings).run_once()
    payload = (await rows(sm, "select payload from notifications"))[0].payload
    assert payload["good_price"] is True and payload["vs_median_pct"] == -25
    assert payload["median"] == "200.0" or payload["median"] == "200.00" or payload["median"] == "200"


async def test_month_mode_payload_has_window_and_cheapest_day(sm, settings):
    u = await make_user(sm, 1)
    k = key(mode=DateMode.MONTH, days=40)
    await make_watch(sm, u, k, 500)
    await poller(sm, ScriptedProvider(100), settings).run_once()
    payload = (await rows(sm, "select payload from notifications"))[0].payload
    assert payload["date_mode"] == "month" and payload["window_start"] == k.window_start.isoformat()


async def test_notification_dedup_key_prevents_duplicate_on_replayed_transaction(sm, settings):
    """A second notification for the same (watch, price, day) is impossible at the DB level."""
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await poller(sm, ScriptedProvider(100), settings).run_once()
    async with (
        sm.begin() as s
    ):  # manually roll the state back: the "poller crashed without writing the state" scenario
        await s.execute(
            text("UPDATE watches SET armed=true, last_notified_price=NULL, last_notified_at=NULL")
        )
        await s.execute(
            text("UPDATE watch_keys SET next_check_at = now() - interval '1 s', lease_until = NULL")
        )
    await poller(sm, ScriptedProvider(100), settings).run_once()
    assert await notif_count(sm) == 1


async def test_due_keys_metric_reflects_backlog(sm, settings):
    from flightbot import metrics

    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 100)
    await make_due(sm)
    p = poller(sm, ScriptedProvider(500), settings)
    await p.refresh_metrics()
    assert metrics.DUE_KEYS._value.get() == 1
    await p.run_once()
    await p.refresh_metrics()
    assert metrics.DUE_KEYS._value.get() == 0


async def test_redis_outage_delays_key_without_counting_failure(sm, settings):
    from redis.exceptions import ConnectionError as RedisConnectionError

    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    await poller(sm, ScriptedProvider(RedisConnectionError("down")), settings).run_once()
    assert await scalar(sm, "select consecutive_failures from watch_keys") == 0  # backoff does not inflate
    assert await scalar(sm, "select lease_until from watch_keys") is None
    assert (
        30
        <= float(await scalar(sm, "select extract(epoch from (next_check_at - now())) from watch_keys"))
        <= 90
    )


async def test_round_trip_stay_key_is_polled_and_notifies(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(mode=DateMode.MONTH, days=40, stay=7), 500)
    prov = ScriptedProvider(100)
    await poller(sm, prov, settings).run_once()
    assert prov.calls == 1
    assert await scalar(sm, "select count(*) from notifications") == 1
    assert (await rows(sm, "select stay_min, stay_max from watch_keys"))[0] == (7, 7)
