"""Bot prosesi: `python -m flightbot.bot`. Polling (dev) və ya webhook (prod, aiohttp)."""

import asyncio
import contextlib
import signal
from datetime import timedelta

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage
from aiogram.types import BotCommand, ErrorEvent
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flightbot import __version__
from flightbot.bot.deps import Deps
from flightbot.bot.handlers import chat_member, fallback, feedback, flow, start, watches_list
from flightbot.bot.handlers import settings as settings_handlers
from flightbot.bot.i18n import SUPPORTED, t
from flightbot.bot.middlewares import DbSessionMiddleware, ThrottlingMiddleware, UserMiddleware
from flightbot.config import Settings, get_settings
from flightbot.db.session import create_engine, create_sessionmaker
from flightbot.logging import get_logger, setup_logging
from flightbot.metrics import start_metrics_server
from flightbot.providers.base import PriceProvider
from flightbot.providers.factory import build_http_client, build_names, build_places, build_provider
from flightbot.providers.names import PlaceNames
from flightbot.providers.places import PlacesProvider

log = get_logger(__name__)
COMMANDS = ("new", "explore", "list", "search", "settings", "help", "delete", "cancel")
FSM_TTL = timedelta(days=3)  # Redis-də bütün açarlar TTL-lidir (volatile-lru təhlükəsizdir)


async def on_error(event: ErrorEvent, settings: Settings) -> bool:
    log.error("update_error", exc_info=event.exception)
    text_ = t(settings.default_language, "error.generic")
    update = event.update
    with contextlib.suppress(Exception):
        if update.callback_query:
            await update.callback_query.answer(text_, show_alert=True)
        elif update.message:
            await update.message.answer(text_)
    return True


def create_dispatcher(
    settings: Settings,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    provider: PriceProvider,
    places: PlacesProvider,
    names: PlaceNames | None = None,
    throttle: tuple[float, int] = (2.0, 6),
) -> Dispatcher:
    storage = RedisStorage(
        redis, key_builder=DefaultKeyBuilder(prefix="fsm"), state_ttl=FSM_TTL, data_ttl=FSM_TTL
    )
    deps = Deps(provider, places, names or PlaceNames(None, None, remote=False), settings)
    dp = Dispatcher(storage=storage, settings=settings, deps=deps)
    # Sıra vacibdir: throttle (ucuz) -> DB sessiyası -> istifadəçi
    dp.update.outer_middleware(ThrottlingMiddleware(redis, rate=throttle[0], burst=throttle[1]))
    dp.update.outer_middleware(DbSessionMiddleware(sessionmaker))
    dp.update.outer_middleware(UserMiddleware(settings))
    # Sıra vacibdir: /start /help /cancel əvvəl, sonra axın, sonra qalanlar
    dp.include_routers(
        start.router,
        flow.router,
        watches_list.router,
        settings_handlers.router,
        feedback.router,
        chat_member.router,
        fallback.router,  # həmişə sonuncu: heç nəyə uyğun gəlməyən hər şeyi tutur
    )
    dp.errors.register(on_error)
    return dp


async def set_commands(bot: Bot, default_language: str) -> None:
    for lang in SUPPORTED:
        await bot.set_my_commands(
            [BotCommand(command=c, description=t(lang, f"cmd.{c}")) for c in COMMANDS],
            language_code=lang,
        )
    await bot.set_my_commands(
        [BotCommand(command=c, description=t(default_language, f"cmd.{c}")) for c in COMMANDS]
    )


def build_webhook_app(
    bot: Bot, dp: Dispatcher, settings: Settings, engine: AsyncEngine, redis: Redis
) -> web.Application:
    """Webhook + /healthz. Telegram `X-Telegram-Bot-Api-Secret-Token` başlığı yoxlanılır:
    yanlış/boş token 401 qaytarır (kənar şəxs saxta update göndərə bilməz)."""
    secret = settings.webhook_secret.get_secret_value()
    if not secret:
        raise RuntimeError("webhook rejimi üçün WEBHOOK_SECRET təyin edilməlidir")
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(
        app, path=settings.webhook_path
    )
    setup_application(app, dp, bot=bot)

    async def healthz(_: web.Request) -> web.Response:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await redis.ping()
        except Exception as exc:  # noqa: BLE001
            log.error("healthz_failed", error=repr(exc))
            return web.json_response({"status": "unhealthy"}, status=503)
        return web.json_response({"status": "ok", "version": __version__})

    app.router.add_get("/healthz", healthz)
    return app


async def run_webhook(
    bot: Bot, dp: Dispatcher, settings: Settings, engine: AsyncEngine, redis: Redis
) -> None:
    if not settings.webhook_base_url:
        raise RuntimeError("webhook rejimi üçün WEBHOOK_BASE_URL təyin edilməlidir")
    app = build_webhook_app(bot, dp, settings, engine, redis)
    await bot.set_webhook(
        url=settings.webhook_base_url.rstrip("/") + settings.webhook_path,
        secret_token=settings.webhook_secret.get_secret_value(),
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, settings.web_host, settings.web_port).start()
    log.info("webhook_started", port=settings.web_port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await runner.cleanup()


async def amain() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    token = settings.bot_token.get_secret_value()
    if not token:
        raise SystemExit("BOT_TOKEN təyin edilməyib (.env faylına baxın)")
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.env, release=__version__)
    start_metrics_server(settings.metrics_port)

    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    redis = Redis.from_url(settings.redis_url)
    http = build_http_client(settings)
    provider = build_provider(settings, redis, http)
    places = build_places(settings, http)
    names = build_names(settings, redis, http)
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = create_dispatcher(
        settings, sessionmaker=sessionmaker, redis=redis, provider=provider, places=places, names=names
    )
    try:
        await set_commands(bot, settings.default_language)
        log.info("bot_starting", mode=settings.bot_mode, provider=settings.provider, version=__version__)
        if settings.bot_mode == "webhook":
            await run_webhook(bot, dp, settings, engine, redis)
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        with contextlib.suppress(Exception):
            await bot.session.close()
            await http.aclose()
            await redis.aclose()
            await engine.dispose()


def main() -> None:
    asyncio.run(amain())
