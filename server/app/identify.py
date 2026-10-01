"""
شناساییِ آهنگ از روی خودِ صدا — «این چه آهنگی بود؟»

دو مسیرِ کاملاً متفاوت، چون یک ابزار هر دو کار را نمی‌کند:

* **AudD** (`providers/audd.py`) — برای تکه‌ی کوتاه و ضبطِ میکروفون. تنها
  مسیری که در حالتِ «شزم» جواب می‌دهد. اختیاری و کلید می‌خواهد.
* **AcoustID** — فینگرپرینتِ کروماپرینتِ همان فایل را با ایندکسِ فایل‌های کامل
  می‌سنجد. برای «این mp3 بی‌تگ کدام آهنگ است؟» عالی است و رایگان، ولی روی
  صدایی که از بلندگو ضبط شده تقریباً هیچ‌وقت جواب نمی‌دهد: نویزِ اتاق و اکو
  سیگنال را عوض می‌کنند، و مدت‌زمانِ یک تکه‌ی بیست‌ثانیه‌ای با هیچ ترکِ کاملی
  نمی‌خواند.

ترتیب هم از همین می‌آید: اول AudD اگر تنظیم شده باشد، بعد AcoustID. اگر
هیچ‌کدام تنظیم نباشند، `missing()` دقیقاً می‌گوید چه چیزی کم است — این پیام
مستقیم به کاربر می‌رسد، چون «نشناختم» و «اصلاً تنظیم نشده» دو چیزِ کاملاً
متفاوت‌اند و قبلاً از بیرون یکسان دیده می‌شدند.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import ACOUSTID_KEY, FFMPEG_BIN, FPCALC, PROXY
from .providers import audd

LOOKUP_URL = "https://api.acoustid.org/v2/lookup"
_TIMEOUT = 15.0

# پایین‌تر از این، AcoustID خودش هم به تطابق مطمئن نیست و نشان دادنش فقط
# کاربر را دنبال نخود سیاه می‌فرستد
MIN_SCORE = 0.35
# چند حدس نشان داده شود — بیشترش تصمیم را سخت‌تر می‌کند، نه آسان‌تر
MAX_MATCHES = 5


class ServiceError(Exception):
    """
    سرویسِ شناسایی درخواست را رد کرد — کلیدِ نامعتبر، سهمیه‌ی تمام‌شده، یا
    شبکه‌ی قطع.

    عمداً از «چیزی پیدا نشد» جداست و تا خودِ کاربر بالا می‌رود. یک بار همین
    دو حالت یکسان دیده شدند و نتیجه‌اش این بود که یک کلیدِ نامعتبر ساعت‌ها
    شبیهِ «این آهنگ در کاتالوگ نیست» به نظر می‌رسید.
    """


@dataclass
class Match:
    title: str
    artist: str
    # اطمینانِ سرویس بین ۰ و ۱. AudD عددی نمی‌دهد و جای خالی‌اش None می‌ماند —
    # ساختنِ یک «۱۰۰٪» الکی فقط اعتمادِ بی‌جا می‌سازد.
    score: float | None
    duration_ms: int = 0


def acoustid_available() -> bool:
    return bool(ACOUSTID_KEY and FPCALC)


def available() -> bool:
    return audd.enabled() or acoustid_available()


def missing() -> str:
    """
    چرا شناسایی خاموش است — به زبانی که مستقیم به کاربر نشان داده می‌شود.
    رشته‌ی خالی یعنی چیزی کم نیست.
    """
    if available():
        return ""
    if ACOUSTID_KEY and not FPCALC:
        return (
            "شناسایی صوتی خاموش است: `fpcalc` (از بسته‌ی Chromaprint) روی این سیستم "
            "پیدا نشد. نصبش کن یا مسیرش را در MUSICBAZI_FPCALC بگذار."
        )
    if FPCALC and not ACOUSTID_KEY:
        return "شناسایی صوتی خاموش است: MUSICBAZI_ACOUSTID_KEY تنظیم نشده."
    return (
        "شناسایی صوتی تنظیم نشده. برای فایلِ کامل: `fpcalc` به‌علاوه‌ی "
        "MUSICBAZI_ACOUSTID_KEY. برای ضبطِ میکروفون: MUSICBAZI_AUDD_TOKEN."
    )


def _run_fpcalc(path: Path) -> tuple[int, str] | None:
    try:
        out = subprocess.run(
            [str(FPCALC), "-json", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        body = json.loads(out.stdout)
        return int(body["duration"]), body["fingerprint"]
    except Exception:
        return None


def _to_wav(path: Path) -> Path | None:
    """
    هر چیزی را به wavِ مونوی ۱۶ کیلوهرتز تبدیل می‌کند.

    fpcalc دیکدرِ خودش را دارد ولی همه‌ی ظرف‌ها را نمی‌شناسد — ویسِ تلگرام
    (ogg/opus) و ویدیو (mp4/webm) دو نمونه‌ی رایج‌اند. ffmpeg هر دو را باز
    می‌کند، پس وقتی fpcalc مستقیم شکست خورد یک بار از این مسیر رد می‌شویم.

    کوتاه نمی‌شود: خودِ fpcalc تحلیل را روی دو دقیقه‌ی اول می‌بندد ولی *مدت*
    را از فایل می‌خواند، و AcoustID با همان مدت در ایندکس می‌گردد. اگر اینجا
    فایلِ چهاردقیقه‌ای را به دو دقیقه می‌بریدیم، مدتِ گزارش‌شده غلط می‌شد و
    تطابق — حتی برای فایلِ کامل و سالم — از دست می‌رفت.
    """
    # fd باید همین‌جا بسته شود: ffmpeg خودش فایل را می‌نویسد و روی ویندوز تا
    # وقتی این توصیف‌گر باز است، حذفِ فایل در `finally` با PermissionError
    # می‌افتد — یعنی به‌ازای هر ویس/ویدیو یک wav روی دیسک جا می‌ماند
    handle, name = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    target = Path(name)
    try:
        subprocess.run(
            [
                FFMPEG_BIN, "-nostdin", "-hide_banner", "-y",
                "-i", str(path),
                "-vn", "-ac", "1", "-ar", "16000",
                str(target),
            ],
            capture_output=True,
            timeout=180,
            check=True,
        )
        return target if target.stat().st_size > 0 else None
    except Exception:
        target.unlink(missing_ok=True)
        return None


def fingerprint(path: Path) -> tuple[int, str] | None:
    """(مدت به ثانیه، فینگرپرینت) یا None. بلاک‌کننده است."""
    if not FPCALC or not path.exists():
        return None
    if result := _run_fpcalc(path):
        return result

    converted = _to_wav(path)
    if converted is None:
        return None
    try:
        return _run_fpcalc(converted)
    finally:
        converted.unlink(missing_ok=True)


def _matches(results: list[dict]) -> list[Match]:
    found: list[Match] = []
    seen: set[tuple[str, str]] = set()

    for result in results:
        score = float(result.get("score") or 0.0)
        if score < MIN_SCORE:
            continue
        for rec in result.get("recordings") or []:
            title = (rec.get("title") or "").strip()
            if not title:
                continue
            artist = ", ".join(
                a.get("name", "") for a in (rec.get("artists") or []) if a.get("name")
            ).strip()
            # یک ضبط می‌تواند در چند ریلیز تکرار شود (سینگل، آلبوم، best of) و
            # AcoustID همه را می‌دهد؛ برای کاربر همه یک چیزند
            key = (title.lower(), artist.lower())
            if key in seen:
                continue
            seen.add(key)
            found.append(
                Match(
                    title=title,
                    artist=artist or "ناشناس",
                    score=round(score, 3),
                    duration_ms=int(float(rec.get("duration") or 0) * 1000),
                )
            )

    found.sort(key=lambda m: m.score or 0, reverse=True)
    return found[:MAX_MATCHES]


# خطاهای خامِ AcoustID برای کاربر بی‌معنی‌اند؛ آن یکی که واقعاً پیش می‌آید
# جمله‌ی خودش را دارد، چون تنها راه رفعش دانستنِ تفاوتِ دو کلیدِ سایت است.
_ACOUSTID_HINTS = {
    4: (
        "کلید AcoustID نامعتبر است. این کلید باید کلیدِ یک *برنامه* باشد: در "
        "acoustid.org/new-application یکی بساز و کلیدش را از acoustid.org/my-applications "
        "بردار — نه کلیدِ شخصیِ acoustid.org/api-key که فقط برای ثبت فینگرپرینت است."
    ),
    6: "درخواستِ AcoustID ناقص بود.",
}


def _by_acoustid(path: Path, fp: tuple[int, str] | None = None) -> list[Match]:
    if not acoustid_available():
        return []

    # صدازننده معمولاً از قبل فینگرپرینت را گرفته (برای تصمیمِ ترتیب)؛ دوباره
    # گرفتنش یعنی یک بار اجرای اضافه‌ی fpcalc روی همان فایل
    fp = fp or fingerprint(path)
    if fp is None:
        # فایل قابلِ فینگرپرینت نبود — نه خطای سرویس است نه تطابق
        return []
    duration, value = fp

    try:
        res = httpx.post(
            LOOKUP_URL,
            data={
                "client": ACOUSTID_KEY,
                "duration": duration,
                "fingerprint": value,
                "meta": "recordings",
            },
            timeout=_TIMEOUT,
            proxy=PROXY,
        )
        body = res.json()
    except Exception as exc:
        raise ServiceError(f"به AcoustID وصل نشد: {exc}") from exc

    if body.get("status") != "ok":
        error = body.get("error") or {}
        raise ServiceError(
            _ACOUSTID_HINTS.get(error.get("code"))
            or f"AcoustID: {error.get('message') or 'درخواست رد شد'}"
        )

    return _matches(body.get("results") or [])


# مرزِ «فایلِ کامل» در برابر «تکه». اندازه‌گیری‌شده: همان ترک، کامل (۲۸۱ ثانیه)
# با AcoustID امتیاز ۰.۹۹ گرفت و تکه‌ی ۱۵ثانیه‌ایِ خودش هیچ تطابقی نداشت.
LONG_ENOUGH_SECONDS = 60


def _by_audd(path: Path) -> list[Match]:
    try:
        found = audd.recognize(path)
    except audd.AuddError as exc:
        raise ServiceError(str(exc)) from exc
    if found is None:
        return []
    return [Match(title=found.title, artist=found.artist, score=None)]


def identify(path: Path) -> list[Match]:
    """
    حدس‌های ممکن برای این فایل صوتی، مرتب‌شده از مطمئن‌ترین.
    لیست خالی یعنی شناخته نشد. بلاک‌کننده است — در thread صدا زده شود.

    ترتیب از روی *طولِ* ورودی تصمیم گرفته می‌شود، نه ثابت:

    * فایلِ کامل → اول AcoustID، که رایگان است و دقیقاً برای همین ساخته شده.
      AudD فقط اگر چیزی پیدا نشد، چون هر درخواستش از سهمیه‌ی پولی کم می‌کند.
    * تکه‌ی کوتاه یا ضبطِ میکروفون → اول AudD، چون AcoustID اینجا عملاً
      هیچ‌وقت جواب نمی‌دهد و زدنش فقط تأخیر است.

    اگر مسیری که *تنظیم شده* درخواست را رد کند `ServiceError` بالا می‌رود —
    ولی وقتی مسیرِ دیگری جواب داده، ردِ آن یکی اهمیتی ندارد و بی‌صدا رد می‌شود.
    """
    fp = fingerprint(path) if acoustid_available() else None
    long_file = fp is not None and fp[0] >= LONG_ENOUGH_SECONDS

    steps = (
        [lambda: _by_acoustid(path, fp), lambda: _by_audd(path)]
        if long_file
        else [lambda: _by_audd(path), lambda: _by_acoustid(path, fp)]
    )

    problem: ServiceError | None = None
    for step in steps:
        try:
            if found := step():
                return found
        except ServiceError as exc:
            # اولین ردِ سرویس نگه داشته می‌شود؛ اگر هیچ مسیری جواب نداد، همان
            # چیزی است که کاربر باید ببیند
            problem = problem or exc

    if problem is not None:
        raise problem
    return []
