from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import partial
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Update
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flightbot.bot.i18n import t
from flightbot.config import Settings
from flightbot.core.clock import utcnow
from flightbot.core.users import get_or_create_user
from flightbot.logging import get_logger
from flightbot.ratelimit import TokenBucket

log = get_logger(__name__)
Handler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


class ThrottlingMiddleware(BaseMiddleware):
    """İstifadəçi başına: saniyədə ~2 əməliyyat, 6-lıq burst. Redis-də olduğu üçün bütün replikalarda eyni."""

    def __init__(self, redis: Redis, rate: float = 2.0, burst: int = 6) -> None:
        self._bucket = TokenBucket(redis)
        self._rate, self._burst = rate, burst

    async def __call__(self, handler: Handler, event: Update, data: dict[str, Any]) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is not None and (event.message or event.callback_query):
            wait = await self._bucket.acquire(f"ui:{tg_user.id}", rate=self._rate, capacity=self._burst)
            if wait > 0:
                log.debug("throttled", tg_user=tg_user.id)
                if event.callback_query:
                    await event.callback_query.answer("⏳")
                return None
        return await handler(event, data)


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def __call__(self, handler: Handler, event: Update, data: dict[str, Any]) -> Any:
        async with self._sm() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except BaseException:
                await session.rollback()
                raise


class UserMiddleware(BaseMiddleware):
    """İstifadəçini tapır/yaradır, `user`, `is_new_user` və `tr` (dilə bağlı tərcümə) yeridir."""

    def __init__(self, settings: Settings, clock: Callable[[], datetime] = utcnow) -> None:
        self._settings = settings
        self._clock = clock

    async def __call__(self, handler: Handler, event: Update, data: dict[str, Any]) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)
        session: AsyncSession = data["session"]
        user, created = await get_or_create_user(
            session,
            tenant_id=self._settings.default_tenant_id,
            telegram_id=tg_user.id,
            language_hint=tg_user.language_code,
            default_language=self._settings.default_language,
            default_home_iata=self._settings.default_home_iata,
            now=self._clock(),
        )
        # Commit: DB bağlantısı pula qayıdır. Provayder çağırışı kimi uzun handler-lər bağlantı tutmur.
        await session.commit()
        data["user"] = user
        data["is_new_user"] = created
        data["tr"] = partial(t, user.language)
        return await handler(event, data)
