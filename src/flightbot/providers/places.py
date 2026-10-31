"""City/airport search (the user doesn't have to know the IATA code)."""

from typing import Protocol

import httpx

from flightbot.core.places import Place, search_static
from flightbot.logging import get_logger

log = get_logger(__name__)

AUTOCOMPLETE_URL = "https://autocomplete.travelpayouts.com/places2"


class PlacesProvider(Protocol):
    async def search(self, term: str, lang: str) -> list[Place]: ...


class StaticPlaces:
    async def search(self, term: str, lang: str) -> list[Place]:
        return search_static(term, lang)


class TravelpayoutsPlaces:
    """Travelpayouts autocomplete (verify the response format with a real request)."""

    def __init__(self, client: httpx.AsyncClient, url: str = AUTOCOMPLETE_URL) -> None:
        self._client = client
        self._url = url

    async def search(self, term: str, lang: str) -> list[Place]:
        resp = await self._client.get(
            self._url,
            params=[
                ("term", term),
                ("locale", lang if lang in ("en", "ru") else "en"),
                ("types[]", "city"),
                ("types[]", "airport"),
            ],
        )
        resp.raise_for_status()
        out: list[Place] = []
        for row in resp.json():
            code = (row.get("code") or "").upper()
            if len(code) != 3:
                continue
            out.append(
                Place(
                    code=code,
                    name=row.get("name") or code,
                    country=row.get("country_name"),
                    kind=row.get("type") or "city",
                )
            )
        return out[:6]


class FallbackPlaces:
    """Falls back to the static list if the primary provider fails or returns nothing."""

    def __init__(self, primary: PlacesProvider, fallback: PlacesProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def search(self, term: str, lang: str) -> list[Place]:
        try:
            found = await self._primary.search(term, lang)
            if found:
                return found
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("places_primary_failed", error=repr(exc))
        return await self._fallback.search(term, lang)
