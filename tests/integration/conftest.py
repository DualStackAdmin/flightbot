import pytest_asyncio
from aiogram import Bot

from flightbot.bot.app import create_dispatcher
from flightbot.providers.places import StaticPlaces
from tests.bot_harness import Chat, MockSession
from tests.helpers import ScriptedProvider


def _fresh_routers() -> None:
    """An aiogram router can be attached to only one Dispatcher; reload the handler modules for every test."""
    import importlib

    from flightbot.bot.handlers import chat_member, fallback, feedback, flow, settings, start, watches_list

    for mod in (flow, start, watches_list, settings, feedback, chat_member, fallback):
        importlib.reload(mod)


@pytest_asyncio.fixture
async def env(sm, redis, settings):
    class Env:
        provider: ScriptedProvider
        throttle = (1000.0, 1000)

        def make(self, provider=None, throttle=None):
            _fresh_routers()
            self.provider = provider or ScriptedProvider(200)
            self.session = MockSession()
            self.bot = Bot(token="42:TEST", session=self.session)
            self.dp = create_dispatcher(
                settings,
                sessionmaker=sm,
                redis=redis,
                provider=self.provider,
                places=StaticPlaces(),
                throttle=throttle or self.throttle,
            )
            return self

        def chat(self, tg_id: int = 111, lang: str = "az") -> Chat:
            return Chat(self.dp, self.bot, self.session, tg_id, lang)

    e = Env().make()
    yield e
    await e.bot.session.close()
