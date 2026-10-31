import httpx
from redis.asyncio import Redis

from flightbot.config import Settings
from flightbot.core.clock import utcnow
from flightbot.providers.base import PriceProvider
from flightbot.providers.fake import FakeProvider
from flightbot.providers.names import PlaceNames
from flightbot.providers.places import (
    FallbackPlaces,
    PlacesProvider,
    StaticPlaces,
    TravelpayoutsPlaces,
)
from flightbot.providers.travelpayouts import TravelpayoutsProvider
from flightbot.providers.wrappers import CachedProvider, RateLimitedProvider
from flightbot.ratelimit import TokenBucket


def build_http_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.provider_timeout_s, connect=5.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


def build_provider(settings: Settings, redis: Redis, http: httpx.AsyncClient) -> PriceProvider:
    """Cached(RateLimited(Raw)): əvvəl keş, keş boşdursa paylaşılan RPS limiti, sonra real sorğu."""
    raw: PriceProvider
    if settings.provider == "travelpayouts":
        token = settings.travelpayouts_token.get_secret_value()
        if not token:
            raise RuntimeError("PROVIDER=travelpayouts üçün TRAVELPAYOUTS_TOKEN təyin edilməlidir")
        raw = TravelpayoutsProvider(http, token)
    else:
        raw = FakeProvider()
    limited = RateLimitedProvider(raw, TokenBucket(redis), rps=settings.provider_rps)
    return CachedProvider(limited, redis, today_fn=lambda: utcnow().date())


def build_places(settings: Settings, http: httpx.AsyncClient) -> PlacesProvider:
    if settings.provider == "travelpayouts":
        return FallbackPlaces(TravelpayoutsPlaces(http), StaticPlaces())
    return StaticPlaces()


def build_names(settings: Settings, redis: Redis, http: httpx.AsyncClient) -> PlaceNames:
    """Fake rejimdə yalnız statik adlar (şəbəkəyə çıxmır)."""
    return PlaceNames(redis, http, remote=settings.provider == "travelpayouts")
