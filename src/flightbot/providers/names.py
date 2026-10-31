"""Şəhər/ölkə adlarının həlli ("hər yerə" nəticələrində dünya şəhərləri üçün).

Əvvəl statik siyahı (az/ru/en adlar), sonra Travelpayouts-un açıq `cities.json` datası (ingiliscə ad + ölkə kodu,
Redis-də 7 gün keşlənir), axırda kodun özü. Format real sorğu ilə yoxlanmalıdır; uğursuz olsa sistem sınmır,
yalnız statik adlar və kod göstərilir.
"""

import asyncio
import time
from dataclasses import dataclass

import httpx
import orjson
from redis.asyncio import Redis

from flightbot.core.places import COUNTRY, STATIC_PLACES
from flightbot.logging import get_logger

log = get_logger(__name__)

CITIES_URL = "https://api.travelpayouts.com/data/en/cities.json"
REDIS_KEY = "places:cities:v1"
CACHE_TTL_S = 7 * 24 * 3600
RETRY_AFTER_FAILURE_S = 600


@dataclass(frozen=True, slots=True)
class PlaceInfo:
    name: str
    country: str | None


class PlaceNames:
    def __init__(self, redis: Redis | None, http: httpx.AsyncClient | None, *, remote: bool) -> None:
        self._redis = redis
        self._http = http
        self._remote = remote and redis is not None and http is not None
        self._map: dict[str, tuple[str, str | None]] = {}
        self._lock = asyncio.Lock()
        self._failed_until = 0.0

    @staticmethod
    def parse_cities(rows: list[dict]) -> dict[str, tuple[str, str | None]]:
        out: dict[str, tuple[str, str | None]] = {}
        for r in rows:
            code = (r.get("code") or "").upper()
            name = r.get("name") or (r.get("name_translations") or {}).get("en")
            if len(code) == 3 and name:
                out[code] = (name, (r.get("country_code") or "").upper() or None)
        return out

    async def ensure_loaded(self) -> None:
        if not self._remote or self._map or time.monotonic() < self._failed_until:
            return
        async with self._lock:
            if self._map:
                return
            try:
                raw = await self._redis.get(REDIS_KEY)
                if raw is not None:
                    self._map = {k: (v[0], v[1]) for k, v in orjson.loads(raw).items()}
                    return
                resp = await self._http.get(CITIES_URL)
                resp.raise_for_status()
                self._map = self.parse_cities(resp.json())
                if self._map:
                    await self._redis.set(REDIS_KEY, orjson.dumps(self._map), ex=CACHE_TTL_S)
            except Exception as exc:  # noqa: BLE001  (ad həlli kritik deyil)
                log.warning("place_names_load_failed", error=repr(exc))
                self._failed_until = time.monotonic() + RETRY_AFTER_FAILURE_S

    async def lookup(self, code: str, lang: str) -> PlaceInfo:
        code = code.upper()
        static = STATIC_PLACES.get(code)
        if static:
            return PlaceInfo(static.get(lang) or static["en"], COUNTRY.get(code))
        await self.ensure_loaded()
        if code in self._map:
            name, cc = self._map[code]
            return PlaceInfo(name, cc)
        return PlaceInfo(code, None)
