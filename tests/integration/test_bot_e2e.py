"""Bot axınının tam sınağı: Dispatcher + bütün middleware-lər + real Postgres/Redis (FSM).
Yalnız Telegram şəbəkəsi mock-dur: aiogram sessiyası bütün çıxış sorğularını tutur."""

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from aiogram.methods import EditMessageReplyMarkup
from sqlalchemy import text

from flightbot.bot.callbacks import MenuCb, MonthCb, WatchCb
from flightbot.bot.i18n import fmt_month
from flightbot.bot.parsing import next_months
from flightbot.bot.render import FbCb
from flightbot.providers.base import PriceQuote, ProviderError
from flightbot.providers.fake import FakeProvider
from tests.bot_harness import Chat
from tests.helpers import ScriptedProvider, rows, scalar, today


def months():
    return next_months(datetime.now(UTC).date(), 8)


def month_label(i: int) -> str:
    return fmt_month(months()[i], "az")


def dmy(days: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=days)).strftime("%d.%m.%Y")


def quote(
    dest: str, price: str, *, days: int = 20, link: str | None = None, transfers: int = 0
) -> PriceQuote:
    return PriceQuote(
        Decimal(price),
        "USD",
        today() + timedelta(days=days),
        None,
        "TK",
        transfers,
        None,
        link,
        "scripted",
        destination=dest,
    )


async def create_watch(chat: Chat, dest: str = "İstanbul", month_idx: int = 1, target: str = "150") -> None:
    """Standart 3 toxunuş: haraya -> ay -> hədəf."""
    await chat.say("/new")
    await chat.press(dest)
    await chat.press(month_label(month_idx))
    await chat.say(target)


async def watch_rows(sm):
    return await rows(
        sm,
        "select w.target_price, w.status, k.origin, k.destination, k.date_mode, k.depart_date, "
        "k.return_date, k.direct_only, k.currency from watches w join watch_keys k on k.id = w.watch_key_id "
        "order by w.id",
    )


# ================================================================== /start
async def test_new_user_lands_directly_on_destination_picker_without_language_question(env, sm):
    chat = env.chat(10, lang="en")
    await chat.say("/start")
    text_ = chat.last_text()
    assert "Where do you want to fly" in text_ and "partner links" in text_  # dil Telegram-dan təxmin olundu
    labels = chat.button_labels()
    assert any("Istanbul" in x for x in labels) and any("Dubai" in x for x in labels)
    assert any("Anywhere" in x for x in labels) and any("Baku" in x and "change" in x for x in labels)
    assert await scalar(sm, "select language from users") == "en"


async def test_unsupported_telegram_language_defaults_to_azerbaijani(env, sm):
    chat = env.chat(10, lang="de")
    await chat.say("/start")
    assert await scalar(sm, "select language from users") == "az"
    assert "Haraya uçmaq istəyirsiniz" in chat.last_text()


async def test_returning_user_gets_menu(env):
    chat = env.chat(10)
    await chat.say("/start")
    await chat.say("/start")
    assert "Yenidən salam" in chat.last_text()
    assert "➕ Yeni izləmə" in chat.button_labels() and "🌍 Hər yerə" in chat.button_labels()


async def test_quick_start_button_on_welcome_message_works(env, sm):
    """Boş səhifə yoxdur: xoş gəldin mesajındakı populyar düymə birbaşa ay seçiminə aparır."""
    chat = env.chat(11)
    await chat.say("/start")
    await chat.press("İstanbul")
    assert "Bakı → İstanbul" in chat.last_text() and "Hansı ay" in chat.last_text()


