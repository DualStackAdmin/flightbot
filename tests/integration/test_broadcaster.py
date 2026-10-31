import json
import time
from datetime import timedelta

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.methods import SendMessage
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text

from flightbot.workers.broadcaster import PAUSE_KEY, Broadcaster, retry_backoff_seconds
from tests.helpers import FakeBot, key, make_user, make_watch, rows, scalar

METHOD = SendMessage(chat_id=1, text="x")
PAYLOAD = {
    "origin": "GYD",
    "destination": "IST",
    "date_mode": "exact",
    "window_start": "2026-12-15",
    "currency": "USD",
    "price": "99",
    "depart_date": "2026-12-15",
    "return_date": None,
    "airline": "TK",
    "transfers": 0,
    "link": None,
    "target_price": "120",
    "good_price": False,
    "vs_median_pct": None,
    "trend": None,
    "previous_price": None,
}


def bc(sm, redis, settings, bot, **kw):
    return Broadcaster(bot, sm, redis, settings, marker="MK", **kw)


async def add(sm, user_id, *, priority=1, tag="a", status="pending", lease=None) -> int:
    async with sm.begin() as s:
        r = await s.execute(
            text(
                "INSERT INTO notifications (user_id, dedup_key, priority, status, payload, lease_until) "
                "VALUES (:u, :d, :p, :s, CAST(:pl AS jsonb), "
                "CASE WHEN :l THEN now() - interval '1 minute' ELSE NULL END) RETURNING id"
            ),
            {
                "u": user_id,
                "d": f"{user_id}:{tag}",
                "p": priority,
                "s": status,
                "pl": json.dumps(PAYLOAD),
                "l": lease is not None,
            },
        )
        return r.scalar_one()


async def status_of(sm, nid):
    return (
        await rows(
            sm,
            "select status, attempts, last_error, telegram_message_id from notifications where id=:i",
            i=nid,
        )
    )[0]


async def test_sends_renders_and_marks_sent(sm, redis, settings):
    u = await make_user(sm, 777, lang="az")
    nid = await add(sm, u)
    bot = FakeBot()
    assert await bc(sm, redis, settings, bot).run_once() == 1

    sent = bot.sent[0]
    assert sent["chat_id"] == 777 and sent["parse_mode"] == "HTML"
    assert "Bakı → İstanbul" in sent["text"] and "99" in sent["text"]
    assert "marker=MK.n" in sent["reply_markup"].inline_keyboard[0][0].url
    assert sent["link_preview_options"].is_disabled is True
    st = await status_of(sm, nid)
    assert st.status == "sent" and st.telegram_message_id == 1001
    assert await scalar(sm, "select sent_at is not null from notifications") is True


async def test_user_language_applied_at_send_time(sm, redis, settings):
    u = await make_user(sm, 1, lang="ru")
    await add(sm, u)
    bot = FakeBot()
    await bc(sm, redis, settings, bot).run_once()
    assert "Баку → Стамбул" in bot.sent[0]["text"]


async def test_pro_notifications_are_sent_before_free(sm, redis, settings):
    free, pro = await make_user(sm, 1), await make_user(sm, 2, plan="pro")
    n_free = await add(sm, free, priority=1, tag="f")
    n_pro = await add(sm, pro, priority=0, tag="p")
    bot = FakeBot()
    b = bc(sm, redis, settings.model_copy(update={"broadcaster_batch": 1}), bot)
    await b.run_once()
    assert (await status_of(sm, n_pro)).status == "sent"
    assert (await status_of(sm, n_free)).status == "pending"
    await b.run_once()
    assert (await status_of(sm, n_free)).status == "sent"


async def test_retry_after_pauses_everyone_and_requeues_without_burning_attempts(sm, redis, settings):
    u1, u2 = await make_user(sm, 1), await make_user(sm, 2)
    n1, n2 = await add(sm, u1, tag="1"), await add(sm, u2, tag="2")
    bot = FakeBot(TelegramRetryAfter(METHOD, "Flood control", 30))
    s2 = settings.model_copy(update={"broadcaster_batch": 1})
    b = bc(sm, redis, s2, bot)

    await b.run_once()  # 1-ci mesaj 429 alır
    st = await status_of(sm, n1)
    assert st.status == "pending" and st.attempts == 0  # cəhd yandırılmadı
    assert float(await redis.get(PAUSE_KEY)) > time.time() + 20  # qlobal pauza
    assert await scalar(
        sm, "select available_at > now() + interval '20 seconds' from notifications where id=:i", i=n1
    )

    await b.run_once()  # pauza aktivdir: 2-ci mesaj da göndərilməməlidir
    assert bot.sent == []
    st2 = await status_of(sm, n2)
    assert st2.status == "pending" and st2.attempts == 0


