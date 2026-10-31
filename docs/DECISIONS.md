# Arxitektura qərarları (ADR)

## ADR-001: Mikroservis yox, modulyar monolit
**Kontekst:** Bir nəfərlik/kiçik komanda, 1-20 min istifadəçi hədəfi.
**Qərar:** Bir kod bazası: `core` (biznes məntiqi), `providers`, `workers`, `bot`. Telegram yalnız bir adapterdir.
**Nəticə:** Sonradan veb panel/Mini App eyni `core`-u istifadə edə bilər. Ayrı servisə bölmək lazım olsa, sərhədlər hazırdır.

## ADR-002: Növbə = Postgres (`SKIP LOCKED`), Celery/Taskiq yox
**Kontekst:** İş vahidləri: "vaxtı çatmış watch_key" və "göndərilməli bildiriş". Hər ikisi onsuz da Postgres sətridir.
**Qərar:** Claim sorğusu `FOR UPDATE SKIP LOCKED` + `lease_until`. Ayrıca broker yoxdur.
**Nəticə:** (+) sadə, durable, tranzaksiyalı, Redis outage-ı növbəni təsir etmir; replikalar təhlükəsizdir. (−) çox yüksək ötürmə (yüz minlərlə iş/saniyə) üçün uyğun deyil. Yük testi: claim sorğusu 300 min sətirdə 0.14 ms. Lazım olsa Taskiq sonradan əlavə olunar.

## ADR-003: Dedup vahidi `watch_key`
**Qərar:** Provayderə sorğu abunəliyə yox, imzaya görə gedir; çevik tarixdə "bir ay = bir sorğu".
**Nəticə:** 21× azalma (yük testi). Qiymət: istifadəçi-spesifik filtrlər (aviaşirkət, baqaj) imzaya daxil edilməlidir (hələ yoxdur) və ya post-filtr olmalıdır. "Növbəti N gün" rejimi bu səbəbdən çıxarıldı.

## ADR-004: Outbox Postgres-dədir
**Qərar:** Poller bildirişi state ilə eyni tranzaksiyada yazır, broadcaster ayrıca göndərir.
**Nəticə:** Redis itkisi bildirişi silmir, at-least-once çatdırılma, retry/backoff/audit cədvəldədir. Əvvəlki dizayndakı Redis siyahısı eviction ilə itə bilərdi.

## ADR-005: Redis yalnız uçucu data üçün
**Qərar:** FSM, provayder keşi, rate limit bucket-ları. `maxmemory-policy volatile-lru`, bütün açarlar TTL-lidir. Məntiqi DB-lər (0/1/2) ayrılmadı: eyni yaddaşı və eviction siyasətini paylaşırlar, ona görə faydasızdır.

## ADR-006: Sayğac DB trigger-i ilə
**Qərar:** `active_watch_count` `watches` üzərindəki trigger-lərlə yenilənir; janitor drift yoxlayır.
**Nəticə:** tətbiq kodunda unudulma/sürüşmə riski yoxdur (əvvəlki dizaynda bu real problem idi).

## ADR-007: Provayder interfeysi
**Qərar:** `PriceProvider.offers()` yeganə sərhəddir; Cached → RateLimited → Raw sarğıları.
**Nəticə:** İkinci provayder əlavə etmək = bir adapter. Tək provayderə asılılıq biznes riskidir; bu riski azaldır, aradan qaldırmır.

## ADR-008: Paylanmış rate limit (Redis Lua token bucket)
**Qərar:** Telegram qlobal/istifadəçi limiti və provayder RPS bütün replikalar üçün Redis-də, vaxt Redis serverindən (`TIME`).
**Nəticə:** `aiolimiter` kimi proses daxili limiterin "N replika = N × limit" problemi yoxdur.

## ADR-009: Ödəniş Telegram Stars ilə (planlaşdırılıb)
Telegram rəqəmsal məhsullar üçün Stars tələb edir (rəsmi qaydanı buraxılışdan əvvəl yoxlayın). Stripe əsas yol kimi nəzərdə tutulmayıb.

## ADR-010: Default izləmə rejimi "ay üzrə", axın 3 toxunuş
**Kontekst:** 7-8 addımlı axında istifadəçilər addımlarda itirdi; dəqiq tarixi çoxları bilmir; dəqiq tarixli sorğular Data API keşində seyrəkdir.
**Qərar:** Standart axın haraya → ay → hədəf. Haradan = ev şəhəri, tək istiqamət, birbaşa=yox. Qalanı "Ətraflı"/"Dəqiq tarix" altındadır. Addım mühərriki (`bot/handlers/flow.py`) hər addımda Geri/Ləğv verir (tarixçə FSM-dədir).
**Nəticə:** (+) daha yüksək aktivləşdirmə, ay rejimi dedup üçün idealdır (bir ay = bir sorğu). (−) Free planın ayrıca "çevik izləmə" limiti mənasızlaşdı və götürüldü.

## ADR-011: "Hər yerə" provayder interfeysinin hissəsidir, keşlənir
`PriceProvider.explore()` ay üzrə ən ucuz istiqamətləri qaytarır; nəticə 1 saat keşlənir (singleflight ilə), beləliklə viral anda eyni sorğu bir dəfə gedir. Dünya şəhərlərinin adları statik siyahı + açıq `cities.json` (Redis-də 7 gün) ilə həll olunur; uğursuz olsa kod göstərilir.

## ADR-012: Sakit saatlar poller-də (göndərmədə yox)
Bildiriş `available_at` ilə outbox-a yazılır; broadcaster dəyişməyib. Üstünlük: broadcaster sadə qalır, növbə gecikməsi metrikası yalnız "vaxtı çatmış" bildirişləri sayır. Çatışmazlıq: səhər çatdırılanda qiymət dəyişmiş ola bilər (bildirişdə qeyd olunur).
