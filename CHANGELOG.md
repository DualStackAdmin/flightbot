# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions: [SemVer](https://semver.org/) (0.x = pre-beta).

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
