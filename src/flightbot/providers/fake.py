"""Deterministic fake provider: for development and demos without a Travelpayouts token.

The price is a function of (route, time): for the same route it changes in 3-hour windows,
so you can see the watch and notification logic working realistically.
"""

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from flightbot.core.places import STATIC_PLACES
from flightbot.core.watch_key import DateMode, WatchKey
from flightbot.providers.base import PriceQuote

_AIRLINES = ["J2", "TK", "PC", "FZ", "SU", "QR"]


def _h(*parts: object) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


class FakeProvider:
    name = "fake"

    def __init__(self, now_fn=None) -> None:
        self._now = now_fn or (lambda: datetime.now(UTC))

    def _price(self, key: WatchKey, depart: date, now: datetime) -> Decimal:
        base = 60 + _h(key.origin, key.destination) % 340
        day_factor = 0.85 + (_h(key.cache_id(), depart) % 40) / 100  # 0.85..1.24
        bucket = int(now.timestamp() // (3 * 3600))
        walk = 0.80 + (_h(key.cache_id(), bucket) % 45) / 100  # 0.80..1.24
        direct = 1.15 if key.direct_only else 1.0
        rt = 1.8 if key.return_date else 1.0
        return Decimal(str(round(base * day_factor * walk * direct * rt, 2)))

    async def offers(self, key: WatchKey, *, limit: int = 30, fresh: bool = False) -> list[PriceQuote]:
        now = self._now()
        if key.date_mode is DateMode.MONTH:
            days = [key.window_start + timedelta(days=i) for i in range(0, 28)]
            days = [d for d in days if d >= now.date() and d <= key.window_end]
        else:
            days = [key.depart_date]
        quotes = []
        for d in days:
            h = _h(key.cache_id(), d, "meta")
            quotes.append(
                PriceQuote(
                    price=self._price(key, d, now),
                    currency=key.currency,
                    depart_date=d,
                    return_date=key.return_date,
                    airline=_AIRLINES[h % len(_AIRLINES)],
                    transfers=0 if key.direct_only else h % 2,
                    found_at=now,
                    link=None,
                    provider=self.name,
                )
            )
        quotes.sort(key=lambda q: q.price)
        return quotes[:limit]

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
        now = self._now()
        quotes = []
        for dest in STATIC_PLACES:
            if dest == origin:
                continue
            key = WatchKey(origin, dest, DateMode.MONTH, month.replace(day=1), None, direct_only, currency)
            depart = max(month.replace(day=1), now.date()) + timedelta(days=_h(key.cache_id()) % 20)
            h = _h(key.cache_id(), "meta")
            quotes.append(
                PriceQuote(
                    price=self._price(key, depart, now),
                    currency=currency,
                    depart_date=depart,
                    return_date=None,
                    airline=_AIRLINES[h % len(_AIRLINES)],
                    transfers=0 if direct_only else h % 2,
                    found_at=now,
                    link=None,
                    provider=self.name,
                    destination=dest,
                )
            )
        quotes.sort(key=lambda q: q.price)
        return quotes[:limit]
