"""Provayder abstraksiyası. Tək provayderə birbaşa bağlılıq biznes riskidir: bütün sistem
yalnız bu interfeysi bilir."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from flightbot.core.watch_key import WatchKey


class ProviderError(Exception):
    """Provayderdən gələn və ya provayderə çatmaqla bağlı xəta."""


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
    destination: str | None = None  # yalnız explore() nəticələrində dolur


class PriceProvider(Protocol):
    name: str

    async def offers(self, key: WatchKey, *, limit: int = 30, fresh: bool = False) -> list[PriceQuote]:
        """Qiymətə görə artan sıralanmış təkliflər. Heç nə tapılmasa boş siyahı."""
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
    ) -> list[PriceQuote]:
        """ "Hər yerə": origin-dən verilmiş ayda dünyada ən ucuz istiqamətlər (hər istiqamətdən 1 təklif),
        qiymətə görə artan. `PriceQuote.destination` dolu olur."""
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