# ======================================================== standart izləmə: 3 toxunuş
async def test_default_watch_takes_three_touches_after_new(env, sm):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")  # 1
    await chat.press(month_label(1))  # 2
    await chat.say("150")  # 3
    assert "İzləmə yaradıldı" in chat.last_text() and "Bakı → İstanbul" in chat.last_text()
    assert "Hazırda: 200 USD" in chat.last_text()
    r = (await watch_rows(sm))[0]
    assert (r.origin, r.destination, r.date_mode, r.return_date, r.direct_only, r.currency) == (
        "GYD",
        "IST",
        "month",
        None,
        False,
        "USD",
    )
    assert float(r.target_price) == 150.0 and r.depart_date == months()[1]
    assert {"➕ Başqa marşrut", "📋 İzləmələrim"} <= set(chat.button_labels())


async def test_target_step_shows_price_and_recommended_quick_button(env, sm):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("Dubay")
    await chat.press(month_label(2))
    assert "Hazırda ən ucuz: <b>200 USD</b>" in chat.last_text()
    labels = chat.button_labels()
    assert labels[0] == "⭐ −15% · 170" and "−10% · 180" in labels and "−25% · 150" in labels
    await chat.press("⭐")
    assert float((await watch_rows(sm))[0].target_price) == 170.0


async def test_waiting_message_is_shown_then_replaced_in_place(env):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.press(month_label(1))
    seen = chat.texts()
    assert any("Qiymətlərə baxıram" in t for t in seen) and "Hazırda ən ucuz" in seen[-1]
    edits = [m for m, _ in chat.outgoing(True) if m.__class__.__name__ == "EditMessageText"]
    assert len(edits) >= 2  # eyni mesaj redaktə olunur, söhbət uzanmır


async def test_typing_price_above_current_asks_for_confirmation(env, sm):
    chat = env.chat()
    await create_watch(chat, target="250")  # hazırkı qiymət 200 < 250
    assert "artıq bu hədəfdən aşağıdır" in chat.last_text()
    assert await scalar(sm, "select count(*) from watches") == 0
    await chat.press("Bəli, davam")
    assert "İzləmə yaradıldı" in chat.last_text()
    assert float((await watch_rows(sm))[0].target_price) == 250.0


async def test_warning_can_be_declined_and_a_better_price_entered(env, sm):
    chat = env.chat()
    await create_watch(chat, target="999")
    await chat.press("Başqa qiymət")
    assert "Hədəf qiyməti seçin" in chat.last_text() or "Hədəf" in chat.last_text()
    await chat.say("120")
    assert float((await watch_rows(sm))[0].target_price) == 120.0


async def test_no_current_price_still_allows_watch_without_quick_buttons(env, sm):
    env.make(provider=ScriptedProvider(ProviderError("down")))
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.press(month_label(1))
    assert "qiymət tapılmadı" in chat.last_text()
    assert not any("%" in x for x in chat.button_labels())  # sürətli hədəf düymələri yoxdur
    await chat.say("100")  # cari qiymət yoxdur: xəbərdarlıq da yoxdur
    assert "İzləmə yaradıldı" in chat.last_text()


async def test_invalid_target_inputs_rejected(env, sm):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.press(month_label(1))
    for bad in ("pulsuz", "-5", "0"):
        await chat.say(bad)
        assert "rəqəm kimi" in chat.last_text()
    await chat.say("99,5")
    assert float((await watch_rows(sm))[0].target_price) == 99.5


async def test_same_route_twice_updates_target(env, sm):
    chat = env.chat()
    await create_watch(chat, target="150")
    await create_watch(chat, target="120")
    assert "İzləmə yeniləndi" in chat.last_text()
    r = await watch_rows(sm)
    assert len(r) == 1 and float(r[0].target_price) == 120.0


async def test_free_plan_allows_three_month_watches_and_blocks_fourth(env, sm):
    chat = env.chat()
    for dest in ("İstanbul", "Dubay", "Tbilisi"):
        await create_watch(chat, dest, target="100")
    assert await scalar(sm, "select count(*) from watches where status='active'") == 3
    await chat.say("/new")
    assert "limitinə çatdınız (3)" in chat.last_text()


