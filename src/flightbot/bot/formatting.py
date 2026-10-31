"""İzləmənin istifadəçiyə göstərilən təsviri (WatchKey dataclass və ORM sətri ilə eyni işləyir)."""

from typing import Any

from flightbot.bot.i18n import fmt_date, fmt_month, t
from flightbot.bot.render import route_title


def describe_key(k: Any, lang: str) -> tuple[str, str, str]:
    """(marşrut, tarixlər, bayraqlar). Bayraqlar ' · birbaşa · gediş-gəliş' formasındadır (boş ola bilər)."""
    route = route_title(k.origin, k.destination, lang)
    month_mode = str(getattr(k.date_mode, "value", k.date_mode)) == "month"
    fmt = fmt_month if month_mode else fmt_date
    dates = fmt(k.depart_date, lang)
    flags: list[str] = []
    if k.return_date:
        dates = f"{dates} → {fmt(k.return_date, lang)}"
        flags.append(t(lang, "flag.round"))
    if k.direct_only:
        flags.append(t(lang, "flag.direct"))
    return route, dates, "".join(f" · {f}" for f in flags)
