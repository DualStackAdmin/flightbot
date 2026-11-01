from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from flightbot.bot.calendar_kb import calendar_rows, clamp_month, prev_month
from flightbot.bot.callbacks import CalCb
from flightbot.core.watch_key import DateMode, InvalidWatch, WatchKey
from flightbot.providers.base import PriceQuote, filter_by_stay, next_month
from flightbot.providers.fake import FakeProvider
from flightbot.providers.travelpayouts import TravelpayoutsProvider

TODAY = date(2026, 10, 31)


def mk(**kw):
    base = dict(origin="GYD", destination="IST", date_mode="month", depart_date=date(2027, 3, 1), today=TODAY)
    base.update(kw)
    return WatchKey.create(**base)


# ------------------------------------------------------------------ WatchKey with a stay
def test_stay_key_is_round_trip_and_part_of_the_signature():
    k7, k14, one_way = mk(stay_min=7, stay_max=7), mk(stay_min=14, stay_max=14), mk()
    assert k7.is_round_trip and k7.has_stay and not one_way.is_round_trip
    assert len({k7.cache_id(), k14.cache_id(), one_way.cache_id()}) == 3
    assert k7 == mk(stay_min=7, stay_max=7)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stay_min": 7},  # both bounds required
        {"stay_min": 0, "stay_max": 0},
        {"stay_min": 8, "stay_max": 7},
        {"stay_min": 31, "stay_max": 31},
        {"stay_min": 7, "stay_max": 7, "date_mode": "exact", "depart_date": date(2027, 3, 5)},
        {"stay_min": 7, "stay_max": 7, "return_date": date(2027, 4, 1)},
    ],
)
def test_invalid_stays(kwargs):
    with pytest.raises(InvalidWatch) as exc:
        mk(**kwargs)
    assert exc.value.code == "bad_stay"


# ----------------------------------------------------------------------- stay filter
def q(dep: date, ret: date | None, price: str, dest="IST") -> PriceQuote:
    return PriceQuote(Decimal(price), "USD", dep, ret, "J2", 0, None, None, "p", destination=dest)


def test_filter_by_stay_keeps_matching_trips_sorted_and_deduped():
    d = date(2027, 3, 10)
    quotes = [
        q(d, d + timedelta(days=7), "200"),
        q(d, d + timedelta(days=7), "200"),  # duplicate
        q(d, d + timedelta(days=6), "100"),  # wrong stay
        q(d, None, "50"),  # one way
        q(date(2027, 4, 2), date(2027, 4, 9), "90"),  # outside the window
        q(date(2027, 3, 28), date(2027, 4, 4), "150"),  # return in the next month: kept
    ]
    out = filter_by_stay(quotes, 7, 7, (date(2027, 3, 1), date(2027, 3, 31)))
    assert [x.price for x in out] == [Decimal("150"), Decimal("200")]


def test_next_month_wraps_the_year():
    assert next_month(date(2026, 12, 15)) == date(2027, 1, 1)
    assert prev_month(date(2027, 1, 1)) == date(2026, 12, 1)


# ------------------------------------------------- Travelpayouts: round trips by length of stay
def payload(*rows):
    return {
        "success": True,
        "currency": "usd",
        "data": [
            {
                "destination": dest,
                "price": p,
                "airline": "J2",
                "transfers": 0,
                "departure_at": f"{dep}T10:00:00+04:00",
                "return_at": f"{ret}T10:00:00+04:00",
                "link": "/x",
            }
            for dest, p, dep, ret in rows
        ],
    }


async def test_stay_offers_query_both_return_months_and_filter_by_stay():
    seen = []

    def handler(req: httpx.Request):
        seen.append(dict(req.url.params))
        if req.url.params["return_at"] == "2027-03":
            return httpx.Response(
                200,
                json=payload(
                    ("IST", 120, "2027-03-05", "2027-03-12"), ("IST", 80, "2027-03-05", "2027-03-08")
                ),
            )
        return httpx.Response(200, json=payload(("IST", 110, "2027-03-27", "2027-04-03")))

    p = TravelpayoutsProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "t")
    out = await p.offers(mk(stay_min=7, stay_max=7))
    assert [s["return_at"] for s in seen] == ["2027-03", "2027-04"]  # the return can spill into next month
    assert all(s["one_way"] == "false" and s["departure_at"] == "2027-03" for s in seen)
    assert int(seen[0]["limit"]) >= 100
    assert [(o.price, (o.return_date - o.depart_date).days) for o in out] == [
        (Decimal("110"), 7),
        (Decimal("120"), 7),
    ]


