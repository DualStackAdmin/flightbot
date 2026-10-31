from datetime import date
from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from flightbot.bot import callbacks as cb
from flightbot.bot.i18n import SUPPORTED, esc, fmt_month, fmt_price, language_name, t
from flightbot.bot.parsing import month_token, quick_targets
from flightbot.core.places import Place, flag_emoji, place_name
from flightbot.core.users import SUPPORTED_CURRENCIES

Row = list[InlineKeyboardButton]
POPULAR = ["IST", "DXB", "TBS", "MOW", "AYT", "LON", "BKK", "PAR"]
POPULAR_SHOWN = 6


def _btn(text: str, data) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def _kb(rows: list[Row]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nav_row(lang: str, *, back: bool = True) -> Row:
    row = []
    if back:
        row.append(_btn(t(lang, "btn.back"), cb.NavCb(action="back")))
    row.append(_btn(t(lang, "btn.cancel_flow"), cb.NavCb(action="cancel")))
    return row


def _pairs(buttons: Row) -> list[Row]:
    return [buttons[i : i + 2] for i in range(0, len(buttons), 2)]


# ------------------------------------------------------------------ axın addımları
def dest_kb(origin: str, lang: str, *, explore: bool) -> InlineKeyboardMarkup:
    codes = [c for c in POPULAR if c != origin][:POPULAR_SHOWN]
    popular = [
        _btn(f"{flag_emoji(_cc(c))} {place_name(c, lang)}".strip(), cb.PlaceCb(role="d", code=c))
        for c in codes
    ]
    rows = _pairs(popular)
    if explore:
        rows.append([_btn(t(lang, "btn.explore"), cb.GoCb(to="explore"))])
    rows.append(
        [
            _btn(
                t(lang, "btn.origin_change", origin=place_name(origin, lang)),
                cb.GoCb(to="origin"),
            )
        ]
    )
    rows.append(nav_row(lang, back=False))
    return _kb(rows)


def _cc(code: str) -> str | None:
    from flightbot.core.places import COUNTRY

    return COUNTRY.get(code)


def places_kb(role: str, places: list[Place], lang: str, *, back: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for p in places:
        label = p.name + (f", {p.country}" if p.country else "") + f" · {p.code}"
        rows.append([_btn(label, cb.PlaceCb(role=role, code=p.code))])
    rows.append(nav_row(lang, back=back))
    return _kb(rows)


def origin_kb(home: str | None, current: str, lang: str, *, back: bool) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    if home and home != current:
        rows.append([_btn(f"📍 {place_name(home, lang)} ({home})", cb.PlaceCb(role="o", code=home))])
    rows.append(nav_row(lang, back=back))
    return _kb(rows)


def months_rows(which: str, months: list[date], lang: str) -> list[Row]:
    buttons = [_btn(fmt_month(m, lang), cb.MonthCb(which=which, ym=month_token(m))) for m in months]
    return _pairs(buttons)


def when_kb(months: list[date], lang: str, *, simple: bool, advanced: bool) -> InlineKeyboardMarkup:
    rows = months_rows("dep", months, lang)
    if not simple:
        rows.append([_btn(t(lang, "btn.exact_date"), cb.GoCb(to="exact"))])
        label = t(lang, "btn.advanced_on" if advanced else "btn.advanced")
        rows.append([_btn(label, cb.GoCb(to="advanced"))])
    rows.append(nav_row(lang))
    return _kb(rows)


def explore_months_kb(months: list[date], origin: str, lang: str, *, back: bool) -> InlineKeyboardMarkup:
    rows = months_rows("dep", months, lang)
    rows.append([_btn(t(lang, "btn.origin_change", origin=place_name(origin, lang)), cb.GoCb(to="origin"))])
    rows.append(nav_row(lang, back=back))
    return _kb(rows)


def ret_months_kb(months: list[date], lang: str) -> InlineKeyboardMarkup:
    rows = months_rows("ret", months, lang)
    rows.append(nav_row(lang))
    return _kb(rows)


def trip_kb(lang: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                _btn(t(lang, "btn.oneway"), cb.TripCb(round_trip=0)),
                _btn(t(lang, "btn.roundtrip"), cb.TripCb(round_trip=1)),
            ],
            nav_row(lang),
        ]
    )


def direct_kb(lang: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                _btn(t(lang, "btn.yes"), cb.DirectCb(direct=1)),
                _btn(t(lang, "btn.no"), cb.DirectCb(direct=0)),
            ],
            nav_row(lang),
        ]
    )


def nav_only_kb(lang: str, *, back: bool = True) -> InlineKeyboardMarkup:
    return _kb([nav_row(lang, back=back)])


