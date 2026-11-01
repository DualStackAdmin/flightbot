# Architecture decisions (ADR)

## ADR-001: A modular monolith, not microservices
**Context:** a one-person/small team, a target of 1-20k users.
**Decision:** one codebase with layers: `core` (business logic), `providers`, `workers`, `bot`. Telegram is just one adapter.
**Consequence:** a web dashboard or Mini App can later reuse the same `core`. If a service ever needs splitting out, the boundaries are already there.

## ADR-002: The queue is Postgres (`SKIP LOCKED`), not Celery/Taskiq
**Context:** the units of work are "a watch_key that is due" and "a notification to send". Both are already Postgres rows.
**Decision:** a claim query with `FOR UPDATE SKIP LOCKED` + `lease_until`. No separate broker.
**Consequence:** (+) simple, durable, transactional, a Redis outage doesn't touch the queue, replicas are safe. (−) not suited to extremely high throughput (hundreds of thousands of jobs per second). Load test: the claim query takes 0.14 ms on 300k rows. Taskiq can be added later if needed.

## ADR-003: The dedup unit is the `watch_key`
**Decision:** provider requests are made per signature, not per subscription; in flexible-date mode "one month = one request".
**Consequence:** a 21× reduction (load test). Cost: user-specific filters (airline, baggage) must be part of the signature (not built yet) or applied as post-filters. The "next N days" mode was dropped for this reason.

## ADR-004: The outbox lives in Postgres
**Decision:** the poller writes the notification in the same transaction as the state; the broadcaster sends it separately.
**Consequence:** losing Redis doesn't delete notifications, delivery is at-least-once, and retry/backoff/audit live in a table. The Redis list in the earlier design could have been lost to eviction.

## ADR-005: Redis only for volatile data
**Decision:** FSM, provider cache, rate-limit buckets. `maxmemory-policy volatile-lru`, and every key has a TTL. Logical databases (0/1/2) were not split: they share memory and the eviction policy, so the split gives no benefit.

## ADR-006: The counter is maintained by DB triggers
**Decision:** `active_watch_count` is updated by triggers on `watches`; the janitor checks for drift.
**Consequence:** no risk of forgetting to update it in application code (a real problem in the earlier design).

## ADR-007: A provider interface
**Decision:** `PriceProvider.offers()` / `explore()` are the only boundary; wrappers compose as Cached → RateLimited → Raw.
**Consequence:** adding a second provider means writing one adapter. Depending on a single provider is a business risk; this reduces it but does not remove it.

## ADR-008: A distributed rate limit (Redis Lua token bucket)
**Decision:** the Telegram global/per-user limits and the provider RPS live in Redis for all replicas, with time taken from the Redis server (`TIME`).
**Consequence:** none of the "N replicas = N × the limit" problem of in-process limiters such as `aiolimiter`.

## ADR-009: Payments via Telegram Stars (planned)
Telegram requires Stars for digital goods (verify the official rules before launch). Stripe is not intended as the primary path.

## ADR-010: The default watch mode is "by month"; the flow is 3 taps
**Context:** a 7-8 step flow lost users; many people don't know the exact date; exact-date queries are sparse in the Data API cache.
**Decision:** the default flow is destination → month → target. Origin = home city, one-way, direct-only off. The rest sits behind "Details" / "Exact date". The flow engine (`bot/handlers/flow.py`) gives every step Back/Cancel (history lives in the FSM).
**Consequence:** (+) higher activation, and month mode is ideal for dedup (one month = one request). (−) the Free plan's separate "flexible watch" limit became meaningless and was removed.

## ADR-011: "Anywhere" is part of the provider interface and is cached
`PriceProvider.explore()` returns the cheapest destinations for a month; the result is cached for one hour (with singleflight), so in a viral moment the same query goes out once. World city names come from a static list plus the open `cities.json` (cached in Redis for 7 days); on failure the code is shown.

## ADR-012: Quiet hours live in the poller, not in delivery
The notification is written to the outbox with `available_at`; the broadcaster is unchanged. Upside: the broadcaster stays simple and the queue-lag metric counts only notifications that are due. Downside: by the time it is delivered in the morning the price may have changed (the notification says so).

## ADR-014: Length of stay is part of the dedup signature
**Context:** most users search round trips ("a week in Istanbul"), not one-way tickets or an exact return month.
**Decision:** a month watch can carry `stay_min/stay_max`. The provider fetches round trips for both possible return months
(the return can spill into the next month) and keeps those whose stay is in range. The rate limiter charges 2 tokens.
**Consequence:** (+) matches how people search; "7 days" watches are still deduplicated across users. (−) twice the provider requests
for these keys, and different stays are different keys. Whether the Data API returns enough round-trip rows per month must be verified with a real token.

## ADR-013: The repository is English; the bot UI is multilingual
**Context:** the repo is meant to become public eventually; the bot serves Azerbaijani, Russian and English users.
**Decision:** all code, comments, docs, scripts and logs are English. User-facing text lives only in the i18n catalogs (`bot/i18n/{az,ru,en}.py`) and the static city names (`core/places.py`). A test verifies key/placeholder parity across languages.
**Consequence:** contributors need no Azerbaijani; adding a language is a self-contained change (see the README).
