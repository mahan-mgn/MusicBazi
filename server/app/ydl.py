"""گزینه‌های مشترک yt-dlp — یک جا تا احراز هویت و تنظیمات شبکه همه‌جا یکسان باشد."""

from __future__ import annotations

import os

from .config import (
    COOKIES_BROWSER,
    COOKIES_FILE,
    FFMPEG_LOCATION,
    JS_RUNTIME,
    POT_BASE_URL,
    POT_SERVER_HOME,
    YTDLP_PROXY,
)


def _live(name: str, imported):
    """
    مقدارِ *همین لحظه* یک تنظیمِ احراز هویت.

    `config.py` این‌ها را در زمانِ import می‌خواند، ولی ویزاردِ راه‌اندازی
    (`setup.py`) بی‌ری‌استارت فقط `os.environ` را عوض می‌کند — پس یک
    `from .config import COOKIES_FILE` کوکیِ تازه‌آپلودشده را بی‌صدا نادیده
    می‌گرفت تا ری‌استارتِ بعدی (دقیقاً همان «کوکی دادم ولی یوتیوب نشکست»).
    محیط برنده است؛ نبودش یعنی برگشت به مقدارِ زمانِ استارت‌آپ.
    """
    if name.startswith("MUSICBAZI_"):
        return os.environ.get(name) or imported
    return os.environ.get(f"MUSICBAZI_{name}") or imported

BASE_OPTS: dict = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "noplaylist": True,
    "retries": 3,
    "fragment_retries": 3,
}


def auth_opts() -> dict:
    """
    چیزهایی که یوتیوب برای استخراج سمت سرور لازم دارد.

    سه گیت مستقل وجود دارد و هر سه باید باز شوند، وگرنه یوتیوب یا «not a bot»
    می‌دهد یا لیست فرمت خالی برمی‌گرداند:
      ۱. گیت ضدربات   → کوکی مرورگر یا کوکی‌فایل
      ۲. PO Token     → سرور bgutil که در vendor/ بیلد شده
      ۳. چالش امضا/n  → yt-dlp-ejs به‌علاوه‌ی یک JS runtime
    """
    opts: dict = {}

    cookies_file = _live("COOKIES_FILE", COOKIES_FILE)
    cookies_browser = _live("COOKIES_BROWSER", COOKIES_BROWSER)
    if cookies_file:
        opts["cookiefile"] = cookies_file
    elif cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser, None, None, None)

    # PO Token دو راه دارد و پلاگین هر دو را می‌شناسد: اسکریپت محلی (ویندوز، بدون
    # داکر) یا سرور HTTP جدا (داکر). اگر آدرس HTTP داده شده باشد همان ارجح است،
    # چون سرورش یک بار بالا می‌آید و node را برای هر توکن دوباره اجرا نمی‌کند.
    if POT_BASE_URL:
        opts["extractor_args"] = {"youtubepot-bgutilhttp": {"base_url": [POT_BASE_URL]}}
    elif POT_SERVER_HOME:
        opts["extractor_args"] = {
            "youtubepot-bgutilscript": {"server_home": [POT_SERVER_HOME]},
        }

    if JS_RUNTIME:
        # پیش‌فرض yt-dlp فقط deno است؛ باید صریح فعالش کنیم
        opts["js_runtimes"] = {JS_RUNTIME: {}}

    return opts


def opts(**extra) -> dict:
    """گزینه‌های پایه + احراز هویت + ffmpeg، به‌علاوه‌ی هر چیزی که صدازننده بدهد."""
    merged = {**BASE_OPTS, **auth_opts()}
    if FFMPEG_LOCATION:
        merged["ffmpeg_location"] = FFMPEG_LOCATION
    if YTDLP_PROXY:
        # هم استخراج و هم خودِ دانلود فرگمنت‌ها از همین‌جا می‌روند —
        # پروکسی کردن فقط استخراج، لینک‌های مستقیمِ غیرقابل‌دسترس می‌دهد
        merged["proxy"] = YTDLP_PROXY
    merged.update(extra)
    return merged


def has_cookies() -> bool:
    return bool(
        _live("COOKIES_FILE", COOKIES_FILE)
        or _live("COOKIES_BROWSER", COOKIES_BROWSER)
    )


def has_jsruntime() -> bool:
    return bool(JS_RUNTIME)


def has_potoken() -> bool:
    return bool(POT_BASE_URL or POT_SERVER_HOME)


def proxy_label() -> str | bool:
    """
    آدرس پروکسی بدون نام‌کاربری و رمز.

    `/health` را کسی می‌بیند که لزوماً صاحب سرور نیست؛ رمزِ پروکسی نباید در
    یک اندپوینت بی‌احراز هویت لو برود، ولی «هست یا نیست» باید دیده شود.
    """
    if not YTDLP_PROXY:
        return False
    scheme, sep, rest = YTDLP_PROXY.partition("://")
    if not sep:
        # بدون طرح — همان «host:port» خالی است و چیزی برای پنهان کردن ندارد
        scheme, rest = "", YTDLP_PROXY
    host = rest.rpartition("@")[2]
    return f"{scheme}://{host}" if scheme else host
