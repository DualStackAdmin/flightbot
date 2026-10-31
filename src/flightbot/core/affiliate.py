"""Booking link (affiliate).

NOTE: verify Travelpayouts' `marker` and `sub_id` format with a real account.
This uses `marker=<MARKER>.<SUB_ID>` (the sub_id is for tracking).
Tracking clicks on your own domain (a redirect service) is a later milestone.
"""

from datetime import date
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

AVIASALES_BASE = "https://www.aviasales.com"


def fallback_search_path(
    origin: str, destination: str, depart: date, return_date: date | None, passengers: int = 1
) -> str:
    """Short Aviasales search format: GYD1507IST1 (one-way), GYD1507IST25071 (round trip)."""
    out = f"{origin}{depart:%d%m}{destination}"
    back = f"{return_date:%d%m}" if return_date else ""
    return f"/search/{out}{back}{passengers}"


def build_booking_link(
    *,
    link_path: str | None,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
    marker: str = "",
    sub_id: str | None = None,
    base: str = AVIASALES_BASE,
) -> str:
    if link_path and link_path.startswith(("http://", "https://")):
        url = link_path
    elif link_path and link_path.startswith("/"):
        url = base + link_path
    else:
        url = base + fallback_search_path(origin, destination, depart_date, return_date)

    if not marker:
        return url

    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "marker"]
    query.append(("marker", f"{marker}.{sub_id}" if sub_id else marker))
    return urlunparse(parts._replace(query=urlencode(query)))