def _target_buttons(current: Decimal, lang: str, data_cls) -> list[Row]:
    rows: list[Row] = []
    quick = quick_targets(current)  # birincisi tövsiyə olunandır
    for idx, (pct, value) in enumerate(quick):
        key = "btn.target_rec" if idx == 0 else "btn.target_pct"
        label = t(lang, key, pct=pct, price=fmt_price(value))
        button = _btn(label, data_cls(cents=value * 100))
        if idx == 0:
            rows.append([button])
        elif idx == 1:
            rows.append([button])
        else:
            rows[-1].append(button)
    return rows


def target_kb(current: Decimal | None, lang: str) -> InlineKeyboardMarkup:
    rows = _target_buttons(current, lang, cb.TargetCb) if current is not None else []
    rows.append(nav_row(lang))
    return _kb(rows)


def target_warning_kb(cents: int, lang: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [_btn(t(lang, "btn.target_continue"), cb.TargetCb(cents=cents, force=1))],
            [_btn(t(lang, "btn.target_other"), cb.GoCb(to="retarget"))],
        ]
    )


def edit_target_kb(current: Decimal | None, lang: str) -> InlineKeyboardMarkup:
    rows = _target_buttons(current, lang, cb.EditTargetCb) if current is not None else []
    rows.append([_btn(t(lang, "btn.cancel_flow"), cb.NavCb(action="cancel"))])
    return _kb(rows)


def created_kb(lang: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                _btn(t(lang, "btn.more_route"), cb.MenuCb(action="new")),
                _btn(t(lang, "btn.my_watches"), cb.MenuCb(action="list")),
            ]
        ]
    )


def menu_kb(lang: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [_btn(t(lang, "menu.new"), cb.MenuCb(action="new"))],
            [_btn(t(lang, "menu.explore"), cb.MenuCb(action="explore"))],
            [
                _btn(t(lang, "menu.search"), cb.MenuCb(action="search")),
                _btn(t(lang, "menu.list"), cb.MenuCb(action="list")),
            ],
        ]
    )


# ------------------------------------------------------------- explore / search nəticələri
def explore_list_kb(items: list[dict], lang: str) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    for i, it in enumerate(items):
        label = f"{flag_emoji(it.get('cc'))} {it['name']} · {fmt_price(it['price'])} {it['currency']}"
        rows.append([_btn(label.strip(), cb.ExploreCb(i=i))])
    rows.append(nav_row(lang))
    return _kb(rows)


def explore_detail_kb(buy_url: str, lang: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=t(lang, "btn.buy"), url=buy_url)],
            [_btn(t(lang, "btn.watch_this"), cb.GoCb(to="watch"))],
            nav_row(lang),
        ]
    )


def search_result_kb(lang: str) -> InlineKeyboardMarkup:
    return _kb([[_btn(t(lang, "btn.watch_this"), cb.GoCb(to="watch"))], nav_row(lang)])


# ------------------------------------------------------------------------------ siyahı
def watch_item_kb(watch_id: int, status: str, lang: str) -> InlineKeyboardMarkup:
    toggle = (
        _btn(t(lang, "btn.resume"), cb.WatchCb(action="resume", id=watch_id))
        if status == "paused"
        else _btn(t(lang, "btn.pause"), cb.WatchCb(action="pause", id=watch_id))
    )
    return _kb(
        [
            [toggle, _btn(t(lang, "btn.edit_target"), cb.WatchCb(action="edit", id=watch_id))],
            [_btn(t(lang, "btn.delete"), cb.WatchCb(action="del", id=watch_id))],
        ]
    )


# ----------------------------------------------------------------------------- ayarlar
def settings_kb(current_lang: str, current_currency: str, quiet: bool) -> InlineKeyboardMarkup:
    langs = [
        _btn(("✅ " if code == current_lang else "") + language_name(code), cb.LangCb(lang=code))
        for code in SUPPORTED
    ]
    currencies = [
        _btn(("✅ " if c == current_currency else "") + c, cb.CurCb(cur=c)) for c in SUPPORTED_CURRENCIES
    ]
    state = t(current_lang, "state.on" if quiet else "state.off")
    return _kb(
        [
            langs,
            currencies,
            [
                _btn(t(current_lang, "btn.home"), cb.GoCb(to="sethome")),
                _btn(t(current_lang, "btn.quiet", state=state), cb.QuietCb()),
            ],
        ]
    )


def delete_kb(lang: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [_btn(t(lang, "btn.delete_confirm"), cb.DeleteCb(action="confirm"))],
            [_btn(t(lang, "btn.cancel"), cb.DeleteCb(action="cancel"))],
        ]
    )


__all__ = ["esc"]
