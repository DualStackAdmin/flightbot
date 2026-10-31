from datetime import date
from decimal import Decimal

import pytest

from flightbot.bot.parsing import (
    month_token,
    next_months,
    parse_month_token,
    parse_price,
    parse_user_date,
    quick_targets,
)

TODAY = date(2026, 10, 31)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15.07.2027", date(2027, 7, 15)),
        ("15/07/2027", date(2027, 7, 15)),
        ("15-07-2027", date(2027, 7, 15)),
        ("5.7.2027", date(2027, 7, 5)),
        ("15.07.27", date(2027, 7, 15)),
        ("2027-07-15", date(2027, 7, 15)),
        ("  15.07.2027  ", date(2027, 7, 15)),
        ("15.12", date(2026, 12, 15)),  # bu il, hələ gəlməyib
        ("15.03", date(2027, 3, 15)),  # keçib -> növbəti il
        ("31.10", date(2026, 10, 31)),  # bu gün: keçmiş sayılmır
    ],
)
def test_parse_user_date_valid(text, expected):
    assert parse_user_date(text, TODAY) == expected


@pytest.mark.parametrize(
    "text", ["", "abc", "32.01.2027", "15.13.2027", "29.02.2027", "15.07", "1507", "15..07.2027"][:7]
)
def test_parse_user_date_invalid(text):
    if text == "15.07":  # bu etibarlı formadır (növbəti baş verən tarix)
        assert parse_user_date(text, TODAY) == date(2027, 7, 15)
    else:
        assert parse_user_date(text, TODAY) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("120", "120.00"),
        ("120.5", "120.50"),
        ("120,5", "120.50"),
        ("120 USD", "120.00"),
        ("$99", "99.00"),
        ("1 200", "1200.00"),
        ("0.01", "0.01"),
    ],
)
def test_parse_price_valid(text, expected):
    assert parse_price(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "abc", "0", "0.00", "-5", "−5", "+5", "100001", "1.2.3", "12-3", None])
def test_parse_price_invalid(text):
    assert parse_price(text) is None


def test_next_months_wraps_year():
    ms = next_months(date(2026, 11, 15), 4)
    assert ms == [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)]


def test_month_token_roundtrip():
    assert parse_month_token(month_token(date(2027, 3, 1))) == date(2027, 3, 1)
    assert parse_month_token("garbage") is None
    assert parse_month_token("2027-13") is None


def test_quick_targets():
    assert quick_targets(Decimal("200")) == [(15, 170), (10, 180), (25, 150)]  # birincisi tövsiyədir
    assert quick_targets(Decimal("1")) == [(15, 1), (10, 1), (25, 1)]  # heç vaxt 0 olmur
