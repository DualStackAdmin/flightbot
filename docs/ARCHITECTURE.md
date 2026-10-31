# Architecture

A modular monolith: one codebase with clean layers. No microservices (ADR-001).

```
Telegram ──► bot (aiogram, polling/webhook) ──┐
                                              ▼
                     ┌────────── PostgreSQL ──────────┐          Redis (volatile data only)
                     │ users, watch_keys, watches,    │          FSM · provider cache
                     │ price_points, notifications    │          rate-limit buckets
                     └──▲───────────────▲─────────────┘
          claim (SKIP LOCKED)           │ claim (SKIP LOCKED)
              ┌────────┴──────┐   ┌─────┴────────────┐
              │ poller        │   │ broadcaster      │──► Telegram (≤25 msg/s)
              │ 1 key = 1 req │   │ outbox → message │
              └──────┬────────┘   └──────────────────┘
                     ▼
        provider (Cached → RateLimited → Travelpayouts/Fake)        janitor: expire, reconcile, purge
```

## Data model
- **watch_keys**: the unique signature of a provider request `(origin, destination, date_mode, depart_date, return_date, direct_only, currency)`. `UNIQUE NULLS NOT DISTINCT` (PG15+). In month mode "one month = one request". Scheduling: `next_check_at`, `lease_until`, `consecutive_failures`.
- **watches**: a user's subscription (`target_price`, `armed`, `last_notified_*`, `status`, `pause_reason`).
- **watch_keys.active_watch_count**: maintained by DB triggers on `watches`; the janitor verifies it (drift metric).
- **price_points**: price history (an unchanged price is not rewritten within 12 hours).
- **notifications**: a transactional outbox. `dedup_key UNIQUE` = `w{watch}:{price}:{day}`.

## Flows
**Check (poller):** claim (`FOR UPDATE SKIP LOCKED` + lease) → 1 provider request → statistics (median/p20) → if suspicious, a second request → **in one transaction**: history, lock the user rows, `decide()` for each subscriber, outbox INSERT, watch state, `next_check_at`.

**Delivery (broadcaster):** claim (priority, `available_at`) → pause / per-user limit / global limit → render (in the user's current language) → `send_message` → `sent`.

**Notification states:** `pending → sending → sent | failed | skipped`. Every exit transition is allowed only from `sending`.

## Invariants (protected by tests)
1. At most 1 provider request per `watch_key` per cycle.
2. The notification and the watch state are in the same transaction: "state advanced but the notification was lost" cannot happen.
3. A second notification for the same (watch, price, day) is impossible at the DB level.
4. Quota and the daily limit are atomic via `FOR UPDATE` on the user row (parallel requests cannot exceed them).
5. Nothing critical lives in Redis; every key has a TTL (`volatile-lru` is safe).
6. Delivery is **at-least-once**: if a worker crashes after sending but before writing the status, a duplicate may rarely go out once the lease expires.

## Failure modes
| Event | Behavior |
|---|---|
| Provider is down | Exponential backoff per key (5 min → 6 h), no notifications, users unaffected |
| Provider 429 | Delayed by `Retry-After`, the failure counter does not increase |
| Telegram 429 | A global pause in Redis; the message returns to the queue without burning an attempt |
| User blocked the bot | User `is_blocked`, watches `paused/blocked`, pending notifications `skipped`; restored when they return |
| Redis is down | The poller delays the key 60 s (not counted as a failure), the broadcaster keeps notifications without burning attempts, the bot throttle fails open; notifications stay in Postgres |
| Worker crashed | Another replica takes over once the lease expires |
| Postgres is down | The bot and workers error out and continue by themselves after recovery (state is in Postgres) |

## v0.2 additions
- **Bot flow engine** (`bot/handlers/flow.py`): every step is its own FSM state; `step` and `history` live in the FSM data (the Back button). Callback transitions edit the message, and a "please wait" message is replaced in place by the result.
- **Explore:** `PriceProvider.explore()` → `CachedProvider` (1 hour, singleflight) → `RateLimitedProvider` → adapter. City names come from `PlaceNames` (static list + `cities.json`, cached in Redis for 7 days).
- **Quiet hours:** the poller writes the notification to the outbox with `available_at = deliver_after(...)` (`core/quiet.py`); the broadcaster is unchanged. `users.quiet_hours` (default on).
- **Redis errors:** the poller delays the key 60 s (not counted as a failure), the broadcaster doesn't burn attempts, the throttle fails open.
