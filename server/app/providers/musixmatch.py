"""
متن آهنگ از Musixmatch — **فقط APIِ رسمی**، با کلیدِ خودِ کاربر.

**پیش‌فرض خاموش است** و بدونِ `MUSICMATCH_API_KEY` در وضعیتِ «نیازمندِ
راه‌اندازی» می‌ماند: `enabled()` بدونِ کلید `False` می‌دهد، پس Provider
بی‌سر‌و‌صدا از زنجیره رد می‌شود (همان الگوی Genius).

قرارداد از **مستنداتِ رسمیِ خودِ Musixmatch**:

- `developer.musixmatch.com/documentation/api-reference/matcher-subtitle-get`
  → `GET matcher.subtitle.get` با پارامترهای `q_track` و `q_artist`
  (هر دو الزامی) و `apikey` (الزامی). خروجی: زیرنویسِ **همگام**.
- `.../track-richsync-get` → `GET track.richsync.get` با `apikey` (الزامی) و
  «حداقل یکی از `commontrack_id` / `track_id` / `track_isrc`». خروجی: متنِ
  **کلمه‌به‌کلمه**.

### ⚠️ محدودیتِ پلن (مهم)

طبقِ مستنداتِ خودِ بستهٔ `pymusixmatch`، `matcher.subtitle.get` **نیازمندِ
پلنِ تجاری است** («This method requires a commercial plan.»). یعنی با کلیدِ
رایگانِ پیش‌فرض، متنِ همگام در دسترس نیست. در آن حالت سرویس پاسخِ خطا
می‌دهد؛ اینجا آن خطا `ProviderError(http)` می‌شود، نه «خالی» — چون
«پلنِ من این را ندارد» با «این ترک را ندارم» یکی نیست.

`track.lyrics.get` (متنِ ساده) روی پلنِ رایگان کار می‌کند ولی معمولاً فقط
بخشِ محدودی از متن را برمی‌گرداند؛ به همین دلیل مسیرِ اصلی اینجا همان
زیرنویس/richsync است و متنِ ساده پشتیبان نیست (ناقص برگرداندن، بدتر از
برنگرداندن است).

### شرایط استفاده

هرگز متن را روی دیسک نمی‌نویسیم و در پاسخِ API هم نمایش نمی‌دهیم مگر همان
جایی که پروژه از قبل متن را نشان می‌دهد. کلید فقط از `config` خوانده
می‌شود و **هرگز چاپ نمی‌شود**.
"""

from __future__ import annotations

import httpx

from ..config import MUSIXMATCH_API, MUSIXMATCH_API_KEY, PROXY
from ..lyrics.matching import duration_matches
from ..lyrics.models import Lyrics
from ..lyrics.parsers import parse_enhanced_lrc, parse_lrc
from ..lyrics.registry import ProviderError

_NAME = "musixmatch"
_TIMEOUT = 10.0

# ۴۰۴ در این API یعنی «این ترک را ندارم» (کدِ ۴۰۴ در پوششِ body هم می‌آید).
_EMPTY_STATUSES = frozenset({404})

# کدهای خطای خودِ Musixmatch که یعنی «ندارم»، نه «خطا».
_EMPTY_BODY_CODES = frozenset({404})


def enabled() -> bool:
    """
    بدونِ کلید خاموش است — «پیکربندی‌نشده» با «قطع بود» یکی نیست، و Providerِ
    پیکربندی‌نشده نباید مانعِ کشِ منفی شود.
    """
    return bool(MUSIXMATCH_API_KEY)


def _error_from(exc: Exception) -> ProviderError:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ProviderError(_NAME, "network", detail=exc.__class__.__name__)
    return ProviderError(_NAME, "body", detail=exc.__class__.__name__)


def _envelope(body: dict) -> tuple[int, dict]:
    """
    پوششِ استانداردِ Musixmatch: `{"message": {"header": {...}, "body": {...}}}`.

    `status_code` را از header بیرون می‌کشد. ساختارِ غیرمنتظره = خطای body.
    """
    message = body.get("message")
    if not isinstance(message, dict):
        raise ProviderError(_NAME, "body", detail="no-message-envelope")
    header = message.get("header") or {}
    status = header.get("status_code") if isinstance(header, dict) else None
    inner = message.get("body") if isinstance(message.get("body"), dict) else {}
    return int(status) if isinstance(status, int) else -1, inner