async def test_forbidden_blocks_user_and_freezes_watches(sm, redis, settings):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 100)
    await make_watch(sm, u, key(dest="DXB"), 100)
    n1, n2 = await add(sm, u, tag="1"), await add(sm, u, tag="2")
    bot = FakeBot(TelegramForbiddenError(METHOD, "Forbidden: bot was blocked by the user"))
    await bc(sm, redis, settings, bot).run_once()

    assert await scalar(sm, "select is_blocked from users") is True
    assert (
        await scalar(sm, "select count(*) from watches where status='paused' and pause_reason='blocked'") == 2
    )
    assert await scalar(sm, "select coalesce(sum(active_watch_count),0) from watch_keys") == 0
    assert (await status_of(sm, n1)).status == "skipped" and (await status_of(sm, n2)).status == "skipped"


async def test_chat_not_found_is_treated_as_blocked(sm, redis, settings):
    u = await make_user(sm, 1)
    await add(sm, u)
    bot = FakeBot(TelegramBadRequest(METHOD, "Bad Request: chat not found"))
    await bc(sm, redis, settings, bot).run_once()
    assert await scalar(sm, "select is_blocked from users") is True


async def test_other_bad_request_fails_permanently_without_retry(sm, redis, settings):
    u = await make_user(sm, 1)
    nid = await add(sm, u)
    bot = FakeBot(TelegramBadRequest(METHOD, "Bad Request: can't parse entities"))
    await bc(sm, redis, settings, bot).run_once()
    st = await status_of(sm, nid)
    assert st.status == "failed" and "parse entities" in st.last_error
    assert await scalar(sm, "select is_blocked from users") is False


async def test_network_error_retries_with_backoff_then_fails_at_max(sm, redis, settings):
    u = await make_user(sm, 1)
    nid = await add(sm, u)
    err = TelegramNetworkError(METHOD, "timeout")
    bot = FakeBot(err, err, err, err)
    b = bc(sm, redis, settings, bot)

    for attempt in (1, 2):
        await b.run_once()
        st = await status_of(sm, nid)
        assert st.status == "pending" and st.attempts == attempt
        assert await scalar(sm, "select available_at > now() + interval '10 seconds' from notifications")
        async with sm.begin() as s:  # backoff-u gözləmə
            await s.execute(text("UPDATE notifications SET available_at = now() - interval '1 second'"))
        await redis.delete("rl:tg:user:1")
    await b.run_once()
    assert (await status_of(sm, nid)).status == "failed"  # attempts=3 == max


async def test_second_notification_to_same_user_is_throttled_per_user(sm, redis, settings):
    u = await make_user(sm, 5)
    n1, n2 = await add(sm, u, tag="1"), await add(sm, u, tag="2")
    bot = FakeBot()
    b = bc(sm, redis, settings, bot)
    await b.run_once()
    sent_now = [await status_of(sm, n) for n in (n1, n2)]
    assert sorted(s.status for s in sent_now) == ["pending", "sent"]  # 1 msg/s per user
    assert len(bot.sent) == 1


async def test_crashed_worker_notification_is_reclaimed_after_lease_expiry(sm, redis, settings):
    u = await make_user(sm, 1)
    nid = await add(sm, u, status="sending", lease=True)  # lease bitib
    bot = FakeBot()
    await bc(sm, redis, settings, bot).run_once()
    st = await status_of(sm, nid)
    assert st.status == "sent" and st.attempts == 1 and len(bot.sent) == 1


async def test_live_lease_is_not_stolen(sm, redis, settings):
    u = await make_user(sm, 1)
    nid = await add(sm, u, status="sending")
    async with sm.begin() as s:
        await s.execute(text("UPDATE notifications SET lease_until = now() + interval '1 minute'"))
    bot = FakeBot()
    assert await bc(sm, redis, settings, bot).run_once() == 0
    assert (await status_of(sm, nid)).status == "sending"


async def test_crash_loop_is_capped_by_max_attempts(sm, redis, settings):
    u = await make_user(sm, 1)
    nid = await add(sm, u)
    async with sm.begin() as s:
        await s.execute(
            text("UPDATE notifications SET status='sending', attempts=3, lease_until=now()-interval '1 s'")
        )
    bot = FakeBot()
    await bc(sm, redis, settings, bot).run_once()  # claim -> attempts=4 > max(3)
    st = await status_of(sm, nid)
    assert st.status == "failed" and st.last_error == "max_attempts_exceeded" and bot.sent == []


