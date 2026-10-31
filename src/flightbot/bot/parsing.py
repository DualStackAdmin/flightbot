"""Parsing of user input (dates, prices). Pure functions, fully tested."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

_ISO = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$")
_DMY = re.compile(r"^(\d{1,2})[-./](\d{1,2})[-./](\d{2}|\d{4})$")
_DM = re.compile(r"^(\d{1,2})[-./](\d{1,2})$")

MAX_PRICE = Decimal("100000")


def parse_user_date(text: str, today: date) -> date | None:
    """DD.MM.YYYY, DD.MM.YY, DD.MM (next occurrence), YYYY-MM-DD. None if invalid."""
    text = (text or "").strip()
    try:
        if m := _ISO.match(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := _DMY.match(text):
            year = int(m[3])
            year = year + 2000 if year < 100 else year
            return date(year, int(m[2]), int(m[1]))
        if m := _DM.match(text):
            d = date(today.year, int(m[2]), int(m[1]))
            if d < today:
                d = date(today.year + 1, int(m[2]), int(m[1]))
            return d
    except ValueError:
        return None
    return None


def parse_price(text: str) -> Decimal | None:
    """'120', '120.5', '120,5', '120 USD' -> Decimal. None for zero, negative, huge or unparseable input."""
    text = text or ""
    if any(ch in text for ch in "-−–+"):  # "-5" must not silently become 5
        return None
    cleaned = re.sub(r"[^\d.,]", "", text.replace(" ", ""))
    if not cleaned:
        return None
    cleaned = cleaned.replace(",", ".")
    if cleaned.count(".") > 1:
        return None
    try:
        value = Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return value if Decimal("0") < value <= MAX_PRICE else None


def next_months(today: date, n: int = 10) -> list[date]:
    """First days of n months, starting with the current month."""
    out: list[date] = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append(date(y, m, 1))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def parse_month_token(token: str) -> date | None:
    """'2026-07' -> date(2026, 7, 1)."""
    try:
        y, m = token.split("-")
        return date(int(y), int(m), 1)
    except (ValueError, AttributeError):
        return None


def month_token(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def quick_targets(current: Decimal, percents: tuple[int, ...] = (15, 10, 25)) -> list[tuple[int, int]]:
    """(percent, target price) pairs; the target is at least 1. The first one (15%) is the recommendation."""
    return [(p, max(1, int(current * (100 - p) / 100))) for p in percents]
