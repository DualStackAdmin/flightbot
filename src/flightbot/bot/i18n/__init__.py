"""Simple, dependency-free i18n: az (default), ru, en. Tests verify that every language has the same keys and
placeholders, so a missing translation is caught in CI."""

import html
from datetime import date
from decimal import Decimal

from flightbot.bot.i18n import az, en, ru

CATALOGS: dict[str, dict[str, str]] = {"az": az.MESSAGES, "ru": ru.MESSAGES, "en": en.MESSAGES}
_MODULES = {"az": az, "ru": ru, "en": en}
SUPPORTED = tuple(CATALOGS)


def t(lang: str, key: str, **kwargs: object) -> str:
    catalog = CATALOGS.get(lang, CATALOGS["en"])
    template = catalog.get(key) or CATALOGS["en"][key]
    return template.format(**kwargs)


def language_name(lang: str) -> str:
    return _MODULES[lang].LANGUAGE_NAME


def fmt_date(d: date, lang: str) -> str:
    mod = _MODULES.get(lang, en)
    if lang == "en":
        return f"{d.day} {mod.MONTHS_GEN[d.month - 1][:3]} {d.year}"
    return f"{d.day} {mod.MONTHS_GEN[d.month - 1]} {d.year}"


def fmt_month(d: date, lang: str) -> str:
    mod = _MODULES.get(lang, en)
    return f"{mod.MONTHS_NOM[d.month - 1]} {d.year}"


def fmt_price(value: Decimal | str | float | int) -> str:
    d = Decimal(str(value))
    text = f"{d:,.2f}".replace(",", " ")
    return text.rstrip("0").rstrip(".") if "." in text else text


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)