# =================================================================== dəqiq tarix və ətraflı
async def test_exact_date_flow(env, sm):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.press("Dəqiq tarix")
    await chat.say("abc")
    assert "başa düşmədim" in chat.last_text()
    await chat.say("01.01.2020")
    assert "keçmişdə" in chat.last_text()
    await chat.say(dmy(900))
    assert "çox uzaqdır" in chat.last_text()
    await chat.say(dmy(30))
    await chat.say("150")
    r = (await watch_rows(sm))[0]
    assert r.date_mode == "exact" and r.return_date is None and not r.direct_only


async def test_advanced_options_round_trip_and_direct(env, sm):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.press("Ətraflı")
    assert any("açıqdır" in x for x in chat.button_labels())
    await chat.press(month_label(2))
    await chat.press("Gediş-gəliş")
    labels = chat.button_labels()
    assert month_label(1) not in labels and month_label(2) in labels  # qayıdış gedişdən əvvəl ola bilməz
    await chat.press(month_label(3))
    await chat.press("Bəli")  # birbaşa
    await chat.press("⭐")
    r = (await watch_rows(sm))[0]
    assert r.date_mode == "month" and r.return_date == months()[3] and r.direct_only is True
    assert "gediş-gəliş" in chat.last_text() and "birbaşa" in chat.last_text()


async def test_exact_round_trip_return_before_departure_rejected(env, sm):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.press("Ətraflı")
    await chat.press("Dəqiq tarix")
    await chat.say(dmy(30))
    await chat.press("Gediş-gəliş")
    await chat.say(dmy(20))
    assert "gedişdən əvvəl ola bilməz" in chat.last_text()
    await chat.say(dmy(37))
    await chat.press("Xeyr")
    await chat.say("120")
    assert (await watch_rows(sm))[0].return_date is not None


# ====================================================================== geri və ləğv
async def test_back_button_returns_to_previous_step_and_edits_in_place(env):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    assert "Hansı ay" in chat.last_text()
    await chat.press("Geri")
    assert "Haraya uçmaq istəyirsiniz" in chat.last_text()
    assert not any("Geri" in x for x in chat.button_labels())  # ilk addımda "Geri" yoxdur
    assert any("Ləğv" in x for x in chat.button_labels())


async def test_back_from_target_to_month_and_choose_another_month(env, sm):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.press(month_label(1))
    await chat.press("Geri")
    assert "Hansı ay" in chat.last_text()
    await chat.press(month_label(3))
    await chat.say("100")
    assert (await watch_rows(sm))[0].depart_date == months()[3]


async def test_cancel_button_ends_flow_and_menu_is_shown(env, sm):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.press("Ləğv")
    assert "Ləğv edildi" in chat.last_text() and "➕ Yeni izləmə" in chat.button_labels()
    assert await scalar(sm, "select count(*) from watches") == 0


async def test_commands_work_in_the_middle_of_a_flow(env):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.say("/cancel")
    assert "Ləğv edildi" in chat.last_text()
    await chat.say("/new")
    await chat.press("İstanbul")
    await chat.say("/new")  # yarımçıq axını yenidən başlayır
    assert "Haraya uçmaq istəyirsiniz" in chat.last_text()


async def test_text_typed_instead_of_pressing_a_button_rerenders_step(env):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("İstanbul")  # ay addımı (düymələr gözlənilir)
    await chat.say("noyabr")
    assert "Hansı ay" in chat.last_text()  # cavabsız qalmır


# =========================================================================== origin
async def test_change_origin_then_complete_flow(env, sm):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("Bakı · dəyiş")
    assert "Haradan uçursunuz" in chat.last_text()
    await chat.say("ankara")
    await chat.press("Ankara")
    assert "Haradan: <b>Ankara</b>" in chat.last_text()  # dest addımına qayıtdı
    assert any("Bakı" in x for x in chat.button_labels()) is False
    await chat.press("İstanbul")
    await chat.press(month_label(1))
    await chat.say("100")
    assert (await watch_rows(sm))[0].origin == "ESB"


