"""Provider abstraction. Depending directly on a single provider is a business risk: the whole system
only knows this interface."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from flightbot.core.watch_key import WatchKey


class ProviderError(Exception):
    """An error coming from the provider or related to reaching it."""


class ProviderRateLimited(ProviderError):
    def __init__(self, retry_after: float = 60.0) -> None:
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class PriceQuote:
    price: Decimal
    currency: str
    depart_date: date
    return_date: date | None
    airline: str | None
    transfers: int | None
    found_at: datetime | None
    link: str | None
    provider: str
    destination: str | None = None  # only filled in explore() results


class PriceProvider(Protocol):
    name: str

    async def offers(self, key: WatchKey, *, limit: int = 30, fresh: bool = False) -> list[PriceQuote]:
        """Offers sorted by price ascending. An empty list if nothing is found."""
        ...

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
        """ "Anywhere": the cheapest destinations in the world from `origin` in a given month (one offer per destination),
        sorted by price ascending. `PriceQuote.destination` is set. With `stay=(min, max)` the offers are
        round trips whose length of stay falls in that range."""
        ...


async def cheapest(provider: PriceProvider, key: WatchKey, *, fresh: bool = False) -> PriceQuote | None:
    offers = await provider.offers(key, fresh=fresh)
    return min(offers, key=lambda q: q.price) if offers else None


def quote_to_json(q: PriceQuote) -> dict[str, Any]:
    return {
        "price": str(q.price),
        "currency": q.currency,
        "depart_date": q.depart_date.isoformat(),
        "return_date": q.return_date.isoformat() if q.return_date else None,
        "airline": q.airline,
        "transfers": q.transfers,
        "found_at": q.found_at.isoformat() if q.found_at else None,
        "link": q.link,
        "provider": q.provider,
        "destination": q.destination,
    }


def quote_from_json(d: dict[str, Any]) -> PriceQuote:
    return PriceQuote(
        price=Decimal(d["price"]),
        currency=d["currency"],
        depart_date=date.fromisoformat(d["depart_date"]),
        return_date=date.fromisoformat(d["return_date"]) if d.get("return_date") else None,
        airline=d.get("airline"),
        transfers=d.get("transfers"),
        found_at=datetime.fromisoformat(d["found_at"]) if d.get("found_at") else None,
        link=d.get("link"),
        provider=d["provider"],
        destination=d.get("destination"),
    )


def next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def filter_by_stay(
    quotes: list[PriceQuote], stay_min: int, stay_max: int, window: tuple[date, date] | None = None
) -> list[PriceQuote]:
    """Keep round trips whose stay is within [stay_min, stay_max] days (and whose departure is inside the window),
    without duplicates, sorted by price."""
    seen: set[tuple] = set()
    out: list[PriceQuote] = []
    for q in sorted(quotes, key=lambda q: q.price):
        if q.return_date is None or not stay_min <= (q.return_date - q.depart_date).days <= stay_max:
            continue
        if window is not None and not window[0] <= q.depart_date <= window[1]:
            continue
        sig = (q.destination, q.depart_date, q.return_date, q.price, q.airline)
        if sig not in seen:
            seen.add(sig)
            out.append(q)
    return out
