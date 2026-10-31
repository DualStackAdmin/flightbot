"""Load / scale check (local, real Postgres + Redis, fake Telegram and provider).

Usage:  python -m scripts.loadtest --yes [--users 7000 --keys 1000 --per-user 3]
WARNING: this DELETES all watch data in the DATABASE_URL database. Use it on a dev/test database only.

What it verifies:
  1. Fan-out: N watches -> only K provider requests (does dedup work?)
  2. Daily limit: no Free user receives more than 3 notifications?
  3. No duplicates: the same price in the second cycle creates no new notification?
  4. Throughput of the broadcaster pipeline (without the Telegram network)
  5. Does the scheduler claim query use the index on a large table?
"""

import argparse
import asyncio
import time
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import text

from flightbot.config import Settings, get_settings
from flightbot.db.session import create_engine, create_sessionmaker
from flightbot.providers.base import PriceQuote
from flightbot.workers.broadcaster import Broadcaster
from flightbot.workers.poller import Poller

DESTS = "ARRAY['IST','DXB','TBS','LON','PAR','BER','ROM','AMS','MAD','PRG']"


class BulkProvider:
    name = "bulk"

    def __init__(self) -> None:
        self.calls = 0

    async def offers(self, key, *, limit=30, fresh=False):
        self.calls += 1
        price = 60 + (hash(key.cache_id()) % 240)
        return [
            PriceQuote(Decimal(price), key.currency, key.depart_date, None, "TK", 0, None, None, self.name)
        ]


class NullBot:
    def __init__(self) -> None:
        self.sent = 0

    async def send_message(self, **kw):
        self.sent += 1

        class M:
            message_id = 1

        return M()


async def seed(sm, users: int, keys: int, per_user: int) -> None:
    async with sm.begin() as s:
        await s.execute(
            text("TRUNCATE notifications, price_points, watches, watch_keys, users RESTART IDENTITY CASCADE")
        )
        await s.execute(
            text("INSERT INTO users (telegram_id, language) SELECT g, 'az' FROM generate_series(1, :n) g"),
            {"n": users},
        )
        await s.execute(
            text(
                f"INSERT INTO watch_keys (origin, destination, date_mode, depart_date, direct_only, currency, expires_on) "
                f"SELECT 'GYD', ({DESTS})[1 + (g % 10)], 'exact', current_date + 10 + (g / 10), false, 'USD', "
                f"current_date + 10 + (g / 10) FROM generate_series(0, :k - 1) g"
            ),
            {"k": keys},
        )
        await s.execute(
            text(
                "INSERT INTO watches (user_id, watch_key_id, target_price) "
                "SELECT u.id, 1 + ((u.id * 7 + j * 131) % :k), 50 + (random() * 350)::int "
                "FROM users u CROSS JOIN generate_series(0, :p - 1) j"
            ),
            {"k": keys, "p": per_user},
        )


async def one(sm, sql, **p):
    async with sm() as s:
        return (await s.execute(text(sql), p)).scalar()