async def test_origin_picker_offers_home_city_button(env):
    chat = env.chat()
    await chat.say("/new")
    await chat.press("Bakı · dəyiş")
    await chat.say("ankara")
    await chat.press("Ankara")
    await chat.press("Ankara · dəyiş")
    assert any("Bakı" in x for x in chat.button_labels())


async def test_destination_equal_to_origin_is_refused(env):
    chat = env.chat()
    await chat.say("/new")
    await chat.say("baki")  # origin Bakıdır; populyar siyahıda yoxdur, amma mətnlə seçilə bilər
    await chat.press("Bakı")
    assert any("eyni ola bilməz" in (a or "") for a in chat.alerts())
    # imtinadan sonra axın davam edir: başqa təyinat seçmək işləyir
    await chat.say("istanbul")
    await chat.press("İstanbul")
    assert "Bakı → İstanbul" in chat.last_text() and "Hansı ay" in chat.last_text()


# ===================================================== fallback: bot heç vaxt susmur
async def test_free_text_city_goes_straight_to_month_step(env):
    chat = env.chat()
    await chat.say("İstanbul")
    assert "Bakı → İstanbul" in chat.last_text() and "Hansı ay" in chat.last_text()


async def test_free_text_route_with_origin(env, sm):
    chat = env.chat()
    await chat.say("Ankara Dubay")
    assert "Ankara → Dubay" in chat.last_text()
    await chat.press(month_label(1))
    await chat.say("100")
    r = (await watch_rows(sm))[0]
    assert (r.origin, r.destination) == ("ESB", "DXB")


@pytest.mark.parametrize("text_", ["Bakı - İstanbul", "GYD IST", "baki → istanbul", "Tel-Əviv İstanbul"])
async def test_route_text_variants(env, text_):
    chat = env.chat()
    await chat.say(text_)
    assert "Hansı ay" in chat.last_text(), text_


async def test_gibberish_unknown_command_and_non_text_get_a_reply_with_menu(env):
    chat = env.chat()
    for action in ("zzzzqq", "/foo"):
        before = len(chat.session.log)
        await chat.say(action)
        assert len(chat.session.log) > before and "başa düşmədim" in chat.last_text()
        assert "➕ Yeni izləmə" in chat.button_labels()
    before = len(chat.session.log)
    await chat.say_non_text()
    assert len(chat.session.log) > before and "başa düşmədim" in chat.last_text()


async def test_stale_button_gets_an_alert_instead_of_spinning(env):
    chat = env.chat()
    await chat.say("/start")
    await chat.say("/cancel")
    await chat.click(MonthCb(which="dep", ym="2030-01").pack())  # state yoxdur
    assert any("vaxtı keçib" in (a or "") for a in chat.alerts())


async def test_provider_failure_during_search_keeps_user_in_flow(env):
    env.make(provider=ScriptedProvider(ProviderError("down")))
    chat = env.chat()
    await chat.say("/search")
    await chat.press("Dubay")
    await chat.press(month_label(1))
    assert "cavab vermir" in chat.last_text() and any("Geri" in x for x in chat.button_labels())


