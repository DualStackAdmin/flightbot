"""WatchKey: the unique signature of a provider request (the dedup unit).

In flexible date mode ("month") "one month = one API request". This is the key condition that keeps fan-out
from exploding.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

IATA_RE = re.compile(r"^[A-Z]{3}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
MAX_HORIZON_DAYS = 360
MAX_STAY_DAYS = 30


class DateMode(StrEnum):
    EXACT = "exact"
    MONTH = "month"


class InvalidWatch(ValueError):
    """`code` is an i18n key (the bot shows the matching message to the user)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _last_of_month(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


@dataclass(frozen=True, slots=True)
class WatchKey:
    origin: str
    destination: str
    date_mode: DateMode
    depart_date: date
    return_date: date | None
    direct_only: bool
    currency: str
    # Round trip by month: how many days the traveller stays (inclusive range). None = not a stay-based key.
    stay_min: int | None = None
    stay_max: int | None = None

    @classmethod
    def create(
        cls,
        *,
        origin: str,
        destination: str,
        date_mode: DateMode | str,
        depart_date: date,
        return_date: date | None = None,
        direct_only: bool = False,
        currency: str = "USD",
        stay_min: int | None = None,
        stay_max: int | None = None,
        today: date,
    ) -> "WatchKey":
        origin = origin.strip().upper()
        destination = destination.strip().upper()
        currency = currency.strip().upper()
        mode = DateMode(date_mode)

        if not IATA_RE.match(origin) or not IATA_RE.match(destination):
            raise InvalidWatch("bad_iata")
        if not CURRENCY_RE.match(currency):
            raise InvalidWatch("bad_currency")
        if origin == destination:
            raise InvalidWatch("same_airport")

        if mode is DateMode.MONTH:
            depart_date = _first_of_month(depart_date)
            if return_date is not None:
                return_date = _first_of_month(return_date)
            if depart_date < _first_of_month(today):
                raise InvalidWatch("date_in_past")
            if return_date is not None and return_date < depart_date:
                raise InvalidWatch("return_before_depart")
        else:
            if depart_date < today:
                raise InvalidWatch("date_in_past")
            if return_date is not None and return_date < depart_date:
                raise InvalidWatch("return_before_depart")

        if (depart_date - today).days > MAX_HORIZON_DAYS:
            raise InvalidWatch("date_too_far")

        if stay_min is not None or stay_max is not None:
            # A stay applies to "round trip, any departure day in the month": exact dates use return_date instead.
            if stay_min is None or stay_max is None or mode is not DateMode.MONTH or return_date is not None:
                raise InvalidWatch("bad_stay")
            if not 1 <= stay_min <= stay_max <= MAX_STAY_DAYS:
                raise InvalidWatch("bad_stay")

        return cls(
            origin, destination, mode, depart_date, return_date, direct_only, currency, stay_min, stay_max
        )

    @property
    def window_start(self) -> date:
        return self.depart_date

    @property
    def window_end(self) -> date:
        """Last day of the departure window. After it the watch counts as expired."""
        if self.date_mode is DateMode.MONTH:
            return _last_of_month(self.depart_date)
        return self.depart_date

    @property
    def is_flexible(self) -> bool:
        return self.date_mode is DateMode.MONTH

    @property
    def is_round_trip(self) -> bool:
        return self.return_date is not None or self.stay_min is not None

    @property
    def has_stay(self) -> bool:
        return self.stay_min is not None

    def horizon_days(self, today: date) -> int:
        """Approximate days until departure (the middle of the window in month mode). Determines check frequency."""
        if self.date_mode is DateMode.MONTH:
            span = (self.window_end - self.window_start).days
            target = self.window_start + timedelta(days=span // 2)
        else:
            target = self.depart_date
        return max(0, (target - today).days)

    def cache_id(self) -> str:
        ret = self.return_date.isoformat() if self.return_date else "-"
        stay = f"{self.stay_min}-{self.stay_max}" if self.has_stay else "-"
        return (
            f"{self.origin}:{self.destination}:{self.date_mode.value}:"
            f"{self.depart_date.isoformat()}:{ret}:{int(self.direct_only)}:{self.currency}:{stay}"
        )
