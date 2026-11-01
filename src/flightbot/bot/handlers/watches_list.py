from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.bot import keyboards as kb
from flightbot.bot.callbacks import EditTargetCb, MenuCb, WatchCb
from flightbot.bot.formatting import describe_key
from flightbot.bot.i18n import esc, fmt_price
from flightbot.bot.parsing import MAX_PRICE, parse_price
from flightbot.bot.states import Flow
from flightbot.bot.ui import edit_or_send
from flightbot.core.clock import utcnow
from flightbot.core.watches import (
    QuotaExceeded,
    delete_watch,
    get_watch_with_key,
    list_watches,
    set_paused,
    update_target,
)
from flightbot.db.models import User, Watch
from flightbot.db.models import WatchKey as WatchKeyRow

router = Router(name="watches_list")


def render_item(watch: Watch, key: WatchKeyRow, lang: str, tr) -> tuple[str, InlineKeyboardMarkup]:
    route, dates, flags = describe_key(key, lang)
    current = (
        f"{fmt_price(key.last_price)} {key.currency}" if key.last_price is not None else tr("list.no_current")
    )
    text = tr(
        "list.item",
        status="⏸ " if watch.status == "paused" else "",
        route=esc(route),
        dates=dates,
        flags=flags,
        target=fmt_price(watch.target_price),
        currency=key.currency,
        current=current,
    )
    return text, kb.watch_item_kb(watch.id, watch.status, lang)


async def send_list(message: Message, user: User, session: AsyncSession, tr) -> None:
    items = await list_watches(session, user.id)
    if not items:
        await message.answer(tr("list.empty"), reply_markup=kb.menu_kb(user.language))
        return
    await message.answer(tr("list.header", n=len(items)))
    for watch, key in items:
        text, markup = render_item(watch, key, user.language, tr)
        await message.answer(text, reply_markup=markup)


@router.message(Command("list"))
async def cmd_list(message: Message, user: User, session: AsyncSession, tr) -> None:
    await send_list(message, user, session, tr)


@router.callback_query(MenuCb.filter(F.action == "list"))
async def menu_list(cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession, tr) -> None:
    await cb.answer()
    await state.clear()
    if isinstance(cb.message, Message):
        await send_list(cb.message, user, session, tr)


@router.callback_query(WatchCb.filter(F.action == "edit"))
async def edit_start(
    cb: CallbackQuery, callback_data: WatchCb, state: FSMContext, user: User, session: AsyncSession, tr
) -> None:
    row = await get_watch_with_key(session, user_id=user.id, watch_id=callback_data.id)
    if row is None:
        await cb.answer(tr("list.not_found"), show_alert=True)
        return
    await cb.answer()
    watch, key = row
    await state.clear()
    await state.update_data(
        edit_watch_id=watch.id,
        edit_currency=key.currency,
        edit_current=(str(key.last_price) if key.last_price is not None else None),
    )
    await state.set_state(Flow.edit_target)
    route, dates, _ = describe_key(key, user.language)
    now = (
        tr("edit.now_line", price=fmt_price(key.last_price), currency=key.currency)
        if key.last_price is not None
        else ""
    )
    text = tr(
        "edit.ask",
        route=esc(route),
        dates=dates,
        target=fmt_price(watch.target_price),
        currency=key.currency,
        now=now,
    )
    if isinstance(cb.message, Message):
        # New message: the list item / notification stays in place
        await cb.message.answer(text, reply_markup=kb.edit_target_kb(key.last_price, user.language))


async def _save_target(
    target: Message | CallbackQuery,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
    price: Decimal,
) -> None:
    d = await state.get_data()
    ok = await update_target(session, user_id=user.id, watch_id=d["edit_watch_id"], target_price=price)
    await state.clear()
    text = (
        tr("edit.saved", target=fmt_price(price), currency=d.get("edit_currency", ""))
        if ok
        else tr("list.not_found")
    )
    msg = target.message if isinstance(target, CallbackQuery) else target
    if isinstance(target, CallbackQuery) and isinstance(msg, Message):
        await edit_or_send(msg, text, kb.created_kb(user.language))
    elif isinstance(msg, Message):
        await msg.answer(text, reply_markup=kb.created_kb(user.language))


@router.callback_query(EditTargetCb.filter(), Flow.edit_target)
async def edit_target_button(
    cb: CallbackQuery, callback_data: EditTargetCb, state: FSMContext, user: User, session: AsyncSession, tr
) -> None:
    price = Decimal(callback_data.cents) / 100
    if not Decimal("0") < price <= MAX_PRICE:  # callback data can be forged by a modified client
        await cb.answer(tr("error.stale"), show_alert=True)
        return
    await cb.answer()
    await _save_target(cb, state, user, session, tr, price)


@router.message(Flow.edit_target, F.text, ~F.text.startswith("/"))
async def edit_target_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr
) -> None:
    price = parse_price(message.text or "")
    if price is None:
        await message.answer(tr("new.bad_price"), reply_markup=kb.edit_target_kb(None, user.language))
        return
    await _save_target(message, state, user, session, tr, price)


@router.callback_query(WatchCb.filter(F.action == "del"))
async def on_delete(cb: CallbackQuery, callback_data: WatchCb, user: User, session: AsyncSession, tr) -> None:
    ok = await delete_watch(session, user_id=user.id, watch_id=callback_data.id)
    await cb.answer()
    if isinstance(cb.message, Message):
        await edit_or_send(cb.message, tr("list.deleted" if ok else "list.not_found"))


@router.callback_query(WatchCb.filter(F.action.in_({"pause", "resume", "npause"})))
async def on_pause_resume(
    cb: CallbackQuery, callback_data: WatchCb, user: User, session: AsyncSession, tr
) -> None:
    msg = cb.message if isinstance(cb.message, Message) else None
    try:
        ok = await set_paused(
            session,
            user_id=user.id,
            watch_id=callback_data.id,
            paused=callback_data.action != "resume",
            now=utcnow(),
        )
    except QuotaExceeded as exc:
        await cb.answer(tr(f"quota.{exc.code}", limit=exc.limit), show_alert=True)
        return
    if not ok:
        await cb.answer(tr("list.not_found"), show_alert=True)
        return

    if callback_data.action == "npause":
        # Pause from a notification: the message stays, only the management buttons are removed
        await cb.answer(tr("notif.paused"), show_alert=True)
        if msg and msg.reply_markup:
            rows = [
                r
                for r in msg.reply_markup.inline_keyboard
                if not any((b.callback_data or "").startswith("wt:") for b in r)
            ]
            await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return

    await cb.answer()
    row = await get_watch_with_key(session, user_id=user.id, watch_id=callback_data.id)
    if row and msg:
        text, markup = render_item(row[0], row[1], user.language, tr)
        await edit_or_send(msg, text, markup)
