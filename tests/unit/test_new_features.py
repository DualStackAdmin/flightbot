import random
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from flightbot.bot.route_text import parse_route, resolve_place_strict
from flightbot.core.places import COUNTRY, STATIC_PLACES, flag_emoji
from flightbot.core.quiet import deliver_after, in_quiet_window
from flightbot.providers.base import ProviderRateLimited, quote_from_json, quote_to_json
from flightbot.providers.fake import FakeProvider
from flightbot.providers.names import PlaceNames
from flightbot.providers.travelpayouts import TravelpayoutsProvider

# ------------------------------------------------------------------- sakit saatlar


@pytest.mark.parametrize(
    ("hour", "start", "end", "expected"),
    [
        (23, 23, 8, True),
        (0, 23, 8, True),
        (7, 23, 8, True),
        (8, 23, 8, False),
        (22, 23, 8, False),
        (12, 23, 8, False),
        (3, 1, 5, True),
        (5, 1, 5, False),
        (3, 0, 0, False),  # start==end: söndürülüb
    ],
)
def test_quiet_window(hour, start, end, expected):
    assert in_quiet_window(hour, start, end) is expected


def at(h: int, m: int = 0) -> datetime:
    # Bakı = UTC+4
    return datetime(2026, 11, 1, h, m, tzinfo=UTC)


def test_outside_quiet_hours_delivers_immediately():
    now = at(10)  # Bakı 14:00
    assert deliver_after(now, tz="Asia/Baku", start_hour=23, end_hour=8) == now


def test_inside_quiet_hours_is_held_until_morning_in_user_timezone():
    now = at(21, 30)  # Bakı 01:30
    out = deliver_after(now, tz="Asia/Baku", start_hour=23, end_hour=8, rng=random.Random(1))
    local = out.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Baku"))
    assert local.hour == 8 and local.minute < 15 and local.day == 2


def test_late_evening_rolls_over_to_next_day():
    now = at(19, 30)  # Bakı 23:30
    out = deliver_after(now, tz="Asia/Baku", start_hour=23, end_hour=8, rng=random.Random(2))
    assert out.day == 2 and out > now


def test_morning_jitter_spreads_delivery():
    now = at(21)
    outs = {
        deliver_after(now, tz="Asia/Baku", start_hour=23, end_hour=8, rng=random.Random(i)) for i in range(30)
    }
    assert len(outs) > 10  # səhər 08:00-da hamıya eyni anda yağmır


# ------------------------------------------------------------------ marşrut mətni


def test_resolve_place_strict_exact_and_unique_prefix_only():
    assert resolve_place_strict("Bakı", "az").code == "GYD"
    assert resolve_place_strict("baku", "az").code == "GYD"
    assert resolve_place_strict("ist", "az").code == "IST"
    assert resolve_place_strict("Стамбул", "az").code == "IST"
    assert resolve_place_strict("ba", "az") is None  # çox qısa və qeyri-dəqiq
    assert resolve_place_strict("zzzz", "az") is None


@pytest.mark.parametrize(
    ("text", "origin", "dest"),
    [
        ("İstanbul", None, "IST"),
        ("Bakı İstanbul", "GYD", "IST"),
        ("baki - istanbul", "GYD", "IST"),
        ("GYD→DXB", "GYD", "DXB"),
        ("Tel-Əviv Roma", "TLV", "ROM"),
        ("Ankara, Dubay", "ESB", "DXB"),
        ("Москва Баку", "MOW", "GYD"),
    ],
)
def test_parse_route(text, origin, dest):
    o, d = parse_route(text, "az")
    assert (o.code if o else None, d.code) == (origin, dest)


@pytest.mark.parametrize("text", ["", "salam necəsən", "a" * 80, "İstanbul İstanbul", "123"])
def test_parse_route_rejects_unclear_text(text):
    assert parse_route(text, "az") is None


# --------------------------------------------------------------------- bayraq/ölkə


def test_flag_emoji():
    assert flag_emoji("TR") == "🇹🇷" and flag_emoji("az") == "🇦🇿"
    assert flag_emoji(None) == "" and flag_emoji("T") == "" and flag_emoji("12") == ""


