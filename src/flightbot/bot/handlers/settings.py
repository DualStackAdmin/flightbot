from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.bot import keyboards as kb
from flightbot.bot.callbacks import CurCb, DeleteCb, LangCb, QuietCb
from flightbot.bot.deps import Deps
from flightbot.bot.i18n import esc, language_name, t
from flightbot.bot.ui import edit_or_send
from flightbot.core.places import place_name
from flightbot.core.users import delete_user_data, set_currency, set_language
from flightbot.core.watches import set_quiet_hours
from flightbot.db.models import User

router = Router(name="settings")


def render_settings(user: User, deps: Deps, *, lang: str, currency: str, quiet: bool):
    home = esc(place_name(user.home_iata, lang)) if user.home_iata else "—"
    text = t(
        lang,
        "settings.title",
        language=language_name(lang),
        currency=currency,
        home=home,
        quiet_from=f"{deps.settings.quiet_start_hour:02d}",
        quiet_to=f"{deps.settings.quiet_end_hour:02d}",
        quiet=t(lang, "state.on" if quiet else "state.off"),
    )
    return text, kb.settings_kb(lang, currency, quiet)


@router.message(Command("settings"))
async def cmd_settings(message: Message, user: User, deps: Deps) -> None:
    text, markup = render_settings(
        user, deps, lang=user.language, currency=user.currency, quiet=user.quiet_hours
    )
    await message.answer(text, reply_markup=markup)


@router.callback_query(LangCb.filter())
async def on_language(
    cb: CallbackQuery, callback_data: LangCb, user: User, session: AsyncSession, deps: Deps
) -> None:
    await set_language(session, user.id, callback_data.lang)
    await cb.answer(t(callback_data.lang, "settings.saved"))
    if isinstance(cb.message, Message):
        text, markup = render_settings(
            user, deps, lang=callback_data.lang, currency=user.currency, quiet=user.quiet_hours
        )
        await edit_or_send(cb.message, text, markup)


@router.callback_query(CurCb.filter())
async def on_currency(
    cb: CallbackQuery, callback_data: CurCb, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    await set_currency(session, user.id, callback_data.cur)
    await cb.answer(tr("settings.saved"))
    if isinstance(cb.message, Message):
        text, markup = render_settings(
            user, deps, lang=user.language, currency=callback_data.cur, quiet=user.quiet_hours
        )
        await edit_or_send(cb.message, text, markup)


@router.callback_query(QuietCb.filter())
async def on_quiet(cb: CallbackQuery, user: User, session: AsyncSession, tr, deps: Deps) -> None:
    new_value = not user.quiet_hours
    await set_quiet_hours(session, user.id, new_value)
    await cb.answer(tr("settings.saved"))
    if isinstance(cb.message, Message):
        text, markup = render_settings(
            user, deps, lang=user.language, currency=user.currency, quiet=new_value
        )
        await edit_or_send(cb.message, text, markup)


@router.message(Command("delete"))
async def cmd_delete(message: Message, user: User, tr) -> None:
    await message.answer(tr("delete.confirm"), reply_markup=kb.delete_kb(user.language))


@router.callback_query(DeleteCb.filter())
async def on_delete(
    cb: CallbackQuery,
    callback_data: DeleteCb,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    tr,
) -> None:
    await cb.answer()
    if callback_data.action == "confirm":
        await state.clear()
        await delete_user_data(session, user.id)
        text_ = tr("delete.done")
    else:
        text_ = tr("cancelled")
    if isinstance(cb.message, Message):
        await edit_or_send(cb.message, text_)
