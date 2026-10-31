from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from flightbot.core.alert_engine import AlertInput, Verdict, decide
from flightbot.core.pricing import EMPTY_STATS, PriceStats

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
RELIABLE = PriceStats(30, D("200"), D("170"))


def inp(**kw) -> AlertInput:
    base = dict(
        now=NOW,
        price=D("100"),
        target_price=D("120"),
        armed=True,
        last_notified_price=None,
        last_notified_at=None,
        notifications_last_24h=0,
        daily_limit=3,
        stats=EMPTY_STATS,
    )
    base.update(kw)
    return AlertInput(**base)


def test_notify_when_at_or_below_target():
    assert decide(inp()).verdict is Verdict.NOTIFY
    assert decide(inp(price=D("120"))).verdict is Verdict.NOTIFY  # <= (equal counts too)


def test_above_target_does_not_notify():
    d = decide(inp(price=D("121")))
    assert d.verdict is Verdict.ABOVE_TARGET and not d.rearm


def test_rearm_when_price_rises_above_target():
    d = decide(inp(price=D("150"), armed=False, last_notified_price=D("100")))
    assert d.verdict is Verdict.ABOVE_TARGET and d.rearm


def test_no_repeat_unless_5_percent_cheaper():
    last = D("100")
    common = dict(armed=False, last_notified_price=last, last_notified_at=NOW - timedelta(hours=24))
    assert decide(inp(price=D("96"), **common)).verdict is Verdict.NOT_CHEAPER_ENOUGH
    assert decide(inp(price=D("95"), **common)).verdict is Verdict.NOTIFY  # tam 5%
    assert decide(inp(price=D("90"), **common)).verdict is Verdict.NOTIFY


def test_cooldown_blocks_even_when_cheaper_enough():
    d = decide(
        inp(
            price=D("90"),
            armed=False,
            last_notified_price=D("100"),
            last_notified_at=NOW - timedelta(hours=5, minutes=59),
        )
    )
    assert d.verdict is Verdict.COOLDOWN


def test_cooldown_expires_after_6_hours():
    d = decide(inp(armed=True, last_notified_at=NOW - timedelta(hours=6)))
    assert d.verdict is Verdict.NOTIFY


def test_daily_limit():
    assert decide(inp(notifications_last_24h=3)).verdict is Verdict.DAILY_LIMIT
    assert decide(inp(notifications_last_24h=2)).verdict is Verdict.NOTIFY
    assert decide(inp(notifications_last_24h=29, daily_limit=30)).verdict is Verdict.NOTIFY


def test_stale_quote_is_ignored_entirely():
    d = decide(inp(found_at=NOW - timedelta(hours=49), armed=False, price=D("500")))
    assert d.verdict is Verdict.STALE and not d.rearm  # a stale price must not re-arm either


def test_fresh_quote_within_48h_ok():
    assert decide(inp(found_at=NOW - timedelta(hours=47))).verdict is Verdict.NOTIFY


def test_anomaly_needs_confirmation():
    low = dict(price=D("70"), stats=RELIABLE)  # 200*0.4 = 80 -> 70 is suspicious
    assert decide(inp(**low)).verdict is Verdict.NEEDS_CONFIRMATION
    assert decide(inp(confirmed=True, **low)).verdict is Verdict.NOTIFY


def test_anomaly_not_flagged_without_reliable_history():
    assert decide(inp(price=D("10"), stats=PriceStats(3, D("200"), D("170")))).verdict is Verdict.NOTIFY


def test_target_above_median_is_fine():
    d = decide(inp(price=D("190"), target_price=D("250"), stats=RELIABLE))
    assert d.verdict is Verdict.NOTIFY


@pytest.mark.parametrize("armed", [True, False])
def test_first_notification_state_without_last_price(armed):
    assert decide(inp(armed=armed)).verdict is Verdict.NOTIFY
