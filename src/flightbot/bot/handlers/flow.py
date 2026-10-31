"""Flow engine: the shared step system for /new, /search and /explore.

Goal: the default watch takes 3 touches (destination -> month -> target price). Origin = home city, one-way,
"direct only" is off. Every step has "Back" and "Cancel". Transitions triggered by a callback edit the existing message.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.bot import keyboards as kb
from flightbot.bot.callbacks import (
    DirectCb,
    ExploreCb,
    GoCb,
    MenuCb,
    MonthCb,
    NavCb,
    PlaceCb,
    TargetCb,
    TripCb,
)
from flightbot.bot.deps import Deps
from flightbot.bot.formatting import describe_key
from flightbot.bot.i18n import esc, fmt_date, fmt_month, fmt_price
from flightbot.bot.parsing import next_months, parse_month_token, parse_price, parse_user_date
from flightbot.bot.render import route_title, stops_text
from flightbot.bot.states import Flow
from flightbot.bot.ui import edit_or_send, show
from flightbot.core.affiliate import build_booking_link
from flightbot.core.clock import utcnow
from flightbot.core.places import flag_emoji, place_name
from flightbot.core.plans import effective_plan, limits_for
from flightbot.core.stats import key_price_stats
from flightbot.core.users import set_home
from flightbot.core.watch_key import MAX_HORIZON_DAYS, InvalidWatch, WatchKey
from flightbot.core.watches import QuotaExceeded, count_active, create_or_update_watch
from flightbot.db.models import User
from flightbot.logging import get_logger
from flightbot.providers.base import PriceQuote, cheapest

log = get_logger(__name__)
router = Router(name="flow")

TEXT_INPUT = (F.text, ~F.text.startswith("/"))
PROVIDER_TIMEOUT_S = 15.0
EXPLORE_TIMEOUT_S = 25.0
MONTH_GRID = 6
EXPLORE_ITEMS = 10

STEP_STATE = {
    "dest": Flow.dest,
    "origin": Flow.origin,
    "when": Flow.when,
    "date": Flow.date,
    "trip": Flow.trip,
    "ret": Flow.ret,
    "direct": Flow.direct,
    "target": Flow.target,
    "x_when": Flow.x_when,
    "x_list": Flow.x_list,
    "x_detail": Flow.x_detail,
    "s_result": Flow.s_result,
}


@dataclass(slots=True)
class Ctx:
    target: Message | CallbackQuery
    state: FSMContext
    user: User
    session: AsyncSession
    tr: Callable[..., str]
    deps: Deps
    edit_msg: Message | None = None  # "please wait" message: the next output should edit it

    @property
    def lang(self) -> str:
        return self.user.language

    async def show(self, text: str, markup=None) -> Message | None:
        if self.edit_msg is not None:
            msg, self.edit_msg = self.edit_msg, None
            return await edit_or_send(msg, text, markup)
        return await show(self.target, text, markup)


def _today() -> date:
    return utcnow().date()


def _origin(d: dict, c: Ctx) -> str:
    return d.get("origin") or c.user.home_iata or c.deps.settings.default_home_iata


def _build_key(d: dict, user: User) -> WatchKey:
    return WatchKey.create(
        origin=d["origin"],
        destination=d["destination"],
        date_mode=d.get("mode", "month"),
        depart_date=date.fromisoformat(d["depart"]),
        return_date=date.fromisoformat(d["ret"]) if d.get("ret") else None,
        direct_only=bool(d.get("direct")),
        currency=user.currency,
        today=_today(),
    )


def _date_error(d: date, today: date, not_before: date | None = None) -> str | None:
    if d < today:
        return "date_in_past"
    if not_before is not None and d < not_before:
        return "return_before_depart"
    if (d - today).days > MAX_HORIZON_DAYS:
        return "date_too_far"
    return None


# ================================================================== step engine
async def goto(c: Ctx, step: str, *, push: bool = True, text: str | None = None) -> None:
    d = await c.state.get_data()
    history = list(d.get("history", []))
    current = d.get("step")
    if push and current and current != step:
        history.append(current)
    await c.state.update_data(step=step, history=history)
    await c.state.set_state(STEP_STATE[step])
    await render(c, step, text)


async def go_back(c: Ctx) -> bool:
    d = await c.state.get_data()
    history = list(d.get("history", []))
    if not history:
        return False
    prev = history.pop()
    await c.state.update_data(step=prev, history=history)
    await c.state.set_state(STEP_STATE[prev])
    await render(c, prev)
    return True


async def render(c: Ctx, step: str, text: str | None = None) -> None:
    d = await c.state.get_data()
    lang, tr = c.lang, c.tr
    origin = _origin(d, c)
    purpose = d.get("purpose", "watch")
    today = _today()
    has_history = bool(d.get("history"))

    if step == "dest":
        await show(
            c.target,
            text or tr("step.dest", origin=esc(place_name(origin, lang))),
            kb.dest_kb(origin, lang, explore=purpose == "watch"),
        )
    elif step == "origin":
        await c.show(tr("step.origin"), kb.origin_kb(c.user.home_iata, origin, lang, back=has_history))
    elif step == "when":
        route = esc(route_title(origin, d["destination"], lang))
        simple = purpose == "search"
        body = f"<b>{route}</b>\n\n{tr('search.ask_month')}" if simple else tr("step.when", route=route)
        await show(
            c.target,
            body,
            kb.when_kb(next_months(today, MONTH_GRID), lang, simple=simple, advanced=bool(d.get("advanced"))),
        )
    elif step == "x_when":
        await show(
            c.target,
            tr("explore.ask_month", origin=esc(place_name(origin, lang))),
            kb.explore_months_kb(next_months(today, MONTH_GRID), origin, lang, back=has_history),
        )
    elif step == "date":
        await c.show(tr("step.date"), kb.nav_only_kb(lang))
    elif step == "trip":
        await c.show(tr("step.trip"), kb.trip_kb(lang))
    elif step == "ret":
        if d.get("mode") == "exact":
            await c.show(tr("step.ret_date"), kb.nav_only_kb(lang))
        else:
            depart_month = date.fromisoformat(d["depart"])
            months = [m for m in next_months(today, 12) if m >= depart_month][:MONTH_GRID]
            await c.show(tr("step.ret_month"), kb.ret_months_kb(months, lang))
    elif step == "direct":
        await c.show(tr("step.direct"), kb.direct_kb(lang))
    elif step == "target":
        await render_target(c)
    elif step == "x_list":
        month = date.fromisoformat(d["explore_month"])
        await show(
            c.target,
            tr("explore.header", origin=esc(place_name(origin, lang)), month=fmt_month(month, lang)),
            kb.explore_list_kb(d["explore"], lang),
        )
    elif step == "x_detail":
        await render_explore_detail(c, d, origin)
    elif step == "s_result":
        await render_search_result(c, d, origin)


# ======================================================================== start
async def begin(
    target: Message | CallbackQuery,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
    purpose: str,
    *,
    origin: str | None = None,
    destination: str | None = None,
    text: str | None = None,
) -> None:
    await state.clear()
    c = Ctx(target, state, user, session, tr, deps)
    if purpose == "watch":
        limits = limits_for(effective_plan(user.plan, user.plan_expires_at, utcnow()))
        if await count_active(session, user.id) >= limits.max_active_watches:
            await show(
                target, tr("quota.max_watches", limit=limits.max_active_watches), kb.menu_kb(user.language)
            )
            return
    origin = origin or user.home_iata or deps.settings.default_home_iata
    await state.update_data(purpose=purpose, origin=origin, history=[], step=None)
    if destination:
        await state.update_data(destination=destination)
        first = "when"
    elif purpose == "explore":
        first = "x_when"
    else:
        first = "dest"
    await goto(c, first, push=False, text=text)


def _ctx(target, state, user, session, tr, deps) -> Ctx:
    return Ctx(target, state, user, session, tr, deps)


@router.message(Command("new"))
async def cmd_new(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await begin(message, state, user, session, tr, deps, "watch")


@router.message(Command("search"))
async def cmd_search(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await begin(message, state, user, session, tr, deps, "search")


@router.message(Command("explore"))
async def cmd_explore(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await begin(message, state, user, session, tr, deps, "explore")


@router.callback_query(MenuCb.filter(F.action.in_({"new", "search", "explore"})))
async def menu_start(
    cb: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    await cb.answer()
    purpose = {"new": "watch", "search": "search", "explore": "explore"}[callback_data.action]
    await begin(cb, state, user, session, tr, deps, purpose)


# ========================================================================= naviqasiya
@router.callback_query(NavCb.filter(F.action == "back"))
async def on_back(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    c = _ctx(cb, state, user, session, tr, deps)
    if not await state.get_state():
        await cb.answer(tr("error.stale"), show_alert=True)
        return
    await cb.answer()
    if not await go_back(c):
        await state.clear()
        await show(cb, tr("cancelled"), kb.menu_kb(user.language))


@router.callback_query(NavCb.filter(F.action == "cancel"))
async def on_cancel(cb: CallbackQuery, state: FSMContext, user: User, tr) -> None:
    await cb.answer()
    await state.clear()
    await show(cb, tr("cancelled"), kb.menu_kb(user.language))


# ============================================================ place selection (destination / origin)
async def _offer_places(message: Message, role: str, c: Ctx, *, back: bool) -> None:
    found = await c.deps.places.search((message.text or "").strip()[:64], c.lang)
    if not found:
        await message.answer(c.tr("place.not_found"), reply_markup=kb.nav_only_kb(c.lang, back=back))
        return
    await message.answer(c.tr("place.pick"), reply_markup=kb.places_kb(role, found, c.lang, back=back))


@router.message(Flow.dest, *TEXT_INPUT)
async def dest_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await _offer_places(message, "d", _ctx(message, state, user, session, tr, deps), back=False)


@router.message(Flow.origin, *TEXT_INPUT)
async def origin_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    d = await state.get_data()
    await _offer_places(
        message, "o", _ctx(message, state, user, session, tr, deps), back=bool(d.get("history"))
    )


@router.callback_query(PlaceCb.filter(F.role == "d"), Flow.dest)
async def pick_destination(
    cb: CallbackQuery,
    callback_data: PlaceCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    d = await state.get_data()
    if callback_data.code == _origin(d, _ctx(cb, state, user, session, tr, deps)):
        await cb.answer(tr("invalid.same_airport"), show_alert=True)
        return
    await cb.answer()
    await state.update_data(destination=callback_data.code, hint_price=None)
    await goto(_ctx(cb, state, user, session, tr, deps), "when")


@router.callback_query(PlaceCb.filter(F.role == "o"), Flow.origin)
async def pick_origin(
    cb: CallbackQuery,
    callback_data: PlaceCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    await cb.answer()
    d = await state.get_data()
    if d.get("purpose") == "sethome":  # /settings -> Home city
        await set_home(session, user.id, callback_data.code)
        await state.clear()
        city = esc(place_name(callback_data.code, user.language))
        await show(cb, tr("home.saved", city=city), kb.menu_kb(user.language))
        return
    await state.update_data(origin=callback_data.code)
    c = _ctx(cb, state, user, session, tr, deps)
    if not await go_back(c):  # empty history (rare): go to the destination step
        await goto(c, "dest", push=False)


@router.callback_query(GoCb.filter(F.to == "origin"), StateFilter(Flow.dest, Flow.x_when))
async def go_origin(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await cb.answer()
    await goto(_ctx(cb, state, user, session, tr, deps), "origin")


@router.callback_query(GoCb.filter(F.to == "sethome"))
async def go_sethome(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await cb.answer()
    await state.clear()
    await state.update_data(purpose="sethome", origin=user.home_iata, history=[], step=None)
    await goto(_ctx(cb, state, user, session, tr, deps), "origin", push=False)


@router.callback_query(GoCb.filter(F.to == "explore"), Flow.dest)
async def go_explore(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await cb.answer()
    await state.update_data(purpose="explore")
    await goto(_ctx(cb, state, user, session, tr, deps), "x_when")


# ================================================================ month / date selection
async def _after_when(c: Ctx) -> None:
    """The date is settled: if "details" is on, ask trip type/direct; otherwise go straight to the target price."""
    d = await c.state.get_data()
    if d.get("advanced"):
        await goto(c, "trip")
    else:
        await c.state.update_data(ret=None, direct=False)
        await goto(c, "target")


@router.callback_query(MonthCb.filter(F.which == "dep"), Flow.when)
async def pick_month(
    cb: CallbackQuery,
    callback_data: MonthCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    month = parse_month_token(callback_data.ym)
    if month is None or month < _today().replace(day=1):
        await cb.answer(tr("invalid.date_in_past"), show_alert=True)
        return
    await cb.answer()
    await state.update_data(depart=month.isoformat(), mode="month", hint_price=None)
    c = _ctx(cb, state, user, session, tr, deps)
    d = await state.get_data()
    if d.get("purpose") == "search":
        await run_search(c)
    else:
        await _after_when(c)


@router.callback_query(GoCb.filter(F.to == "exact"), Flow.when)
async def go_exact(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await cb.answer()
    await state.update_data(mode="exact", hint_price=None)
    await goto(_ctx(cb, state, user, session, tr, deps), "date")


@router.callback_query(GoCb.filter(F.to == "advanced"), Flow.when)
async def go_advanced(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await cb.answer()
    d = await state.get_data()
    await state.update_data(advanced=not d.get("advanced"))
    await render(_ctx(cb, state, user, session, tr, deps), "when")


@router.message(Flow.date, *TEXT_INPUT)
async def date_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    today = _today()
    d = parse_user_date(message.text or "", today)
    if d is None:
        await message.answer(tr("new.bad_date"), reply_markup=kb.nav_only_kb(user.language))
        return
    if err := _date_error(d, today):
        await message.answer(tr(f"invalid.{err}"), reply_markup=kb.nav_only_kb(user.language))
        return
    await state.update_data(depart=d.isoformat(), mode="exact", hint_price=None)
    await _after_when(_ctx(message, state, user, session, tr, deps))


@router.callback_query(TripCb.filter(), Flow.trip)
async def pick_trip(
    cb: CallbackQuery,
    callback_data: TripCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    await cb.answer()
    c = _ctx(cb, state, user, session, tr, deps)
    if callback_data.round_trip:
        await goto(c, "ret")
    else:
        await state.update_data(ret=None)
        await goto(c, "direct")


@router.message(Flow.ret, *TEXT_INPUT)
async def return_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    d = await state.get_data()
    if d.get("mode") != "exact":
        await message.answer(tr("step.ret_month"), reply_markup=kb.nav_only_kb(user.language))
        return
    today = _today()
    parsed = parse_user_date(message.text or "", today)
    if parsed is None:
        await message.answer(tr("new.bad_date"), reply_markup=kb.nav_only_kb(user.language))
        return
    if err := _date_error(parsed, today, not_before=date.fromisoformat(d["depart"])):
        await message.answer(tr(f"invalid.{err}"), reply_markup=kb.nav_only_kb(user.language))
        return
    await state.update_data(ret=parsed.isoformat())
    await goto(_ctx(message, state, user, session, tr, deps), "direct")


@router.callback_query(MonthCb.filter(F.which == "ret"), Flow.ret)
async def pick_return_month(
    cb: CallbackQuery,
    callback_data: MonthCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    month = parse_month_token(callback_data.ym)
    d = await state.get_data()
    if month is None or month < date.fromisoformat(d["depart"]):
        await cb.answer(tr("invalid.return_before_depart"), show_alert=True)
        return
    await cb.answer()
    await state.update_data(ret=month.isoformat())
    await goto(_ctx(cb, state, user, session, tr, deps), "direct")


@router.callback_query(DirectCb.filter(), Flow.direct)
async def pick_direct(
    cb: CallbackQuery,
    callback_data: DirectCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    await cb.answer()
    await state.update_data(direct=bool(callback_data.direct))
    await goto(_ctx(cb, state, user, session, tr, deps), "target")


# ===================================================================== target price
async def _current_price(provider, key: WatchKey) -> Decimal | None:
    try:
        quote = await asyncio.wait_for(cheapest(provider, key), PROVIDER_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001  (a provider error must not break the flow)
        log.warning("current_price_failed", error=repr(exc))
        return None
    return quote.price if quote else None


async def render_target(c: Ctx) -> None:
    d = await c.state.get_data()
    try:
        key = _build_key(d, c.user)
    except (InvalidWatch, KeyError) as exc:
        code = getattr(exc, "code", None)
        await c.show(c.tr(f"invalid.{code}") if code else c.tr("new.state_lost"), kb.menu_kb(c.lang))
        await c.state.clear()
        return

    # No silent waiting: show "checking prices" right away while the provider is queried
    hint = d.get("hint_price")
    waiting = await c.show(c.tr("target.looking")) if hint is None else None
    c.edit_msg = waiting
    current = Decimal(hint) if hint is not None else await _current_price(c.deps.provider, key)
    stats = await key_price_stats(c.session, key, utcnow())

    cur = key.currency
    info = [
        c.tr("target.current", price=fmt_price(current), currency=cur)
        if current is not None
        else c.tr("target.none")
    ]
    if stats.reliable and stats.median is not None:
        info.append(c.tr("target.median", median=fmt_price(stats.median), currency=cur))
    route, dates, _flags = describe_key(key, c.lang)
    await c.state.update_data(current_price=str(current) if current is not None else None)
    text = c.tr("step.target", route=esc(route), dates=dates, info="\n".join(info) + "\n", currency=cur)
    await c.show(text, kb.target_kb(current, c.lang))


@router.callback_query(GoCb.filter(F.to == "retarget"), Flow.target)
async def go_retarget(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await cb.answer()
    await render_target(_ctx(cb, state, user, session, tr, deps))


@router.callback_query(TargetCb.filter(), Flow.target)
async def target_button(
    cb: CallbackQuery,
    callback_data: TargetCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    await cb.answer()
    await handle_target(
        _ctx(cb, state, user, session, tr, deps),
        Decimal(callback_data.cents) / 100,
        force=bool(callback_data.force),
    )


@router.message(Flow.target, *TEXT_INPUT)
async def target_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    price = parse_price(message.text or "")
    if price is None:
        await message.answer(tr("new.bad_price"), reply_markup=kb.nav_only_kb(user.language))
        return
    await handle_target(_ctx(message, state, user, session, tr, deps), price, force=False)


async def handle_target(c: Ctx, price: Decimal, *, force: bool) -> None:
    d = await c.state.get_data()
    current = Decimal(d["current_price"]) if d.get("current_price") else None
    if not force and current is not None and price >= current:
        # The price is already below the target: a notification would fire immediately. The user must choose this knowingly.
        text = c.tr("target.already", current=fmt_price(current), currency=c.user.currency)
        await c.show(text, kb.target_warning_kb(int(price * 100), c.lang))
        return
    await finish_watch(c, price, current)


async def finish_watch(c: Ctx, price: Decimal, current: Decimal | None) -> None:
    d = await c.state.get_data()
    try:
        key = _build_key(d, c.user)
    except (InvalidWatch, KeyError) as exc:
        code = getattr(exc, "code", None)
        await c.show(c.tr(f"invalid.{code}") if code else c.tr("new.state_lost"), kb.menu_kb(c.lang))
        await c.state.clear()
        return
    try:
        _, created = await create_or_update_watch(
            c.session, user_id=c.user.id, key=key, target_price=price, now=utcnow()
        )
    except QuotaExceeded as exc:
        await c.show(c.tr(f"quota.{exc.code}", limit=exc.limit), kb.menu_kb(c.lang))
        await c.state.clear()
        return
    route, dates, flags = describe_key(key, c.lang)
    summary = c.tr(
        "summary.line",
        route=esc(route),
        dates=dates,
        target=fmt_price(price),
        currency=key.currency,
        flags=flags,
    )
    now_line = (
        c.tr("created.now_line", price=fmt_price(current), currency=key.currency)
        if current is not None
        else ""
    )
    await show(
        c.target,
        c.tr("created.text" if created else "updated.text", summary=summary, now=now_line),
        kb.created_kb(c.lang),
    )
    await c.state.clear()


# ===================================================================== /search
async def run_search(c: Ctx) -> None:
    d = await c.state.get_data()
    try:
        key = WatchKey.create(
            origin=d["origin"],
            destination=d["destination"],
            date_mode="month",
            depart_date=date.fromisoformat(d["depart"]),
            currency=c.user.currency,
            today=_today(),
        )
    except (InvalidWatch, KeyError):
        await c.show(c.tr("new.state_lost"), kb.menu_kb(c.lang))
        await c.state.clear()
        return
    waiting = await c.show(c.tr("search.searching"))
    c.edit_msg = waiting
    try:
        offers = await asyncio.wait_for(c.deps.provider.offers(key), PROVIDER_TIMEOUT_S + 5)
    except Exception as exc:  # noqa: BLE001
        log.warning("search_failed", error=repr(exc))
        await c.show(c.tr("search.failed"), kb.nav_only_kb(c.lang))
        return
    if not offers:
        await c.show(c.tr("search.none"), kb.nav_only_kb(c.lang))
        return
    best: dict[date, PriceQuote] = {}
    for q in offers:
        if q.depart_date not in best or q.price < best[q.depart_date].price:
            best[q.depart_date] = q
    top = sorted(best.values(), key=lambda q: q.price)[:5]
    items = [
        {
            "date": q.depart_date.isoformat(),
            "price": str(q.price),
            "currency": q.currency,
            "transfers": q.transfers,
            "airline": q.airline,
        }
        for q in top
    ]
    await c.state.update_data(search=items, hint_price=str(top[0].price))
    await goto(c, "s_result")


async def render_search_result(c: Ctx, d: dict, origin: str) -> None:
    key_route = esc(route_title(origin, d["destination"], c.lang))
    month = fmt_month(date.fromisoformat(d["depart"]), c.lang)
    lines = [c.tr("search.header", route=key_route, month=month)]
    for it in d["search"]:
        parts = [
            p
            for p in (stops_text(c.lang, it["transfers"]), esc(it["airline"]) if it["airline"] else None)
            if p
        ]
        lines.append(
            c.tr(
                "search.line",
                date=fmt_date(date.fromisoformat(it["date"]), c.lang),
                price=fmt_price(it["price"]),
                currency=it["currency"],
                details=" · ".join(parts) or "—",
            )
        )
    lines += ["", c.tr("notif.disclaimer")]
    await c.show("\n".join(lines), kb.search_result_kb(c.lang))


# ===================================================================== /explore
@router.callback_query(MonthCb.filter(F.which == "dep"), Flow.x_when)
async def pick_explore_month(
    cb: CallbackQuery,
    callback_data: MonthCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    month = parse_month_token(callback_data.ym)
    if month is None or month < _today().replace(day=1):
        await cb.answer(tr("invalid.date_in_past"), show_alert=True)
        return
    await cb.answer()
    c = _ctx(cb, state, user, session, tr, deps)
    d = await state.get_data()
    origin = _origin(d, c)
    c.edit_msg = await show(cb, tr("explore.looking"))
    try:
        quotes = await asyncio.wait_for(
            deps.provider.explore(
                origin=origin, month=month, currency=user.currency, limit=EXPLORE_ITEMS * 2
            ),
            EXPLORE_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001  (provider/timeout: a friendly message to the user)
        log.warning("explore_failed", error=repr(exc))
        await c.show(tr("explore.failed"), kb.nav_only_kb(user.language))
        return
    quotes = [q for q in quotes if q.destination and q.destination != origin][:EXPLORE_ITEMS]
    if not quotes:
        await c.show(tr("explore.none"), kb.nav_only_kb(user.language))
        return
    items = []
    for q in quotes:
        info = await deps.names.lookup(q.destination, user.language)
        items.append(
            {
                "code": q.destination,
                "name": esc(info.name),
                "cc": info.country,
                "price": str(q.price),
                "currency": q.currency,
                "depart": q.depart_date.isoformat(),
                "transfers": q.transfers,
                "airline": q.airline,
                "link": q.link,
            }
        )
    await state.update_data(explore=items, explore_month=month.isoformat(), origin=origin)
    await goto(c, "x_list")


@router.callback_query(ExploreCb.filter(), Flow.x_list)
async def pick_explore_item(
    cb: CallbackQuery,
    callback_data: ExploreCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    deps: Deps,
) -> None:
    d = await state.get_data()
    items = d.get("explore") or []
    if not 0 <= callback_data.i < len(items):
        await cb.answer(tr("error.stale"), show_alert=True)
        return
    await cb.answer()
    it = items[callback_data.i]
    await state.update_data(
        x_index=callback_data.i,
        destination=it["code"],
        depart=d["explore_month"],
        mode="month",
        ret=None,
        direct=False,
        hint_price=it["price"],
    )
    await goto(_ctx(cb, state, user, session, tr, deps), "x_detail")


async def render_explore_detail(c: Ctx, d: dict, origin: str) -> None:
    it = d["explore"][d["x_index"]]
    month = date.fromisoformat(d["explore_month"])
    depart = date.fromisoformat(it["depart"])
    parts = [
        p for p in (stops_text(c.lang, it["transfers"]), esc(it["airline"]) if it["airline"] else None) if p
    ]
    route = f"{esc(place_name(origin, c.lang))} → {it['name']}"
    text = c.tr(
        "explore.detail",
        flag=flag_emoji(it.get("cc")),
        route=route,
        month=fmt_month(month, c.lang),
        price=fmt_price(it["price"]),
        currency=it["currency"],
        date=fmt_date(depart, c.lang),
        details=" · ".join(parts) or "—",
    )
    url = build_booking_link(
        link_path=it.get("link"),
        origin=origin,
        destination=it["code"],
        depart_date=depart,
        return_date=None,
        marker=c.deps.settings.travelpayouts_marker,
        sub_id=f"x{c.user.id}",
    )
    await c.show(text.strip(), kb.explore_detail_kb(url, c.lang))


@router.callback_query(GoCb.filter(F.to == "watch"), StateFilter(Flow.x_detail, Flow.s_result))
async def go_watch(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    d = await state.get_data()
    if not all(k in d for k in ("origin", "destination", "depart")):
        await cb.answer(tr("error.stale"), show_alert=True)
        return
    await cb.answer()
    await state.update_data(mode="month", ret=None, direct=False)
    await goto(_ctx(cb, state, user, session, tr, deps), "target")


# ============================================================== text outside the current step
@router.message(StateFilter(*STEP_STATE.values()), F.text, ~F.text.startswith("/"))
async def text_in_wrong_step(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    """The user typed instead of pressing a button: re-show the current step (never leave them without a reply)."""
    d = await state.get_data()
    step = d.get("step")
    if step in STEP_STATE:
        await render(_ctx(message, state, user, session, tr, deps), step)
    else:
        await state.clear()
        await message.answer(tr("fallback.unknown"), reply_markup=kb.menu_kb(user.language))
