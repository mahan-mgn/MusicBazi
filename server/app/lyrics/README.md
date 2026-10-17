# استخراجِ چندمنبعیِ متنِ آهنگ

معماری، فهرستِ منابع، تنظیمات و قراردادِ API. **هیچ ادعایی در این سند دربارهٔ
کارکردِ زندهٔ هیچ منبعی نیست** — همه‌چیز از کد و تست‌های mock می‌آید.

---

## معماری

```
GET /api/stream/lyrics                 (main.py)
   ├─ بدونِ provider → stream_cache.get_or_fetch_lyrics(track)
   │     کشِ دیسک: STREAM_CACHE_DIR/<cache_key_for(id)>.lrc
   │     → lyrics_manager.fetch(track)   ← زنجیرهٔ خودکار
   └─ با provider → lyrics_sources.fetch_from(name, track, force=)
         فقط همان منبع، کشِ حافظه، بدونِ لمسِ کشِ دیسک
```

### لایه‌ها

| ماژول | نقش |
|---|---|
| `models.py` | `Lyrics`/`LyricLine`/`LyricWord` مشترک |
| `registry.py` | `ProviderEntry`، `ProviderRegistry`، `CircuitBreaker` |
| `manager.py` | زنجیرهٔ خودکار + کشِ منفی |
| `matching.py` | تطبیقِ عنوان/هنرمند/مدت + تشخیصِ تکراری |
| `parsers.py` | LRC خطی، Enhanced LRC، TTML |
| `sources.py` | فهرستِ منابع و واکشیِ تک‌منبعی |

### تفکیکِ خطا (قراردادِ همهٔ Providerها)

- `fetch_strict(title, artist, album, duration_ms, *, video_id=None, isrc=None)`
- `ProviderError(kind="network"|"http"|"body")` = «نمی‌دانم» → **کشِ منفی نمی‌گیرد**
- `None` = «ندارم» (۲۰۰ خالی، یا ۴۰۴ِ مستند) → کشِ منفیِ کوتاه
- هر Provider یک `fetch` عمومی هم دارد: هر خطا → `None`

### کش

| نوع | محل | عمر |
|---|---|---|
| نتیجهٔ زنجیرهٔ خودکار | `<STREAM_CACHE_DIR>/<key>.lrc` | دائمی تا پاک‌شدن |
| کشِ منفیِ زنجیره | حافظه (`LYRICS_MISS_TTL_S`) | ۳۰۰ ثانیه |
| نتیجهٔ Provider-محور | حافظه (`sources._cache`) | موفق: دائمی؛ خالی: TTL؛ خطا: هرگز |
| ترجیحِ کاربر | SQLite `lyrics_preferences` | دائمی |

### قطع‌کنندهٔ مدار

`LYRICS_BREAKER_THRESHOLD` خطای **پیاپی** → `LYRICS_BREAKER_COOLDOWN_S` ثانیه
کنار. برای `lrclib` و `genius` پیش‌فرض **خاموش** است تا رفتارِ قبل از افزودنش
حفظ شود؛ با `MUSICBAZI_LYRICS_BREAKER_<NAME>_ENABLED=1` روشن می‌شود.

---

## منابع

| منبع | زنجیرهٔ خودکار | قابلِ انتخاب | وضعیت | یادداشت |
|---|---|---|---|---|
| `lrclib` | ✅ | ✅ | DONE | عمومی، MIT |
| `genius` | ❌ | با توکن | DONE | **شرایط استفاده scraping را ممنوع می‌کند**؛ `manual_only` |
| `musixmatch` | ❌ | با کلید | نیازمند راه‌اندازی | فقط APIِ رسمی؛ متنِ همگام نیازمندِ پلنِ تجاری |
| `lyricsplus` | ❌ | ✅ | DONE | Apache-2.0 |
| `unison` | ❌ | ✅ | DONE | AGPL-3.0؛ استفادهٔ تجاریِ داده مجوز می‌خواهد |
| `betterlyrics` | ❌ | ✅ | آزمایشی | بخشی از قرارداد استنباطی |
| `binilyrics` | ❌ | ✅ | DONE | LICENSE/terms عمومی ندارد |
| `lrc_red` | ❌ | ✅ | آزمایشی | قرارداد از کلاینتِ ثالث (PARTIAL) |
| `simpmusic` | ❌ | ✅ | DONE | کلیدش `videoId` است |
| `paxsenix` | ❌ | ✅ | آزمایشی | فقط از OpenAPI؛ شرایط استفاده ندارد |
| `kugou` | — | ❌ | **PROHIBITED** | نیازمندِ جعلِ هویتِ اپِ موبایل — کد ندارد |
| `megalobiz` | — | ❌ | **PROHIBITED** | `robots.txt` این کلاینت را کل‌سایت می‌بندد — کد ندارد |

