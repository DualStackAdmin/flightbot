"""Qiymət statistikası: "yaxşı qiymət" nişanı, anomaliya aşkarlanması, tendensiya."""

from dataclasses import dataclass
from decimal import Decimal

MIN_SAMPLES = 14
GOOD_PRICE_WINDOW_DAYS = 90
ANOMALY_RATIO = Decimal("0.4")  # median-ın 60%-dən çox aşağı = şübhəli
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
    """Son 90 günün aşağı 20%-lik hissəsində (kifayət qədər ölçmə varsa)."""
    return stats.reliable and stats.p20 is not None and price <= stats.p20


def is_anomalous_low(price: Decimal, stats: PriceStats) -> bool:
    """Median-dan 60%-dən çox ucuz. Səhv data və ya xəta tarifi ola bilər, təsdiq lazımdır."""
    return stats.reliable and stats.median is not None and price < stats.median * ANOMALY_RATIO


def vs_median_pct(price: Decimal, stats: PriceStats) -> int | None:
    """Median-a nisbətən faiz fərqi (mənfi = ucuz). Dəqiq ölçmə yoxdursa None."""
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
