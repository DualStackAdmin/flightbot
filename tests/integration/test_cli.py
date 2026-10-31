from sqlalchemy import text

from flightbot.cli import collect_stats, set_plan
from flightbot.core.plans import effective_plan
from tests.helpers import key, make_user, make_watch, scalar


async def test_grant_and_revoke_pro(sm):
    from datetime import UTC, datetime

    await make_user(sm, 55)
    assert await set_plan(sm, telegram_id=55, plan="pro", days=30)
    row = (await _user(sm)).one()
    assert effective_plan(row.plan, row.plan_expires_at, datetime.now(UTC)) == "pro"
    assert await set_plan(sm, telegram_id=55, plan="free", days=None)
    row = (await _user(sm)).one()
    assert effective_plan(row.plan, row.plan_expires_at, datetime.now(UTC)) == "free"
    assert not await set_plan(sm, telegram_id=999, plan="pro", days=1)  # yoxdur


async def _user(sm):
    async with sm() as s:
        return await s.execute(text("select plan, plan_expires_at from users"))


async def test_stats_report_feedback_and_block_rates(sm):
    u1, u2 = await make_user(sm, 1), await make_user(sm, 2)
    await make_watch(sm, u1, key(), 100)
    async with sm.begin() as s:
        await s.execute(text("UPDATE users SET is_blocked = true WHERE id = :u"), {"u": u2})
        for i, fb in enumerate((1, 1, 1, -1)):
            await s.execute(
                text(
                    "INSERT INTO notifications (user_id, dedup_key, payload, feedback, status) VALUES (:u, :k, '{}', :f, 'sent')"
                ),
                {"u": u1, "k": f"k{i}", "f": fb},
            )
    st = await collect_stats(sm)
    assert st["users_total"] == 2 and st["users_blocked"] == 1 and st["blocked_pct"] == 50.0
    assert st["watches_active"] == 1 and st["watch_keys_active"] == 1
    assert st["feedback_up"] == 3 and st["feedback_down"] == 1 and st["feedback_down_pct"] == 25.0
    assert await scalar(sm, "select count(*) from users") == 2
