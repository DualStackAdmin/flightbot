from datetime import date
from decimal import Decimal

import httpx
import pytest

from flightbot.core.watch_key import DateMode, WatchKey
from flightbot.providers.base import ProviderError, ProviderRateLimited
from flightbot.providers.fake import FakeProvider
from flightbot.providers.travelpayouts import TravelpayoutsProvider

TODAY = date(2026, 10, 31)
KEY = WatchKey.create(
    origin="GYD",
    destination="IST",
    date_mode=DateMode.EXACT,
    depart_date=date(2026, 12, 15),
    today=TODAY,
)
MONTH_KEY = WatchKey.create(
    origin="GYD",
    destination="IST",
    date_mode=DateMode.MONTH,
    depart_date=date(2026, 12, 1),
    return_date=date(2027, 1, 1),
    today=TODAY,
)


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def payload(*prices, **extra):
    return {
        "success": True,
        "currency": "usd",
        "data": [
            {
                "origin": "GYD",
                "destination": "IST",
                "price": p,
                "airline": "TK",
                "departure_at": "2026-12-15T14:15:00+04:00",
                "return_at": None,
                "transfers": 0,
                "link": "/search/GYD1512IST1?t=x",
                "currency": "usd",
            }
            for p in prices
        ],
        **extra,
    }


async def test_parses_and_sorts_by_price():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(req.url.params)
        seen["token"] = req.headers["X-Access-Token"]
        return httpx.Response(200, json=payload(150, 99.5, 120))

    p = TravelpayoutsProvider(client(handler), "secret")
    offers = await p.offers(KEY)
    assert [o.price for o in offers] == [Decimal("99.5"), Decimal("120"), Decimal("150")]
    assert offers[0].depart_date == date(2026, 12, 15) and offers[0].currency == "USD"
    assert seen["origin"] == "GYD" and seen["departure_at"] == "2026-12-15"
    assert seen["one_way"] == "true" and seen["currency"] == "usd" and seen["token"] == "secret"


async def test_month_round_trip_params():
    seen = {}

    def handler(req):
        seen.update(req.url.params)
        return httpx.Response(200, json=payload())

    await TravelpayoutsProvider(client(handler), "t").offers(MONTH_KEY)
    assert seen["departure_at"] == "2026-12" and seen["return_at"] == "2027-01"
    assert seen["one_way"] == "false"


async def test_empty_data_returns_empty_list():
    p = TravelpayoutsProvider(client(lambda r: httpx.Response(200, json=payload())), "t")
    assert await p.offers(KEY) == []


async def test_bad_rows_are_skipped_not_fatal():
    data = payload(100)
    data["data"].append({"price": "abc"})
    data["data"].append({"departure_at": "2026-12-15T10:00:00+04:00", "price": -5})
    p = TravelpayoutsProvider(client(lambda r: httpx.Response(200, json=data)), "t")
    assert len(await p.offers(KEY)) == 1


async def test_429_raises_rate_limited_with_retry_after():
    p = TravelpayoutsProvider(client(lambda r: httpx.Response(429, headers={"Retry-After": "42"})), "t")
    with pytest.raises(ProviderRateLimited) as exc:
        await p.offers(KEY)
    assert exc.value.retry_after == 42


async def test_auth_failure_is_not_retried():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(401)

    with pytest.raises(ProviderError):
        await TravelpayoutsProvider(client(handler), "bad", retries=3).offers(KEY)
    assert len(calls) == 1


async def test_5xx_is_retried_then_fails(monkeypatch):
    async def no_sleep(_):  # testi sürətləndir
        pass

    monkeypatch.setattr("flightbot.providers.travelpayouts.asyncio.sleep", no_sleep)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(ProviderError):
        await TravelpayoutsProvider(client(handler), "t", retries=2).offers(KEY)
    assert len(calls) == 3


async def test_5xx_then_success(monkeypatch):
    async def no_sleep(_):
        pass

    monkeypatch.setattr("flightbot.providers.travelpayouts.asyncio.sleep", no_sleep)
    responses = iter([httpx.Response(502), httpx.Response(200, json=payload(77))])
    p = TravelpayoutsProvider(client(lambda r: next(responses)), "t")
    assert (await p.offers(KEY))[0].price == Decimal("77")


async def test_success_false_raises():
    p = TravelpayoutsProvider(
        client(lambda r: httpx.Response(200, json={"success": False, "error": "x"})), "t"
    )
    with pytest.raises(ProviderError):
        await p.offers(KEY)


async def test_fake_provider_is_deterministic_and_sorted():
    from datetime import UTC, datetime

    fixed = datetime(2026, 10, 31, 12, tzinfo=UTC)
    fp = FakeProvider(now_fn=lambda: fixed)
    a, b = await fp.offers(MONTH_KEY), await fp.offers(MONTH_KEY)
    assert a == b and len(a) > 5
    assert [q.price for q in a] == sorted(q.price for q in a)
    assert all(MONTH_KEY.window_start <= q.depart_date <= MONTH_KEY.window_end for q in a)
