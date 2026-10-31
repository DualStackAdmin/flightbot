# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versiyalar: [SemVer](https://semver.org/) (0.x = qapalı beta öncəsi).

## [0.2.0]
### Əlavə edildi
- **3 toxunuşluq axın:** haraya → ay → hədəf. Haradan = ev şəhəri, default tək istiqamət; "Dəqiq tarix" və "Ətraflı" (gediş-gəliş, birbaşa) ayrıca düymələrlə.
- **🌍 Hər yerə (`/explore`):** ay üzrə dünyada ən ucuz istiqamətlər, bilet linki, "xəbər ver"; şəhər adları statik siyahı + `cities.json`.
- **Geri / Ləğv** hər addımda, mesajların yerində redaktəsi.
- **Fallback:** "İstanbul" / "Bakı Dubay" yazmaq birbaşa axına keçir; bot heç vaxt cavabsız qalmır.
- Hədəf qiymət köməyi: hazırkı qiymət, 90 günlük median, ⭐ tövsiyə −15%, "artıq ödənib" xəbərdarlığı.
- Bildiriş düymələri: ⏸ Dayandır, 🎯 Hədəfi dəyiş; `/list`-də 🎯 Dəyiş.
- **Sakit saatlar** (23:00-08:00 Bakı), `/settings`-dən söndürülür; ev şəhəri ayarı.
- Affiliate marker `794979` (sub_id izləməsi); `/delete`; admin CLI; `install.sh`, `update.sh`, `deploy.yml`, Dependabot.
### Dəyişdi
- Free planda ayrıca "1 çevik izləmə" limiti götürüldü (default rejim ay üzrədir).
- Provayder keşi ümumiləşdirildi (explore üçün də singleflight).
### Düzəldildi
- Redis düşəndə bildirişlərin cəhd sayı yandırılması; poller uğursuzluq sayğacı şişməsi.
- Hədəf qiymətin saat formatı (08:00).

## [0.1.0]
- İlk versiya: dedup (`watch_keys`), outbox, alert mühərriki, poller/broadcaster/janitor, bot (az/ru/en), `/search`, Docker/CI, yük testi.
### Düzəldildi (testlərin tutduğu)
- Gündəlik limit race-i; asyncpg `AmbiguousParameterError`; bildiriş state-machine boşluğu; `parse_price("-5")`.
