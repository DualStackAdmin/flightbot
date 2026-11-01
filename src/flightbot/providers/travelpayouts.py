"""Travelpayouts / Aviasales Data API adapter (prices_for_dates).

NOTE (verify with a real token): the response fields and limits are based on the documentation
and may change. The Data API serves CACHED prices found by users in roughly the last 48 hours; it is not a guarantee
of a price that is "bookable right now". The notification text says so.

`explore()` ("anywhere" search) calls the same endpoint without `destination` and with `unique=true`:
per the docs only the cheapest ticket per destination is returned. Verify this behavior with a real token.
"""

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from flightbot import metrics
from flightbot.core.watch_key import DateMode, WatchKey
from flightbot.logging import get_logger
from flightbot.providers.base import (
    PriceQuote,
    ProviderError,
    ProviderRateLimited,
    filter_by_stay,
    next_month,
)

log = get_logger(__name__)

PRICES_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
# Round trips by length of stay: fetch more rows, because many are filtered out by the stay.
STAY_FETCH_LIMIT = 100


def _date_param(d: date, mode: DateMode) -> str:
    return d.strftime("%Y-%m") if mode is DateMode.MONTH else d.isoformat()


def parse_rows(payload: dict[str, Any], default_currency: str, provider_name: str) -> list[PriceQuote]:
    if not payload.get("success", True):
        raise ProviderError(f"provider returned success=false: {payload.get('error')}")
    quotes: list[PriceQuote] = []
    for row in payload.get("data") or []:
        try:
            depart = datetime.fromisoformat(row["departure_at"]).date()
            return_raw = row.get("return_at")
            ret = datetime.fromisoformat(return_raw).date() if return_raw else None
            price = Decimal(str(row["price"]))
            if price <= 0:
                continue
            quotes.append(
                PriceQuote(
                    price=price,
                    currency=(row.get("currency") or payload.get("currency") or default_currency).upper(),
                    depart_date=depart,
                    return_date=ret,
                    airline=row.get("airline"),
                    transfers=row.get("transfers"),
                    found_at=None,  # bu endpoint found_at vermir
                    link=row.get("link"),
                    provider=provider_name,
                    destination=(row.get("destination") or "").upper() or None,
                )
            )
        except (KeyError, ValueError, InvalidOperation, TypeError):
            log.warning("provider_bad_row", row=row)
            continue
    quotes.sort(key=lambda q: q.price)
    return quotes


def parse_offers(payload: dict[str, Any], key: WatchKey, provider_name: str) -> list[PriceQuote]:
    return parse_rows(payload, key.currency, provider_name)


class TravelpayoutsProvider:
    name = "travelpayouts"

    def __init__(
        self,
        client: httpx.AsyncClient,
        token: str,
        *,
        retries: int = 2,
        base_url: str = PRICES_URL,
    ) -> None:
        self._client = client
        self._token = token
        self._retries = retries
        self._url = base_url

    def _params(self, key: WatchKey, limit: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "origin": key.origin,
            "destination": key.destination,
            "departure_at": _date_param(key.depart_date, key.date_mode),
            "currency": key.currency.lower(),
            "sorting": "price",
            "direct": "true" if key.direct_only else "false",
            "one_way": "false" if key.is_round_trip else "true",
            "unique": "false",
            "limit": limit,
            "page": 1,
        }
        if key.return_date:
            params["return_at"] = _date_param(key.return_date, key.date_mode)
        return params

    async def _fetch(self, params: dict[str, Any]) -> dict[str, Any]:
        """Retry/backoff and error mapping: shared by all request types."""
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = await self._client.get(
                    self._url, params=params, headers={"X-Access-Token": self._token}
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                metrics.PROVIDER_REQUESTS.labels(self.name, "network_error").inc()
            else:
                if resp.status_code == 429:
                    metrics.PROVIDER_REQUESTS.labels(self.name, "429").inc()
                    raise ProviderRateLimited(float(resp.headers.get("Retry-After", 60) or 60))
                if resp.status_code >= 500:
                    metrics.PROVIDER_REQUESTS.labels(self.name, "5xx").inc()
                    last_exc = ProviderError(f"HTTP {resp.status_code}")
                elif resp.status_code in (401, 403):
                    metrics.PROVIDER_REQUESTS.labels(self.name, "auth").inc()
                    raise ProviderError(f"auth failed: HTTP {resp.status_code} (check the token/account)")
                elif resp.status_code >= 400:
                    metrics.PROVIDER_REQUESTS.labels(self.name, "4xx").inc()
                    raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    metrics.PROVIDER_REQUESTS.labels(self.name, "ok").inc()
                    try:
                        return resp.json()
                    except ValueError as exc:  # JSON decode
                        raise ProviderError(f"invalid JSON: {exc}") from exc
            if attempt < self._retries:
                await asyncio.sleep(0.5 * (3**attempt))
        raise ProviderError(f"provider unavailable: {last_exc!r}")

    async def offers(self, key: WatchKey, *, limit: int = 30, fresh: bool = False) -> list[PriceQuote]:
        if not key.has_stay:
            payload = await self._fetch(self._params(key, limit))
            return parse_offers(payload, key, self.name)
        # Round trip with a length of stay: the return can fall into the next month, so ask for both
        # return months and keep only the trips whose stay matches. Costs 2 requests (see RateLimitedProvider).
        quotes: list[PriceQuote] = []
        for return_month in (key.depart_date, next_month(key.depart_date)):
            params = self._params(key, STAY_FETCH_LIMIT)
            params["return_at"] = return_month.strftime("%Y-%m")
            quotes += parse_offers(await self._fetch(params), key, self.name)
        window = (key.window_start, key.window_end)
        return filter_by_stay(quotes, key.stay_min, key.stay_max, window)[:limit]

    async def explore(
        self,
        *,
        origin: str,
        month: date,
        currency: str,
        direct_only: bool = False,
        limit: int = 20,
        fresh: bool = False,
        stay: tuple[int, int] | None = None,
    ) -> list[PriceQuote]:
        params: dict[str, Any] = {
            "origin": origin,
            "departure_at": month.strftime("%Y-%m"),
            "currency": currency.lower(),
            "sorting": "price",
            "direct": "true" if direct_only else "false",
            "one_way": "true",
            "unique": "true",  # only the cheapest per destination when no destination is given
            "limit": max(limit * 3, 30),  # enough left after filtering (origin==dest, duplicates)
            "page": 1,
        }
        if stay is None:
            quotes = parse_rows(await self._fetch(params), currency, self.name)
        else:
            quotes = []
            for return_month in (month, next_month(month)):
                quotes += parse_rows(
                    await self._fetch(
                        {**params, "one_way": "false", "return_at": return_month.strftime("%Y-%m")}
                    ),
                    currency,
                    self.name,
                )
            last_day = next_month(month) - timedelta(days=1)
            quotes = filter_by_stay(quotes, stay[0], stay[1], (month.replace(day=1), last_day))
        best: dict[str, PriceQuote] = {}
        for q in quotes:  # sorted by price ascending
            if q.destination and q.destination != origin and q.destination not in best:
                best[q.destination] = q
        return list(best.values())[:limit]
