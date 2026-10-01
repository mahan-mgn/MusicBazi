# موزیک بازی روی Railway

راه‌اندازی این‌جا با `Dockerfile.railway` انجام می‌شود — **یک سرویس، یک کانتینر**:
nginx (فرانت + پروکسی `/api`) + uvicorn + سرور PO Token هر سه داخل یک کانتینر،
با `deploy/railway-entrypoint.sh` به‌عنوان supervisor. چرا تک‌کانتینر: اپ
تک‌مبدأ ساخته شده و Railway هم Volume را فقط به یک سرویس می‌چسباند.

> **قبل از شروع، دو واقعیت را بدانی:**
> 1. **Railway رایگانِ دائمی نیست.** Trial = ۵ دلار اعتبار یک‌بار‌مصرف برای ۳۰ روز
>    (بدون کارت). بعدش Hobby = ۵ دلار/ماه. Volume روی Trial سقف ۵۰۰MB دارد،
>    روی Hobby ۵GB (و ۰.۱۵ دلار/GB/ماه). کتابخانه + کاورها + دانلودها رشد می‌کنند.
> 2. **یوتیوب از آی‌پی دیتاسنتر سخت‌تر بات تشخیص می‌دهد.** PO Token و کوکی در
>    همین کانتینر هست، ولی دانلود یوتیوب را **همان روز اول** تست کن.
>    کاتالوگ‌ها (SoundCloud/Spotify/Apple/Deezer) معمولاً بی‌مشکل‌اند.

## ۱ — اکانت و پروژه

```bash
npm i -g @railway/cli      # یک‌بار
railway login              # مرورگر باز می‌شود؛ با GitHub لاگین کن
railway init               # نام پروژه: musicbazi
```

یا از داشبورد: https://railway.com → New Project → Empty.

## ۲ — سرویس از روی GitHub

1. مخزن `mahan-mgn/MusicBazi` را به پروژه وصل کن (Deploy from GitHub repo).
   Railway خودش `railway.json` را می‌بیند و `Dockerfile.railway` را بیلد می‌کند.
2. **اسم سرویس را حتماً `musicbazi` بگذار** — بعداً به آن Volume می‌چسبد.
3. اولین بیلد ~۵-۸ دقیقه (ffmpeg + librosa + بیلد bgutil). صبر کن سبز شود.

اگر از CLI دیپلوی می‌کنی (بدون GitHub): `railway up` داخل پوشه ریپو.

## ۳ — Volume (دیتابیس + دانلودها این‌جا می‌مانند)

داشبورد → سرویس `musicbazi` → تب **Volumes** → Attach Volume:

| تنظیم | مقدار |
|---|---|
| Mount Path | `/data` |

بدون این، کتابخانه/آمار/کوکی/کلیدها با هر دیپلوی می‌پرند.
سقف Trial (۵۰۰MB) برای شروعِ خالی کافی است؛ برای استفاده‌ی جدی Hobby لازم است.

## ۴ — متغیرهای محیطی

همه **اختیاری‌اند** — ویزاردِ راه‌اندازی داخل خودِ اپ (`/?setup=1`) هرکدام را
بخواهی می‌پرسد و روی Volume ذخیره می‌کند (ماندگار). اگر ترجیح می‌دهی از
داشبورد (Variables) بگذاری، همان نام‌های `.env.docker.example`:

```
MUSICBAZI_SPOTIFY_CLIENT_ID / MUSICBAZI_SPOTIFY_CLIENT_SECRET
MUSICBAZI_GEMINI_API_KEY
MUSICBAZI_ACOUSTID_KEY / MUSICBAZI_AUDD_TOKEN
MUSICBAZI_TELEGRAM_BOT_TOKEN        # بات جدا نیست؛ سرور اصلی خودش بالا می‌آوردش
```

کوکی یوتیوب: از همان ویزارد آپلودش کن → `/data/db/cookies.txt` روی Volume
می‌نشیند و باقی می‌ماند. (دست‌ورز: `MUSICBAZI_COOKIES_FILE=/data/db/cookies.txt`
خودکار ست می‌شود.)

## ۵ — دامنه

سرویس → Settings → Networking → **Generate Domain** →
آدرشی مثل `https://musicbazi-xxxx.railway.app` می‌گیری. HTTPS خودکار است →
PWA، سرویس‌ورکر آفلاین و میکروفون کار می‌کنند. دامنه‌ی خودت بعداً با
Custom Domain (CNAME + TXT) وصل می‌شود.

## ۶ — تست (به همین ترتیب)

```bash
curl https://<domain>/api/health          # {"ok":true,...}
# مرورگر: جستجوی یک آهنگ (SoundCloud/Deezer) → دانلود ۱۲۸ → پخش
# بعد یک لینک یوتیوب — این همان گیت بات‌وال است
```

## آپدیت بعدی

```bash
git push origin main        # اگر از GitHub وصل کرده باشی: auto-deploy
# یا دستی:
railway up
```

## محدودیت‌های شناخته‌شده‌ی این معماری

- **دیتای لوکال منتقل نمی‌شود** — Railway راهِ آپلود به Volume ندارد؛ دیپلوی
  با کتابخانه‌ی خالی شروع می‌کند (کاتالوگ کش خودش را می‌سازد).
- **RAM سقف ۱GB روی Trial** — uvicorn + node + nginx + ffmpeg با هم لب‌به‌لب
  است؛ دانلود همزمان را با `MUSICBAZI_CONCURRENCY=1` پایین بیاور اگر OOM دیدی.
- **Egress ۰.۰۵ دلار/GB** — هر آهنگی که کاربر می‌گیرد از این حساب می‌رود.
- **حالت اینترانت/قطعی** (reach.py) روی Railway بی‌معناست — سرور خودش بیرون
  از فیلتر است.
- **بات تلگرام** جدا نیست: `MUSICBAZI_TELEGRAM_BOT_TOKEN` که ست شود سرور اصلی
  خودش بات را در-process بالا می‌آورد (نیاز به ری‌استارت بعد از ذخیره).
