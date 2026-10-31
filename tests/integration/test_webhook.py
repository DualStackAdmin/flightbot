import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from flightbot.bot.app import build_webhook_app
from tests.helpers import scalar

SECRET = "s3cret-token_123"


@pytest.fixture
def secured_settings(settings):
    from pydantic import SecretStr

    return settings.model_copy(update={"webhook_secret": SecretStr(SECRET), "webhook_path": "/tg"})


def update(tg_id=909, text="/start"):
    return {
        "update_id": int(time.time() * 1000) % 10**9,
        "message": {
            "message_id": 1,
            "date": int(time.time()),
            "chat": {"id": tg_id, "type": "private"},
            "from": {"id": tg_id, "is_bot": False, "first_name": "T", "language_code": "az"},
            "text": text,
        },
    }


async def test_webhook_rejects_missing_or_wrong_secret_and_accepts_correct(
    env, sm, engine, redis, secured_settings
):
    app = build_webhook_app(env.bot, env.dp, secured_settings, engine, redis)
    async with TestClient(TestServer(app)) as client:
        no_header = await client.post("/tg", json=update())
        wrong = await client.post("/tg", json=update(), headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
        assert no_header.status == 401 and wrong.status == 401
        assert await scalar(sm, "select count(*) from users") == 0  # saxta update emal olunmadı

        ok = await client.post("/tg", json=update(), headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
        assert ok.status == 200
        # SimpleRequestHandler cavabı fon task-ında emal edir; qısa gözləmə
        import asyncio

        for _ in range(50):
            if await scalar(sm, "select count(*) from users"):
                break
            await asyncio.sleep(0.05)
        assert await scalar(sm, "select count(*) from users") == 1


async def test_healthz_ok_and_unhealthy_when_redis_down(env, engine, redis, secured_settings):
    app = build_webhook_app(env.bot, env.dp, secured_settings, engine, redis)
    async with TestClient(TestServer(app)) as client:
        r = await client.get("/healthz")
        assert r.status == 200 and (await r.json())["status"] == "ok"

    class DeadRedis:
        async def ping(self):
            raise ConnectionError("down")

    app2 = build_webhook_app(env.bot, env.dp, secured_settings, engine, DeadRedis())
    async with TestClient(TestServer(app2)) as client:
        assert (await client.get("/healthz")).status == 503


def test_webhook_requires_secret(env, engine, redis, settings):
    with pytest.raises(RuntimeError):
        build_webhook_app(env.bot, env.dp, settings, engine, redis)
