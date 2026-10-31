# Yol xəritəsi

## Bitib (v0.2)
Dedup, outbox, alert mühərriki, poller/broadcaster/janitor, bot (az/ru/en), 3 toxunuşluq axın, geri/ləğv, fallback, `/explore` (hər yerə), `/search`, hədəfi dəyişmək, bildiriş düymələri, sakit saatlar, ev şəhəri, `/delete`, admin CLI, Docker/CI/deploy skriptləri, yük testi.

## Növbəti (ən yüksək təsirdən aşağıya)
1. **Real tokenlərlə doğrulama** (`LAUNCH_CHECKLIST.md`), adapterin düzəldilməsi.
2. **Qapalı beta** və bildiriş keyfiyyətinin ölçülməsi (👎 faizi).
3. **Hadisə izləməsi (huni):** `/start` → ilk izləmə → bildiriş kliki; `acquisition_source` + deep link.
3b. **Affiliate klik izləməsi:** öz redirect servisi (`/r/<notification_id>`), klik və konversiya statistikası.
4. **Telegram Stars ilə Pro:** `payments` cədvəli, `pre_checkout_query`/`successful_payment` handler-ləri, müddət bitəndə xəbərdarlıq.
5. "Ən ucuz qiymət qrafiki" (Pro), `/list` səhifələməsi, vaxtı keçmiş izləmə üçün "yeni tarix?" təklifi.
6. **Böyümə:** deal kanalına avtomatik post, referral, Telegram Mini App / veb panel.
7. **Filtrlər:** aviaşirkət, baqaj, sərnişin sayı (imza və dedup dizaynına təsir edir, ADR-003).
8. **İkinci provayder adapteri** (risk azaldılması).
9. **B2B / white-label:** `tenant_id` sxemdə var; hər tenant üçün bot tokeni, marker və RLS.
10. Dil: türk dili; sakit saatlar (istifadəçi saat qurşağı).

## Bilinən məhdudiyyətlər
- Çatdırılma at-least-once (nadir dublikat mümkündür, ARCHITECTURE.md).
- Poller hər abunəçi üçün ayrıca INSERT edir; yüz minlərlə abunəçi/açar olarsa toplu INSERT-ə keçid lazımdır.
- `price_points` partisiyalanmayıb (400 günlük saxlama ilə kifayətdir; böyüyəndə partisiya və ya TimescaleDB).
- Bot polling rejimində tək replika işləməlidir.
