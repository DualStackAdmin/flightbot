# Məhsul spesifikasiyası (v0.2, icra vəziyyəti ilə)

**Kimin üçün:** Bakıdan və regiondan ucuz bilet axtaranlar. Dillər: az (Telegram dilinə görə təxmin, default az), ru, en. Valyuta: USD, AZN, EUR.

## UX prinsipləri
1. İlk izləmə 60 saniyədən az: standart axın **3 toxunuşdur** (haraya → ay → hədəf).
2. Hər mesajın növbəti addımı (düymə) var. Dead-end yoxdur.
3. Bot heç vaxt susmur (axından kənar mətn, naməlum əmr, stiker, köhnəlmiş düymə).
4. Düymə > yazmaq (mobil). Ağıllı defoltlar: haradan = ev şəhəri, rejim = ay üzrə, tək istiqamət.
5. Dürüstlük: keşlənmiş data qeydi, partnyor link açıqlaması, saxta təcililik yoxdur.

## Ssenarilər
| Ssenari | Vəziyyət |
|---|---|
| `/start`: dil təxmin olunur, dərhal populyar istiqamət düymələri (dil sualı yoxdur) | ✅ |
| `/new`: haraya → ay → hədəf (3 toxunuş); "📅 Dəqiq tarix", "⚙️ Ətraflı" (gediş-gəliş, birbaşa) isteğe bağlı | ✅ |
| Hər addımda Geri / Ləğv; callback keçidləri eyni mesajı redaktə edir | ✅ |
| Hədəf addımı: hazırkı qiymət, 90 gün median (varsa), ⭐ tövsiyə −15%, −10%, −25%; hədəf artıq ödənibsə xəbərdarlıq | ✅ |
| Yaratdıqdan sonra: hazırkı qiymət, "➕ Başqa marşrut", "📋 İzləmələrim" | ✅ |
| **🌍 Hər yerə (`/explore`)**: ay seçimi → o ay üzrə ən ucuz 10 istiqamət (bayraq, qiymət) → detal (bilet linki + "xəbər ver") | ✅ (real cavab formatı yoxlanmalıdır) |
| `/search`: marşrut üzrə ayın ən ucuz 5 günü → "xəbər ver" | ✅ |
| Fallback: "İstanbul", "Bakı Dubay", "GYD-IST" yazmaq birbaşa ay addımına aparır | ✅ |
| `/list`: dayandır, davam et, **hədəfi dəyiş**, sil | ✅ |
| Bildiriş düymələri: ⏸ Dayandır, 🎯 Hədəfi dəyiş, 👍/👎 | ✅ |
| `/settings`: dil, valyuta, **ev şəhəri**, **sakit saatlar** | ✅ |
| `/delete` | ✅ |
| "Bu həftəsonu" sürətli seçimi | ❌ buraxıldı: dəqiq tarixli sorğular Data API keşində seyrəkdir; ay rejimi daha etibarlıdır |
| "Növbəti N gün" rejimi | ❌ çıxarıldı: bir izləmə = bir API sorğusu qaydasını pozur ("ay üzrə" əvəz edir) |

## Bildiriş qaydaları (hamısı `core/alert_engine.py`-da, testlərlə)
- **Trigger:** qiymət ≤ hədəf. **Təkrar yox:** əvvəlki bildirişdən ≥5% ucuz olmadıqca. **Re-arm:** qiymət hədəfdən yuxarı qalxıb yenidən düşəndə. **Cooldown:** 6 saat.
- **Gündəlik limit:** Free 3, Pro 30. **Köhnə data:** 48 saatdan köhnə qiymət (provayder `found_at` verirsə) getmir.
- **Anomaliya:** median-dan 60%-dən çox aşağı qiymət (≥14 ölçmə) ikinci, keşsiz sorğu ilə təsdiqlənir; təsdiqlənməyən nə bildirişə, nə tarixçəyə düşür.
- **"Yaxşı qiymət" nişanı:** son 90 günün aşağı 20%-i (≥14 ölçmə).
- **Sakit saatlar:** 23:00-08:00 (Bakı) arasında yaranan bildiriş outbox-a yazılır, səhər 08:00-dan sonra (0-15 dəq jitter) göndərilir. İstifadəçi `/settings`-dən söndürə bilər.
- Mətndə həmişə: qiymət keşlənmiş datadır, saytda dəyişə bilər.

## Planlar
| | Free | Pro |
|---|---|---|
| Aktiv izləmə | 3 | 25 |
| Yoxlama tezliyi | ~3-24 saat (qalxışa qalan vaxta görə) | ~1-6 saat |
| Bildiriş prioriteti | normal | əvvəl |
| Gündəlik bildiriş | 3 | 30 |

**Dəyişiklik (v0.1-dən):** "1 çevik (ay üzrə) izləmə" Free limiti **götürüldü**. Default rejim ay üzrə olduğu üçün o limit "3 izləmə" vədini pozurdu. Mexanizm kodda qalır (`PlanLimits.max_flexible_watches`).
Pro hələlik `flightbot.cli grant-pro` ilə verilir (ödəniş yoxdur).

## Gəlir
1. **Affiliate:** hər bilet linki `marker=794979.<sub_id>` daşıyır (`TRAVELPAYOUTS_MARKER`). Bildirişdə `sub_id=n<id>`, explore-da `x<user_id>`. **794979-un Travelpayouts partnyor ID-si (marker) olduğunu kabinetdə təsdiqləyin:** "referal proqramı" kodu ilə marker fərqli şeylərdir, səhv olsa komissiya yazılmır.
2. Pro plan, Telegram Stars ilə (hələ yazılmayıb), ~500 aktiv istifadəçidən sonra.

## Uğur ölçüləri
`python -m flightbot.cli stats`: aktiv istifadəçilər, 7 gün aktivlik, 👎 faizi (hədəf <10%), bloklama faizi.
Prometheus: `notification_queue_lag_seconds`, `telegram_errors_total{type="retry_after"}` (hədəf 0), `due_watch_keys`.
**Hələ ölçülmür:** `/start` → ilk izləmə huni və ilk izləməyə qədər vaxt (hadisə izləməsi əlavə olunmalıdır).
