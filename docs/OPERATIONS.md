# Əməliyyat təlimatı (runbook)

## Komponentlər və miqyas
| Komponent | Replika | Qeyd |
|---|---|---|
| bot | webhook: N (load balancer arxasında); polling: **1** | polling-də iki replika `getUpdates` konfliktinə düşür |
| worker | N | `docker compose up -d --scale worker=3`; poller/broadcaster/janitor SKIP LOCKED ilə təhlükəsizdir |
| postgres | 1 (+ backup/PITR) | bağlantılar çoxalsa PgBouncer (transaction mode) + `DB_STATEMENT_CACHE_SIZE=0` |
| redis | 1 | itsə FSM və limit bucket-ları sıfırlanır, bildirişlər itmir |

Broadcaster replikaları Telegram limitini bölüşür (Redis bucket), replika əlavə etmək limiti artırmır: ötürmə tavanı `TELEGRAM_GLOBAL_RPS`-dir.

## Buraxılış və miqrasiya
```bash
docker compose build && docker compose up -d   # migrate servisi `alembic upgrade head` işlədir, sonra bot/worker qalxır
```
Yeni miqrasiya: `make revision m="təsvir"`, sonra **əl ilə yoxlayın** (trigger, partial index). Testlərdəki `test_migration_matches_models` model/miqrasiya drift-ini tutur. Geri qayıtma: `alembic downgrade -1` (ilk miqrasiya üçün downgrade test olunub).

## Metrika və xəbərdarlıqlar
`bot:9100/metrics`, `worker:9100/metrics`. Qaydalar: `deploy/alerts.yml` (Alertmanager qoşulmayıb).

| Siqnal | Hədd | İlk baxış |
|---|---|---|
| `notification_queue_lag_seconds` | > 300 san | broadcaster işləyirmi? `telegram_errors_total{type="retry_after"}`; Telegram limiti çatır? |
| `telegram_errors_total{type="retry_after"}` | hədəf 0 | `TELEGRAM_GLOBAL_RPS`-i azaldın, tək bot tokeni üçün başqa proses göndərirmi? |
| `due_watch_keys` | > 500 uzun müddət | provayder RPS və ya poller replikası çatmır |
| `provider_requests_total{status!="ok"}` | > 20% | provayder statusu, token, kvota |
| `active_watch_count_drift_total` | > 0 | trigger-lər mövcuddur? (baş verməməlidir) |

Qeyd: orijinal planda "keş vurma >85%" hədəfi var idi. Burada əsas qənaət keşdən yox, `watch_key` dedup-dan gəlir (poller interval ≥ keş TTL), ona görə keş nisbəti ikinci dərəcəli göstəricidir və xəbərdarlıq qoyulmayıb.

## Hadisə ssenariləri
- **Provayder düşüb:** heç nə etmək lazım deyil: açarlar backoff-la gözləyir, istifadəçilər `/search` zamanı "xidmət cavab vermir" görür. Uzun sürərsə status elan edin.
- **Telegram flood:** broadcaster özü pauza edir. Təkrarlanırsa limiti azaldın və başqa prosesin eyni tokenlə yazıb-yazmadığına baxın.
- **Redis düşüb:** bot FSM işləmir (istifadəçilər axını yenidən başlayır), worker-lər gözləyir. Redis qayıdanda hər şey davam edir. Əlavə əməliyyat lazım deyil.
- **Bildirişlər çox gedir/şikayət:** `python -m flightbot.cli stats` (👎 faizi). Qaydaları `core/alert_engine.py`-da sərtləşdirin (cooldown, 5% qaydası).
- **Kütləvi bloklama:** `users_blocked` artırsa, bildiriş tezliyi/keyfiyyətinə baxın.
- **İstifadəçi pulsuz plandan yuxarı istəyir:** `python -m flightbot.cli grant-pro <telegram_id> --days 30`.

## Backup
Yalnız Postgres vacibdir (`pg_dump` cədvəli və ya idarə olunan xidmətdə PITR). Redis-i backup etməyə ehtiyac yoxdur.

## Məlumat saxlama
Janitor (saatlıq): vaxtı keçmiş izləmələri `expired` edir, 30 gündən köhnə bitmiş bildirişləri və 400 gündən köhnə qiymət tarixçəsini silir, istinadsız köhnə açarları təmizləyir. `/delete` istifadəçinin bütün datasını silir.