def _subtitle_text(inner: dict) -> str | None:
    """
    `subtitle_body` (LRC) → رشتهٔ زمان‌دار.

    ⚠️ `richsync_body` عمداً خوانده **نمی‌شود**: آن یک رشتهٔ **JSON** است
    (`[{"ts":…,"te":…,"l":…,"x":…}]`)، نه LRC. پارسرِ LRC این پروژه آن را
    نمی‌فهمد و `richsync` هم جداگانه کلمه‌به‌کلمه است. تا وقتی یک پارسرِ
    اختصاصی برایش نوشته نشود، از مسیرِ زیرنویسِ LRC استفاده می‌شود.
    """
    value = inner.get("subtitle_body")
    if isinstance(value, str) and value.strip():
        return value
    return None


def fetch_strict(
    title: str,
    artist: str,
    album: str | None,
    duration_ms: int,
    *,
    video_id: str | None = None,
    isrc: str | None = None,
) -> Lyrics | None:
    """
    مثل `fetch`، ولی خطای گذرا را با `ProviderError` اعلام می‌کند.

    مسیر: `matcher.subtitle.get` (زیرنویسِ همگام). کلید فقط از config.
    """
    if not title or not artist or not MUSIXMATCH_API_KEY:
        return None

    params: dict[str, str] = {
        "q_track": title,
        "q_artist": artist,
        "apikey": MUSIXMATCH_API_KEY,
    }
    if isrc:
        params["track_isrc"] = isrc
    if duration_ms:
        params["f_subtitle_length"] = str(round(duration_ms / 1000))

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, proxy=PROXY) as client:
        try:
            res = client.get(f"{MUSIXMATCH_API}/matcher.subtitle.get", params=params)
        except Exception as exc:
            raise _error_from(exc) from exc

    if res.status_code in _EMPTY_STATUSES:
        return None
    if res.status_code >= 400:
        # ۴۰۱/۴۰۳ یعنی کلید نامعتبر یا پلنِ ناکافی — «نمی‌دانم»، نه «ندارم».
        raise ProviderError(_NAME, "http", status=res.status_code)

    try:
        body = res.json()
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc
    if not isinstance(body, dict):
        raise ProviderError(_NAME, "body", detail="not-an-object")

    status, inner = _envelope(body)
    if status in _EMPTY_BODY_CODES:
        return None
    if status != 200:
        # پلنِ ناکافی، ترکِ نامعتبر و بقیهٔ کدها اینجا می‌افتند.
        raise ProviderError(_NAME, "http", status=status if status > 0 else None)

    payload = _subtitle_text(inner)
    if not payload:
        return None

    # تطبیق: این API با عنوان/هنرمندِ *درخواستی* جستجو می‌کند و عنوانِ بازگشتی
    # را در پوششِ subtitle نمی‌دهد. پس تنها سیگنالِ قابلِ‌سنجش، مدت است — و
    # آن هم فقط اگر در پاسخ آمده باشد.
    #
    # `title_matches` عمداً اینجا معنا ندارد: نتیجه عنوان برنمی‌گرداند، پس
    # نبودِ آن «رد» نیست، «بی‌سیگنال» است. تنها چیزی که می‌تواند رد کند
    # مدتِ *متناقض* است.
    candidate_ms = _seconds_to_ms(inner.get("subtitle_length"))
    if duration_ms and candidate_ms and not duration_matches(candidate_ms, duration_ms):
        return None

    try:
        found = parse_enhanced_lrc(payload) or parse_lrc(payload)
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc
    return found


def _seconds_to_ms(value: object) -> int | None:
    if isinstance(value, (int, float)) and value > 0:
        return int(round(float(value) * 1000))
    return None


def fetch(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    """قرارداد عمومی — هر خطایی `None` می‌شود."""
    try:
        return fetch_strict(title, artist, album, duration_ms)
    except Exception:
        return None
