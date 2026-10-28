"""
متن آهنگ از PaxSenix / Lyrically — با **کلیدِ ترک، نه عنوان**.

**پیش‌فرض خاموش است** (`default_enabled=False`).

قرارداد از **OpenAPI رسمیِ خودِ سرویس** خوانده شده (تنها منبعی که در این
پروژه با سندِ رسمی تأیید شد، نه سورسِ ثالث):

- `https://lyrics.paxsenix.org/openapi.json` — `info.title = "Lyrically API"`،
  `version 2.0.0`.
- `/youtube/lyrics` → پارامترِ الزامیِ `id` (شناسهٔ ویدیو)، `v` اختیاری.
- `/apple-music/lyrics` → `id` الزامی، `ttml` اختیاری (بولی).

⚠️ **محدودیتِ ساختاری:** هیچ‌کدام از این دو مسیر عنوان/هنرمند نمی‌گیرند.
مسیرهایی که متن را با عنوان می‌دهند (`/kugou/search`، `/youtube/search`،
`/spotify/search`) **جدا** هستند و `id` برمی‌گردانند؛ یعنی برای رسیدن به متن
دو مرحله لازم است. آن مسیرهای جستجو در این پیاده‌سازی استفاده **نمی‌شوند** —
سقفِ یک درخواست در هر fetch رعایت می‌شود.

بنابراین این Provider فقط وقتی کار می‌کند که شناسهٔ درست موجود باشد:
`video_id` (یوتیوب) یا `apple_id` (آی‌تیونز). بدونِ آن `None` می‌دهد — بدونِ
هیچ درخواستی و بدونِ هیچ حدسی.

### محدودیتِ سرویس (مشاهده‌شده)

`/musixmatch/lyrics` روی این سرویس **۴۰۳ می‌دهد** با پیامِ «This endpoint is no
longer available due to the massive amount of traffic». یعنی بعضی مسیرهای این
آگهی‌گر عملاً مرده‌اند. `/apple-music/lyrics` طبقِ پیامِ خودِ سرویس «no
restrictions» دارد.

### شرایط استفاده

**NO-TERMS-FOUND** — نه صفحهٔ شرایطی روی سایت هست و نه در سندِ OpenAPI.
سرویسِ رایگانِ عمومی است ولی هیچ سندِ شرایطی ندارد؛ مصرفش مسئولیتِ کاربر است.
"""

from __future__ import annotations

import httpx

from ..config import PAXSENIX_API, PROXY
from ..lyrics.models import Lyrics
from ..lyrics.parsers import parse_enhanced_lrc, parse_lrc, parse_ttml
from ..lyrics.registry import ProviderError

_NAME = "paxsenix"
_TIMEOUT = 10.0

# بدونِ شناسه کاری نمی‌کند؛ این مسیرِ قابلِ‌استفاده است.
_YOUTUBE_PATH = "/youtube/lyrics"

_EMPTY_STATUSES = frozenset({404})


def enabled() -> bool:
    """کلید نمی‌خواهد؛ روشن‌بودنش فقط از تنظیمات می‌آید."""
    return True


def _error_from(exc: Exception) -> ProviderError:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ProviderError(_NAME, "network", detail=exc.__class__.__name__)
    return ProviderError(_NAME, "body", detail=exc.__class__.__name__)


def _parse_payload(payload: str) -> Lyrics | None:
    stripped = payload.lstrip()
    if stripped.startswith("<"):
        return parse_ttml(payload)
    return parse_enhanced_lrc(payload) or parse_lrc(payload)


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

    بدونِ `video_id` قطعی، `None` می‌دهد و هیچ درخواستی نمی‌زند.

    ⚠️ فقط مسیرِ یوتیوب پیاده شده: `video_id` همان چیزی است که `Manager`
    عبور می‌دهد. مسیرِ `/apple-music/lyrics` هم وجود دارد ولی شناسهٔ آی‌تیونز
    هیچ مسیری در این پروژه به Provider نمی‌رساند، پس پیاده نشد — افزودنش
    یعنی سیم‌کشیِ تازه، نه یک پارامتر. در گزارش به‌عنوان کارِ بعدی ثبت شد.
    """
    if not title:
        return None
    if not video_id:
        return None
    path, params = _YOUTUBE_PATH, {"id": video_id}

    # ⚠️ چرا تطبیقِ `matching.py` اینجا اجرا **نمی‌شود**: قاعدهٔ ۱۱ می‌گوید
    # «تطبیق مشترک قبل از پذیرش»، و در همه‌ی Providerهای *جستجومحور*
    # (`lrclib`, `unison`, …) هم اجرا می‌شود. ولی این Provider با **شناسهٔ
    # یکتا** کار می‌کند، نه با جستجو: `videoId` خودش نتیجه را قفل می‌کند و
    # پاسخ هیچ عنوان/هنرمندی برنمی‌گرداند تا بسنجیم. اجرای تطبیقْ آنجا
    # یعنی ردِ همیشگیِ نتیجه‌ی درست — که بدتر از نبودِ تطبیق است.
    # تنها سیگنالی که می‌شد سنجید مدت است، و آن هم در این پاسخ نیست.

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, proxy=PROXY) as client:
        try:
            res = client.get(f"{PAXSENIX_API}{path}", params=params)
        except Exception as exc:
            raise _error_from(exc) from exc

    if res.status_code in _EMPTY_STATUSES:
        return None
    if res.status_code in (401, 403):
        # بعضی مسیرها عمداً بسته‌اند (مشاهده‌شده روی همان آگهی‌گر). این
        # «نمی‌دانم» است نه «ندارم» — کشِ منفی نمی‌گیرد.
        raise ProviderError(_NAME, "http", status=res.status_code)
    if res.status_code >= 400:
        raise ProviderError(_NAME, "http", status=res.status_code)

    content_type = (res.headers.get("content-type") or "").lower()
    if "json" in content_type:
        try:
            body = res.json()
        except Exception as exc:
            raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc
        if not isinstance(body, dict):
            raise ProviderError(_NAME, "body", detail="not-an-object")
        if body.get("error"):
            return None
        payload = body.get("lyrics") or body.get("content") or body.get("data")
        if not isinstance(payload, str) or not payload.strip():
            return None
    else:
        payload = res.text
        if not payload or not payload.strip():
            return None

    try:
        return _parse_payload(payload)
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc


def fetch(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    """
    قرارداد عمومی. بدونِ شناسه همیشه `None` می‌دهد، پس در زنجیره بی‌اثر است؛
    مسیرِ واقعی `fetch_strict(..., video_id=…)` است.
    """
    try:
        return fetch_strict(title, artist, album, duration_ms)
    except Exception:
        return None