def test_every_static_place_has_a_country():
    assert set(STATIC_PLACES) == set(COUNTRY)


# ----------------------------------------------------------------- explore: provayder


def explore_payload(*rows, success=True):
    return {
        "success": success,
        "currency": "usd",
        "data": [
            {
                "origin": "GYD",
                "destination": d,
                "price": p,
                "airline": "TK",
                "transfers": 0,
                "departure_at": f"2026-12-{day:02d}T10:00:00+04:00",
                "return_at": None,
                "link": f"/search/GYD{day:02d}12{d}1?t=x",
                "currency": "usd",
            }
            for d, p, day in rows
        ],
    }


async def test_travelpayouts_explore_params_and_dedup_by_destination():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(req.url.params)
        return httpx.Response(
            200,
            json=explore_payload(
                ("IST", 80, 3), ("IST", 70, 5), ("DXB", 95, 7), ("GYD", 10, 9), ("TBS", 60, 2)
            ),
        )

    p = TravelpayoutsProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "tok")
    out = await p.explore(origin="GYD", month=date(2026, 12, 1), currency="USD", limit=10)
    assert "destination" not in seen  # "hər yerə": təyinat verilmir
    assert seen["origin"] == "GYD" and seen["departure_at"] == "2026-12" and seen["unique"] == "true"
    assert seen["one_way"] == "true" and seen["sorting"] == "price" and seen["currency"] == "usd"
    assert [(q.destination, q.price) for q in out] == [
        ("TBS", Decimal("60")),
        ("IST", Decimal("70")),
        ("DXB", Decimal("95")),
    ]  # origin==dest süzülüb, hər istiqamətdən ən ucuzu


async def test_travelpayouts_explore_respects_limit_and_handles_rate_limit():
    rows = [(f"A{i:02d}"[:3], 100 + i, 5) for i in range(20)]
    p = TravelpayoutsProvider(
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=explore_payload(*rows)))
        ),
        "t",
    )
    assert len(await p.explore(origin="GYD", month=date(2026, 12, 1), currency="USD", limit=5)) == 5
    p429 = TravelpayoutsProvider(
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "9"}))
        ),
        "t",
    )
    with pytest.raises(ProviderRateLimited):
        await p429.explore(origin="GYD", month=date(2026, 12, 1), currency="USD")


async def test_fake_explore_is_sorted_complete_and_excludes_origin():
    fp = FakeProvider(now_fn=lambda: datetime(2026, 11, 1, 12, tzinfo=UTC))
    out = await fp.explore(origin="GYD", month=date(2026, 12, 1), currency="USD", limit=100)
    assert len(out) == len(STATIC_PLACES) - 1 and all(q.destination != "GYD" for q in out)
    assert [q.price for q in out] == sorted(q.price for q in out)
    assert out == await fp.explore(origin="GYD", month=date(2026, 12, 1), currency="USD", limit=100)


def test_quote_json_roundtrip_keeps_destination():
    from flightbot.providers.base import PriceQuote

    q = PriceQuote(
        Decimal("9.5"), "USD", date(2026, 12, 3), None, "TK", 0, None, "/x", "p", destination="IST"
    )
    assert quote_from_json(quote_to_json(q)) == q
    old = quote_to_json(q)
    old.pop("destination")  # köhnə keş qeydləri destination sahəsiz idi
    assert quote_from_json(old).destination is None


# ---------------------------------------------------------------------- ad həlli


def test_parse_cities_is_tolerant():
    rows = [
        {"code": "kul", "name": "Kuala Lumpur", "country_code": "my"},
        {"code": "XX", "name": "bad code"},
        {"code": "BAD", "name": None},
        {"code": "SIN", "name_translations": {"en": "Singapore"}, "country_code": "SG"},
    ]
    assert PlaceNames.parse_cities(rows) == {"KUL": ("Kuala Lumpur", "MY"), "SIN": ("Singapore", "SG")}


async def test_names_static_first_then_code_without_network():
    names = PlaceNames(None, None, remote=False)
    info = await names.lookup("IST", "az")
    assert (info.name, info.country) == ("İstanbul", "TR")
    assert (await names.lookup("KUL", "az")).name == "KUL"  # naməlum: kodun özü, xəta yox
