"""Automatically freezes/restores subscriptions when a user blocks/unblocks the bot."""

from aiogram import Router
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from flightbot.core.users import mark_blocked, mark_unblocked
from flightbot.db.models import User
from flightbot.logging import get_logger

log = get_logger(__name__)
router = Router(name="chat_member")


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, user: User, session: AsyncSession) -> None:
    if event.chat.type != "private":
        return
    status = event.new_chat_member.status
    if status == "kicked":
        log.info("user_blocked_bot_event", user_id=user.id)
        await mark_blocked(session, user.id)
    elif status == "member":
        log.info("user_unblocked_bot_event", user_id=user.id)
        await mark_unblocked(session, user.id)