# ====================================================================== /explore
async def test_explore_lists_cheapest_destinations_and_leads_to_a_watch(env, sm):
    env.provider.explore_result = [
        quote("IST", "79", link="/search/GYD1512IST1?t=abc"),
        quote("KUL", "310"),
        quote("DXB", "95", transfers=1),
    ]
    chat = env.chat(7)
    await chat.say("/explore")
    assert "hansı ay uçmaq" in chat.last_text()
    await chat.press(month_label(1))
    labels = chat.button_labels()
    assert any("İstanbul" in x and "79 USD" in x for x in labels)
    assert any("KUL" in x and "310 USD" in x for x in labels)  # naməlum kod: kodun özü
    assert any("🇹🇷" in x for x in labels) and any("🇦🇪" in x for x in labels)
    assert env.provider.explore_calls == 1 and env.provider.calls == 0

    await chat.press("İstanbul")
    detail = chat.last_text()
    assert "Ən ucuz: <b>79 USD</b>" in detail and "Bakı → İstanbul" in detail
    url = chat.url_of("Bilet tap")
    assert "marker=794979." in url and "t=abc" in url  # affiliate marker və sub_id

    await chat.press("xəbər ver")
    assert "Hazırda ən ucuz: <b>79 USD</b>" in chat.last_text()
    assert env.provider.calls == 0  # explore qiyməti istifadə olunur, ikinci provayder sorğusu yoxdur
    await chat.press("⭐")
    r = (await watch_rows(sm))[0]
    assert (r.destination, r.date_mode, r.depart_date, r.return_date) == ("IST", "month", months()[1], None)
    assert float(r.target_price) == 67.0  # 79 * 0.85 = 67.15 -> 67


async def test_explore_back_navigation_detail_to_list_to_months(env):
    env.provider.explore_result = [quote("IST", "79"), quote("DXB", "95")]
    chat = env.chat()
    await chat.say("/explore")
    await chat.press(month_label(1))
    await chat.press("Dubay")
    await chat.press("Geri")
    assert "Ən ucuz istiqamətlər" in chat.last_text()
    await chat.press("Geri")
    assert "hansı ay uçmaq" in chat.last_text()


async def test_explore_from_destination_step_button_and_menu(env):
    env.provider.explore_result = [quote("IST", "79")]
    chat = env.chat()
    await chat.say("/new")
    await chat.press("Hər yerə")
    assert "hansı ay uçmaq" in chat.last_text()
    await chat.say("/start")
    await chat.click(MenuCb(action="explore").pack())
    assert "hansı ay uçmaq" in chat.last_text()


async def test_explore_empty_and_failure(env):
    env.provider.explore_result = []
    chat = env.chat(1)
    await chat.say("/explore")
    await chat.press(month_label(1))
    assert "istiqamət tapılmadı" in chat.last_text()
    env.provider.explore_result = ProviderError("down")
    chat2 = env.chat(2)
    await chat2.say("/explore")
    await chat2.press(month_label(1))
    assert "cavab vermir" in chat2.last_text()


async def test_explore_with_changed_origin(env):
    env.provider.explore_result = [quote("IST", "79")]
    chat = env.chat()
    await chat.say("/explore")
    await chat.press("Bakı · dəyiş")
    await chat.say("ankara")
    await chat.press("Ankara")
    assert "Ankara" in chat.last_text()
    await chat.press(month_label(1))
    assert "Ankara → hər yerə" in chat.last_text()


# ======================================================================== /search
async def test_search_shows_cheapest_days_then_can_start_watch(env, sm):
    env.make(provider=FakeProvider())
    chat = env.chat()
    await chat.say("/search")
    assert not any("Hər yerə" in x for x in chat.button_labels())  # /search-də explore düyməsi yoxdur
    await chat.press("Dubay")
    assert not any("Dəqiq tarix" in x for x in chat.button_labels())  # yalnız ay seçimi
    await chat.press(month_label(1))
    result = chat.last_text()
    assert "ən ucuz günlər" in result and result.count("•") == 5 and "Bakı → Dubay" in result
    await chat.press("xəbər ver")
    assert "Hazırda ən ucuz" in chat.last_text()
    await chat.say("30")
    r = (await watch_rows(sm))[0]
    assert (r.destination, r.date_mode, r.return_date, r.direct_only) == ("DXB", "month", None, False)


async def test_search_with_no_results(env):
    env.make(provider=ScriptedProvider(None))
    chat = env.chat()
    await chat.say("/search")
    await chat.press("Dubay")
    await chat.press(month_label(1))
    assert "qiymət tapılmadı" in chat.last_text()