async def main(users: int, keys: int, per_user: int) -> None:
    base = get_settings()
    settings = Settings(
        **{
            **base.model_dump(),
            "poller_batch": 100,
            "poller_concurrency": 10,
            "broadcaster_batch": 200,
            "broadcaster_concurrency": 20,
            "telegram_global_rps": 1_000_000.0,
            "telegram_user_rps": 1_000_000.0,
            "quiet_start_hour": 0,  # quiet hours disabled: the measurement must not depend on the time of day
            "quiet_end_hour": 0,
        }
    )
    engine = create_engine(settings)
    sm = create_sessionmaker(engine)
    redis = Redis.from_url(settings.redis_url)
    await redis.flushdb()

    print(f"Seed: {users} users x {per_user} watches, {keys} unique routes ...")
    t0 = time.perf_counter()
    await seed(sm, users, keys, per_user)
    n_watches = await one(sm, "select count(*) from watches")
    n_keys = await one(sm, "select count(*) from watch_keys")
    ratio = n_watches / n_keys
    print(
        f"  {n_watches} watches, {n_keys} unique keys (avg {ratio:.1f} subscribers per key), {time.perf_counter() - t0:.1f}s"
    )

    provider = BulkProvider()
    poller = Poller(sm, provider, settings)
    t0 = time.perf_counter()
    while await poller.run_once():
        pass
    dt = time.perf_counter() - t0
    notifs = await one(sm, "select count(*) from notifications")
    max_per_user = await one(
        sm, "select max(c) from (select count(*) c from notifications group by user_id) x"
    )
    print(
        f"\n[1] Poller: {dt:.1f}s, provider requests = {provider.calls} (watches: {n_watches}) -> {n_watches / provider.calls:.1f}x reduction"
    )
    print(f"    notifications created: {notifs}; max per user: {max_per_user} (Free limit 3)")
    assert provider.calls == n_keys, "every key should have been requested exactly once"
    assert max_per_user <= 3, "daily limit violated!"

    before = notifs
    provider.calls = 0
    async with sm.begin() as s:
        await s.execute(
            text("UPDATE watch_keys SET next_check_at = now() - interval '1 second', lease_until = NULL")
        )
    while await poller.run_once():
        pass
    after = await one(sm, "select count(*) from notifications")
    print(
        f"[3] Second cycle (price unchanged): new notifications = {after - before} (no duplicates: {after == before})"
    )
    assert after == before

    bot = NullBot()
    bc = Broadcaster(bot, sm, redis, settings, marker="bench")
    t0 = time.perf_counter()
    while await bc.run_once():
        pass
    dt = time.perf_counter() - t0
    sent = await one(sm, "select count(*) from notifications where status='sent'")
    print(
        f"[4] Broadcaster (no Telegram network, fake bot): {sent} notifications / {dt:.1f}s = {sent / dt:.0f} msg/s pipeline ceiling"
    )
    print(f"    (the real ceiling is set by the Telegram limit: ~25 msg/s => {sent / 25 / 60:.1f} minutes)")

    # 5. Index usage of the claim query (large table)
    print("\n[5] Claim query plan: 300,000 'inactive' keys + 2,000 due active keys ...")
    async with sm.begin() as s:
        await s.execute(
            text(
                "INSERT INTO watch_keys (origin, destination, date_mode, depart_date, direct_only, currency, expires_on, active_watch_count) "
                "SELECT 'X' || chr(65 + ((g / 26) % 26)) || chr(65 + ((g / 676) % 26)), "
                "'Y' || chr(65 + (g % 26)) || 'A', 'exact', current_date + ((g / 17576) % 300), false, 'USD', "
                "current_date + 300, 0 FROM generate_series(0, 299999) g"
            )
        )
        await s.execute(
            text(
                "UPDATE watch_keys SET active_watch_count = 1, next_check_at = now() - interval '1 hour', lease_until = NULL "
                "WHERE id IN (SELECT id FROM watch_keys WHERE active_watch_count = 0 ORDER BY id LIMIT 2000)"
            )
        )
    async with engine.connect() as conn:
        await conn.execute(text("ANALYZE watch_keys"))
        await conn.commit()
    async with sm() as s:
        plan = (
            await s.execute(
                text(
                    "EXPLAIN (ANALYZE, COSTS OFF, TIMING ON) SELECT id FROM watch_keys "
                    "WHERE active_watch_count > 0 AND next_check_at <= now() "
                    "AND (lease_until IS NULL OR lease_until < now()) "
                    "ORDER BY next_check_at LIMIT 100 FOR UPDATE SKIP LOCKED"
                )
            )
        ).all()
        await s.rollback()
    for (line,) in plan:
        print("   ", line)
    total = await one(sm, "select count(*) from watch_keys")
    print(f"    table: {total} rows")

    await redis.flushdb()
    await redis.aclose()
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="I confirm that the database will be wiped")
    ap.add_argument("--users", type=int, default=7000)
    ap.add_argument("--keys", type=int, default=1000)
    ap.add_argument("--per-user", type=int, default=3)
    a = ap.parse_args()
    if not a.yes:
        raise SystemExit("--yes not given: aborting because the database would be wiped")
    asyncio.run(main(a.users, a.keys, a.per_user))
