# Operations runbook

## Components and scaling
| Component | Replicas | Notes |
|---|---|---|
| bot | webhook: N (behind a load balancer); polling: **1** | two polling replicas conflict on `getUpdates` |
| worker | N | `docker compose up -d --scale worker=3`; poller/broadcaster/janitor are safe with SKIP LOCKED |
| postgres | 1 (+ backup/PITR) | as connections grow add PgBouncer (transaction mode) + `DB_STATEMENT_CACHE_SIZE=0` |
| redis | 1 | if lost, FSM state and limit buckets reset; notifications are not lost |

Broadcaster replicas share the Telegram limit (a Redis bucket): adding replicas does not raise it. The throughput ceiling is `TELEGRAM_GLOBAL_RPS`.

## Releases and migrations
```bash
docker compose build && docker compose up -d   # the migrate service runs `alembic upgrade head`, then bot/worker start
```
New migration: `make revision m="description"`, then **review it by hand** (triggers, partial indexes). `test_migration_matches_models` catches model/migration drift. Roll back with `alembic downgrade -1` (downgrade of the first migration is tested).

## Metrics and alerts
`bot:9100/metrics`, `worker:9100/metrics`. Rules: `deploy/alerts.yml` (Alertmanager is not wired up).

| Signal | Threshold | First look |
|---|---|---|
| `notification_queue_lag_seconds` | > 300 s | is the broadcaster running? `telegram_errors_total{type="retry_after"}`; is the Telegram limit reached? |
| `telegram_errors_total{type="retry_after"}` | target 0 | lower `TELEGRAM_GLOBAL_RPS`; is another process sending with the same bot token? |
| `due_watch_keys` | > 500 for a long time | the provider RPS or the poller replicas are not enough |
| `provider_requests_total{status!="ok"}` | > 20% | provider status, token, quota |
| `active_watch_count_drift_total` | > 0 | do the triggers exist? (should never happen) |

Note: the original plan had a "cache hit > 85%" target. Here the main saving comes from `watch_key` dedup, not from the cache (the poll interval is ≥ the cache TTL), so the cache ratio is secondary and no alert is defined for it.

## Incident scenarios
- **Provider is down:** nothing to do. Keys wait with backoff and users see "service not responding" on `/search`. Announce a status if it lasts long.
- **Telegram flood:** the broadcaster pauses itself. If it repeats, lower the limit and check whether another process writes with the same token.
- **Redis is down:** the bot's FSM stops working (users restart the flow) and workers wait. When Redis returns everything resumes. No extra action needed.
- **Too many notifications / complaints:** `python -m flightbot.cli stats` (👎 rate). Tighten the rules in `core/alert_engine.py` (cooldown, the 5% rule).
- **Mass blocking:** if `users_blocked` rises, look at notification frequency and quality.
- **A user wants more than the free plan:** `python -m flightbot.cli grant-pro <telegram_id> --days 30`.

## Backups
Only Postgres matters (`pg_dump`, or PITR on a managed service). There is no need to back up Redis.

## Data retention
The janitor (hourly): marks expired watches `expired`, deletes finished notifications older than 30 days and price history older than 400 days, and cleans up unreferenced old keys. `/delete` removes all of a user's data.
