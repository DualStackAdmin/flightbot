# FlightBot ✈️

**A Telegram bot that tracks flight prices and tells you when a fare drops below your target.**
Home-city departures, "cheapest day of the month" watches, and an "anywhere" search that lists the cheapest destinations worldwide.

`Python 3.12` · `aiogram 3` · `PostgreSQL 16` · `Redis 7` · `SQLAlchemy 2 (async)` · `Alembic` · `Docker`

> **Status: v0.3.1, pre-beta.** The repository is currently private and proprietary (see [LICENSE](LICENSE)).
> Choose a license before making it public, and read the note on the affiliate marker in [Configuration](#configuration).
> See the [CHANGELOG](CHANGELOG.md) and [`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md).

**Contents:** [User experience](#user-experience) · [Technical foundations](#technical-foundations) · [Installation](#installation) ·
[Bot commands](#bot-commands) · [Configuration](#configuration) · [Languages](#languages) · [Tests](#tests) · [Security](#security) ·
[Workflow and releases](#workflow-and-releases) · [Project layout](#project-layout) · [Documentation](#documentation)

## User experience

- **Round trips the way people search:** `/new` → destination → **trip** (one way · round trip of 3/4/5/6/7/14 days · exact dates on a tap calendar · direct-only toggle) → month → target price. Origin defaults to the user's home city.
- **🌍 Anywhere:** pick one way or an N-day round trip and a month, and see the cheapest destinations worldwide from your home city; open one for a booking link or "notify me when cheaper".
- **The bot never goes silent:** typing "Istanbul" or "Baku Dubai" is enough, and anything it doesn't understand gets a reply with the menu.
- **Back / Cancel on every step**; messages are edited in place, so the chat doesn't grow.
- **Target-price help:** current price, 90-day median, a ⭐ recommended target, and a warning when the target is already met.
- **Manage from the notification:** ⏸ pause, 🎯 change target, 👍/👎 feedback. **Quiet hours** (23:00-08:00 Baku time by default) hold night-time notifications until morning.
- 3 UI languages (az / ru / en), AZN / USD / EUR, and `/delete` to erase all of a user's data.

## Technical foundations

- **Dedup:** 800 people watching the same route cost **one** provider request (`watch_keys`). In the load test, 21,000 watches produced 1,000 requests.
- **Outbox:** notifications are written to Postgres and sent by a separate broadcaster, so they survive a Redis outage.
- **Respects Telegram limits:** a distributed token bucket (25 msg/s global, 1 msg/s per user) and a shared pause on RetryAfter.
- **Trustworthy alerts:** no repeats, cooldown, daily limit, and anomaly confirmation (protection against "error fare" false positives).
- **Horizontal scale:** every worker uses `SKIP LOCKED`, so any number of replicas is safe.

## Installation

### Linux server (recommended): clone the repo + one command
Details, including how to create the private GitHub repo: [`docs/DEPLOY.md`](docs/DEPLOY.md).
```bash
git clone git@github.com:<you>/flightbot.git /opt/flightbot && cd /opt/flightbot
./scripts/install.sh      # installs Docker if needed, creates .env (asks for BOT_TOKEN), starts everything
```
Update with `./scripts/update.sh` (git pull + rebuild + migrations). For a token-free trial use `PROVIDER=fake` (demo prices).

### Local (without Docker)
```bash
python -m venv .venv && source .venv/bin/activate && make install
export DATABASE_URL=postgresql+asyncpg://flightbot:flightbot@localhost:5432/flightbot
export REDIS_URL=redis://localhost:6379/0 BOT_TOKEN=123:abc
make migrate
python -m flightbot.bot        # in one terminal
python -m flightbot.workers    # in another (poller + broadcaster + janitor)
```
Webhook mode, recommended: **Cloudflare Tunnel** (no open ports, hidden server IP): set `BOT_MODE=webhook`, `WEBHOOK_BASE_URL` and `TUNNEL_TOKEN`, then `docker compose --profile tunnel up -d` (see [`docs/CLOUDFLARE.md`](docs/CLOUDFLARE.md)).
Alternative: Caddy with automatic TLS (`DOMAIN`, `docker compose --profile webhook up -d`, opens ports 80/443).
Prometheus: `--profile monitoring`.

## Bot commands

| Command | What it does |
|---|---|
| `/new` | New watch (destination → trip type / length of stay → month or calendar → target) |
| `/explore` | 🌍 Anywhere: the cheapest destinations for a chosen month |
| `/search` | The 5 cheapest options of a month for one route (one way or N-day round trip) |
| `/list` | Your watches: pause / resume / change target / delete |
| `/settings` | Language, currency, home city, quiet hours |
| `/delete` | Permanently delete all your data (with confirmation) |

Admin: `python -m flightbot.cli stats` · `grant-pro <telegram_id> --days 30` · `revoke-pro <telegram_id>`.

## Configuration

Full list: [`.env.example`](.env.example) and `src/flightbot/config.py`.

| Variable | Default | Notes |
|---|---|---|
| `BOT_TOKEN` | n/a | required |
| `PROVIDER` | `fake` | `travelpayouts` requires `TRAVELPAYOUTS_TOKEN` |
| `TRAVELPAYOUTS_MARKER` | `794979` | affiliate partner ID. **Replace it with your own, or leave it empty, before publishing or sharing the code: anyone who deploys the defaults would earn commissions for this marker.** Confirm in your Travelpayouts dashboard that the number is a *marker*, not a referral-program code. |
| `PROVIDER_RPS` | 3 | verify the real limit in the provider's docs |
| `BOT_MODE` | `polling` | `webhook` needs `WEBHOOK_BASE_URL` + `WEBHOOK_SECRET` |
| `TELEGRAM_GLOBAL_RPS` | 25 | Telegram allows ~30; keeps 5 msg/s of headroom for live replies |
| `QUIET_START_HOUR` / `QUIET_END_HOUR` / `QUIET_TZ` | 23 / 8 / `Asia/Baku` | equal hours disable quiet hours |
| `DEFAULT_LANGUAGE` | `az` | fallback when the user's Telegram language isn't supported |
| `DB_STATEMENT_CACHE_SIZE` | 100 | set to `0` behind PgBouncer (transaction mode) |

## Languages

The bot UI ships in **Azerbaijani (default fallback), Russian and English** (`src/flightbot/bot/i18n/`), and the built-in city names are in the same three languages (`core/places.py`).
Everything else in the repository (code, comments, docs, scripts) is in English. The language is guessed from the user's Telegram settings and can be changed in `/settings`.
CI checks that every language has the same message keys and placeholders, so a missing translation fails the build.

Adding a language (outline): create `bot/i18n/<code>.py` (copy `en.py`: `MESSAGES`, `MONTHS_NOM`, `MONTHS_GEN`, `LANGUAGE_NAME`), register it in `bot/i18n/__init__.py`,
add the code to `SUPPORTED_LANGUAGES` (`core/users.py`) and to the `Settings.default_language` literal, extend the `ck_users_language` constraint with a new Alembic migration,
and add city names in `core/places.py`. Run the tests: the parity test tells you what is missing.

## Tests

```bash
make test        # needs real PostgreSQL and Redis
make lint
make loadtest    # 21,000 watches: dedup / limit / index checks (WIPES the database!)
```
Tests read `TEST_DATABASE_URL` / `TEST_REDIS_URL` (defaults: local `flightbot_test`, Redis db 15).
Coverage: alert rules, the SKIP LOCKED race, quota and daily-limit races, outbox/broadcaster failure paths, Redis outage, quiet hours,
the bot flow with a mocked Telegram session (tap by tap: default flow, back/cancel, fallback, explore, editing, settings),
webhook secret verification, and a migration ↔ model drift check.
The bot end-to-end tests drive the UI in Azerbaijani, so their assertions intentionally contain Azerbaijani bot messages.

## Security

See [`SECURITY.md`](SECURITY.md) for the threat model, the v0.3.1 review and open recommendations, and [`docs/CLOUDFLARE.md`](docs/CLOUDFLARE.md) for edge protection.


- `.env` (tokens, passwords) is **never** committed (`.gitignore`); `install.sh` creates it with `chmod 600`.
- The repo should stay **private** until you decide otherwise: `./scripts/publish_to_github.sh` creates it private, aborts if it is public, and scans tracked files for tokens before pushing.
- Give the server a **read-only** deploy key (`docs/DEPLOY.md`) and use a separate SSH key for CI/CD.
- The webhook is protected with `X-Telegram-Bot-Api-Secret-Token` (a wrong token returns 401, verified by a test).
- If a token or password is committed by accident: **rotate it first** (BotFather `/revoke`, a new Travelpayouts token), then purge it from the git history. Removing it from history alone is not enough.
- User data is minimal (Telegram ID, language, currency, watches); `/delete` removes all of it.

## Workflow and releases

```bash
make install && make test && make lint     # before/after changes
git switch -c feature/<name>               # small changes may go straight to main (single developer)
git commit -am "..." && git push
git tag -a v0.3.0 -m "v0.3.0" && git push --tags   # release; update CHANGELOG.md
```
CI (`.github/workflows/ci.yml`) runs lint and the tests against real Postgres/Redis on every push. Dependabot opens weekly dependency updates.
On the server: `./scripts/update.sh`. For a schema change create a migration with `make revision m="description"` and **review it by hand**.

## Project layout

```
src/flightbot/
  core/        # business logic: watch_key, alert_engine, schedule, quiet, pricing, plans, users, watches
  providers/   # provider interface, Travelpayouts, Fake, cache/rate-limit wrappers, places, names
  workers/     # poller, broadcaster, janitor
  bot/         # aiogram: handlers (flow engine), keyboards, middlewares, i18n, render
  db/          # models, session
migrations/    # Alembic (includes triggers and seed data)
scripts/       # install.sh, update.sh, publish_to_github.sh, loadtest.py
deploy/        # Prometheus, alert rules, Caddyfile
docs/          # spec, architecture, ADRs, runbook, deploy, launch checklist, roadmap
```

## Documentation

| Document | Purpose |
|---|---|
| [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) | Product rules, plans, notification logic |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, flows, invariants, failure modes |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Architecture decision records (ADRs) and their reasons |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Runbook: metrics, alerts, incident scenarios, backups |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Private GitHub repo and Linux server setup |
| [`docs/CLOUDFLARE.md`](docs/CLOUDFLARE.md) | Cloudflare Tunnel, WAF rules, Access, server firewall |
| [`SECURITY.md`](SECURITY.md) | Threat model, security review, recommendations |
| [`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md) | What to verify with real tokens before launch |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Next steps and known limitations |

## What is verified, and what is not

**Verified:** automated tests against real Postgres/Redis, the load test, a real worker process, and `install.sh` (in Docker-free dry-run mode).
**Not verified:** running against real Telegram, real Travelpayouts responses (the adapter is only tested against mocked HTTP; especially the
"anywhere" query and the `cities.json` format), starting Docker/compose, `deploy.yml`, and Telegram Stars payments (not implemented).
Go through [`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md) before launch.
