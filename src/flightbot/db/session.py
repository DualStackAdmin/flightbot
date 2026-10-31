from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from flightbot.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict = {}
    if settings.db_statement_cache_size != 100:
        # DB_STATEMENT_CACHE_SIZE=0 for PgBouncer transaction mode
        connect_args["statement_cache_size"] = settings.db_statement_cache_size
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
