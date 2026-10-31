from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.bot.render import FbCb
from flightbot.core.watches import record_feedback
from flightbot.db.models import User

router = Router(name="feedback")


@router.callback_query(FbCb.filter())
async def on_feedback(cb: CallbackQuery, callback_data: FbCb, user: User, session: AsyncSession, tr) -> None:
    ok = await record_feedback(
        session, notification_id=callback_data.id, user_id=user.id, vote=callback_data.vote
    )
    await cb.answer(tr("feedback.thanks") if ok else None)
    # After a vote the feedback buttons (last row) are removed; "Find ticket" and the management buttons stay
    if ok and isinstance(cb.message, Message) and cb.message.reply_markup:
        rows = cb.message.reply_markup.inline_keyboard[:-1]
        await cb.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