async def test_two_broadcasters_never_double_send(sm, redis, settings):
    import asyncio

    for i in range(20):
        u = await make_user(sm, 100 + i)
        await add(sm, u, tag="x")
    bot_a, bot_b = FakeBot(), FakeBot()
    await asyncio.gather(bc(sm, redis, settings, bot_a).run_once(), bc(sm, redis, settings, bot_b).run_once())
    chat_ids = [m["chat_id"] for m in bot_a.sent + bot_b.sent]
    assert len(chat_ids) == 20 and len(set(chat_ids)) == 20
    assert await scalar(sm, "select count(*) from notifications where status='sent'") == 20


async def test_global_rate_limit_spreads_sends_across_replicas(sm, redis, settings):
    """Paylanmış limit: iki broadcaster birlikdə qlobal limitdən çox göndərə bilməz."""
    import asyncio

    low = settings.model_copy(update={"telegram_global_rps": 5.0})
    for i in range(12):
        u = await make_user(sm, 200 + i)
        await add(sm, u, tag="x")
    bots = [FakeBot(), FakeBot()]
    t0 = time.monotonic()
    await asyncio.gather(*(bc(sm, redis, low, b).run_once() for b in bots))
    elapsed = time.monotonic() - t0
    assert len(bots[0].sent) + len(bots[1].sent) == 12
    # capacity 5 + 5/s: 12 mesaj >= ~1.2 san (tək replika limiti ikiqat aşa bilməz)
    assert elapsed >= 1.0


async def test_blocked_user_notification_skipped_without_sending(sm, redis, settings):
    u = await make_user(sm, 1)
    nid = await add(sm, u)
    async with sm.begin() as s:
        await s.execute(text("UPDATE users SET is_blocked=true"))
    bot = FakeBot()
    await bc(sm, redis, settings, bot).run_once()
    assert (await status_of(sm, nid)).status == "skipped" and bot.sent == []


async def test_queue_metrics_report_lag(sm, redis, settings):
    from flightbot import metrics

    u = await make_user(sm, 1)
    await add(sm, u)
    async with sm.begin() as s:
        await s.execute(text("UPDATE notifications SET available_at = now() - interval '90 seconds'"))
    await bc(sm, redis, settings, FakeBot()).refresh_metrics()
    assert metrics.QUEUE_DEPTH._value.get() == 1
    assert 85 <= metrics.QUEUE_LAG._value.get() <= 100


def test_retry_backoff_schedule():
    assert [retry_backoff_seconds(n) for n in (1, 2, 3, 10)] == [30, 60, 120, 1800]
    assert timedelta(seconds=retry_backoff_seconds(1)) == timedelta(seconds=30)


class DeadRedis:
    """Redis-in düşməsini simulyasiya edir."""

    def register_script(self, _src):
        async def boom(*a, **kw):
            raise RedisConnectionError("redis down")

        return boom

    async def get(self, *_):
        raise RedisConnectionError("redis down")

    async def set(self, *a, **kw):
        raise RedisConnectionError("redis down")


async def test_redis_outage_never_burns_attempts_or_fails_notifications(sm, settings):
    u = await make_user(sm, 1)
    nid = await add(sm, u)
    bot = FakeBot()
    b = Broadcaster(bot, sm, DeadRedis(), settings, marker="")
    for _ in range(6):  # max_attempts=3-dən çox dəfə; Redis hələ də düşüb
        await b.run_once()
        async with sm.begin() as s:
            await s.execute(text("UPDATE notifications SET available_at = now() - interval '1 second'"))
    st = await status_of(sm, nid)
    assert st.status == "pending" and st.attempts == 0 and bot.sent == []


async def test_notification_delivered_after_redis_recovers(sm, redis, settings):
    u = await make_user(sm, 1)
    nid = await add(sm, u)
    await Broadcaster(FakeBot(), sm, DeadRedis(), settings).run_once()
    async with sm.begin() as s:
        await s.execute(text("UPDATE notifications SET available_at = now() - interval '1 second'"))
    bot = FakeBot()
    await bc(sm, redis, settings, bot).run_once()  # Redis qayıtdı
    assert (await status_of(sm, nid)).status == "sent" and len(bot.sent) == 1
