import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from flightbot.core.watch_key import DateMode
from flightbot.core.watches import QuotaExceeded, create_or_update_watch, set_paused
from tests.helpers import key, make_user, make_watch, scalar


async def create(sm, uid, k, target=100):
    async with sm.begin() as s:
        return await create_or_update_watch(
            s, user_id=uid, key=k, target_price=Decimal(target), now=datetime.now(UTC)
        )


async def test_free_plan_allows_three_active_watches(sm):
    u = await make_user(sm, 1)
    for dest in ("IST", "DXB", "TBS"):
        await create(sm, u, key(dest=dest))
    with pytest.raises(QuotaExceeded) as exc:
        await create(sm, u, key(dest="LON"))
    assert exc.value.code == "max_watches" and exc.value.limit == 3


async def test_pro_plan_allows_more(sm):
    u = await make_user(sm, 1, plan="pro")
    for i, dest in enumerate(("IST", "DXB", "TBS", "LON", "PAR")):
        await create(sm, u, key(dest=dest, days=20 + i))
    assert await scalar(sm, "select count(*) from watches") == 5


async def test_expired_pro_falls_back_to_free_limits(sm):
    from sqlalchemy import text

    u = await make_user(sm, 1, plan="pro")
    async with sm.begin() as s:
        await s.execute(text("UPDATE users SET plan_expires_at = now() - interval '1 day'"))
    for dest in ("IST", "DXB", "TBS"):
        await create(sm, u, key(dest=dest))
    with pytest.raises(QuotaExceeded):
        await create(sm, u, key(dest="LON"))


async def test_free_plan_has_no_separate_flexible_limit(sm):
    """Default rejim "ay üzrə"dir: 3 ay-izləməsi Free üçün normaldır."""
    u = await make_user(sm, 1)
    for dest in ("IST", "DXB", "TBS"):
        await create(sm, u, key(dest=dest, mode=DateMode.MONTH, days=40))
    assert await scalar(sm, "select count(*) from watches") == 3


async def test_flexible_limit_mechanism_still_enforced_when_a_plan_defines_it(sm, monkeypatch):
    from flightbot.core import watches as watches_mod
    from flightbot.core.plans import PlanLimits

    monkeypatch.setattr(watches_mod, "limits_for", lambda plan: PlanLimits(3, 1, 3))
    u = await make_user(sm, 1)
    await create(sm, u, key(mode=DateMode.MONTH, days=40))
    with pytest.raises(QuotaExceeded) as exc:
        await create(sm, u, key(dest="DXB", mode=DateMode.MONTH, days=40))
    assert exc.value.code == "max_flexible"
    await create(sm, u, key(dest="DXB"))  # dəqiq tarix hələ olar


async def test_quota_cannot_be_bypassed_by_parallel_requests(sm):
    """10 paralel sorğu: kvota istifadəçi sətri üzərində FOR UPDATE ilə atomikdir."""
    u = await make_user(sm, 1)
    dests = ["IST", "DXB", "TBS", "LON", "PAR", "BER", "ROM", "AMS", "MAD", "PRG"]
    results = await asyncio.gather(*(create(sm, u, key(dest=d)) for d in dests), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    failed = [r for r in results if isinstance(r, QuotaExceeded)]
    assert len(ok) == 3 and len(failed) == 7
    assert await scalar(sm, "select count(*) from watches") == 3


async def test_same_route_updates_target_and_rearms_instead_of_duplicating(sm):
    u = await make_user(sm, 1)
    k = key()
    w1, created1 = await create(sm, u, k, 100)
    async with sm.begin() as s:
        from sqlalchemy import text

        await s.execute(text("UPDATE watches SET armed=false, last_notified_price=90"))
    w2, created2 = await create(sm, u, k, 80)
    assert created1 and not created2 and w1.id == w2.id
    assert await scalar(sm, "select target_price from watches") == Decimal("80.00")
    assert await scalar(sm, "select armed from watches") is True
    assert await scalar(sm, "select last_notified_price from watches") is None


async def test_resume_respects_quota(sm):
    u = await make_user(sm, 1)
    w1 = await make_watch(sm, u, key(dest="IST"), 100)
    async with sm.begin() as s:
        await set_paused(s, user_id=u, watch_id=w1, paused=True, now=datetime.now(UTC))
    for dest in ("DXB", "TBS", "LON"):
        await make_watch(sm, u, key(dest=dest), 100)
    with pytest.raises(QuotaExceeded):
        async with sm.begin() as s:
            await set_paused(s, user_id=u, watch_id=w1, paused=False, now=datetime.now(UTC))


async def test_cannot_touch_other_users_watch(sm):
    u1, u2 = await make_user(sm, 1), await make_user(sm, 2)
    w = await make_watch(sm, u1, key(), 100)
    async with sm.begin() as s:
        assert not await set_paused(s, user_id=u2, watch_id=w, paused=True, now=datetime.now(UTC))


async def test_new_watch_on_already_cheap_key_schedules_immediate_check(sm):
    from sqlalchemy import text

    u1, u2 = await make_user(sm, 1), await make_user(sm, 2)
    k = key()
    await make_watch(sm, u1, k, 100)
    async with sm.begin() as s:
        await s.execute(
            text("UPDATE watch_keys SET last_price = 80, next_check_at = now() + interval '5 hours'")
        )
    await make_watch(sm, u2, k, 90)  # 80 <= 90 -> dərhal yoxlanmalıdır
    assert await scalar(sm, "select next_check_at <= now() from watch_keys") is True


async def test_new_watch_does_not_force_recheck_when_price_above_target(sm):
    from sqlalchemy import text

    u1, u2 = await make_user(sm, 1), await make_user(sm, 2)
    k = key()
    await make_watch(sm, u1, k, 100)
    async with sm.begin() as s:
        await s.execute(
            text("UPDATE watch_keys SET last_price = 200, next_check_at = now() + interval '5 hours'")
        )
    await make_watch(sm, u2, k, 90)
    assert await scalar(sm, "select next_check_at > now() from watch_keys") is True
