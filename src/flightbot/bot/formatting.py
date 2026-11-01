"""Human-readable description of a watch (works with both the WatchKey dataclass and the ORM row)."""

from typing import Any

from flightbot.bot.i18n import fmt_date, fmt_month, t
from flightbot.bot.render import route_title


def describe_key(k: Any, lang: str) -> tuple[str, str, str]:
    """(route, dates, flags). Flags are localized, e.g. ' · direct · round trip' (may be empty)."""
    route = route_title(k.origin, k.destination, lang)
    month_mode = str(getattr(k.date_mode, "value", k.date_mode)) == "month"
    fmt = fmt_month if month_mode else fmt_date
    dates = fmt(k.depart_date, lang)
    flags: list[str] = []
    stay_min = getattr(k, "stay_min", None)
    if k.return_date:
        dates = f"{dates} → {fmt(k.return_date, lang)}"
        flags.append(t(lang, "flag.round"))
    elif stay_min is not None:
        stay_max = getattr(k, "stay_max", stay_min)
        flags.append(t(lang, "flag.round"))
        flags.append(t(lang, "flag.stay", n=stay_min if stay_min == stay_max else f"{stay_min}-{stay_max}"))
    if k.direct_only:
        flags.append(t(lang, "flag.direct"))
    return route, dates, "".join(f" · {f}" for f in flags)
