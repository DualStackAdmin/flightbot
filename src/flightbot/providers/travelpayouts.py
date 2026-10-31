"""Travelpayouts / Aviasales Data API adapteri (prices_for_dates).

DİQQƏT (real token ilə mütləq yoxlayın): cavab sahələri və limitlər sənədləşmədəki
məlumata əsaslanır və dəyişə bilər. Data API son ~48 saatda istifadəçilərin tapdığı
KEŞLƏNMİŞ qiymətləri verir, "indi alına bilən" qiymətin zəmanəti deyil. Bildiriş mətni bunu qeyd edir.

`explore()` (hər yerə axtarışı) `destination` verilmədən və `unique=true` ilə eyni endpoint-i çağırır:
sənədə görə hər istiqamət üçün yalnız ən ucuz bilet qayıdır. Bu davranışı real tokenlə yoxlayın.
"""

import asyncio
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from flightbot import metrics
from flightbot.core.watch_key import DateMode, WatchKey
from flightbot.logging import get_logger
from flightbot.providers.base import PriceQuote, ProviderError, ProviderRateLimited

log = get_logger(__name__)

PRICES_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


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
            "one_way": "false" if key.return_date else "true",
            "unique": "false",
            "limit": limit,
            "page": 1,
        }
        if key.return_date:
            params["return_at"] = _date_param(key.return_date, key.date_mode)
        return params

    async def _fetch(self, params: dict[str, Any]) -> dict[str, Any]:
        """Retry/backoff və xəta xəritələməsi: bütün sorğu növləri üçün ortaq."""
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
                    raise ProviderError(f"auth failed: HTTP {resp.status_code} (token/hesab yoxlayın)")
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
        payload = await self._fetch(self._params(key, limit))
        return parse_offers(payload, key, self.name)

    async def explore(
        self,
        *,
        origin: str,
        month: date,
        currency: str,
        direct_only: bool = False,
        limit: int = 20,
        fresh: bool = False,
    ) -> list[PriceQuote]:
        params: dict[str, Any] = {
            "origin": origin,
            "departure_at": month.strftime("%Y-%m"),
            "currency": currency.lower(),
            "sorting": "price",
            "direct": "true" if direct_only else "false",
            "one_way": "true",
            "unique": "true",  # destination verilmədikdə hər istiqamətdən yalnız ən ucuzu
            "limit": max(limit * 3, 30),  # filtrdən (origin==dest, dublikat) sonra kifayət qədər qalsın
            "page": 1,
        }
        quotes = parse_rows(await self._fetch(params), currency, self.name)
        best: dict[str, PriceQuote] = {}
        for q in quotes:  # qiymətə görə artan
            if q.destination and q.destination != origin and q.destination not in best:
                best[q.destination] = q
        return list(best.values())[:limit]
