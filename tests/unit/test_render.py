from flightbot.bot.i18n import SUPPORTED
from flightbot.bot.render import FbCb, render_notification

PAYLOAD = {
    "origin": "GYD",
    "destination": "IST",
    "date_mode": "exact",
    "window_start": "2026-12-15",
    "currency": "USD",
    "price": "99.50",
    "depart_date": "2026-12-15",
    "return_date": None,
    "airline": "TK",
    "transfers": 0,
    "link": "/search/GYD1512IST1?t=x",
    "target_price": "120",
    "good_price": True,
    "vs_median_pct": -23,
    "trend": "down",
    "previous_price": "130",
}


def test_renders_in_every_language_without_missing_keys():
    for lang in SUPPORTED:
        text, kb = render_notification(PAYLOAD, lang, marker="m1", notification_id=7)
        assert "99.5" in text and "USD" in text and "23" in text
        assert kb.inline_keyboard[0][0].url.startswith("https://www.aviasales.com/search/")
        assert "marker=m1.n7" in kb.inline_keyboard[0][0].url


def test_az_text_has_route_names_and_badge():
    text, _ = render_notification(PAYLOAD, "az", marker="", notification_id=1)
    assert "Bakı → İstanbul" in text and "Yaxşı qiymət" in text and "keşlənmiş" in text


def test_feedback_buttons_roundtrip_callback_data():
    _, kb = render_notification(PAYLOAD, "en", marker="", notification_id=55)
    up, down = kb.inline_keyboard[1]
    assert FbCb.unpack(up.callback_data) == FbCb(id=55, vote=1)
    assert FbCb.unpack(down.callback_data) == FbCb(id=55, vote=-1)
    assert len(up.callback_data.encode()) <= 64


def test_flexible_and_round_trip_render():
    p = {**PAYLOAD, "date_mode": "month", "window_start": "2026-12-01", "return_date": "2026-12-22"}
    text, _ = render_notification(p, "ru", marker="", notification_id=1)
    assert "декабр" in text.lower() or "декабрь" in text


def test_airline_text_is_html_escaped():
    p = {**PAYLOAD, "airline": "<b>X</b>"}
    text, _ = render_notification(p, "en", marker="", notification_id=1)
    assert "&lt;b&gt;X" in text
