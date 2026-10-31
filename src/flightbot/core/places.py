"""Statik şəhər/aeroport siyahısı (az/ru/en adlarla) və ad üzrə axtarış.

Provayderin autocomplete-i əlçatmaz olanda və ya FakeProvider ilə inkişaf zamanı fallback kimi işləyir.
"""

import unicodedata
from dataclasses import dataclass

_TRANSLIT = str.maketrans({"ə": "e", "Ə": "e", "ı": "i", "İ": "i", "ß": "ss", "ё": "е"})


def normalize(text: str) -> str:
    """Kiçik hərf, diakritiksiz, az-xüsusi hərflər sadələşdirilmiş (Bakı == baki == baku-yaxın)."""
    text = text.translate(_TRANSLIT).casefold()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


@dataclass(frozen=True, slots=True)
class Place:
    code: str
    name: str
    country: str | None = None
    kind: str = "city"


# code: (az, ru, en)
_NAMES: dict[str, tuple[str, str, str]] = {
    "GYD": ("Bakı", "Баку", "Baku"),
    "KVD": ("Gəncə", "Гянджа", "Ganja"),
    "NAJ": ("Naxçıvan", "Нахичевань", "Nakhchivan"),
    "IST": ("İstanbul", "Стамбул", "Istanbul"),
    "AYT": ("Antalya", "Анталья", "Antalya"),
    "ESB": ("Ankara", "Анкара", "Ankara"),
    "DXB": ("Dubay", "Дубай", "Dubai"),
    "DOH": ("Doha", "Доха", "Doha"),
    "TLV": ("Tel-Əviv", "Тель-Авив", "Tel Aviv"),
    "THR": ("Tehran", "Тегеран", "Tehran"),
    "CAI": ("Qahirə", "Каир", "Cairo"),
    "SSH": ("Şarm-əl-Şeyx", "Шарм-эль-Шейх", "Sharm El Sheikh"),
    "MOW": ("Moskva", "Москва", "Moscow"),
    "LED": ("Sankt-Peterburq", "Санкт-Петербург", "Saint Petersburg"),
    "AER": ("Soçi", "Сочи", "Sochi"),
    "IEV": ("Kiyev", "Киев", "Kyiv"),
    "TBS": ("Tbilisi", "Тбилиси", "Tbilisi"),
    "BUS": ("Batumi", "Батуми", "Batumi"),
    "TAS": ("Daşkənd", "Ташкент", "Tashkent"),
    "ALA": ("Almatı", "Алматы", "Almaty"),
    "DEL": ("Dehli", "Дели", "Delhi"),
    "BKK": ("Banqkok", "Бангкок", "Bangkok"),
    "LON": ("London", "Лондон", "London"),
    "PAR": ("Paris", "Париж", "Paris"),
    "BER": ("Berlin", "Берлин", "Berlin"),
    "FRA": ("Frankfurt", "Франкфурт", "Frankfurt"),
    "ROM": ("Roma", "Рим", "Rome"),
    "MIL": ("Milan", "Милан", "Milan"),
    "AMS": ("Amsterdam", "Амстердам", "Amsterdam"),
    "BCN": ("Barselona", "Барселона", "Barcelona"),
    "MAD": ("Madrid", "Мадрид", "Madrid"),
    "VIE": ("Vyana", "Вена", "Vienna"),
    "PRG": ("Praqa", "Прага", "Prague"),
    "WAW": ("Varşava", "Варшава", "Warsaw"),
    "ATH": ("Afina", "Афины", "Athens"),
    "NYC": ("Nyu-York", "Нью-Йорк", "New York"),
}
COUNTRY: dict[str, str] = {
    "GYD": "AZ",
    "KVD": "AZ",
    "NAJ": "AZ",
    "IST": "TR",
    "AYT": "TR",
    "ESB": "TR",
    "DXB": "AE",
    "DOH": "QA",
    "TLV": "IL",
    "THR": "IR",
    "CAI": "EG",
    "SSH": "EG",
    "MOW": "RU",
    "LED": "RU",
    "AER": "RU",
    "IEV": "UA",
    "TBS": "GE",
    "BUS": "GE",
    "TAS": "UZ",
    "ALA": "KZ",
    "DEL": "IN",
    "BKK": "TH",
    "LON": "GB",
    "PAR": "FR",
    "BER": "DE",
    "FRA": "DE",
    "ROM": "IT",
    "MIL": "IT",
    "AMS": "NL",
    "BCN": "ES",
    "MAD": "ES",
    "VIE": "AT",
    "PRG": "CZ",
    "WAW": "PL",
    "ATH": "GR",
    "NYC": "US",
}
# Bakıdan ən çox axtarılan istiqamətlər (quick-start düymələri üçün sıra)
POPULAR_FROM_HOME = ["IST", "DXB", "TBS", "MOW", "AYT", "LON"]
_LANG_INDEX = {"az": 0, "ru": 1, "en": 2}

STATIC_PLACES: dict[str, dict[str, str]] = {
    code: {"az": n[0], "ru": n[1], "en": n[2]} for code, n in _NAMES.items()
}


def place_name(code: str, lang: str) -> str:
    """Kod üçün ad. Siyahıda yoxdursa kodun özü."""
    names = STATIC_PLACES.get(code.upper())
    if not names:
        return code.upper()
    return names.get(lang) or names["en"]


def search_static(term: str, lang: str = "en", limit: int = 6) -> list[Place]:
    q = normalize(term)
    if not q:
        return []
    exact: list[Place] = []
    prefix: list[Place] = []
    contains: list[Place] = []
    for code, names in STATIC_PLACES.items():
        place = Place(code=code, name=names.get(lang) or names["en"], kind="city")
        if q == code.casefold():
            exact.append(place)
            continue
        normalized_names = [normalize(n) for n in names.values()]
        if any(n.startswith(q) for n in normalized_names):
            prefix.append(place)
        elif len(q) >= 3 and any(q in n for n in normalized_names):
            contains.append(place)
    return (exact + prefix + contains)[:limit]


def flag_emoji(country_code: str | None) -> str:
    """'TR' -> 🇹🇷. Naməlum/yanlış kod üçün boş sətir."""
    if not country_code or len(country_code) != 2 or not country_code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country_code.upper())
