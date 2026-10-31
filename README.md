# FlightBot ✈️

**Telegram üzərində aviabilet qiymətlərini izləyən və qiymət hədəfdən aşağı düşəndə xəbər verən platforma.**
Bakıdan çıxış, Azərbaycan dili, AZN, "ay üzrə ən ucuz gün" və "hər yerə" axtarışı.

`Python 3.12` · `aiogram 3` · `PostgreSQL 16` · `Redis 7` · `SQLAlchemy 2 (async)` · `Alembic` · `Docker`

> 🔒 **Qapalı (private) layihə.** Mənbə kodu paylaşılmır, bax: [LICENSE](LICENSE). Versiya: **v0.2.0**, qapalı beta öncəsi
> (bax: [CHANGELOG](CHANGELOG.md), [`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md)).

**Məzmun:** [İstifadəçi təcrübəsi](#istifadəçi-təcrübəsi) · [Texniki əsas](#texniki-əsas) · [Quraşdırma](#quraşdırma) ·
[Bot əmrləri](#bot-əmrləri) · [Konfiqurasiya](#konfiqurasiya-əsas) · [Testlər](#testlər) · [Təhlükəsizlik](#təhlükəsizlik) ·
[İş axışı və versiyalar](#iş-axışı-və-versiyalar) · [Struktur](#struktur) · [Sənədlər](#sənədlər)

## İstifadəçi təcrübəsi

- **3 toxunuşla izləmə:** `/new` → haraya → ay → hədəf. Haradan = ev şəhəri (Bakı), tək istiqamət, birbaşa məcburi deyil ("⚙️ Ətraflı" düyməsi ilə açılır).
- **🌍 Hər yerə:** ay seçin, Bakıdan həmin ay üzrə dünyada ən ucuz istiqamətləri görün, birini seçin: bilet linki və ya "qiymət düşəndə xəbər ver".
- **Bot heç vaxt susmur:** "İstanbul" və ya "Bakı Dubay" yazmaq kifayətdir, tanınmayan hər şeyə menyu ilə cavab verir.
- **Hər addımda Geri / Ləğv**, mesajlar yerində redaktə olunur (söhbət uzanmır).
- **Hədəf qiymət köməyi:** hazırkı qiymət, 90 günlük median, ⭐ tövsiyə olunan hədəf; hədəf artıq ödənibsə xəbərdarlıq.
- **Bildirişdən idarəetmə:** ⏸ Dayandır, 🎯 Hədəfi dəyiş, 👍/👎 rəy. **Sakit saatlar** (23:00-08:00 Bakı vaxtı) gecə bildirişlərini səhərə saxlayır.
- 3 dil (az/ru/en), AZN/USD/EUR, `/delete` ilə bütün məlumatı silmək.

## Texniki əsas

- **Dedup:** eyni marşrutu izləyən 800 nəfər = **1** provayder sorğusu (`watch_keys`). Yük testində 21 000 izləmə → 1 000 sorğu.
- **Outbox:** bildirişlər Postgres-də yazılır, ayrıca broadcaster göndərir. Redis düşsə belə bildiriş itmir.
- **Telegram limitlərinə hörmət:** paylanmış token bucket (25 msg/s qlobal, 1 msg/s istifadəçi), RetryAfter üçün ümumi pauza.
- **Etibarlı bildiriş:** təkrar yoxdur, cooldown, gündəlik limit, anomaliya təsdiqi (xəta tarifi yalançı siqnalı).
- **Horizontal miqyas:** bütün worker-lər `SKIP LOCKED` ilə işləyir, istənilən sayda replika təhlükəsizdir.

## Quraşdırma

### Linux server (tövsiyə olunan): repo klonla + 1 əmr
Ətraflı: [`docs/DEPLOY.md`](docs/DEPLOY.md) (GitHub-da qapalı repo yaratmaq da orada).
```bash
git clone git@github.com:<siz>/flightbot.git /opt/flightbot && cd /opt/flightbot
./scripts/install.sh      # Docker-i özü quraşdırır, .env yaradır (BOT_TOKEN soruşur), hər şeyi işə salır
```
Yeniləmə: `./scripts/update.sh` (git pull + yenidən qur + miqrasiya). Token olmadan sınaq üçün `PROVIDER=fake` (demo qiymətlər).

### Lokal (Docker-siz)
```bash
python -m venv .venv && source .venv/bin/activate && make install
export DATABASE_URL=postgresql+asyncpg://flightbot:flightbot@localhost:5432/flightbot
export REDIS_URL=redis://localhost:6379/0 BOT_TOKEN=123:abc
make migrate
python -m flightbot.bot        # bir terminalda
python -m flightbot.workers    # digərində (poller + broadcaster + janitor)
```
Webhook + avtomatik TLS: `.env`-də `BOT_MODE=webhook`, `WEBHOOK_BASE_URL`, `WEBHOOK_SECRET`, `DOMAIN` və `docker compose --profile webhook up -d`.
Prometheus: `--profile monitoring`.

## Bot əmrləri

| Əmr | Nə edir |
|---|---|
| `/new` | Yeni izləmə (haraya → ay → hədəf) |
| `/explore` | 🌍 Hər yerə: seçilmiş ay üzrə ən ucuz istiqamətlər |
| `/search` | Marşrut üzrə ayın ən ucuz 5 günü |
| `/list` | İzləmələr: dayandır / davam et / hədəfi dəyiş / sil |
| `/settings` | Dil, valyuta, ev şəhəri, sakit saatlar |
| `/delete` | Bütün məlumatı təsdiqlə birdəfəlik silmək |

Admin: `python -m flightbot.cli stats` · `grant-pro <telegram_id> --days 30` · `revoke-pro <telegram_id>`.

## Konfiqurasiya (əsas)

Tam siyahı: [`.env.example`](.env.example) və `src/flightbot/config.py`.

| Dəyişən | Default | Qeyd |
|---|---|---|
| `BOT_TOKEN` | n/a | məcburi |
| `PROVIDER` | `fake` | `travelpayouts` üçün `TRAVELPAYOUTS_TOKEN` |
| `TRAVELPAYOUTS_MARKER` | `794979` | partnyor ID: affiliate gəlir buradan; kabinetdə təsdiqləyin |
| `PROVIDER_RPS` | 3 | real limiti provayder sənədindən yoxlayın |
| `BOT_MODE` | `polling` | `webhook` üçün `WEBHOOK_BASE_URL` + `WEBHOOK_SECRET` |
| `TELEGRAM_GLOBAL_RPS` | 25 | Telegram ~30; 5 msg/s canlı cavablar üçün ehtiyat |
| `QUIET_START_HOUR` / `QUIET_END_HOUR` / `QUIET_TZ` | 23 / 8 / `Asia/Baku` | bərabər olsalar sakit saatlar söndürülür |
| `DB_STATEMENT_CACHE_SIZE` | 100 | PgBouncer (transaction mode) arxasında `0` |

## Testlər

```bash
make test        # real PostgreSQL + Redis lazımdır
make lint
make loadtest    # 21 000 izləmə, dedup/limit/indeks yoxlaması (DB-ni silir!)
```
Testlər `TEST_DATABASE_URL` / `TEST_REDIS_URL` oxuyur (default: lokal `flightbot_test`, Redis db 15).
Əhatə: alert qaydaları, SKIP LOCKED yarışı, kvota və gündəlik limit race-ləri, outbox/broadcaster xəta halları,
Redis outage, sakit saatlar, bot axını (Telegram mock sessiyası ilə, düymə-düymə: standart axın, geri/ləğv,
fallback, explore, redaktə, ayarlar), webhook secret yoxlaması, miqrasiya ↔ model drift yoxlaması.

## Təhlükəsizlik

- `.env` (tokenlər, parollar) **heç vaxt** repo-ya düşmür (`.gitignore`); `install.sh` onu `chmod 600` ilə yaradır.
- Repo yalnız **private** olmalıdır: `./scripts/publish_to_github.sh` repo-nu private yaradır, açıq olarsa dayanır və push-dan əvvəl izlənən fayllarda token axtarır.
- Serverə repo-ya **yalnız oxuma** icazəli deploy key verin (`docs/DEPLOY.md`). CI/CD üçün ayrıca SSH açarı istifadə edin.
- Webhook `X-Telegram-Bot-Api-Secret-Token` ilə qorunur (səhv token → 401, testlə təsdiqlənib).
- Token və ya parol təsadüfən commit olunsa: **əvvəlcə dəyişdirin** (BotFather `/revoke`, Travelpayouts-da yeni token), sonra git tarixçəsindən silin. Yalnız tarixçədən silmək kifayət deyil.
- İstifadəçi məlumatı minimaldır (Telegram ID, dil, valyuta, izləmələr); `/delete` hamısını silir.

## İş axışı və versiyalar

```bash
make install && make test && make lint     # dəyişiklikdən əvvəl/sonra
git switch -c feature/<ad>                 # kiçik dəyişikliklər birbaşa main-ə də ola bilər (tək developer)
git commit -am "..." && git push
git tag -a v0.3.0 -m "v0.3.0" && git push --tags   # buraxılış; CHANGELOG.md-ni yeniləyin
```
CI (`.github/workflows/ci.yml`) hər push-da lint + testləri real Postgres/Redis ilə işlədir. Dependabot həftəlik asılılıq yeniləmələri açır.
Serverdə yeniləmə: `./scripts/update.sh`. Sxem dəyişəndə yeni miqrasiya: `make revision m="təsvir"` və **əl ilə yoxlayın**.

## Struktur

```
src/flightbot/
  core/        # biznes məntiqi: watch_key, alert_engine, schedule, quiet, pricing, plans, users, watches
  providers/   # provayder interfeysi, Travelpayouts, Fake, keş/rate-limit sarğıları, places, names
  workers/     # poller, broadcaster, janitor
  bot/         # aiogram: handlers (flow mühərriki), keyboards, middlewares, i18n, render
  db/          # modellər, session
migrations/    # Alembic (trigger-lər və seed daxil)
scripts/       # install.sh, update.sh, loadtest.py
deploy/        # Prometheus, alert qaydaları, Caddyfile
docs/          # spesifikasiya, arxitektura, ADR-lər, runbook, deploy, launch checklist, roadmap
```

## Sənədlər

| Sənəd | Nə üçün |
|---|---|
| [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) | Məhsul qaydaları, planlar, bildiriş məntiqi |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Komponentlər, axınlar, dəyişməzlər, uğursuzluq rejimləri |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Arxitektura qərarları (ADR) və səbəbləri |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Runbook: metrika, xəbərdarlıq, hadisə ssenariləri, backup |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | GitHub (qapalı) və Linux server quraşdırması |
| [`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md) | Buraxılışdan əvvəl real tokenlə yoxlanmalı şeylər |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Növbəti addımlar, bilinən məhdudiyyətlər |

## Nəyin yoxlanıb, nəyin yoxlanmadığı

**Yoxlanıb:** real Postgres/Redis ilə avtomatik testlər, yük testi, real worker prosesi, `install.sh` (Docker-siz dry-run rejimində).
**Yoxlanmayıb:** real Telegram ilə işləmə, real Travelpayouts cavabları (adapter yalnız saxta HTTP ilə sınanıb; xüsusən "hər yerə"
sorğusu və `cities.json` formatı), Docker/compose işə salınması, `deploy.yml`, Telegram Stars ödənişi (yoxdur).
Buraxılışdan əvvəl [`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md)-i keçin.
