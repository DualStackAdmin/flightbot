# Arxitektura

Modulyar monolit: bir kod bazası, təmiz qatlar. Mikroservis yoxdur (ADR-001).

```
Telegram ──► bot (aiogram, polling/webhook) ──┐
                                              ▼
                     ┌────────── PostgreSQL ──────────┐          Redis (yalnız uçucu data)
                     │ users, watch_keys, watches,    │          FSM · provayder keşi
                     │ price_points, notifications    │          rate limit bucket-ları
                     └──▲───────────────▲─────────────┘
          claim (SKIP LOCKED)           │ claim (SKIP LOCKED)
              ┌────────┴──────┐   ┌─────┴────────────┐
              │ poller        │   │ broadcaster      │──► Telegram (≤25 msg/s)
              │ 1 açar=1 sorğu│   │ outbox → mesaj   │
              └──────┬────────┘   └──────────────────┘
                     ▼
        provayder (Cached → RateLimited → Travelpayouts/Fake)        janitor: expire, reconcile, purge
```

## Məlumat modeli
- **watch_keys**: provayderə gedən sorğunun unikal imzası `(origin, destination, date_mode, depart_date, return_date, direct_only, currency)`. `UNIQUE NULLS NOT DISTINCT` (PG15+). Ay rejimində "bir ay = bir sorğu". Planlaşdırma: `next_check_at`, `lease_until`, `consecutive_failures`.
- **watches**: istifadəçinin abunəliyi (`target_price`, `armed`, `last_notified_*`, `status`, `pause_reason`).
- **watch_keys.active_watch_count**: `watches` üzərindəki DB trigger-i ilə saxlanılır; janitor yoxlayır (drift metrikası).
- **price_points**: qiymət tarixçəsi (dəyişməyən qiymət 12 saat ərzində təkrar yazılmır).
- **notifications**: transactional outbox. `dedup_key UNIQUE` = `w{watch}:{qiymət}:{gün}`.

## Axınlar
**Yoxlama (poller):** claim (`FOR UPDATE SKIP LOCKED` + lease) → provayderdən 1 sorğu → statistika (median/p20) → şübhəlidirsə ikinci sorğu → **bir tranzaksiyada**: tarixçə, istifadəçi sətirlərinin kilidi, hər abunəçi üçün `decide()`, outbox INSERT, watch vəziyyəti, `next_check_at`.

**Çatdırılma (broadcaster):** claim (prioritet, `available_at`) → pauza/istifadəçi limiti/qlobal limit → render (istifadəçinin hazırkı dilində) → `send_message` → `sent`.

**Bildiriş vəziyyətləri:** `pending → sending → sent | failed | skipped`. Bütün çıxış keçidləri yalnız `sending`-dən icazəlidir.

## Dəyişməzlər (testlərlə qorunur)
1. Bir dövrdə bir `watch_key` üçün ən çox 1 provayder sorğusu.
2. Bildiriş və watch vəziyyəti eyni tranzaksiyadadır: "state irəliləyib, bildiriş itib" olmur.
3. Eyni (watch, qiymət, gün) üçün DB səviyyəsində ikinci bildiriş mümkün deyil.
4. Kvota və gündəlik limit istifadəçi sətri üzərində `FOR UPDATE` ilə atomikdir (paralel sorğularla aşılmır).
5. Redis-də kritik data yoxdur; bütün açarların TTL-i var (`volatile-lru` təhlükəsizdir).
6. Çatdırılma **at-least-once**-dır: worker mesajı göndərib status yazmamış çöksə, lease bitəndə nadir hallarda təkrar gedə bilər.

## Uğursuzluq rejimləri
| Hadisə | Davranış |
|---|---|
| Provayder düşüb | Açar üzrə eksponensial backoff (5 dəq → 6 saat), bildiriş yoxdur, istifadəçilər təsirlənmir |
| Provayder 429 | `Retry-After` qədər gecikdirilir, uğursuzluq sayğacı artmır |
| Telegram 429 | Redis-də qlobal pauza, mesaj cəhd yandırmadan növbəyə qayıdır |
| İstifadəçi botu bloklayıb | İstifadəçi `is_blocked`, abunəliklər `paused/blocked`, gözləyən bildirişlər `skipped`; geri qayıdanda bərpa |
| Redis düşüb | Poller açarı 60 san gecikdirir (uğursuzluq sayılmır), broadcaster bildirişi cəhd yandırmadan saxlayır, bot throttle fail-open; bildirişlər Postgres-də qalır |
| Worker çökdü | Lease bitəndə başqa replika götürür |
| Postgres düşüb | Bot və worker-lər xəta verir, bərpadan sonra özü davam edir (state Postgres-dədir) |

## v0.2 əlavələri
- **Bot axın mühərriki** (`bot/handlers/flow.py`): hər addım ayrı FSM state-dir; `step` və `history` FSM data-sındadır (Geri düyməsi). Callback keçidləri mesajı redaktə edir, gözləmə mesajı ("baxıram") nəticə ilə eyni mesajda əvəzlənir.
- **Explore:** `PriceProvider.explore()` → `CachedProvider` (1 saat, singleflight) → `RateLimitedProvider` → adapter. Şəhər adları `PlaceNames` (statik + `cities.json`, Redis 7 gün).
- **Sakit saatlar:** poller bildirişi outbox-a `available_at = deliver_after(...)` ilə yazır (`core/quiet.py`); broadcaster dəyişməyib. `users.quiet_hours` (default açıq).
- **Redis xətası:** poller açarı 60 san gecikdirir (uğursuzluq sayılmır), broadcaster cəhd yandırmır, throttle fail-open.