**همهٔ منابعِ قابلِ استفاده به‌جز `lrclib` پیش‌فرض خاموش‌اند** و فقط با env
روشن می‌شوند. زنجیرهٔ خودکار پیش‌فرض: `lrclib`.

### افزودنِ Providerِ جدید

۱. `providers/<name>.py` با الگوی `fetch_strict` + `fetch` + `_error_from`.
۲. تطبیقِ `matching.py` **قبل** از پذیرش — مگر Provider با شناسهٔ یکتا کار کند
   و پاسخش عنوان برنگرداند (مثل `simpmusic`/`paxsenix`)؛ آن حالت را کامنت کن.
۳. ثبت در `manager._PROVIDERS` با `default_enabled=False`، `label`،
   `capabilities`، `terms_note`.
۴. اگر قراردادش کامل تأیید نشده: `experimental=True`.
۵. تستِ mock در سطح HTTP: موفقیت، خالی، ۴۰۴/۴۲۹/۵xx/Timeout، بدنهٔ نامعتبر،
   تطبیقِ اشتباهِ مدت، نبودِ کلید، نشتِ توکن، ادامه به Providerِ بعدی.

---

## تنظیمات (env)

| کلید | پیش‌فرض | کار |
|---|---|---|
| `MUSICBAZI_LYRICS` | on | کلِ قابلیت |
| `MUSICBAZI_LYRICS_PROVIDERS_ORDER` | `lrclib,genius` | ترتیب |
| `MUSICBAZI_LYRICS_PROVIDER_<NAME>_ENABLED` | — | kill-switch |
| `MUSICBAZI_LYRICS_GENIUS_POLICY` | `manual_only` | `keep_auto` برمی‌گرداند |
| `MUSICBAZI_LYRICS_ENHANCED_LRC` | **off** | تگِ کلمه در خروجی |
| `MUSICBAZI_LYRICS_MISS_TTL` | 300 | کشِ منفی (s) |
| `MUSICBAZI_LYRICS_BREAKER_THRESHOLD` / `_COOLDOWN_S` | 3 / 120 | قطع‌کننده |
| `MUSICBAZI_GENIUS_ACCESS_TOKEN` | — | Genius |
| `MUSICBAZI_MUSIXMATCH_API_KEY` | — | Musixmatch |

---

## قراردادِ API

| متد | مسیر | نکته |
|---|---|---|
| GET | `/api/stream/lyrics` | **بدونِ `provider` = رفتارِ اصلی، بی‌تغییر** |
| GET | `/api/lyrics/sources` | **صفر درخواست به Providerها** |
| GET/PUT/DELETE | `/api/lyrics/preference` | ترجیحِ هر آهنگ (`provider=""` = خودکار) |

`/api/stream/lyrics?provider=X` : ۲۰۰ (+`x-lyrics-source`) · ۴۰۴ ناشناخته/ندارد ·
۴۰۹ پیکربندی‌نشده · ۵۰۲ خطای Provider (بدونِ جزئیاتِ حساس).

---

## UI

کنترلِ «منبعِ متن» در `src/components/LyricsSourceMenu.tsx`، کنارِ پنلِ متن در
`NowPlaying`. باز کردنش فقط `/api/lyrics/sources` را می‌خواند؛ واکشیِ متن
تنها بعد از انتخاب و برای همان یک منبع انجام می‌شود. انتخاب در سرور ذخیره
می‌شود، پس با پاک‌شدنِ دادهٔ اپ (اندروید/Capacitor) از دست نمی‌رود.
