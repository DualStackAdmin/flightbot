# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions: [SemVer](https://semver.org/) (0.x = pre-beta).

## [0.3.1]
### Security
- Secrets are redacted from logs and Sentry events, including tracebacks (Telegram API URLs contain the bot token).
- Docker: the bot's port is no longer published (internal `expose` only), Prometheus binds to `127.0.0.1`,
  `POSTGRES_PASSWORD` is required, Redis requires `REDIS_PASSWORD`, app containers are read-only with all capabilities dropped and `no-new-privileges`.
- New `tunnel` profile: Cloudflare Tunnel (`cloudflared`) publishes the webhook without opening inbound ports (docs/CLOUDFLARE.md).
- Caddy only proxies `POST /telegram/webhook`.
- Target prices from buttons are range-checked (callback data can be forged).
- Provider booking links are only used for trusted hosts over HTTPS.
- Per-user budget for `/search` and `/explore` (`SEARCH_BURST`, `SEARCH_PER_MINUTE`).
- CI runs with read-only permissions; the deploy workflow can pin the server host key (`DEPLOY_KNOWN_HOSTS`).
- `SECURITY.md` with the threat model, findings and open recommendations.
### Upgrade notes
- `update.sh` / `install.sh` add a random `REDIS_PASSWORD` to an existing `.env`. If `POSTGRES_PASSWORD` was never set,
  the old database still uses the password `flightbot`: set `POSTGRES_PASSWORD=flightbot` in `.env` first, then change it
  inside Postgres (`ALTER USER flightbot PASSWORD '...'`) and in `.env` together.
- If you published port 8080 directly before, switch to the `tunnel` (recommended) or `webhook` profile.

## [0.3.0]
### Added
- **Round trips by length of stay:** a trip step right after the destination: one way, round trip of 3/4/5/6/7/14 days, or exact dates on a calendar, plus a "direct only" toggle. The stay is part of the dedup signature (`watch_keys.stay_min/stay_max`, migration `0003`).
- **Tap calendar** for exact dates (Monday-first, localized weekdays, past and out-of-range days disabled, month navigation). Typing a date still works. Return must be after departure and within 30 days.
- `/search` and `/explore` support N-day round trips (results show departure → return dates; booking links are round-trip searches).
### Changed
- The old "⚙️ Details" step (round trip / direct) is replaced by the trip step. Typing exact dates moved into the calendar step.
- Stay-based round trips cost 2 provider requests (both possible return months) and are charged 2 tokens by the shared rate limiter.

## [0.2.1]
### Changed
- The whole repository is now in English: code comments and docstrings, error and log messages, CLI/script output, configuration comments, tests, README and `docs/`. No behavior changed.
- The bot UI is unchanged: Azerbaijani, Russian and English catalogs (`bot/i18n/`) and the built-in city names stay multilingual.
### Added
- README: a "Languages" section (how to add a language), a note on replacing the affiliate marker before publishing, and "Before making the repo public" steps in `docs/DEPLOY.md`.

## [0.2.0]
### Added
- **3-tap flow:** destination → month → target. Origin = home city, one-way by default; "Exact date" and "Details" (round trip, direct) are separate buttons.
- **🌍 Anywhere (`/explore`):** the cheapest destinations worldwide for a month, booking link, "notify me"; city names come from a static list plus `cities.json`.
- **Back / Cancel** on every step; messages are edited in place.
- **Fallback:** typing "Istanbul" / "Baku Dubai" jumps straight into the flow; the bot never goes unanswered.
- Target-price help: current price, 90-day median, ⭐ recommended −15%, an "already met" warning.
- Notification buttons: ⏸ Pause, 🎯 Change target; 🎯 Change in `/list`.
- **Quiet hours** (23:00-08:00 Baku), switchable in `/settings`; home-city setting.
- Affiliate marker `794979` (sub_id tracking); `/delete`; admin CLI; `install.sh`, `update.sh`, `publish_to_github.sh`, `deploy.yml`, Dependabot.
### Changed
- The separate "1 flexible watch" limit on the Free plan was removed (the default mode is by month).
- The provider cache was generalized (singleflight also covers explore).
### Fixed
- Notification attempts being burned when Redis is down; the poller failure counter inflating.
- Hour format of the quiet-hours setting (08:00).

## [0.1.0]
- First version: dedup (`watch_keys`), outbox, alert engine, poller/broadcaster/janitor, bot (az/ru/en), `/search`, Docker/CI, load test.
### Fixed (caught by the tests)
- Daily-limit race; asyncpg `AmbiguousParameterError`; a notification state-machine gap; `parse_price("-5")`.
