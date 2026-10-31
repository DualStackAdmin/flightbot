# Buraxılışdan əvvəl yoxlama siyahısı

Bu layihədə hər şey real Postgres/Redis-ə qarşı test olunub, amma aşağıdakılar **real hesab/token tələb edir** və hələ yoxlanmayıb.

## 1. Travelpayouts (ən vacib, adapter yalnız saxta HTTP ilə sınanıb)
- [ ] Real tokenlə bir sorğu: `PROVIDER=travelpayouts` və `/search`. Cavab sahələri (`departure_at`, `price`, `airline`, `transfers`, `link`, `currency`) gözlənildiyi kimidirmi? (`providers/travelpayouts.py::parse_offers`)
- [ ] `departure_at=YYYY-MM` (ay sorğusu) və `return_at=YYYY-MM` real olaraq işləyirmi, yoxsa ay rejimi başqa cür sorğu tələb edir?
- [ ] AZN valyutası dəstəklənirmi? Dəstəklənmirsə `SUPPORTED_CURRENCIES`-dən çıxarın və ya çevirmə əlavə edin.
- [ ] Rəsmi sorğu limitləri və `PROVIDER_RPS` dəyəri. Data API-nin keş yaşı (bildirişdəki "keşlənmiş data" qeydi həqiqətə uyğundurmu).
- [ ] Partnyor şərtləri: keşləmə/göstərmə qaydaları, real vaxtlı Search API üçün ayrıca təsdiq lazımdırmı.
- [ ] `link` sahəsinin domeni/prefiksi və **marker formatı**: `core/affiliate.py` `marker=<MARKER>.<SUB_ID>` istifadə edir. Komissiyanın düzgün izləndiyini bir test sifarişi ilə təsdiqləyin.
- [ ] `autocomplete` cavab formatı (`providers/places.py`); xəta olsa statik siyahıya düşür.

## 2. Telegram
- [ ] BotFather-də bot yaradın; `BOT_TOKEN`. Əmrlər başlanğıcda avtomatik təyin olunur (az/ru/en).
- [ ] Webhook: HTTPS domen (Caddy profili), `WEBHOOK_SECRET` uzun təsadüfi sətir. Secret yoxlaması test olunub (səhv token → 401).
- [ ] Real axın: `/start` → `/new` → bildiriş → 👍/👎 → botu blokla → `/start`. (Bot hələ real Telegram ilə işlədilməyib.)
- [ ] Ödəniş: Telegram rəqəmsal xidmətlər üçün Stars tələb edir. Pro-nu satmazdan əvvəl rəsmi qaydaları yoxlayın (Stars hələ yazılmayıb).
- [ ] Zirvə yükündə Telegram-ın ödənişli yayım seçimi (30 msg/s-dən yuxarı) mövcuddur; lazım olsa ayrıca dəyərləndirin.

## 3. Hüquqi və məxfilik
- [ ] Məxfilik siyasəti və istifadə şərtləri (bot təsvirində/`/help`-də link).
- [ ] Saxlanılan data: Telegram ID, dil, valyuta, izləmələr, bildirişlər. `/delete` mövcuddur və test olunub.
- [ ] Yerli şəxsi məlumat qanunu / Avropa istifadəçiləri üçün GDPR tələblərinin yoxlanması (hüquqşünasla).
- [ ] Affiliate açıqlaması: bildirişlərdəki linklər partnyor linkidir.

## 4. Əməliyyat
- [ ] Postgres backup/PITR işləyir və bərpa bir dəfə sınanıb.
- [ ] `.env` gizlidir, `POSTGRES_PASSWORD` dəyişdirilib, `ENV=prod`.
- [ ] `SENTRY_DSN` və Alertmanager (və ya digər xəbərdarlıq kanalı) qoşulub. `deploy/alerts.yml` tək başına xəbər göndərmir.
- [ ] `docker compose` real serverdə bir dəfə qaldırılıb (burada Docker işlədilməyib).
- [ ] Server resursu: 1 vCPU/2 GB ilk mərhələ üçün yetərlidir (yük testi 1 CPU-da edilib), amma real provayder gecikməsi ilə yenidən ölçün.

## 5. Keyfiyyət (ilk 2 həftə, qapalı beta)
- [ ] 20-50 istifadəçi, `python -m flightbot.cli stats` hər gün.
- [ ] Hədəflər: 👎 < 10%, bloklama < 5%, `telegram retry_after` = 0, queue lag < 60 san.
- [ ] Bildirişlərin real "alına bilən" qiymətə uyğunluğunu əl ilə yoxlayın (keş qiyməti saytda fərqli ola bilər).

## 6. Yeni funksiyalar üçün əlavə yoxlamalar (v0.2)
- [ ] **Marker:** `794979` Travelpayouts kabinetində "Partner ID / marker" kimi görünür? (referal proqramı kodu deyil). Bir test klikindən sonra statistikada `sub_id` ilə görünür?
- [ ] **"Hər yerə" (`explore`)**: real tokenlə `prices_for_dates` sorğusu `destination` verilmədən və `unique=true` ilə hər istiqamətdən yalnız ən ucuz bileti qaytarır? (`providers/travelpayouts.py::explore`). Qaytarmırsa sorğu başqa endpoint-ə keçirilməlidir.
- [ ] **Ad həlli:** `https://api.travelpayouts.com/data/en/cities.json` açıq və `code`, `name`, `country_code` sahələrini qaytarır? (Əks halda dünya şəhərləri kod kimi görünür, sistem sınmır.)
- [ ] **Sakit saatlar:** real telefonda gecə vaxtı bildirişin səhərə saxlandığını bir dəfə yoxlayın; hədəf auditoriya başqa saat qurşağındadırsa `QUIET_TZ`.
- [ ] **Hədəf düymələri:** −15% tövsiyəsi real qiymət paylanmasında məntiqlidir? Rəy və yaradılan izləmə hədəflərinə baxıb tənzimləyin (`bot/parsing.py::quick_targets`).
- [ ] **Azərbaycan mətnləri:** doğma danışan biri bütün `bot/i18n/az.py` mətnlərini oxuyub tonu ("siz", sözlər) düzəltməlidir.
- [ ] **5 real adamla sınaq:** heç nə izah etmədən telefonda ilk izləməni yaratmalarını izləyin; haradan ilişdiklərini yazın.
- [ ] **GitHub/Linux:** `install.sh` təmiz Ubuntu serverində bir dəfə işlədilsin; `update.sh` və (istifadə edirsinizsə) `deploy.yml` sınansın.
