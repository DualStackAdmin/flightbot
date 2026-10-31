"""Test infrastructure for the bot: a session that mocks the Telegram network, and a user simulator."""

import time
from collections.abc import AsyncIterator

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.methods.base import TelegramMethod


class MockSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.log: list[tuple[TelegramMethod, int | None]] = []
        self._mid = 1000

    async def close(self) -> None: ...

    async def stream_content(self, *a, **kw) -> AsyncIterator[bytes]:  # pragma: no cover
        if False:
            yield b""

    async def make_request(self, bot: Bot, method, timeout=None):  # noqa: ASYNC109
        self._mid += 1
        mid = self._mid
        if isinstance(method, EditMessageText):
            mid = method.message_id or mid
        self.log.append((method, mid))
        if isinstance(method, SendMessage | EditMessageText):
            from aiogram.types import Message

            return Message.model_validate(
                {
                    "message_id": mid,
                    "date": int(time.time()),
                    "chat": {"id": method.chat_id or 0, "type": "private"},
                    "text": method.text,
                },
                context={"bot": bot},
            )
        return True


class Chat:
    """Simulates a single Telegram user."""

    def __init__(self, dp, bot: Bot, session: MockSession, tg_id: int, lang: str = "az") -> None:
        self.dp, self.bot, self.session, self.tg_id, self.lang = dp, bot, session, tg_id, lang
        self._uid = 0
        self._cursor = len(session.log)

    def _from(self) -> dict:
        return {"id": self.tg_id, "is_bot": False, "first_name": "T", "language_code": self.lang}

    def _next(self) -> int:
        self._uid += 1
        return self._uid + int(time.time() * 1000) % 10**9

    async def say(self, text_: str) -> None:
        self._cursor = len(self.session.log)
        await self.dp.feed_raw_update(
            self.bot,
            {
                "update_id": self._next(),
                "message": {
                    "message_id": self._next(),
                    "date": int(time.time()),
                    "chat": {"id": self.tg_id, "type": "private"},
                    "from": self._from(),
                    "text": text_,
                },
            },
        )

    async def say_non_text(self) -> None:
        """A non-text message (e.g. a location)."""
        self._cursor = len(self.session.log)
        await self.dp.feed_raw_update(
            self.bot,
            {
                "update_id": self._next(),
                "message": {
                    "message_id": self._next(),
                    "date": int(time.time()),
                    "chat": {"id": self.tg_id, "type": "private"},
                    "from": self._from(),
                    "location": {"latitude": 40.4, "longitude": 49.8},
                },
            },
        )

    def url_of(self, label_part: str) -> str:
        for m, _ in reversed(self.outgoing()):
            for b in self._buttons_of(m):
                if label_part in b.text and b.url:
                    return b.url
        raise AssertionError(f"url button not found: {label_part!r}")

    async def click(self, data: str, *, message_id: int = 1, reply_markup: dict | None = None) -> None:
        self._cursor = len(self.session.log)
        msg = {
            "message_id": message_id,
            "date": int(time.time()),
            "chat": {"id": self.tg_id, "type": "private"},
            "from": {"id": 42, "is_bot": True, "first_name": "bot"},
            "text": "x",
        }
        if reply_markup:
            msg["reply_markup"] = reply_markup
        await self.dp.feed_raw_update(
            self.bot,
            {
                "update_id": self._next(),
                "callback_query": {
                    "id": str(self._next()),
                    "from": self._from(),
                    "chat_instance": "ci",
                    "data": data,
                    "message": msg,
                },
            },
        )

    # --------------------------------------------------------------- oxuma
    def outgoing(self, since_last_action: bool = False):
        items = self.session.log[self._cursor :] if since_last_action else self.session.log
        return [(m, mid) for m, mid in items if isinstance(m, SendMessage | EditMessageText)]

    def texts(self, since_last_action: bool = True) -> list[str]:
        return [m.text for m, _ in self.outgoing(since_last_action)]

    def last_text(self) -> str:
        return self.outgoing()[-1][0].text

    def alerts(self) -> list[str | None]:
        return [m.text for m, _ in self.session.log if isinstance(m, AnswerCallbackQuery)]

    def _buttons_of(self, method):
        markup = getattr(method, "reply_markup", None)
        if not markup or not hasattr(markup, "inline_keyboard"):
            return []
        return [b for row in markup.inline_keyboard for b in row]

    def button_labels(self) -> list[str]:
        for m, _ in reversed(self.outgoing()):
            labels = [b.text for b in self._buttons_of(m)]
            if labels:
                return labels
        return []

    async def press(self, label_part: str) -> None:
        """Finds a button by its text in the most recent messages and presses it."""
        for m, mid in reversed(self.outgoing()):
            for b in self._buttons_of(m):
                if label_part in b.text and b.callback_data:
                    await self.click(b.callback_data, message_id=mid)
                    return
        raise AssertionError(f"button not found: {label_part!r}; available: {self.button_labels()}")
