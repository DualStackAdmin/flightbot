from decimal import Decimal as D

from flightbot.core import pricing as p

STATS = p.PriceStats(count=30, median=D("200"), p20=D("170"))
THIN = p.PriceStats(count=5, median=D("200"), p20=D("170"))


def test_good_price_requires_enough_samples():
    assert p.is_good_price(D("160"), STATS)
    assert p.is_good_price(D("170"), STATS)
    assert not p.is_good_price(D("171"), STATS)
    assert not p.is_good_price(D("100"), THIN)


def test_anomaly_threshold_is_60_percent_below_median():
    assert p.is_anomalous_low(D("79"), STATS)
    assert not p.is_anomalous_low(D("80"), STATS)  # exact boundary: median*0.4 = 80
    assert not p.is_anomalous_low(D("10"), THIN)  # not enough data


def test_vs_median_pct():
    assert p.vs_median_pct(D("150"), STATS) == -25
    assert p.vs_median_pct(D("150"), THIN) is None


def test_trend():
    assert p.trend(D("90"), D("100")) == "down"
    assert p.trend(D("110"), D("100")) == "up"
    assert p.trend(D("100.5"), D("100")) == "flat"
    assert p.trend(D("100"), None) is None
