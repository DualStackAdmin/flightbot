from datetime import date
from urllib.parse import parse_qs, urlparse

from flightbot.core.affiliate import build_booking_link, fallback_search_path

D1, D2 = date(2026, 7, 15), date(2026, 7, 25)


def q(url):
    return parse_qs(urlparse(url).query)


def test_fallback_path_formats():
    assert fallback_search_path("GYD", "IST", D1, None) == "/search/GYD1507IST1"
    assert fallback_search_path("GYD", "IST", D1, D2) == "/search/GYD1507IST25071"


def test_uses_provider_link_and_appends_marker_with_sub_id():
    url = build_booking_link(
        link_path="/search/GYD1507IST1?t=abc",
        origin="GYD",
        destination="IST",
        depart_date=D1,
        return_date=None,
        marker="123456",
        sub_id="n42",
    )
    assert url.startswith("https://www.aviasales.com/search/GYD1507IST1")
    assert q(url)["t"] == ["abc"] and q(url)["marker"] == ["123456.n42"]


def test_no_marker_leaves_url_untouched():
    url = build_booking_link(
        link_path="/search/X?t=1", origin="GYD", destination="IST", depart_date=D1, return_date=None
    )
    assert "marker" not in url


def test_existing_marker_is_replaced_not_duplicated():
    url = build_booking_link(
        link_path="/s?marker=evil",
        origin="GYD",
        destination="IST",
        depart_date=D1,
        return_date=None,
        marker="mine",
    )
    assert q(url)["marker"] == ["mine"]


def test_fallback_when_no_link():
    url = build_booking_link(
        link_path=None, origin="GYD", destination="IST", depart_date=D1, return_date=D2, marker="m"
    )
    assert "/search/GYD1507IST25071" in url and q(url)["marker"] == ["m"]


def test_absolute_link_kept():
    url = build_booking_link(
        link_path="https://example.com/x",
        origin="GYD",
        destination="IST",
        depart_date=D1,
        return_date=None,
        marker="m",
    )
    assert url.startswith("https://example.com/x")
