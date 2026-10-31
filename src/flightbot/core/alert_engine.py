"""Alert mühərriki: məhsulun beyni. Təmiz funksiya (DB və şəbəkəsiz), tam test olunur.

Qaydalar (spesifikasiya v0.1):
  1. Trigger: qiymət <= hədəf
  2. Təkrar yox: əvvəlki bildirişdən ən azı 5% ucuz olmadıqca yenidən göndərmə
  3. Re-arm: qiymət hədəfdən yuxarı qalxanda izləmə yenidən silahlanır
  4. Cooldown: hər izləmə üçün min. 6 saat
  5. Gündəlik limit: plana görə
  6. Köhnə data: 48 saatdan köhnə qiymət bildirişə getmir
  7. Anomaliya: median-dan 60%-dən çox aşağı qiymət ikinci sorğu ilə təsdiqlənməlidir
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
    # 6. köhnə data: heç bir state dəyişikliyi etmədən atılır
    if inp.found_at is not None and inp.now - inp.found_at > STALE_AFTER:
        return Decision(Verdict.STALE)

    # 1 + 3. hədəfdən yuxarı: silahsızdırsa yenidən silahlandır
    if inp.price > inp.target_price:
        return Decision(Verdict.ABOVE_TARGET, rearm=not inp.armed)

    # 2. silahsızdırsa yalnız əvvəlki bildirişdən ≥5% ucuzlaşma halında
    if not inp.armed and inp.last_notified_price is not None:
        if inp.price > inp.last_notified_price * REPEAT_IMPROVEMENT:
            return Decision(Verdict.NOT_CHEAPER_ENOUGH)

    # 4. cooldown
    if inp.last_notified_at is not None and inp.now - inp.last_notified_at < COOLDOWN:
        return Decision(Verdict.COOLDOWN)

    # 5. gündəlik limit
    if inp.notifications_last_24h >= inp.daily_limit:
        return Decision(Verdict.DAILY_LIMIT)

    # 7. anomaliya
    if is_anomalous_low(inp.price, inp.stats) and not inp.confirmed:
        return Decision(Verdict.NEEDS_CONFIRMATION)

    return Decision(Verdict.NOTIFY)
