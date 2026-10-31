import asyncio
import os
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from flightbot.config import Settings

TEST_DB = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://flightbot:flightbot@localhost:5432/flightbot_test"
)
TEST_REDIS = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")
ROOT = os.path.dirname(os.path.dirname(__file__))


def pytest_collection_modifyitems(items):
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        env="test",
        database_url=TEST_DB,
        redis_url=TEST_REDIS,
        poller_batch=20,
        poller_concurrency=5,
        broadcaster_batch=40,
        broadcaster_max_attempts=3,
        telegram_global_rps=1000.0,  # testlərdə qlobal limit mane olmasın
        telegram_user_rps=1.0,
        provider_rps=1000.0,
        quiet_start_hour=0,  # testlərdə sakit saatlar söndürülüb (bərabər = söndürülüb);
        quiet_end_hour=0,  # konkret testlər onu özləri aktivləşdirir
    )


def _alembic_config() -> Config:
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB)
    return cfg


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DB, pool_size=20, max_overflow=20)
    try:
        async with eng.connect() as c:
            await c.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL əlçatmazdır ({exc!r}); integration testləri atlanır")
    async with eng.begin() as c:
        await c.execute(text("DROP SCHEMA public CASCADE"))
        await c.execute(text("CREATE SCHEMA public"))
    cfg = _alembic_config()
    # env.py daxilində asyncio.run istifadə olunur, ona görə ayrı thread-də
    await asyncio.to_thread(command.upgrade, cfg, "head")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sm(engine) -> async_sessionmaker[AsyncSession]:
    async with engine.begin() as c:
        await c.execute(
            text("TRUNCATE notifications, price_points, watches, watch_keys, users RESTART IDENTITY CASCADE")
        )
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def redis():
    r = Redis.from_url(TEST_REDIS)
    try:
        await r.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis əlçatmazdır ({exc!r})")
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()


class MutableClock:
    """Test üçün idarə olunan saat."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now
