from datetime import date, timedelta

import pytest

from flightbot.core.watch_key import DateMode, InvalidWatch, WatchKey

TODAY = date(2026, 10, 31)


def mk(**kw):
    base = dict(
        origin="gyd",
        destination="ist",
        date_mode="exact",
        depart_date=TODAY + timedelta(days=20),
        today=TODAY,
    )
    base.update(kw)
    return WatchKey.create(**base)


def test_normalizes_codes_and_currency():
    k = mk(currency="usd")
    assert (k.origin, k.destination, k.currency) == ("GYD", "IST", "USD")


def test_same_signature_gives_equal_keys():
    assert mk() == mk(origin="GYD ")


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"origin": "GY"}, "bad_iata"),
        ({"destination": "123"}, "bad_iata"),
        ({"destination": "gyd"}, "same_airport"),
        ({"depart_date": TODAY - timedelta(days=1)}, "date_in_past"),
        ({"return_date": TODAY + timedelta(days=10)}, "return_before_depart"),
        ({"depart_date": TODAY + timedelta(days=400)}, "date_too_far"),
        ({"currency": "US"}, "bad_currency"),
    ],
)
def test_validation_errors(kwargs, code):
    with pytest.raises(InvalidWatch) as exc:
        mk(**kwargs)
    assert exc.value.code == code


def test_month_mode_normalizes_to_first_day_and_one_key_per_month():
    a = mk(date_mode="month", depart_date=date(2026, 12, 3))
    b = mk(date_mode="month", depart_date=date(2026, 12, 28))
    assert a == b and a.depart_date == date(2026, 12, 1)
    assert a.window_end == date(2026, 12, 31) and a.is_flexible


def test_current_month_is_allowed_in_month_mode():
    k = mk(date_mode="month", depart_date=date(2026, 10, 1))
    assert k.window_end == date(2026, 10, 31)


def test_previous_month_rejected():
    with pytest.raises(InvalidWatch):
        mk(date_mode="month", depart_date=date(2026, 9, 15))


def test_round_trip_month_mode_return_before_depart():
    with pytest.raises(InvalidWatch):
        mk(date_mode="month", depart_date=date(2026, 12, 1), return_date=date(2026, 11, 1))


def test_horizon_days_exact_and_month():
    assert mk(depart_date=TODAY + timedelta(days=20)).horizon_days(TODAY) == 20
    month_key = mk(date_mode="month", depart_date=date(2026, 12, 1))
    assert 40 < month_key.horizon_days(TODAY) < 60  # the middle of the month


def test_horizon_never_negative():
    k = mk(date_mode="month", depart_date=date(2026, 10, 1))
    assert k.horizon_days(date(2026, 10, 31)) == 0


def test_cache_id_distinguishes_every_signature_field():
    base = mk()
    variants = [
        mk(direct_only=True),
        mk(currency="AZN"),
        mk(return_date=TODAY + timedelta(days=30)),
        mk(destination="DXB"),
    ]
    ids = {base.cache_id(), *(v.cache_id() for v in variants)}
    assert len(ids) == 5


def test_date_mode_enum_accepts_string():
    assert mk(date_mode="month", depart_date=date(2026, 12, 1)).date_mode is DateMode.MONTH
