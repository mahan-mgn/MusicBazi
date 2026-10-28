# بات تلگرام روی Botkeep

بات روی [Botkeep](https://botkeep.cloud) اجرا می‌شود و به سرور زندهٔ
**https://musicbazi.ir** وصل می‌شود. لپ‌تاپ لازم نیست روشن بماند.

---

## چرا بات تنها می‌رود و سرور نمی‌آید

بات یک **کلاینت HTTP** روی API سرور است
([`server/app/bot/client.py`](server/app/bot/client.py)): جستجو، دانلود، کاور،
متن آهنگ و شناسایی، همه از `/api/...` می‌آیند. خودش نه `ffmpeg` دارد نه
`yt-dlp` (کامنت [`run.py:1206`](server/app/bot/run.py): «بات هیچ تبدیلی نمی‌کند»).

| جزء | کجا | چرا |
|---|---|---|
| **بات** (`app.bot.run`) | Botkeep | باید ۲۴/۷ و مستقل از لپ‌تاپ باشد |
| **سرور** (`app.main:app`) | `musicbazi.ir` | از قبل بالاست |

پلن رایگان Botkeep سقف **۵۱۲MB رم و ۱GB دیسک** دارد و `apt`/root نمی‌دهد —
`server/Dockerfile` با `apt-get install ffmpeg nodejs libchromaprint-tools` و
`librosa` در requirements از این سقف رد می‌شود. بات اما فقط `pydantic` و
`httpx` و `python-telegram-bot` می‌خواهد.

> **تست‌شده:** بات با `MUSICBAZI_API_BASE_URL=https://musicbazi.ir` بالا آمد و
> `/api/telegram/status` گفت `{"connected":true,"botUsername":"music_bazibot"}`.

---

## ۱ — ساخت اپ در Botkeep

1. وارد https://botkeep.cloud/app شو → **New / Create**.
2. نوع پروژه: **Python**.
3. منبع: **GitHub** → `mahan-mgn/MusicBazi` → شاخه‌ی مورد نظر.
4. **Install command** (اگر فیلد جدا دارد): `pip install -r requirements.txt`
   اگر ندارد، نصب خودکار از `requirements.txt` **ریشه** انجام می‌شود.
5. **Start command:**

   ```
   python main.py
   ```

6. منابع: کل اسلات رایگان (۵۱۲MB / ۵۰٪ CPU).

> **چرا `main.py` و نه `python -m app.bot.run`؟** Botkeep از **ریشه‌ی** مخزن
> اجرا می‌کند و پکیجِ `app` داخل `server/` است. [`main.py`](main.py) ریشه فقط
> `server/` را به `sys.path` می‌گذارد و `.env` ریشه را بارگذاری می‌کند — هیچ
> منطقی از بات را عوض نمی‌کند.

---

## ۲ — متغیرهای محیطی

در بخش **Environment / Secrets** اپ:

| کلید | مقدار | لازم؟ |
|---|---|---|
| `MUSICBAZI_TELEGRAM_BOT_TOKEN` | توکن BotFather | **بله** |
| `MUSICBAZI_API_BASE_URL` | `https://musicbazi.ir` | **بله** |
| `MUSICBAZI_DATA_DIR` | `/data` | توصیه |
| `MUSICBAZI_TELEGRAM_WEBAPP_URL` | `https://musicbazi.ir` | اختیاری |
| `MUSICBAZI_TELEGRAM_CACHE_CHAT_ID` | آیدی چتِ کش | اختیاری |

**`MUSICBAZI_DATA_DIR` چرا؟** بات دو فایل می‌نویسد: `bot.db` (دنبال‌کردن‌ها) و
`bot.log`. پیش‌فرضشان `server/data/` است که داخل مخزن است؛ اگر میزبان اجازه‌ی
نوشتن ندهد، `config.py` هنگام import با `PermissionError` می‌افتد. گذاشتنش روی
یک مسیر قابل‌نوشتن این را حل می‌کند.

`MUSICBAZI_TELEGRAM_PROXY` **لازم نیست** — سرور بات خارج از ایران است و
`api.telegram.org` را مستقیم می‌گیرد.

`MUSICBAZI_TELEGRAM_CACHE_CHAT_ID` فقط برای inline mode لازم است: تلگرام
ادیتِ پیام inline را با `file_id` قبول می‌کند نه آپلود؛ بات فایل را یک‌بار در
آن چت می‌فرستد تا `file_id` بگیرد. بدونش، نتیجه‌ی inline لینک مستقیم نشان
می‌دهد.

---

## ۳ — تست پذیرش

1. **کنترل پنل Botkeep** → باید لاگ `بات تلگرام بالا آمد.` را ببینی.
2. در مرورگر: `https://musicbazi.ir/api/telegram/status`
   → باید `{"connected":true,"botUsername":"music_bazibot",...}` بدهد.
   این تنها تست قابل‌اتکاست؛ حضور بات بعد از **۹۰ ثانیه** بدون ضربان منقضی
   می‌شود (`PRESENCE_TTL` در `server/app/telegram.py`).
3. در تلگرام `/start` → پاسخ باید بیاید.
4. یک **جستجوی کوتاه** → نتیجه از سرور می‌آید.
5. **دانلود یک آهنگ کوچک** → مهم‌ترین تست. مسیر
   [`file_bytes`](server/app/bot/client.py) فایل را کامل در رم می‌گیرد و بعد
   [`send_audio`](server/app/bot/run.py) آپلود می‌کند؛ در ۵۱۲MB رم فایل‌های
   بزرگ‌تر تنگ می‌شوند.

> نکته: سرور زنده الان `cookies: false` و `linked: false` است. `linked: false`
> یعنی هیچ حسابی از سایت به بات وصل نشده — برای `/start link_...` باید از وب
> انجام شود. این به بات ربطی ندارد و روی Botkeep هم همین است.

---

## ۴ — «همیشه فعال» واقعاً یعنی چه

FAQ خودِ Botkeep صریح است: **۲۴/۷ بدون SLA** و **ری‌استارت خودکار پس از کرش
وعده داده نشده** — پنل فقط وضعیت پروسه و لاگ را نشان می‌دهد.

بات هر چند وقت یک‌بار به `/api/telegram/bot` ضربان می‌فرستد. پس برای اینکه
بفهمی افتاده، یک مانیتور رایگان (UptimeRobot / Better Stack) روی این آدرس بزن:

```
https://musicbazi.ir/api/telegram/status
```

اگر `connected` شد `false` یا تایم‌اوت داد، ایمیل می‌گیری. این تنها راهِ
قابل‌اتکاست؛ منتظرِ ری‌استارت خودکار نمان.

---

## ۵ — محدودیت‌هایی که باید بدانی

- **پهنای باند دوبرابر:** هر آهنگ یک‌بار از `musicbazi.ir` به Botkeep و یک‌بار
  از Botkeep به تلگرام می‌رود. سقف آپلود تلگرام ۵۰MB است
  ([`logic.py:42`](server/app/bot/logic.py)).
- **دیسک ۱GB:** `bot.db` و `bot.log` (چرخشِ ۲MB × ۳) کوچک‌اند — فایل‌های صوتی
  اینجا نمی‌مانند.
- **دیسکِ ماندگار تضمین‌نشده:** FAQ اصطلاح «persistent volume» را به کار
  نمی‌برد. مهم نیست: تنها حالتِ محلیِ بات `bot.db` است که از سرور بازسازی می‌شود.
- **بدون Docker:** Botkeep از Docker پشتیبانی نمی‌کند؛ به همین دلیل `main.py`
  و `requirements.txt` ریشه لازم شدند.
- **بات روی سرور زنده ≠ کتابخانهٔ لپ‌تاپ.** بات به `musicbazi.ir` وصل است، پس
  کتابخانه و آرشیو همان سرور را می‌بیند، نه فایل‌های محلی لپ‌تاپ.

---

## نکته‌ی Railway

اگر روزی خواستی بات را جای دیگری ببری، بدان که
[`deploy/railway-entrypoint.sh`](deploy/railway-entrypoint.sh) بات را استارت
**نمی‌کند** — فقط `potoken` و `uvicorn` و `nginx`. برای آن باید یک بلوک
`while :; do python -m app.bot.run; done &` اضافه شود.
