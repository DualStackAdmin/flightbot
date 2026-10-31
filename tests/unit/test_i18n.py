import string
from datetime import date

import pytest

from flightbot.bot.i18n import CATALOGS, SUPPORTED, fmt_date, fmt_month, fmt_price, t


def placeholders(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def test_all_languages_have_identical_keys():
    ref = set(CATALOGS["en"])
    for lang in SUPPORTED:
        assert set(CATALOGS[lang]) == ref, f"{lang}: {set(CATALOGS[lang]) ^ ref}"


@pytest.mark.parametrize("lang", ["az", "ru"])
def test_placeholders_match_english(lang):
    for key, template in CATALOGS["en"].items():
        assert placeholders(CATALOGS[lang][key]) == placeholders(template), f"{lang}:{key}"


def test_no_empty_translations():
    for lang, cat in CATALOGS.items():
        for key, text in cat.items():
            assert text.strip(), f"{lang}:{key}"


def test_unknown_language_falls_back_to_english():
    assert t("xx", "cancelled") == CATALOGS["en"]["cancelled"]


def test_date_formats():
    assert fmt_date(date(2026, 7, 15), "az") == "15 iyul 2026"
    assert fmt_date(date(2026, 7, 15), "ru") == "15 июля 2026"
    assert fmt_date(date(2026, 7, 15), "en") == "15 Jul 2026"
    assert fmt_month(date(2026, 7, 1), "ru") == "июль 2026"


def test_fmt_price():
    assert fmt_price("99.00") == "99"
    assert fmt_price("99.50") == "99.5"
    assert fmt_price("1234") == "1 234"


def test_settings_screen_formats_quiet_hours_with_leading_zero():
    from types import SimpleNamespace

    from flightbot.bot.handlers.settings import render_settings
    from flightbot.config import Settings

    deps = SimpleNamespace(settings=Settings(quiet_start_hour=23, quiet_end_hour=8))
    user = SimpleNamespace(home_iata="GYD")
    text_, _ = render_settings(user, deps, lang="az", currency="USD", quiet=True)
    assert "23:00–08:00" in text_ and "açıq" in text_