async def test_one_way_and_exact_round_trip_still_use_a_single_request():
    calls = []

    def handler(req):
        calls.append(dict(req.url.params))
        return httpx.Response(200, json={"success": True, "data": []})

    p = TravelpayoutsProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "t")
    await p.offers(mk())
    await p.offers(mk(date_mode="exact", depart_date=date(2027, 3, 5), return_date=date(2027, 3, 12)))
    assert len(calls) == 2
    assert calls[0]["one_way"] == "true" and "return_at" not in calls[0]
    assert calls[1]["one_way"] == "false" and calls[1]["return_at"] == "2027-03-12"


async def test_explore_with_stay_filters_round_trips_per_destination():
    def handler(req):
        if req.url.params.get("one_way") != "false":
            return httpx.Response(400)
        return httpx.Response(
            200,
            json=payload(
                ("IST", 150, "2027-03-05", "2027-03-12"),
                ("DXB", 90, "2027-03-05", "2027-03-07"),  # 2 days: filtered out
                ("TBS", 100, "2027-03-20", "2027-03-27"),
            ),
        )

    p = TravelpayoutsProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "t")
    out = await p.explore(origin="GYD", month=date(2027, 3, 1), currency="USD", stay=(7, 7))
    assert [(o.destination, o.price) for o in out] == [("TBS", Decimal("100")), ("IST", Decimal("150"))]


async def test_fake_provider_honours_the_stay():
    from datetime import UTC, datetime

    fp = FakeProvider(now_fn=lambda: datetime(2026, 10, 31, 12, tzinfo=UTC))
    out = await fp.offers(mk(stay_min=5, stay_max=5))
    assert out and all((o.return_date - o.depart_date).days == 5 for o in out)
    xs = await fp.explore(origin="GYD", month=date(2027, 3, 1), currency="USD", stay=(7, 7), limit=100)
    assert xs and all((o.return_date - o.depart_date).days == 7 for o in xs)


# ------------------------------------------------------------------------- calendar
def labels(rows):
    return [[b.text for b in row] for row in rows]


def test_calendar_is_monday_first_and_blocks_days_outside_the_range():
    rows = calendar_rows("dep", date(2027, 3, 1), "az", min_day=date(2027, 3, 10), max_day=date(2027, 3, 20))
    lab = labels(rows)
    assert lab[0] == ["·", "mart 2027", "·"]  # no navigation: the whole range is in March
    assert lab[1] == ["B.e", "Ç.a", "Ç", "C.a", "C", "Ş", "B"]
    assert lab[2] == ["·"] * 7  # 1-7 March are before min_day
    assert lab[3] == ["·", "·", "10", "11", "12", "13", "14"]  # 10 March 2027 is a Wednesday
    picks = [
        CalCb.unpack(b.callback_data).v for row in rows for b in row if ":pick:" in (b.callback_data or "")
    ]
    assert picks[0] == "20270310" and picks[-1] == "20270320" and len(picks) == 11


def test_calendar_first_day_of_month_lands_on_monday_column():
    rows = calendar_rows("dep", date(2027, 3, 1), "en", min_day=date(2027, 3, 1), max_day=date(2027, 3, 31))
    assert labels(rows)[2][0] == "1"  # 1 March 2027 is a Monday


def test_calendar_navigation_only_within_range():
    rows = calendar_rows("ret", date(2027, 4, 1), "en", min_day=date(2027, 3, 25), max_day=date(2027, 5, 5))
    prev_btn, title, next_btn = rows[0]
    assert prev_btn.text == "‹" and CalCb.unpack(prev_btn.callback_data).v == "202703"
    assert next_btn.text == "›" and CalCb.unpack(next_btn.callback_data).v == "202705"
    assert title.text == "April 2027" and labels(rows)[1][0] == "Mo"


def test_clamp_month():
    lo, hi = date(2027, 3, 10), date(2027, 6, 1)
    assert clamp_month(date(2027, 1, 5), lo, hi) == date(2027, 3, 1)
    assert clamp_month(date(2027, 9, 5), lo, hi) == date(2027, 6, 1)
    assert clamp_month(date(2027, 4, 9), lo, hi) == date(2027, 4, 1)


def test_watch_key_is_hashable_with_stay():
    assert len({mk(stay_min=3, stay_max=3), mk(stay_min=3, stay_max=3)}) == 1
    assert DateMode.MONTH.value == "month"
