"""Schema, triggers and model/migration consistency."""

import asyncio
from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from flightbot.core.users import mark_blocked, mark_unblocked
from flightbot.core.watches import delete_watch, set_paused
from flightbot.db.base import Base
from flightbot.workers.janitor import reconcile_counts
from tests.helpers import key, make_user, make_watch, scalar


async def count(sm, key_id=1):
    return await scalar(sm, "select active_watch_count from watch_keys where id=:i", i=key_id)


async def test_migration_matches_models(engine):
    """There must be no drift between the migration and the models (a new column must not be forgotten without a migration)."""

    def diff(sync_conn):
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(ctx, Base.metadata)

    async with engine.connect() as conn:
        result = await conn.run_sync(diff)
    assert result == [], result


async def test_default_tenant_seeded(sm):
    assert await scalar(sm, "select slug from tenants where id=1") == "default"


async def test_trigger_tracks_active_count_through_lifecycle(sm):
    u1, u2 = await make_user(sm, 1), await make_user(sm, 2)
    k = key()
    w1 = await make_watch(sm, u1, k, 100)
    assert await count(sm) == 1
    await make_watch(sm, u2, k, 90)  # same key, second user
    assert await count(sm) == 2
    assert await scalar(sm, "select count(*) from watch_keys") == 1  # dedup

    async with sm.begin() as s:
        assert await set_paused(s, user_id=u1, watch_id=w1, paused=True, now=datetime.now(UTC))
    assert await count(sm) == 1
    async with sm.begin() as s:
        assert await set_paused(s, user_id=u1, watch_id=w1, paused=False, now=datetime.now(UTC))
    assert await count(sm) == 2
    async with sm.begin() as s:
        assert await delete_watch(s, user_id=u1, watch_id=w1)
    assert await count(sm) == 1


async def test_blocking_user_freezes_watches_and_unblocking_restores(sm):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 100)
    await make_watch(sm, u, key(dest="DXB"), 100)
    assert await scalar(sm, "select sum(active_watch_count) from watch_keys") == 2
    async with sm.begin() as s:
        await mark_blocked(s, u)
    assert await scalar(sm, "select sum(active_watch_count) from watch_keys") == 0
    assert await scalar(sm, "select count(*) from watches where pause_reason='blocked'") == 2
    async with sm.begin() as s:
        await mark_unblocked(s, u)
    assert await scalar(sm, "select sum(active_watch_count) from watch_keys") == 2


async def test_user_paused_watch_is_not_resumed_by_unblock(sm):
    u = await make_user(sm, 1)
    w = await make_watch(sm, u, key(), 100)
    async with sm.begin() as s:
        await set_paused(s, user_id=u, watch_id=w, paused=True, now=datetime.now(UTC))
        await mark_blocked(s, u)
        await mark_unblocked(s, u)
    assert await scalar(sm, "select status from watches where id=:i", i=w) == "paused"


async def test_reconcile_detects_and_fixes_manual_drift(sm):
    u = await make_user(sm, 1)
    await make_watch(sm, u, key(), 100)
    async with sm.begin() as s:
        await s.execute(text("UPDATE watch_keys SET active_watch_count = 5"))
    async with sm.begin() as s:
        assert await reconcile_counts(s) == 1
    assert await count(sm) == 1
    async with sm.begin() as s:
        assert await reconcile_counts(s) == 0


async def test_unique_constraints(sm):
    u = await make_user(sm, 1)
    k = key()
    await make_watch(sm, u, k, 100)
    async with sm.begin() as s:
        await s.execute(
            text("INSERT INTO notifications (user_id, dedup_key, payload) VALUES (:u, 'x', '{}')"),
            {"u": u},
        )
    with pytest.raises(IntegrityError):
        async with sm.begin() as s:
            await s.execute(
                text("INSERT INTO notifications (user_id, dedup_key, payload) VALUES (:u, 'x', '{}')"),
                {"u": u},
            )


async def test_nulls_not_distinct_makes_one_way_keys_unique(sm):
    """The same one-way key (return_date NULL) must not create two rows (PG15+ NULLS NOT DISTINCT)."""
    u1, u2 = await make_user(sm, 1), await make_user(sm, 2)
    k = key()
    await asyncio.gather(make_watch(sm, u1, k, 100), make_watch(sm, u2, k, 100))
    assert await scalar(sm, "select count(*) from watch_keys") == 1
