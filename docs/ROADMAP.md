# Roadmap

## Done (v0.2)
Dedup, outbox, alert engine, poller/broadcaster/janitor, bot (az/ru/en), the 3-tap flow, back/cancel, fallback, `/explore` (anywhere), `/search`, target editing, notification buttons, quiet hours, home city, `/delete`, admin CLI, Docker/CI/deploy scripts, load test, an English-language repository.

## Next (highest impact first)
1. **Verify with real tokens** (`LAUNCH_CHECKLIST.md`) and fix the adapter.
2. **Closed beta** and measuring notification quality (👎 rate).
3. **Event tracking (funnel):** `/start` → first watch → notification click; `acquisition_source` + deep links.
3b. **Affiliate click tracking:** your own redirect service (`/r/<notification_id>`) with click and conversion stats.
4. **Pro via Telegram Stars:** a `payments` table, `pre_checkout_query`/`successful_payment` handlers, an expiry warning.
5. A "cheapest price chart" (Pro), `/list` pagination, a "new date?" offer for expired watches.
6. **Growth:** auto-posting to a deals channel, referrals, a Telegram Mini App / web dashboard.
7. **Filters:** airline, baggage, passengers (affects the signature and the dedup design, ADR-003).
8. **A second provider adapter** (risk reduction).
9. **B2B / white label:** `tenant_id` is in the schema; per-tenant bot token, marker, and RLS.
10. More languages (e.g. Turkish); user-specific quiet-hour time zones.

## Known limitations
- Delivery is at-least-once (a rare duplicate is possible, see ARCHITECTURE.md).
- The poller issues one INSERT per subscriber; with hundreds of thousands of subscribers per key, move to bulk INSERTs.
- `price_points` is not partitioned (400-day retention is enough; partition or use TimescaleDB as it grows).
- In polling mode the bot must run as a single replica.
