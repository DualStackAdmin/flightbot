"""Alert engine: the brain of the product. A pure function (no DB, no network), fully tested.

Rules (spec v0.1):
  1. Trigger: price <= target
  2. No repeats: don't notify again unless at least 5% cheaper than the previous notification
  3. Re-arm: the watch is re-armed when the price rises above the target
  4. Cooldown: at least 6 hours per watch
  5. Daily limit: depends on the plan
  6. Stale data: a price older than 48 hours is not notified
  7. Anomaly: a price more than 60% below the median must be confirmed by a second request
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from flightbot.core.pricing import PriceStats, is_anomalous_low

REPEAT_IMPROVEMENT = Decimal("0.95")
COOLDOWN = timedelta(hours=6)
STALE_AFTER = timedelta(hours=48)


class Verdict(StrEnum):
    NOTIFY = "notify"
    ABOVE_TARGET = "above_target"
    NOT_CHEAPER_ENOUGH = "not_cheaper_enough"
    COOLDOWN = "cooldown"
    DAILY_LIMIT = "daily_limit"
    STALE = "stale"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass(frozen=True, slots=True)
class AlertInput:
    now: datetime
    price: Decimal
    target_price: Decimal
    armed: bool
    last_notified_price: Decimal | None
    last_notified_at: datetime | None
    notifications_last_24h: int
    daily_limit: int
    stats: PriceStats
    found_at: datetime | None = None
    confirmed: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    rearm: bool = False


def decide(inp: AlertInput) -> Decision:
    # 6. stale data: dropped without changing any state
    if inp.found_at is not None and inp.now - inp.found_at > STALE_AFTER:
        return Decision(Verdict.STALE)

    # 1 + 3. above target: re-arm if it was disarmed
    if inp.price > inp.target_price:
        return Decision(Verdict.ABOVE_TARGET, rearm=not inp.armed)

    # 2. when disarmed, only notify again if at least 5% cheaper than the last notification
    if not inp.armed and inp.last_notified_price is not None:
        if inp.price > inp.last_notified_price * REPEAT_IMPROVEMENT:
            return Decision(Verdict.NOT_CHEAPER_ENOUGH)

    # 4. cooldown
    if inp.last_notified_at is not None and inp.now - inp.last_notified_at < COOLDOWN:
        return Decision(Verdict.COOLDOWN)

    # 5. daily limit
    if inp.notifications_last_24h >= inp.daily_limit:
        return Decision(Verdict.DAILY_LIMIT)

    # 7. anomaliya
    if is_anomalous_low(inp.price, inp.stats) and not inp.confirmed:
        return Decision(Verdict.NEEDS_CONFIRMATION)

    return Decision(Verdict.NOTIFY)