# ========================================================================= /list
async def test_list_pause_resume_delete(env, sm):
    chat = env.chat()
    await create_watch(chat)
    await chat.say("/list")
    assert "İzləmələriniz (1)" in chat.texts()[0]
    assert "Bakı → İstanbul" in chat.last_text() and "≤ 150 USD" in chat.last_text()
    assert {"⏸ Dayandır", "🎯 Dəyiş", "🗑 Sil"} <= set(chat.button_labels())

    await chat.press("Dayandır")
    assert await scalar(sm, "select status from watches") == "paused"
    assert "⏸" in chat.last_text()
    assert await scalar(sm, "select active_watch_count from watch_keys") == 0
    await chat.press("Davam et")
    assert await scalar(sm, "select status from watches") == "active"
    await chat.press("Sil")
    assert await scalar(sm, "select count(*) from watches") == 0 and "Silindi" in chat.last_text()


async def test_edit_target_from_list_with_quick_button_and_typed_price(env, sm):
    chat = env.chat()
    await create_watch(chat, target="150")
    async with sm.begin() as s:
        await s.execute(text("UPDATE watch_keys SET last_price = 200"))
    await chat.say("/list")
    await chat.press("Dəyiş")
    ask = chat.last_text()
    assert "Hazırkı hədəf: ≤ 150 USD" in ask and "Hazırda: 200 USD" in ask
    assert chat.button_labels()[0] == "⭐ −15% · 170"
    await chat.press("⭐")
    assert "Hədəf yeniləndi: ≤ 170 USD" in chat.last_text()
    assert float(await scalar(sm, "select target_price from watches")) == 170.0

    await chat.say("/list")
    await chat.press("Dəyiş")
    await chat.say("xyz")
    assert "rəqəm kimi" in chat.last_text()
    await chat.say("111")
    assert float(await scalar(sm, "select target_price from watches")) == 111.0
    assert await scalar(sm, "select armed from watches") is True


async def test_edit_target_without_known_price_has_no_quick_buttons_and_can_be_cancelled(env, sm):
    chat = env.chat()
    await create_watch(chat)
    await chat.say("/list")
    await chat.press("Dəyiş")
    assert not any("%" in x for x in chat.button_labels())
    await chat.press("Ləğv")
    assert "Ləğv edildi" in chat.last_text()
    assert float(await scalar(sm, "select target_price from watches")) == 150.0


async def test_user_cannot_touch_other_users_watch(env, sm):
    owner, intruder = env.chat(1), env.chat(2)
    await create_watch(owner)
    wid = await scalar(sm, "select id from watches")
    for action in ("del", "pause", "edit"):
        await intruder.click(WatchCb(action=action, id=wid).pack())
    r = await watch_rows(sm)
    assert len(r) == 1 and r[0].status == "active"


async def test_empty_list_offers_menu(env):
    chat = env.chat()
    await chat.say("/list")
    assert "Hələ izləməniz yoxdur" in chat.last_text() and "➕ Yeni izləmə" in chat.button_labels()


async def test_menu_buttons_start_flows(env):
    chat = env.chat()
    await chat.say("/start")
    await chat.say("/start")
    await chat.click(MenuCb(action="new").pack())
    assert "Haraya uçmaq istəyirsiniz" in chat.last_text()
    await chat.click(MenuCb(action="list").pack())
    assert "Hələ izləməniz yoxdur" in chat.last_text()


