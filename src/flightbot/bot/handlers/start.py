from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.bot import keyboards as kb
from flightbot.bot.deps import Deps
from flightbot.bot.handlers.flow import begin
from flightbot.db.models import User

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, user: User, session: AsyncSession, is_new_user: bool, tr, deps: Deps
) -> None:
    if is_new_user:
        # A new user lands directly on the "where to?" step: the language is guessed from Telegram so there is no question,
        # and the popular-destination buttons are on the welcome message itself (no blank page).
        await begin(message, state, user, session, tr, deps, "watch", text=tr("start.new"))
        return
    await state.clear()
    await message.answer(tr("start.back"), reply_markup=kb.menu_kb(user.language))


@router.message(Command("help"))
async def cmd_help(message: Message, user: User, tr) -> None:
    await message.answer(tr("help"), reply_markup=kb.menu_kb(user.language))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, user: User, tr) -> None:
    await state.clear()
    await message.answer(tr("cancelled"), reply_markup=kb.menu_kb(user.language))
