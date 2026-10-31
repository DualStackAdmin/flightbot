from datetime import timedelta

from sqlalchemy import text

from flightbot.core.watch_key import DateMode
from flightbot.workers.janitor import run_janitor_once
from tests.helpers import key, make_user, make_watch, scalar, today


async def test_expires_watches_whose_window_has_passed_and_keeps_future(sm):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(days=10), 100)
    await make_watch(sm, u, key(dest="DXB", days=20), 100)
    async with sm.begin() as s:  # IST açarının tarixi keçib
        await s.execute(text("UPDATE watch_keys SET expires_on = current_date - 1 WHERE destination='IST'"))
    result = await run_janitor_once(sm, today())
    assert result["expired"] == 1
    assert await scalar(sm, "select count(*) from watches where status='expired'") == 1
    assert await scalar(sm, "select active_watch_count from watch_keys where destination='IST'") == 0
    assert await scalar(sm, "select active_watch_count from watch_keys where destination='DXB'") == 1


async def test_month_watch_expires_only_after_month_end(sm):
    u = await make_user(sm, 1)
    k = key(mode=DateMode.MONTH, days=5)
    await make_watch(sm, u, k, 100)
    await run_janitor_once(sm, k.window_end)  # ayın son günü: hələ keçməyib
    assert await scalar(sm, "select status from watches") == "active"
    await run_janitor_once(sm, k.window_end + timedelta(days=1))
    assert await scalar(sm, "select status from watches") == "expired"


async def test_paused_watches_expire_too(sm):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(days=3), 100)
    async with sm.begin() as s:
        await s.execute(text("UPDATE watches SET status='paused', pause_reason='user'"))
    await run_janitor_once(sm, today() + timedelta(days=10))
    assert await scalar(sm, "select status from watches") == "expired"


async def test_purges_old_notifications_and_history_but_keeps_recent(sm):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 100)
    async with sm.begin() as s:
        await s.execute(
            text(
                "INSERT INTO notifications (user_id, dedup_key, status, payload, created_at) VALUES "
                "(:u,'old','sent','{}', now() - interval '40 days'),"
                "(:u,'old-pending','pending','{}', now() - interval '40 days'),"
                "(:u,'new','sent','{}', now() - interval '1 day')"
            ),
            {"u": u},
        )
        await s.execute(
            text(
                "INSERT INTO price_points (watch_key_id, observed_at, price, currency, depart_date, provider) VALUES "
                "(1, now() - interval '500 days', 1, 'USD', current_date, 'x'),"
                "(1, now() - interval '5 days', 1, 'USD', current_date, 'x')"
            )
        )
    r = await run_janitor_once(sm, today())
    assert r["notifications"] == 1 and r["price_points"] == 1
    keys = {x for x in (await _dedups(sm))}
    assert keys == {"old-pending", "new"}  # gözləyən bildiriş heç vaxt silinmir


async def _dedups(sm):
    async with sm() as s:
        return [r[0] for r in (await s.execute(text("select dedup_key from notifications"))).all()]


async def test_orphaned_expired_keys_are_deleted_only_when_unreferenced(sm):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(days=1), 100)
    async with sm.begin() as s:
        await s.execute(text("UPDATE watch_keys SET expires_on = current_date - 5"))
    await run_janitor_once(sm, today())
    assert await scalar(sm, "select count(*) from watch_keys") == 1  # expired watch hələ istinad edir
    async with sm.begin() as s:
        await s.execute(text("DELETE FROM watches"))
    await run_janitor_once(sm, today())
    assert await scalar(sm, "select count(*) from watch_keys") == 0
