# Pre-launch checklist

Everything in this project is tested against real Postgres/Redis, but the items below **need real accounts/tokens** and have not been verified yet.

## 1. Travelpayouts (most important; the adapter is only tested against mocked HTTP)
- [ ] Make one real request: `PROVIDER=travelpayouts` and `/search`. Do the response fields (`departure_at`, `price`, `airline`, `transfers`, `link`, `currency`) match expectations? (`providers/travelpayouts.py::parse_offers`)
- [ ] Does `departure_at=YYYY-MM` (a month query) and `return_at=YYYY-MM` really work, or does month mode need a different request?
- [ ] Is the AZN currency supported? If not, remove it from `SUPPORTED_CURRENCIES` or add conversion.
- [ ] The official rate limits and the right `PROVIDER_RPS`. The age of Data API cache entries (is the "cached data" notice in notifications accurate?).
- [ ] Partner-program terms: caching/display rules, and whether the real-time Search API needs separate approval.
- [ ] The domain/prefix of the `link` field and the **marker format**: `core/affiliate.py` uses `marker=<MARKER>.<SUB_ID>`. Confirm commissions are attributed correctly with one test booking.
- [ ] The `autocomplete` response format (`providers/places.py`); on failure it falls back to the static list.

## 2. Telegram
- [ ] Create the bot in BotFather; set `BOT_TOKEN`. Commands are set automatically at startup (az/ru/en).
- [ ] Webhook: an HTTPS domain (the Caddy profile) and `WEBHOOK_SECRET` as a long random string. The secret check is tested (a wrong token returns 401).
- [ ] Real flow: `/start` → `/new` → notification → 👍/👎 → block the bot → `/start`. (The bot has not been run against real Telegram yet.)
- [ ] Payments: Telegram requires Stars for digital services. Verify the official rules before selling Pro (Stars are not built yet).
- [ ] At peak load Telegram offers paid broadcasts above 30 msg/s; evaluate it separately if needed.

## 3. Legal and privacy
- [ ] A privacy policy and terms of service (linked from the bot description / `/help`).
- [ ] Stored data: Telegram ID, language, currency, watches, notifications. `/delete` exists and is tested.
- [ ] Check local personal-data law / GDPR for EU users (with a lawyer).
- [ ] Affiliate disclosure: links in notifications are partner links.

## 4. Operations
- [ ] Postgres backup/PITR works and a restore has been tried once.
- [ ] `.env` is private, `POSTGRES_PASSWORD` changed, `ENV=prod`.
- [ ] `SENTRY_DSN` and Alertmanager (or another alert channel) connected. `deploy/alerts.yml` alone sends nothing.
- [ ] `docker compose` started once on a real server (Docker was not available where this was generated).
- [ ] Server sizing: 1 vCPU / 2 GB is enough at first (the load test ran on 1 CPU), but measure again with real provider latency.

## 5. Quality (first 2 weeks, closed beta)
- [ ] 20-50 users; run `python -m flightbot.cli stats` daily.
- [ ] Targets: 👎 < 10%, blocks < 5%, Telegram `retry_after` = 0, queue lag < 60 s.
- [ ] Manually compare notified prices with what is really bookable (a cached price may differ on the site).

## 6. Extra checks for v0.2 features
- [ ] **Marker:** does `794979` show up in the Travelpayouts dashboard as "Partner ID / marker" (not a referral-program code)? After a test click, does it appear in the statistics with its `sub_id`?
- [ ] **"Anywhere" (`explore`)**: with a real token, does the `prices_for_dates` request without `destination` and with `unique=true` return only the cheapest ticket per destination? (`providers/travelpayouts.py::explore`). If not, the request has to move to another endpoint.
- [ ] **Round trips by stay (v0.3):** with a real token, does `prices_for_dates` with `one_way=false`, `departure_at=YYYY-MM`, `return_at=YYYY-MM` return enough rows for 3-14 day stays (we fetch 100 rows for both return months and filter)? If results are sparse, consider a ±1 day stay range (the model already supports it).
- [ ] **Name resolution:** is `https://api.travelpayouts.com/data/en/cities.json` open and does it return `code`, `name`, `country_code`? (Otherwise world cities show as codes; the system doesn't break.)
- [ ] **Quiet hours:** check once on a real phone at night that a notification is held until morning; set `QUIET_TZ` if your audience is in another time zone.
- [ ] **Target buttons:** is the −15% recommendation sensible on real price distributions? Look at user feedback and created targets and tune it (`bot/parsing.py::quick_targets`).
- [ ] **Translations:** a native speaker should read all of `bot/i18n/az.py` (and `ru.py`) and fix tone and wording.
- [ ] **5 real people:** watch them create their first watch on a phone without any explanation and write down where they get stuck.
- [ ] **GitHub/Linux:** run `install.sh` once on a clean Ubuntu server; test `update.sh` and (if you use it) `deploy.yml`.