# ============================================================ bildirişdən idarəetmə
async def test_notification_pause_button_pauses_and_removes_management_row(env, sm):
    chat = env.chat(21)
    await create_watch(chat)
    wid = await scalar(sm, "select id from watches")
    markup = {
        "inline_keyboard": [
            [{"text": "buy", "url": "https://x.y"}],
            [
                {"text": "p", "callback_data": WatchCb(action="npause", id=wid).pack()},
                {"text": "e", "callback_data": WatchCb(action="edit", id=wid).pack()},
            ],
            [{"text": "fb", "callback_data": FbCb(id=1, vote=1).pack()}],
        ]
    }
    await chat.click(WatchCb(action="npause", id=wid).pack(), reply_markup=markup)
    assert await scalar(sm, "select status from watches") == "paused"
    assert any("dayandırıldı" in (a or "") for a in chat.alerts())
    edit = [m for m, _ in chat.session.log if isinstance(m, EditMessageReplyMarkup)][-1]
    left = [b.text for row in edit.reply_markup.inline_keyboard for b in row]
    assert left == ["buy", "fb"]


async def test_notification_edit_target_button_opens_edit_flow_as_new_message(env, sm):
    chat = env.chat(22)
    await create_watch(chat)
    wid = await scalar(sm, "select id from watches")
    await chat.click(WatchCb(action="edit", id=wid).pack())
    assert "Yeni hədəf qiyməti" in chat.last_text()
    await chat.say("77")
    assert float(await scalar(sm, "select target_price from watches")) == 77.0


# ======================================================================= /settings
async def test_settings_language_currency_and_quiet_hours(env, sm):
    chat = env.chat()
    await chat.say("/settings")
    assert "Sakit saatlar (00:00–00:00): açıq" in chat.last_text()  # test konfiqurasiyasında söndürülüb
    await chat.press("English")
    assert "Settings" in chat.last_text() and await scalar(sm, "select language from users") == "en"
    await chat.press("AZN")
    assert "AZN" in chat.last_text() and await scalar(sm, "select currency from users") == "AZN"
    await chat.press("Quiet hours")
    assert await scalar(sm, "select quiet_hours from users") is False and "off" in chat.last_text()
    await chat.press("Quiet hours")
    assert await scalar(sm, "select quiet_hours from users") is True
    await chat.say("/help")
    assert "How it works" in chat.last_text()


async def test_new_watches_use_user_currency(env, sm):
    chat = env.chat()
    await chat.say("/settings")
    await chat.press("AZN")
    await create_watch(chat)
    assert (await watch_rows(sm))[0].currency == "AZN" and "AZN" in chat.last_text()


async def test_set_home_city_changes_default_origin(env, sm):
    chat = env.chat()
    await chat.say("/settings")
    await chat.press("Ev şəhəri")
    assert "Haradan uçursunuz" in chat.last_text()
    await chat.say("ankara")
    await chat.press("Ankara")
    assert "Ev şəhəriniz: <b>Ankara</b>" in chat.last_text()
    assert await scalar(sm, "select home_iata from users") == "ESB"
    await chat.say("/new")
    assert "Haradan: <b>Ankara</b>" in chat.last_text()


# ===================================================== bloklama / bloku açma / feedback
def member_update(tg_id: int, status: str) -> dict:
    user = {"id": tg_id, "is_bot": False, "first_name": "T"}
    bot_user = {"id": 42, "is_bot": True, "first_name": "bot", "username": "b"}
    new = {"user": bot_user, "status": status}
    if status == "kicked":
        new["until_date"] = 0
    return {
        "update_id": int(time.time() * 1000) % 10**9,
        "my_chat_member": {
            "chat": {"id": tg_id, "type": "private"},
            "from": user,
            "date": int(time.time()),
            "old_chat_member": {"user": bot_user, "status": "member"},
            "new_chat_member": new,
        },
    }


async def test_my_chat_member_kicked_freezes_and_member_restores(env, sm):
    chat = env.chat(77)
    await create_watch(chat)
    await env.dp.feed_raw_update(env.bot, member_update(77, "kicked"))
    assert await scalar(sm, "select is_blocked from users") is True
    assert await scalar(sm, "select status from watches") == "paused"
    assert await scalar(sm, "select active_watch_count from watch_keys") == 0
    await env.dp.feed_raw_update(env.bot, member_update(77, "member"))
    assert await scalar(sm, "select is_blocked from users") is False
    assert await scalar(sm, "select status from watches") == "active"


