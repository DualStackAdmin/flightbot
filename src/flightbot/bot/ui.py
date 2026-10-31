"""Mesajı göstərmə köməkçiləri: callback-dən gələndə eyni mesajı redaktə edirik (söhbət uzanmır)."""

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def edit_or_send(msg: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> Message:
    try:
        res = await msg.edit_text(text, reply_markup=markup)
        return res if isinstance(res, Message) else msg
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return msg
        return await msg.answer(text, reply_markup=markup)  # redaktə mümkün deyil: yenisini göndər


async def show(
    target: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> Message | None:
    """CallbackQuery -> mövcud mesajı redaktə et; Message (mətn girişi/əmr) -> yeni mesaj."""
    if isinstance(target, CallbackQuery):
        if isinstance(target.message, Message):
            return await edit_or_send(target.message, text, markup)
        return None
    return await target.answer(text, reply_markup=markup)
