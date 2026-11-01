"""Inline calendar for picking dates with taps instead of typing (Monday-first, localized)."""

import calendar as _calendar
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from flightbot.bot.callbacks import CalCb
from flightbot.bot.i18n import fmt_month, t
from flightbot.providers.base import next_month

FILLER = "·"


def prev_month(d: date) -> date:
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)


def _noop(which: str, text: str = FILLER) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=CalCb(which=which, action="noop", v="").pack())


def calendar_rows(
    which: str, month: date, lang: str, *, min_day: date, max_day: date
) -> list[list[InlineKeyboardButton]]:
    """Header with month navigation, weekday row, and the days of `month`. Days outside
    [min_day, max_day] are shown as a dot and cannot be picked."""
    month = month.replace(day=1)
    can_prev = month > min_day.replace(day=1)
    can_next = month < max_day.replace(day=1)
    header = [
        InlineKeyboardButton(
            text="‹", callback_data=CalCb(which=which, action="nav", v=f"{prev_month(month):%Y%m}").pack()
        )
        if can_prev
        else _noop(which),
        _noop(which, fmt_month(month, lang)),
        InlineKeyboardButton(
            text="›", callback_data=CalCb(which=which, action="nav", v=f"{next_month(month):%Y%m}").pack()
        )
        if can_next
        else _noop(which),
    ]
    rows = [header, [_noop(which, w) for w in t(lang, "cal.weekdays").split(",")]]
    for week in _calendar.Calendar(firstweekday=0).monthdayscalendar(month.year, month.month):
        row = []
        for day in week:
            if day == 0:
                row.append(_noop(which))
                continue
            d = date(month.year, month.month, day)
            if min_day <= d <= max_day:
                row.append(
                    InlineKeyboardButton(
                        text=str(day), callback_data=CalCb(which=which, action="pick", v=f"{d:%Y%m%d}").pack()
                    )
                )
            else:
                row.append(_noop(which))
        rows.append(row)
    return rows


def clamp_month(month: date, min_day: date, max_day: date) -> date:
    month = month.replace(day=1)
    return max(min_day.replace(day=1), min(month, max_day.replace(day=1)))


def calendar_kb(
    which: str, month: date, lang: str, *, min_day: date, max_day: date, nav_row
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[*calendar_rows(which, month, lang, min_day=min_day, max_day=max_day), nav_row]
    )
