from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flightbot.core.users import get_or_create_user
from flightbot.core.watch_key import DateMode, WatchKey
from flightbot.core.watches import create_or_update_watch
from flightbot.db.models import User
from flightbot.providers.base import PriceQuote


def today() -> date:
    return datetime.now(UTC).date()


def key(
    origin="GYD",
    dest="IST",
    *,
    days=30,
    mode=DateMode.EXACT,
    ret_days=None,
    direct=False,
    currency="USD",
) -> WatchKey:
    t = today()
    return WatchKey.create(
        origin=origin,
        destination=dest,
        date_mode=mode,
        depart_date=t + timedelta(days=days),
        return_date=(t + timedelta(days=ret_days)) if ret_days else None,
        direct_only=direct,
        currency=currency,
        today=t,
    )


async def make_user(sm: async_sessionmaker[AsyncSession], tg_id: int, *, plan="free", lang="az") -> int:
    async with sm.begin() as s:
        user, _ = await get_or_create_user(
            s,
            tenant_id=1,
            telegram_id=tg_id,
            language_hint=lang,
            default_language="az",
            default_home_iata="GYD",
            now=datetime.now(UTC),
        )
        uid = user.id
        if plan != "free":
            await s.execute(text("UPDATE users SET plan = :p WHERE id = :id"), {"p": plan, "id": uid})
    return uid


async def make_watch(sm, user_id: int, k: WatchKey, target: str | int | Decimal) -> int:
    async with sm.begin() as s:
        watch, _ = await create_or_update_watch(
            s, user_id=user_id, key=k, target_price=Decimal(str(target)), now=datetime.now(UTC)
        )
        return watch.id


async def make_due(sm) -> None:
    async with sm.begin() as s:
        await s.execute(
            text("UPDATE watch_keys SET next_check_at = now() - interval '1 second', lease_until = NULL")
        )


async def scalar(sm, sql: str, **params):
    async with sm() as s:
        return (await s.execute(text(sql), params)).scalar()


async def rows(sm, sql: str, **params):
    async with sm() as s:
        return (await s.execute(text(sql), params)).all()


class ScriptedProvider:
    """A provider with pre-scripted responses. The last element repeats."""

    name = "scripted"

    def __init__(self, *script) -> None:
        self.script = list(script)
        self.calls = 0
        self.fresh_calls = 0
        self.explore_result: list | Exception | None = None  # explore() response: a list or an exception
        self.explore_calls = 0

    def set(self, *script) -> None:
        self.script = list(script)

    async def offers(self, k: WatchKey, *, limit: int = 30, fresh: bool = False):
        self.calls += 1
        if fresh:
            self.fresh_calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        if item is None:
            return []
        return [
            PriceQuote(
                price=Decimal(str(item)),
                currency=k.currency,
                depart_date=k.depart_date,
                return_date=k.return_date,
                airline="TK",
                transfers=0,
                found_at=None,
                link=None,
                provider=self.name,
            )
        ]

    async def explore(self, *, origin, month, currency, direct_only=False, limit=20, fresh=False):
        self.explore_calls += 1
        res = self.explore_result
        if isinstance(res, Exception):
            raise res
        return list(res or [])[:limit]


class FakeBot:
    """Stand-in for the aiogram Bot. Exceptions in the `errors` queue are raised in order (None = success)."""

    def __init__(self, *errors) -> None:
        self.errors = list(errors)
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        if self.errors:
            exc = self.errors.pop(0)
            if exc is not None:
                raise exc
        self.sent.append(kwargs)
        return SimpleNamespace(message_id=1000 + len(self.sent))


async def get_user(sm, uid: int) -> User:
    async with sm() as s:
        return (await s.execute(text("select 1"))) and await s.get(User, uid)
