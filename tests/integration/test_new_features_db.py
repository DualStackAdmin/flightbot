import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import text

from flightbot.core.watches import update_target
from flightbot.providers.base import PriceQuote
from flightbot.providers.names import REDIS_KEY, PlaceNames
from flightbot.providers.wrappers import CachedProvider
from flightbot.workers.broadcaster import Broadcaster
from flightbot.workers.poller import Poller
from tests.conftest import MutableClock
from tests.helpers import FakeBot, ScriptedProvider, key, make_user, make_watch, rows, scalar, today


def q(dest, price="50"):
    return PriceQuote(
        Decimal(price), "USD", today() + timedelta(days=20), None, "TK", 0, None, None, "s", destination=dest
    )


# ------------------------------------------------------------------ sakit saatlar (poller)
def quiet_settings(settings):
    return settings.model_copy(update={"quiet_start_hour": 23, "quiet_end_hour": 8, "quiet_tz": "Asia/Baku"})


async def test_notification_created_in_quiet_hours_is_held_until_morning(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    clock = MutableClock(datetime(2026, 11, 1, 21, 30, tzinfo=UTC))  # Baku 01:30
    p = Poller(sm, ScriptedProvider(100), quiet_settings(settings), clock=clock)
    await p.run_once()
    r = (await rows(sm, "select status, available_at from notifications"))[0]
    assert r.status == "pending"
    assert r.available_at.astimezone(UTC) >= datetime(2026, 11, 2, 4, 0, tzinfo=UTC)  # Baku 08:00
    # the broadcaster does not send it yet (the real clock is "now", available_at is in the future)
    async with sm.begin() as s:
        await s.execute(text("UPDATE notifications SET available_at = now() + interval '5 hours'"))
    from redis.asyncio import Redis

    bot = FakeBot()
    redis = Redis.from_url("redis://localhost:6379/15")
    try:
        assert await Broadcaster(bot, sm, redis, settings).run_once() == 0 and bot.sent == []
    finally:
        await redis.aclose()


async def test_notification_outside_quiet_hours_is_immediate(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    clock = MutableClock(datetime(2026, 11, 1, 10, 0, tzinfo=UTC))  # Baku 14:00
    await Poller(sm, ScriptedProvider(100), quiet_settings(settings), clock=clock).run_once()
    assert await scalar(sm, "select available_at = :t from notifications", t=clock.now) is True


async def test_user_who_disabled_quiet_hours_gets_night_notification_immediately(sm, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 500)
    async with sm.begin() as s:
        await s.execute(text("UPDATE users SET quiet_hours = false"))
    clock = MutableClock(datetime(2026, 11, 1, 21, 30, tzinfo=UTC))
    await Poller(sm, ScriptedProvider(100), quiet_settings(settings), clock=clock).run_once()
    assert await scalar(sm, "select available_at = :t from notifications", t=clock.now) is True


async def test_payload_contains_watch_id_for_management_buttons(sm, settings):
    u = await make_user(sm, 1)
    wid = await make_watch(sm, u, key(), 500)
    await Poller(sm, ScriptedProvider(100), settings).run_once()
    payload = (await rows(sm, "select payload from notifications"))[0].payload
    assert payload["watch_id"] == wid


async def test_broadcast_renders_management_row_in_user_language(sm, redis, settings):
    import json

    from tests.integration.test_broadcaster import PAYLOAD, add

    u = await make_user(sm, 9, lang="ru")
    wid = await make_watch(sm, u, key(), 500)
    nid = await add(sm, u)
    async with sm.begin() as s:
        await s.execute(
            text("UPDATE notifications SET payload = CAST(:p AS jsonb) WHERE id = :i"),
            {"p": json.dumps({**PAYLOAD, "watch_id": wid}), "i": nid},
        )
    bot = FakeBot()
    await Broadcaster(bot, sm, redis, settings, marker="794979").run_once()
    markup = bot.sent[0]["reply_markup"]
    labels = [[b.text for b in row] for row in markup.inline_keyboard]
    assert len(labels) == 3 and "Приостановить" in labels[1][0] and "Изменить" in labels[1][1]
    assert "marker=794979.n" in markup.inline_keyboard[0][0].url


# ------------------------------------------------------------------- updating the target
async def test_update_target_rearms_and_schedules_immediate_check_if_already_cheap(sm):
    u = await make_user(sm, 1)
    wid = await make_watch(sm, u, key(), 100)
    async with sm.begin() as s:
        await s.execute(text("UPDATE watches SET armed=false, last_notified_price=90"))
        await s.execute(
            text("UPDATE watch_keys SET last_price = 80, next_check_at = now() + interval '5 hours'")
        )
    async with sm.begin() as s:
        assert await update_target(s, user_id=u, watch_id=wid, target_price=Decimal("85"))
    r = (await rows(sm, "select target_price, armed, last_notified_price from watches"))[0]
    assert r.target_price == Decimal("85.00") and r.armed is True and r.last_notified_price is None
    assert await scalar(sm, "select next_check_at <= now() from watch_keys") is True


async def test_update_target_rejects_foreign_watch(sm):
    u1, u2 = await make_user(sm, 1), await make_user(sm, 2)
    wid = await make_watch(sm, u1, key(), 100)
    async with sm.begin() as s:
        assert not await update_target(s, user_id=u2, watch_id=wid, target_price=Decimal("1"))
    assert await scalar(sm, "select target_price from watches") == Decimal("100.00")


# ---------------------------------------------------------------- explore: cache/singleflight
class SlowExplore(ScriptedProvider):
    async def explore(self, **kw):
        await asyncio.sleep(0.3)
        return await super().explore(**kw)


async def test_explore_is_cached_and_coalesced(redis):
    inner = SlowExplore(1)
    inner.explore_result = [q("IST", "79"), q("DXB", "95")]
    cp = CachedProvider(inner, redis, today_fn=today)
    args = dict(origin="GYD", month=date(2026, 12, 1), currency="USD", limit=10)
    results = await asyncio.gather(*(cp.explore(**args) for _ in range(8)))
    assert inner.explore_calls == 1 and all(r[0].destination == "IST" for r in results)
    await cp.explore(**args)
    assert inner.explore_calls == 1  # from the cache
    assert 0 < await redis.ttl("explore:GYD:2026-12:USD:0:-") <= 3600
    await cp.explore(**args, fresh=True)
    assert inner.explore_calls == 2


async def test_explore_cache_key_separates_origin_month_currency_and_direct(redis):
    inner = ScriptedProvider(1)
    inner.explore_result = [q("IST")]
    cp = CachedProvider(inner, redis, today_fn=today)
    base = dict(origin="GYD", month=date(2026, 12, 1), currency="USD")
    await cp.explore(**base)
    await cp.explore(**{**base, "origin": "ESB"})
    await cp.explore(**{**base, "month": date(2027, 1, 1)})
    await cp.explore(**{**base, "currency": "AZN"})
    await cp.explore(**base, direct_only=True)
    assert inner.explore_calls == 5


# ------------------------------------------------------------------- name resolution (Redis)
async def test_names_loaded_once_cached_in_redis_and_failure_does_not_break(redis):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json=[{"code": "KUL", "name": "Kuala Lumpur", "country_code": "MY"}])

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    names = PlaceNames(redis, http, remote=True)
    info = await names.lookup("KUL", "az")
    assert (info.name, info.country) == ("Kuala Lumpur", "MY") and len(calls) == 1
    assert await redis.exists(REDIS_KEY) and await redis.ttl(REDIS_KEY) > 6 * 24 * 3600
    await names.lookup("KUL", "ru")
    assert len(calls) == 1
    other = PlaceNames(redis, http, remote=True)  # another replica: reads from Redis, doesn't hit the network
    assert (await other.lookup("KUL", "az")).name == "Kuala Lumpur" and len(calls) == 1

    await redis.flushdb()
    broken = PlaceNames(
        redis, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))), remote=True
    )
    assert (await broken.lookup("KUL", "az")).name == "KUL"  # doesn't break, shows the code
    assert (await broken.lookup("IST", "az")).name == "İstanbul"