async def test_feedback_is_stored_only_owner_can_vote_and_only_feedback_row_removed(env, sm):
    chat, other = env.chat(5), env.chat(6)
    await chat.say("/help")
    await other.say("/help")
    uid = await scalar(sm, "select id from users where telegram_id=5")
    async with sm.begin() as s:
        await s.execute(
            text("INSERT INTO notifications (id, user_id, dedup_key, payload) VALUES (900, :u, 'k', '{}')"),
            {"u": uid},
        )
    markup = {
        "inline_keyboard": [
            [{"text": "buy", "url": "https://x.y"}],
            [{"text": "manage", "callback_data": WatchCb(action="edit", id=1).pack()}],
            [{"text": "up", "callback_data": FbCb(id=900, vote=1).pack()}],
        ]
    }
    await other.click(FbCb(id=900, vote=-1).pack(), reply_markup=markup)
    assert await scalar(sm, "select feedback from notifications") is None
    await chat.click(FbCb(id=900, vote=1).pack(), reply_markup=markup)
    assert await scalar(sm, "select feedback from notifications") == 1
    edits = [m for m, _ in chat.session.log if isinstance(m, EditMessageReplyMarkup)]
    assert edits and len(edits[-1].reply_markup.inline_keyboard) == 2  # buy + manage qalır


# =========================================================================== throttle
async def test_flood_is_throttled_per_user(env):
    env.make(throttle=(1.0, 3))
    spammer, normal = env.chat(1), env.chat(2)
    for _ in range(12):
        await spammer.say("/help")
    helps = [t for t in spammer.texts(False) if "Necə işləyir" in t]
    assert 3 <= len(helps) <= 5
    await normal.say("/help")
    assert "Necə işləyir" in normal.last_text()


async def test_unhandled_error_replies_gracefully(env, monkeypatch):
    import flightbot.bot.handlers.settings as settings_mod

    async def boom(*a, **kw):
        raise RuntimeError("bug")

    chat = env.chat()
    monkeypatch.setattr(settings_mod, "set_language", boom)
    await chat.say("/settings")
    await chat.press("English")
    assert any("Xəta" in (a or "") for a in chat.alerts()) or any("Xəta" in t for t in chat.texts(False))


# ========================================================================== /delete
async def test_delete_my_data_removes_everything_after_confirmation(env, sm):
    chat = env.chat(31)
    await create_watch(chat)
    await chat.say("/delete")
    assert "birdəfəlik silinəcək" in chat.last_text()
    assert await scalar(sm, "select count(*) from users") == 1
    await chat.press("Bəli, hamısını sil")
    assert "məlumatlarınız silindi" in chat.last_text()
    assert await scalar(sm, "select count(*) from users") == 0
    assert await scalar(sm, "select count(*) from watches") == 0
    assert await scalar(sm, "select active_watch_count from watch_keys") == 0


async def test_delete_can_be_cancelled(env, sm):
    chat = env.chat(32)
    await create_watch(chat)
    await chat.say("/delete")
    await chat.press("Ləğv et")
    assert "Ləğv edildi" in chat.last_text()
    assert (
        await scalar(sm, "select count(*) from users") == 1
        and await scalar(sm, "select count(*) from watches") == 1
    )


async def test_deleting_one_user_does_not_touch_others_on_same_route(env, sm):
    a, b = env.chat(41), env.chat(42)
    await create_watch(a)
    await create_watch(b)
    assert await scalar(sm, "select active_watch_count from watch_keys") == 2
    await a.say("/delete")
    await a.press("Bəli, hamısını sil")
    assert await scalar(sm, "select count(*) from users") == 1
    assert await scalar(sm, "select active_watch_count from watch_keys") == 1
