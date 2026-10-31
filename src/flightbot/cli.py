"""Admin CLI: `python -m flightbot.cli stats | grant-pro | revoke-pro`.

Ödəniş (Telegram Stars) əlavə olunana qədər Pro planı əl ilə verməyin yoludur.
`stats` spesifikasiyadakı uğur metriklərini verir: aktiv istifadəçilər, bildiriş keyfiyyəti (👍/👎), bloklama faizi.
"""

import argparse
import asyncio
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flightbot.config import get_settings
from flightbot.core.clock import utcnow
from flightbot.db.session import create_engine, create_sessionmaker

STATS_SQL = {
    "users_total": "SELECT count(*) FROM users",
    "users_pro": "SELECT count(*) FROM users WHERE plan = 'pro' AND (plan_expires_at IS NULL OR plan_expires_at > now())",
    "users_blocked": "SELECT count(*) FROM users WHERE is_blocked",
    "users_active_7d": "SELECT count(*) FROM users WHERE last_seen_at > now() - interval '7 days'",
    "users_with_watch": "SELECT count(DISTINCT user_id) FROM watches WHERE status = 'active'",
    "watches_active": "SELECT count(*) FROM watches WHERE status = 'active'",
    "watch_keys_active": "SELECT count(*) FROM watch_keys WHERE active_watch_count > 0",
    "notifications_pending": "SELECT count(*) FROM notifications WHERE status IN ('pending', 'sending')",
    "notifications_sent_7d": "SELECT count(*) FROM notifications WHERE status = 'sent' AND sent_at > now() - interval '7 days'",
    "notifications_failed_7d": "SELECT count(*) FROM notifications WHERE status = 'failed' AND created_at > now() - interval '7 days'",
    "feedback_up": "SELECT count(*) FROM notifications WHERE feedback = 1",
    "feedback_down": "SELECT count(*) FROM notifications WHERE feedback = -1",
}


async def collect_stats(sm: async_sessionmaker[AsyncSession]) -> dict[str, float | int]:
    out: dict[str, float | int] = {}
    async with sm() as s:
        for name, sql in STATS_SQL.items():
            out[name] = int((await s.execute(text(sql))).scalar() or 0)
    votes = out["feedback_up"] + out["feedback_down"]
    out["feedback_down_pct"] = round(100 * out["feedback_down"] / votes, 1) if votes else 0.0
    out["blocked_pct"] = (
        round(100 * out["users_blocked"] / out["users_total"], 1) if out["users_total"] else 0.0
    )
    return out


async def set_plan(
    sm: async_sessionmaker[AsyncSession], *, telegram_id: int, plan: str, days: int | None
) -> bool:
    expires = utcnow() + timedelta(days=days) if (plan == "pro" and days) else None
    async with sm.begin() as s:
        res = await s.execute(
            text("UPDATE users SET plan = :p, plan_expires_at = :e WHERE telegram_id = :t"),
            {"p": plan, "e": expires, "t": telegram_id},
        )
        return (res.rowcount or 0) > 0


async def _run(args: argparse.Namespace) -> int:
    engine = create_engine(get_settings())
    sm = create_sessionmaker(engine)
    try:
        if args.cmd == "stats":
            for k, v in (await collect_stats(sm)).items():
                print(f"{k:26} {v}")
        elif args.cmd == "grant-pro":
            ok = await set_plan(sm, telegram_id=args.telegram_id, plan="pro", days=args.days)
            print("OK" if ok else "istifadəçi tapılmadı")
            return 0 if ok else 1
        elif args.cmd == "revoke-pro":
            ok = await set_plan(sm, telegram_id=args.telegram_id, plan="free", days=None)
            print("OK" if ok else "istifadəçi tapılmadı")
            return 0 if ok else 1
    finally:
        await engine.dispose()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="flightbot.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats", help="əsas göstəricilər")
    g = sub.add_parser("grant-pro", help="Pro plan ver")
    g.add_argument("telegram_id", type=int)
    g.add_argument("--days", type=int, default=30, help="müddət (0 = müddətsiz)")
    r = sub.add_parser("revoke-pro", help="Pro planı geri al")
    r.add_argument("telegram_id", type=int)
    args = ap.parse_args()
    if args.cmd == "grant-pro" and args.days == 0:
        args.days = None
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
