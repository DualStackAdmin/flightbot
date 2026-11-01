"""Worker process: `python -m flightbot.workers [--roles poller,broadcaster,janitor]`.

All roles work via SKIP LOCKED, so any number of replicas is safe.
"""

import argparse
import asyncio
import contextlib
import signal

from aiogram import Bot
from redis.asyncio import Redis

from flightbot import __version__
from flightbot.config import get_settings
from flightbot.core.clock import utcnow
from flightbot.db.session import create_engine, create_sessionmaker
from flightbot.logging import get_logger, sentry_before_send, setup_logging
from flightbot.metrics import start_metrics_server
from flightbot.providers.factory import build_http_client, build_provider
from flightbot.workers import janitor
from flightbot.workers.broadcaster import Broadcaster
from flightbot.workers.poller import Poller

ALL_ROLES = ("poller", "broadcaster", "janitor")


async def amain(roles: set[str]) -> None:
    settings = get_settings()
    setup_logging(
        settings.log_level,
        settings.log_json,
        secrets=[
            settings.bot_token.get_secret_value(),
            settings.travelpayouts_token.get_secret_value(),
            settings.webhook_secret.get_secret_value(),
        ],
    )
    log = get_logger("worker")
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.env,
            release=__version__,
            send_default_pii=False,
            before_send=sentry_before_send,
        )
    start_metrics_server(settings.metrics_port)

    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    redis = Redis.from_url(settings.redis_url)
    http = build_http_client(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    bot: Bot | None = None
    tasks: list[asyncio.Task] = []
    try:
        if "poller" in roles:
            provider = build_provider(settings, redis, http)
            tasks.append(asyncio.create_task(Poller(sessionmaker, provider, settings).run_forever(stop)))
        if "broadcaster" in roles:
            token = settings.bot_token.get_secret_value()
            if not token:
                raise RuntimeError("BOT_TOKEN must be set for the broadcaster")
            bot = Bot(token=token)
            broadcaster = Broadcaster(
                bot, sessionmaker, redis, settings, marker=settings.travelpayouts_marker
            )
            tasks.append(asyncio.create_task(broadcaster.run_forever(stop)))
        if "janitor" in roles:
            tasks.append(
                asyncio.create_task(
                    janitor.run_forever(
                        sessionmaker, stop, settings.janitor_interval_s, lambda: utcnow().date()
                    )
                )
            )
        log.info("workers_running", roles=sorted(roles), provider=settings.provider)
        await stop.wait()
        log.info("shutdown_requested")
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            if bot is not None:
                await bot.session.close()
            await http.aclose()
            await redis.aclose()
            await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="FlightBot workers")
    parser.add_argument(
        "--roles", default=",".join(ALL_ROLES), help="comma-separated: " + ",".join(ALL_ROLES)
    )
    args = parser.parse_args()
    roles = {r.strip() for r in args.roles.split(",") if r.strip()}
    unknown = roles - set(ALL_ROLES)
    if unknown:
        raise SystemExit(f"unknown role(s): {sorted(unknown)}")
    asyncio.run(amain(roles))


if __name__ == "__main__":
    main()
