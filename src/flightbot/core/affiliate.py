"""Satın alma linki (affiliate).

DİQQƏT: Travelpayouts-un `marker` və `sub_id` formatını real hesabda yoxlayın.
Burada `marker=<MARKER>.<SUB_ID>` forması istifadə olunur (sub_id izləmə üçün).
Kliklərin öz domeninizdə izlənməsi (redirect servisi) sonrakı mərhələdir.
"""

from datetime import date
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

AVIASALES_BASE = "https://www.aviasales.com"


def fallback_search_path(
    origin: str, destination: str, depart: date, return_date: date | None, passengers: int = 1
) -> str:
    """Aviasales axtarış qısa formatı: GYD1507IST1 (tək), GYD1507IST25071 (gediş-gəliş)."""
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
