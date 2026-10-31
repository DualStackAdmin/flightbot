"""Axından kənar yazılan mətndən marşrut çıxarmaq: "Bakı İstanbul", "istanbul", "GYD-IST".
Yalnız statik siyahı ilə və yalnız ƏMİN uyğunluqla (yanlış marşrut təklif etməkdənsə, susmaq yaxşıdır)."""

import re

from flightbot.core.places import STATIC_PLACES, Place, normalize, search_static

_SEPARATORS = re.compile(r"\s*(?:→|->|—|–|-|,|>|/)\s*|\s+")
MAX_LEN = 60


def resolve_place_strict(term: str, lang: str) -> Place | None:
    q = normalize(term)
    if not q:
        return None
    found = search_static(term, lang)
    if not found:
        return None
    for place in found:
        names = STATIC_PLACES[place.code].values()
        if q == place.code.casefold() or any(normalize(n) == q for n in names):
            return place
    if len(found) == 1 and len(q) >= 3:  # tək prefiks uyğunluğu (məs. "bak" -> Bakı)
        return found[0]
    return None


def parse_route(text: str, lang: str) -> tuple[Place | None, Place] | None:
    """(origin|None, destination). Tək yer = (None, dest): mənşə istifadəçinin ev şəhəridir."""
    text = (text or "").strip()
    if not text or len(text) > MAX_LEN:
        return None
    single = resolve_place_strict(text, lang)
    if single:
        return None, single
    for m in _SEPARATORS.finditer(text):
        left, right = text[: m.start()], text[m.end() :]
        a, b = resolve_place_strict(left, lang), resolve_place_strict(right, lang)
        if a and b and a.code != b.code:
            return a, b
    return None
