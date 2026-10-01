import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# server/.env اگر بود بارگذاری می‌شود تا کوکی و بقیه‌ی تنظیمات لازم نباشد
# هر بار دستی export شوند. متغیر محیطیِ واقعی همیشه اولویت دارد.
def _env(name: str, default: str | None = None) -> str | None:
    return os.getenv(f"MUSICBAZI_{name}", default)


def _flag(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


try:
    from dotenv import dotenv_values

    def _apply_env_file(path: Path) -> None:
        """
        مقدارهای یک فایل `.env` را می‌نشیند — ولی فقط آن‌جا که محیط *واقعاً*
        چیزی نگفته است.

        `load_dotenv(override=False)` اینجا جواب نمی‌دهد: `docker-compose.yml`
        برای هر کلیدی که در `.env` میزبان نباشد، رشته‌ی **خالی** تزریق می‌کند
        (`${MUSICBAZI_SPOTIFY_CLIENT_ID:-}`) و آن رشته‌ی خالی «ست‌شده» حساب
        می‌شود، پس فایلِ ویزارد روی `/data` بی‌صدا نادیده گرفته می‌شد. خالی
        یعنی «نگفته».
        """
        if not path.exists():
            return
        for key, value in dotenv_values(path).items():
            if not value:
                continue
            if not (os.environ.get(key) or "").strip():
                os.environ[key] = value

    # `DATA_DIR/.env` اول می‌آید: همان فایلی است که ویزاردِ راه‌اندازی
    # (`app/setup.py`) می‌نویسد و در داکر روی volume می‌نشیند، برخلاف
    # `server/.env` که داخل ایمیج است و با هر بازسازی می‌پرد.
    #
    # `MUSICBAZI_ENV_NO_FILES=1` هیچ فایلی را نمی‌خواند. تست‌ها از آن استفاده
    # می‌کنند: کلیدهای واقعیِ `server/.env` توسعه‌دهنده نباید به تستِ شناسایی
    # نشت کند (کند، شکننده، و روی سهمیه‌ی کسی حساب می‌شد).
    if not os.getenv("MUSICBAZI_ENV_NO_FILES"):
        _env_dir = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
        _apply_env_file(_env_dir / ".env")
        _apply_env_file(BASE_DIR / ".env")
except ImportError:
    pass


# جایی که فایل‌های دانلودشده نگه داشته می‌شوند
DOWNLOAD_DIR = Path(_env("DOWNLOAD_DIR", str(BASE_DIR / "downloads")))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# دیتابیس SQLite — صف و کتابخانه اینجا دوام می‌آورند
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(_env("DB", str(DATA_DIR / "musicbazi.db")))

# کش موقت فایل‌های استریم آنلاین — مجزا از دانلودهای دائمی کتابخانه
STREAM_CACHE_DIR = Path(_env("STREAM_CACHE_DIR", str(DATA_DIR / "cache" / "stream")))
STREAM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
STREAM_CACHE_MAX_MB = int(_env("STREAM_CACHE_MAX_MB", "1024"))

# چند دانلود همزمان — بیشتر از این هم به یوتیوب فشار می‌آورد هم throttle می‌خوریم
MAX_CONCURRENT_DOWNLOADS = int(_env("CONCURRENCY", "3"))

# کارهای شکست‌خورده/لغوشده بعد از این مدت پاک می‌شوند (ثانیه).
# کارهای موفق پاک نمی‌شوند — آنها همان کتابخانه‌اند.
JOB_TTL_SECONDS = int(_env("JOB_TTL", "3600"))

# فایل‌های دانلودشده بعد از این مدت از دیسک حذف می‌شوند (ثانیه، پیش‌فرض ۷ روز).
# صفر یعنی هیچ‌وقت — دیسک را خودت مدیریت می‌کنی.
FILE_RETENTION_SECONDS = int(_env("FILE_RETENTION", str(7 * 24 * 3600)))

# ffmpeg برای ترنسکد و امبد کاور لازم است
FFMPEG_LOCATION = _env("FFMPEG") or (
    str(Path(p).parent) if (p := shutil.which("ffmpeg")) else None
)

# خودِ فایل اجرایی — yt-dlp پوشه می‌خواهد (FFMPEG_LOCATION) ولی بلندی‌سنجی و
# بریدنِ چپترها ffmpeg را مستقیم صدا می‌زنند و به مسیر کامل نیاز دارند.
FFMPEG_BIN = shutil.which("ffmpeg", path=FFMPEG_LOCATION) or shutil.which("ffmpeg") or "ffmpeg"

# یوتیوب دیگر منبع اول نیست (پایین‌تر را ببین — ساندکلاد اول امتحان می‌شود)،
# ولی همچنان به‌عنوان پشتیبان وقتی ساندکلاد جواب نداد فعال است. برای استخراج
# سمت سرور احراز هویت می‌خواهد («Sign in to confirm you're not a bot»)، یکی
# از این دو را ست کن:
#   MUSICBAZI_COOKIES_FILE=C:\path\to\cookies.txt        (فرمت Netscape)
#   MUSICBAZI_COOKIES_BROWSER=firefox                     (یا chrome/edge/brave)
COOKIES_FILE = _env("COOKIES_FILE") or None
COOKIES_BROWSER = _env("COOKIES_BROWSER") or None

# یوتیوب علاوه بر کوکی، PO Token هم می‌خواهد. دو حالت دارد:
#   ۱. اسکریپتی — سرورش در vendor/ بیلد می‌شود (setup_potoken.sh). حالت پیش‌فرض روی ویندوز.
#   ۲. HTTP — سرورش جدا بالاست و فقط آدرسش را می‌دهیم. حالت داکر.
_default_pot = BASE_DIR / "vendor" / "bgutil-ytdlp-pot-provider" / "server"
POT_SERVER_HOME = _env("POT_SERVER_HOME") or (
    str(_default_pot) if (_default_pot / "build" / "generate_once.js").exists() else None
)
POT_BASE_URL = _env("POT_BASE_URL") or None

# یوتیوب چالش امضا را با جاوااسکریپت می‌دهد و yt-dlp برای حلش به یک JS runtime
# نیاز دارد. پیش‌فرض خودش فقط deno را می‌پذیرد، پس اگر نبود سراغ node می‌رویم.
JS_RUNTIME = _env("JS_RUNTIME") or next(
    (r for r in ("deno", "bun", "node") if shutil.which(r)), None
)

# چیدمان فایل‌ها داخل آرشیو ZIP — نه روی دیسک سرور. جای‌گذارها:
#   {artist} {albumartist} {album} {title} {track} {disc} {year} {genre}
# `/` پوشه می‌سازد. مقداری که غایب باشد بخشِ خودش را حذف می‌کند، پس ترکِ
# بی‌آلبوم دو سطح بالاتر می‌نشیند به‌جای اینکه در پوشه‌ای بی‌نام گم شود.
PATH_TEMPLATE = _env("PATH_TEMPLATE", "{albumartist}/{album}/{track} - {title}")

# فایل .m3u کنار ترک‌ها در آرشیو — ترتیب آلبوم را نگه می‌دارد
M3U_ENABLED = _flag("M3U", True)

# پروکسی — برای شبکه‌هایی که یوتیوب یا خودِ کاتالوگ‌ها از آن‌ها مستقیم در دسترس
# نیستند. قالب: http://host:port ، socks5://host:port ، یا با احراز هویت
# socks5://user:pass@host:port
#
# socks5h به‌جای socks5 یعنی DNS هم آن‌طرف حل شود — اگر خودِ resolver محلی هم
# فیلتر شده باشد (که در عمل معمولاً هست) تنها حالتی است که کار می‌کند.
#
# متغیرهای استاندارد HTTP_PROXY عمداً تنها راه نیستند: yt-dlp و httpx هرکدام
# قاعده‌ی خودشان را برای خواندنشان دارند و رفتار یکسان نمی‌شد.
PROXY = _env("PROXY") or None

# اگر فقط استخراج صوت به پروکسی نیاز دارد و کاتالوگ‌ها مستقیم در دسترس‌اند،
# این را جدا ست کن. نبودنش یعنی همان PROXY برای همه‌چیز.
YTDLP_PROXY = _env("YTDLP_PROXY") or PROXY

# ترتیب منابعی که برای پیدا کردن فایل صوتی امتحان می‌شوند — پیش‌فرض اول
# ساندکلاد بعد یوتیوب: برای ترک‌هایی که از اسپاتیفای/اپل‌موزیک/دیزر می‌آیند
# (که خودشان فایل صوتی ندارند و resolver باید یک نسخه‌ی قابل‌دانلود پیدا کند)
# این یعنی فایل نهایی تا جایی که ممکن است از ساندکلاد می‌آید و فقط وقتی
# ساندکلاد جواب قانع‌کننده‌ای نداشت یا آن ترک اصلاً آنجا نبود، سراغ یوتیوب
# می‌رود (منطقش در resolver.resolve است). تگ‌ها همیشه از همان کاتالوگ اصلی
# (اسپاتیفای/اپل/دیزر) نوشته می‌شوند چون tagging از Track می‌آید نه از منبع صوت.
AUDIO_SOURCES = tuple(
    s.strip()
    for s in _env("AUDIO_SOURCES", "soundcloud,youtube").split(",")
    if s.strip()
)

# کاتالوگ ساندکلاد در جستجو — پیش‌فرض فعال
SOUNDCLOUD_ENABLED = _flag("SOUNDCLOUD", True)
SOUNDCLOUD_CLIENT_ID = _env("SOUNDCLOUD_CLIENT_ID") or None

# متن آهنگ از LRCLIB — عمومی، بدون کلید. کنار فایل .lrc می‌سازد و در تگ هم می‌نشیند.
LYRICS_ENABLED = _flag("LYRICS", True)
LRCLIB_API = _env("LRCLIB_API", "https://lrclib.net")

# متن آهنگ از Genius — جایگزینِ LRCLIB وقتی چیزی پیدا نشد. فقط متن ساده می‌دهد
# (بدون هم‌زمان‌سازی) و نیاز به کلید دارد.
# کلید رایگان: https://genius.com/api-clients → New API Client → Generate Access Token
GENIUS_ACCESS_TOKEN = _env("GENIUS_ACCESS_TOKEN") or None

# تحلیل حس‌وحالِ صوتی (والانس/انرژی) بعد از هر دانلود — با librosa، بدون کلید.
# چند ثانیه CPU به‌ازای هر ترک می‌گیرد؛ اگر librosa نصب نباشد یا خاموش شود،
# فقط این دو مقدار خالی می‌مانند و شافل به حالت کاملاً تصادفیِ قبلی برمی‌گردد.
MOOD_ENABLED = _flag("MOOD", True)

# نرمال‌سازی بلندی (EBU R128): بعد از هر دانلود، بلندیِ ادراکی و اوجِ واقعیِ
# فایل اندازه گرفته می‌شود تا پخش‌کننده بتواند همه‌ی ترک‌ها را هم‌تراز پخش کند —
# بدون آن، ترکِ یوتیوبی و ترکِ اورجینال چند دسی‌بل اختلاف دارند و هر بار باید
# دستی صدا را کم و زیاد کرد. فقط اندازه می‌گیریم؛ خودِ فایل دست‌نخورده می‌ماند.
LOUDNESS_ENABLED = _flag("LOUDNESS", True)

# هدفِ نرمال‌سازی (LUFS). ۱۴- استاندارد عملیِ اسپاتیفای/یوتیوب است.
LOUDNESS_TARGET = float(_env("LOUDNESS_TARGET", "-14"))

# اسپاتیفای API عمومی ندارد. بدون این دو، لینک اسپاتیفای فقط از روی عنوانِ
# oEmbed حدس زده می‌شود؛ با آنها آلبوم و پلی‌لیست دقیق خوانده می‌شوند.
# https://developer.spotify.com/dashboard → Client ID / Client Secret
SPOTIFY_CLIENT_ID = _env("SPOTIFY_CLIENT_ID") or None
SPOTIFY_CLIENT_SECRET = _env("SPOTIFY_CLIENT_SECRET") or None

# چت‌بات پیشنهاد پلی‌لیست («وایب»): تشخیص حال‌وهوای پیام با Gemini — اختیاری.
# بدون کلید، به نگاشتِ کلیدواژه‌ای فارسی برمی‌گردد (server/app/vibe.py).
# کلیدِ رایگان: https://aistudio.google.com/apikey
# مدل عمداً GA است (بدون پسوندِ preview) و قابلِ بازنویسی، چون شناسه‌های
# Gemini هر چند ماه جابه‌جا می‌شوند و نمی‌خواهیم برای یک تغییرِ اسم دیپلوی کنیم.
GEMINI_API_KEY = _env("GEMINI_API_KEY") or None
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.6-flash")
# v1beta نه v1: `responseSchema` در v1 کامل پشتیبانی نمی‌شود. در config است چون
# هم `vibe.py` مصرفش می‌کند هم `setup.py` (آزمایشِ کلید) و setup نباید vibe را
# import کند.
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# تأیید صوتی با AcoustID: بعد از دانلود، فینگرپرینت فایل را با کاتالوگ چک می‌کند
# تا مطمئن شویم واقعاً همان ترک است. به `fpcalc` (chromaprint) و یک کلید رایگان
# نیاز دارد: https://acoustid.org/new-application
ACOUSTID_KEY = _env("ACOUSTID_KEY") or None
FPCALC = _env("FPCALC") or shutil.which("fpcalc")

# شناساییِ آهنگ از روی صدا (AudD) — اختیاری، و تنها راهی که روی *ضبطِ
# میکروفون* و تکه‌ی کوتاه جواب می‌دهد. AcoustID پایین‌تر کارِ دیگری می‌کند:
# فایلِ کامل را می‌شناسد، نه صدایی که از بلندگو ضبط شده.
# توکن: https://dashboard.audd.io
AUDD_TOKEN = _env("AUDD_TOKEN") or None
AUDD_API = _env("AUDD_API", "https://api.audd.io/")

# بات تلگرام — کلاینتِ HTTP جدا برای همین API، نه یک مسیر جدا در resolver.
# بدون توکن، run.py همان اول لاگ می‌کند و خارج می‌شود.
# توکن رایگان: @BotFather در تلگرام → /newbot
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN") or None

# پروکسیِ خودِ تلگرام.
#
# بات تنها جایی است که مستقیم با یک سرویسِ بیرونی حرف می‌زند و از مسیرِ
# `resolver`/`httpx`ِ بقیه‌ی برنامه رد نمی‌شود، پس MUSICBAZI_PROXY خودبه‌خود
# شاملش نمی‌شد. روی شبکه‌ای که api.telegram.org مستقیم درنمی‌آید نتیجه‌اش این
# بود که getUpdates با «getaddrinfo failed» می‌افتاد و آپلودِ فایل وسطِ راه
# TimedOut می‌گرفت — بی‌آنکه چیزی از تنظیماتِ پروکسی اشتباه به نظر برسد.
# جدا از PROXY نگه داشته شده چون ممکن است کاتالوگ‌ها مستقیم بیایند و فقط
# تلگرام پروکسی بخواهد (یا برعکس).
TELEGRAM_PROXY = (
    _env("TELEGRAM_PROXY")
    or PROXY
    or os.getenv("HTTPS_PROXY")
    or os.getenv("ALL_PROXY")
    or os.getenv("HTTP_PROXY")
    or None
)
# فقط وقتی بات پروسه‌ی جدایی از خودِ سرور است لازم می‌شود (مثل سرویس داکر)
API_BASE_URL = _env("API_BASE_URL", "http://localhost:8000")

# دیتابیسِ محلیِ بات — فقط دنبال‌کردنِ هنرمندها، کاملاً جدا از SQLite سرور
# (`app/db.py`). بات همچنان فقط با HTTP به API حرف می‌زند؛ این فایل تنها
# حافظه‌ی خودِ بات است و حتی وقتی سرور و بات در دو کانتینر جدا اجرا می‌شوند
# هم مشکلی پیش نمی‌آورد.
BOT_DB_PATH = Path(_env("BOT_DB", str(DATA_DIR / "bot.db")))

# فاصله‌ی چک‌کردنِ انتشار تازه‌ی هنرمندهای دنبال‌شده (ثانیه، پیش‌فرض ۳۰ دقیقه)
FOLLOW_POLL_INTERVAL = int(_env("FOLLOW_POLL_INTERVAL", str(30 * 60)))

# چتِ کش برای inline mode: تلگرام ادیتِ پیامِ inline را فقط با file_id یا URL
# قبول می‌کند، نه آپلودِ مستقیمِ فایل — پس فایل یک‌بار اینجا (چت/کانالی که بات
# در آن ادمین است) فرستاده می‌شود تا file_id بگیرد، بعد همان file_id روی پیامِ
# inline می‌نشیند. بدونش، نتیجه‌ی inline فقط لینکِ مستقیمِ فایل را نشان می‌دهد.
_cache_chat_raw = _env("TELEGRAM_CACHE_CHAT_ID")
TELEGRAM_CACHE_CHAT_ID = int(_cache_chat_raw) if _cache_chat_raw else None

# آدرسِ مینی‌اپ تلگرام (HTTPS). اگر ست شود، دکمه‌ی منوی بات و دکمه‌ی استارت مستقیم
# وب‌اپلیکیشنِ موزیک‌بازی را درون تلگرام باز می‌کنند.
TELEGRAM_WEBAPP_URL = (
    _env("TELEGRAM_WEBAPP_URL")
    or _env("WEBAPP_URL")
    or None
)

# مبدأهایی که اجازه‌ی CORS دارند.
#
# دِوسرورِ ویت همیشه هست. دو تای بعدی مالِ اپ اندروید (Capacitor) است که صفحه
# را از روی خودِ دستگاه سرو می‌کند و هر درخواستش به سرور cross-origin است —
# بدون این‌ها اپ نصب می‌شود ولی هیچ داده‌ای نمی‌گیرد.
#
# با MUSICBAZI_ALLOWED_ORIGINS (جدا با کاما) می‌شود آدرس دیگری هم اضافه کرد.
_DEFAULT_ORIGINS = (
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "https://localhost",
    "capacitor://localhost",
)
ALLOWED_ORIGINS = tuple(
    dict.fromkeys(
        list(_DEFAULT_ORIGINS)
        + [o.strip() for o in _env("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    )
)

ITUNES_API = "https://itunes.apple.com"
DEEZER_API = "https://api.deezer.com"
SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
GENIUS_API = "https://api.genius.com"

# APIهای بالادست گاهی بیست ثانیه هم طول می‌کشند؛ تایم‌اوت تنگ باعث خطای بی‌مورد می‌شود
HTTP_TIMEOUT = 30.0
SEARCH_LIMIT = 20


# ---------- حالتِ اینترانت ----------
#
# در ایران قطعیِ اینترنتِ بین‌الملل یعنی اینترنتِ ملی همچنان برقرار است: سرورِ
# خانگی از روی وای‌فای در دسترس است ولی هیچ‌کدام از کاتالوگ‌ها و منابعِ صوتی
# نیستند. این چند تنظیم همان حالت را قابلِ تشخیص و قابلِ تحمل می‌کنند.

# آینه‌ی محلیِ کاور (`artcache.py`). خاموش کردنش یعنی برگشت به رفتارِ قبلی:
# آدرسِ CDN مستقیم به مرورگر می‌رود و موقعِ قطعی سفید می‌ماند.
ART_MIRROR_ENABLED = _flag("ART_MIRROR", True)

# کشِ کاتالوگ (`catcache.py`) — جستجو و صفحه‌ی آلبوم/هنرمند در حالتِ اینترانت.
CATALOG_CACHE_ENABLED = _flag("CATALOG_CACHE", True)

# آدرس‌هایی که برای تشخیصِ «بین‌الملل هست یا نه» زده می‌شوند. *هر* پاسخِ HTTP
# یعنی رسیدیم — حتی ۴۰۴. چیزی که اندازه می‌گیریم دسترسیِ شبکه است نه سلامتِ API.
# یکی که جواب بدهد کافی است.
#
# اینجا عمداً *خودِ کاتالوگ‌ها* نیستند، هرچند وسوسه‌انگیز است.
#
# نسخه‌ی اول این فایل `itunes.apple.com` و `api.deezer.com` را می‌زد، با این
# استدلال که «همان چیزی را بسنج که برنامه لازم دارد». روی یک اتصالِ ایرانی این
# بدترین انتخابِ ممکن بود: اپل آی‌پی‌های ایران را به‌خاطر تحریم مسدود می‌کند و
# دیزر geo-block دارد، پس هر دو مرتب قطع‌ووصل می‌شوند *در حالی که اینترنت
# کاملاً سالم است*. نتیجه‌اش این بود که برنامه بی‌دلیل به حالتِ اینترانت می‌رفت
# و — چون در آن حالت دیگر مسیرِ زنده را امتحان نمی‌کرد — هیچ‌وقت نمی‌فهمید
# اشتباه کرده.
#
# پس پروب باید به سؤالِ ساده‌ترِ «اصلاً مسیری به بیرون هست؟» جواب بدهد، با
# آدرس‌هایی که خودشان سیاست جغرافیایی ندارند. هر سه کوچک‌اند (۲۰۴ یا چند خط
# متن) و از شبکه‌های متفاوتی می‌آیند؛ سومی با آی‌پی صداست تا وقتی خودِ DNS
# دستکاری شده هم جواب بدهد.
#
# خالی گذاشتنِ این متغیر تشخیص را کلاً خاموش می‌کند (همیشه «آنلاین») — راهِ
# فرار برای شبکه‌ای که هیچ‌کدام از این‌ها را نمی‌دهد.
REACH_PROBES = tuple(
    u.strip()
    for u in _env(
        "REACH_PROBES",
        "https://cloudflare.com/cdn-cgi/trace"
        ",https://www.gstatic.com/generate_204"
        ",https://1.1.1.1/cdn-cgi/trace",
    ).split(",")
    if u.strip()
)

# چند دورِ ناموفقِ پشت‌سرهم لازم است تا «قطع» اعلام شود.
#
# نامتقارن است و باید باشد: برگشتن به آنلاین با *یک* موفقیت اتفاق می‌افتد، ولی
# رفتن به اینترانت دو شکستِ پیاپی می‌خواهد. دلیلش این است که هزینه‌ی دو حالت
# یکی نیست — یک اعلامِ اشتباهِ «قطع» جستجوی زنده را خاموش می‌کند و دانلودها را
# به صف می‌فرستد، در حالی که یک اعلامِ اشتباهِ «وصل» فقط یک درخواستِ ناموفق
# است که خودش هم فوراً تصحیح می‌شود.
#
# یک بسته‌ی گم‌شده نباید برنامه را برای دو دقیقه به حالتِ اینترانت ببرد.
REACH_STRIKES = max(1, int(_env("REACH_STRIKES", "2")))

# تنگ عمدی است: در حالتِ قطعی این درخواست‌ها تا آخرین ثانیه صبر می‌کنند و
# تایم‌اوتِ بلند یعنی کاربر برای فهمیدنِ یک چیزِ از قبل معلوم منتظر می‌ماند.
REACH_TIMEOUT = float(_env("REACH_TIMEOUT", "6"))

# فاصله‌ی پروب وقتی وصل است (ثانیه). از دست رفتنِ اینترنت را خودِ درخواستِ
# شکست‌خورده فوراً گزارش می‌کند، پس اینجا لازم نیست تند باشد.
REACH_INTERVAL = float(_env("REACH_INTERVAL", "120"))

# فاصله‌ی پروب وقتی قطع است. تندتر، چون برگشتنِ اینترنت خبری است که صفِ دانلودِ
# معوق منتظرش است.
REACH_RETRY_INTERVAL = float(_env("REACH_RETRY_INTERVAL", "30"))

# دانلودی که موقعِ قطعی درخواست شده، به‌جای شکست در صف می‌ماند و با برگشتنِ
# اینترنت خودکار شروع می‌شود.
DEFER_DOWNLOADS = _flag("DEFER_DOWNLOADS", True)

# پرکردنِ پس‌زمینه‌ی آینه‌ی کاور: کاورهایی که آدرسشان ثبت شده ولی تصویرشان
# گرفته نشده. مرورِ عادی بیشترشان را پر می‌کند؛ این حلقه بقیه را می‌گیرد تا
# موقعِ قطعی چیزی سفید نماند.
ART_WARM_ENABLED = _flag("ART_WARM", True)
ART_WARM_BATCH = int(_env("ART_WARM_BATCH", "24"))
ART_WARM_INTERVAL = float(_env("ART_WARM_INTERVAL", "60"))


# ---------- راه‌اندازی ----------
#
# ویزاردِ first-run (`app/setup.py` + `src/components/SetupWizard.tsx`) تا وقتی
# این خاموش است، هر بار که صفحه باز می‌شود دوباره ظاهر می‌شود. «رد کردن» هم
# همین را روشن می‌کند — کاربری که نخواست کلید بدهد نباید هر بار در همان صفحه
# گیر کند؛ از منوی «تنظیمات» همیشه راهِ برگشت هست.
SETUP_DONE = _flag("SETUP_DONE", False)
