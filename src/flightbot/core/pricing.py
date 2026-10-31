"""Price statistics: the "good price" badge, anomaly detection, trend."""

from dataclasses import dataclass
from decimal import Decimal

MIN_SAMPLES = 14
GOOD_PRICE_WINDOW_DAYS = 90
ANOMALY_RATIO = Decimal("0.4")  # more than 60% below the median = suspicious
TREND_EPSILON = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class PriceStats:
    count: int
    median: Decimal | None
    p20: Decimal | None

    @property
    def reliable(self) -> bool:
        return self.count >= MIN_SAMPLES and self.median is not None


EMPTY_STATS = PriceStats(0, None, None)


def is_good_price(price: Decimal, stats: PriceStats) -> bool:
    """In the lowest 20% of the last 90 days (if there are enough samples)."""
    return stats.reliable and stats.p20 is not None and price <= stats.p20


def is_anomalous_low(price: Decimal, stats: PriceStats) -> bool:
    """More than 60% below the median. May be bad data or an error fare, so it needs confirmation."""
    return stats.reliable and stats.median is not None and price < stats.median * ANOMALY_RATIO


def vs_median_pct(price: Decimal, stats: PriceStats) -> int | None:
    """Percentage difference from the median (negative = cheaper). None if there are not enough samples."""
    if not stats.reliable or not stats.median:
        return None
    return int(((price / stats.median) - 1) * 100)


def trend(price: Decimal, previous: Decimal | None) -> str | None:
    if previous is None or previous == 0:
        return None
    change = (price - previous) / previous
    if change <= -TREND_EPSILON:
        return "down"
    if change >= TREND_EPSILON:
        return "up"
    return "flat"
