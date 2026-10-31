"""Rendering of the notification text and buttons. The payload is language-independent; the language is applied
at send time (if the user changes language in between, they get the right one)."""

from datetime import date
from decimal import Decimal
from typing import Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from flightbot.bot.callbacks import WatchCb
from flightbot.bot.i18n import esc, fmt_date, fmt_month, fmt_price, t
from flightbot.core.affiliate import build_booking_link
from flightbot.core.places import place_name


class FbCb(CallbackData, prefix="fb"):
    id: int
    vote: int  # 1 | -1


def stops_text(lang: str, transfers: int | None) -> str | None:
    if transfers is None:
        return None
    return t(lang, "stops.direct") if transfers == 0 else t(lang, "stops.n", n=transfers)


def route_title(origin: str, destination: str, lang: str) -> str:
    return f"{place_name(origin, lang)} → {place_name(destination, lang)}"


def render_notification(
    payload: dict[str, Any], lang: str, *, marker: str, notification_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    cur = payload["currency"]
    price = Decimal(payload["price"])
    depart = date.fromisoformat(payload["depart_date"])
    ret = date.fromisoformat(payload["return_date"]) if payload.get("return_date") else None
    flexible = payload.get("date_mode") == "month"

    lines = [t(lang, "notif.title", route=esc(route_title(payload["origin"], payload["destination"], lang)))]
    badge = t(lang, "notif.badge_good") if payload.get("good_price") else ""
    lines.append(t(lang, "notif.price", price=fmt_price(price), currency=cur, badge=badge))

    if flexible:
        key = "notif.dates_flex_round" if ret else "notif.dates_flex"
        lines.append(
            t(
                lang,
                key,
                depart=fmt_date(depart, lang),
                ret=fmt_date(ret, lang) if ret else "",
                month=fmt_month(date.fromisoformat(payload["window_start"]), lang),
            )
        )
    elif ret:
        lines.append(t(lang, "notif.dates_round", depart=fmt_date(depart, lang), ret=fmt_date(ret, lang)))
    else:
        lines.append(t(lang, "notif.dates_exact", depart=fmt_date(depart, lang)))

    stops = stops_text(lang, payload.get("transfers"))
    airline = payload.get("airline")
    if airline and stops:
        lines.append(t(lang, "notif.airline", airline=esc(airline), stops=stops))
    elif stops:
        lines.append(t(lang, "notif.stops_only", stops=stops))

    pct = payload.get("vs_median_pct")
    if pct is not None and pct < 0:
        lines.append(t(lang, "notif.vs_median", pct=abs(pct)))
    if payload.get("trend") == "down" and payload.get("previous_price"):
        lines.append(t(lang, "notif.trend_down", prev=fmt_price(payload["previous_price"]), currency=cur))
    lines.append(t(lang, "notif.target", target=fmt_price(payload["target_price"]), currency=cur))
    lines.append("")
    lines.append(t(lang, "notif.disclaimer"))

    link = build_booking_link(
        link_path=payload.get("link"),
        origin=payload["origin"],
        destination=payload["destination"],
        depart_date=depart,
        return_date=ret,
        marker=marker,
        sub_id=f"n{notification_id}",
    )
    rows = [[InlineKeyboardButton(text=t(lang, "btn.buy"), url=link)]]
    watch_id = payload.get("watch_id")
    if watch_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "btn.pause_short"),
                    callback_data=WatchCb(action="npause", id=watch_id).pack(),
                ),
                InlineKeyboardButton(
                    text=t(lang, "btn.edit_target"),
                    callback_data=WatchCb(action="edit", id=watch_id).pack(),
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t(lang, "btn.fb_up"), callback_data=FbCb(id=notification_id, vote=1).pack()
            ),
            InlineKeyboardButton(
                text=t(lang, "btn.fb_down"), callback_data=FbCb(id=notification_id, vote=-1).pack()
            ),
        ]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    return "\n".join(lines), kb
