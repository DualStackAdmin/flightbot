# Product specification (v0.2, with implementation status)

**Audience:** people in Baku and the region looking for cheap flights. Languages: az (guessed from the Telegram language, default az), ru, en. Currencies: USD, AZN, EUR.

## UX principles
1. The first watch takes under 60 seconds: destination → trip → month → target (4 taps).
2. Every message has a next step (a button). No dead ends.
3. The bot never goes silent (off-flow text, unknown commands, stickers, stale buttons).
4. Buttons over typing (mobile). Smart defaults: origin = home city, mode = by month, one-way.
5. Honesty: a cached-data notice, an affiliate disclosure, no fake urgency.

## Scenarios
| Scenario | Status |
|---|---|
| `/start`: language is guessed, popular-destination buttons appear immediately (no language question) | ✅ |
| `/new`: destination → **trip** (one way · round trip 3/4/5/6/7/14 days · exact dates on a calendar · direct-only toggle) → month (or calendar) → target | ✅ (v0.3) |
| Tap calendar for exact dates: past/out-of-range days disabled, month navigation, typing still works; return ≤ 30 days after departure | ✅ (v0.3) |
| Back / Cancel on every step; callback transitions edit the same message | ✅ |
| Target step: current price, 90-day median (if any), ⭐ recommended −15%, −10%, −25%; a warning when the target is already met | ✅ |
| After creating: current price, "➕ Another route", "📋 My watches" | ✅ |
| **🌍 Anywhere (`/explore`)**: trip (one way / N days) → month → the 10 cheapest destinations (flag, price) → detail (booking link + "notify me") | ✅ (the real response format needs verification) |
| `/search`: trip (one way / N days) → month → the 5 cheapest options (departure → return) → "notify me" | ✅ |
| Fallback: typing "Istanbul", "Baku Dubai" or "GYD-IST" jumps straight to the month step | ✅ |
| `/list`: pause, resume, **change target**, delete | ✅ |
| Notification buttons: ⏸ Pause, 🎯 Change target, 👍/👎 | ✅ |
| `/settings`: language, currency, **home city**, **quiet hours** | ✅ |
| `/delete` | ✅ |
| "This weekend" quick pick | ❌ skipped: exact-date queries are sparse in the Data API cache; month mode is more reliable |
| A flexible stay range (e.g. 5-7 days) | ⏳ supported by the data model (`stay_min`/`stay_max`), the UI offers exact N for now |
| "Next N days" mode | ❌ removed: it breaks the one-watch = one-API-request rule ("by month" replaces it) |

## Notification rules (all in `core/alert_engine.py`, covered by tests)
- **Trigger:** price ≤ target. **No repeats:** unless at least 5% cheaper than the previous notification. **Re-arm:** when the price rises above the target and drops again. **Cooldown:** 6 hours.
- **Daily limit:** Free 3, Pro 30. **Stale data:** a price older than 48 hours (when the provider reports `found_at`) is not sent.
- **Anomaly:** a price more than 60% below the median (with ≥14 samples) is confirmed by a second, uncached request; an unconfirmed price reaches neither a notification nor the history.
- **"Good price" badge:** within the lowest 20% of the last 90 days (≥14 samples).
- **Quiet hours:** a notification created between 23:00 and 08:00 (Baku) is written to the outbox and sent after 08:00 (0-15 min jitter). Users can disable it in `/settings`.
- The text always says the price is cached data and may change on the site.

## Plans
| | Free | Pro |
|---|---|---|
| Active watches | 3 | 25 |
| Check frequency | ~3-24 h (depending on time to departure) | ~1-6 h |
| Notification priority | normal | first |
| Daily notifications | 3 | 30 |

**Change from v0.1:** the Free-plan limit of "1 flexible (by-month) watch" was **removed**. The default mode is by month, so that limit broke the promise of 3 watches. The mechanism remains in code (`PlanLimits.max_flexible_watches`).
Pro is currently granted with `flightbot.cli grant-pro` (there is no payment flow yet).

## Revenue
1. **Affiliate:** every booking link carries `marker=<MARKER>.<sub_id>` (`TRAVELPAYOUTS_MARKER`). The sub_id is `n<id>` in notifications and `x<user_id>` in explore. **Confirm in the Travelpayouts dashboard that your number is the partner ID (marker):** a referral-program code is a different thing, and commissions would not be recorded.
2. Pro plan via Telegram Stars (not built yet), after roughly 500 active users.

## Success metrics
`python -m flightbot.cli stats`: active users, 7-day activity, 👎 rate (target <10%), block rate.
Prometheus: `notification_queue_lag_seconds`, `telegram_errors_total{type="retry_after"}` (target 0), `due_watch_keys`.
**Not measured yet:** the `/start` → first watch funnel and time to first watch (event tracking needs to be added).
