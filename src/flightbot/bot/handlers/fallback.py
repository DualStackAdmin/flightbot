"""Heç vaxt cavabsız qoyma: axından kənar mətn, naməlum əmr, köhnəlmiş düymə, mətn olmayan mesaj."""

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.bot import keyboards as kb
from flightbot.bot.deps import Deps
from flightbot.bot.handlers.flow import begin
from flightbot.bot.route_text import parse_route
from flightbot.db.models import User

router = Router(name="fallback")


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def free_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession, tr, deps: Deps
) -> None:
    """ "İstanbul" və ya "Bakı Dubay" kimi yazı: marşrutu tanıyıb birbaşa ay seçiminə keçir."""
    parsed = parse_route(message.text or "", user.language)
    if parsed:
        origin, dest = parsed
        origin_code = origin.code if origin else (user.home_iata or deps.settings.default_home_iata)
        if dest.code != origin_code:
            await begin(
                message, state, user, session, tr, deps, "watch", origin=origin_code, destination=dest.code
            )
            return
    await message.answer(tr("fallback.unknown"), reply_markup=kb.menu_kb(user.language))


@router.message()
async def anything_else(message: Message, user: User, tr) -> None:
    """Naməlum əmr, stiker, şəkil və s.: səssiz qalma, menyunu göstər."""
    await message.answer(tr("fallback.unknown"), reply_markup=kb.menu_kb(user.language))


@router.callback_query()
async def stale_button(cb: CallbackQuery, tr) -> None:
    await cb.answer(tr("error.stale"), show_alert=True)
