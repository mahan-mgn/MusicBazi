"""
متن آهنگ از SimpMusic — بدون کلید، ولی **فقط با شناسه‌ی ویدیوی یوتیوب**.

**پیش‌فرض خاموش است** (`default_enabled=False`). کلید نمی‌خواهد ولی سرویسِ
ثالث با مجوزِ بررسی‌نشده است.

قرارداد از سورسِ عمومیِ خودِ پروژه:

- `maxrave-dev/core` (زیرماژولِ `maxrave-dev/SimpMusic`، شاخهٔ `multiplatform`،
  ماژول `service/lyricsService`) و `SimpMusic/…/lyrics`.
- `GET {base}/v1/{videoId}` — بدونِ احراز هویت برای خواندن.
- پوششِ `BaseResponse<T>` = `{success, error?, data?}`، و `error.code == 404`
  یعنی «متن ندارم» (نه خطا).
- `data.syncedLyrics` و `data.richSyncLyrics` رشته‌ی **LRC**‌اند، نه آرایه.

⚠️ **UNREACHABLE از جریانِ اصلی.**

کلیدِ جستجوی این سرویس `videoId` یوتیوب است، نه عنوان/هنرمند؛ این API
جستجوی متنی ندارد. ولی **هیچ مسیری در جریانِ اصلی این شناسه را به Provider
نمی‌رساند**:

- `Track` فیلدِ `videoId` ندارد (`app/models.py:24`) و `sourceUrl` هم برای
  ترک‌های اسپاتیفای/اپل/دیزر/ساندکلاد آدرسِ همان پلتفرم است، نه یوتیوب.
- `LyricsManager` هر Provider را با چهار آرگومانِ موقعیتی صدا می‌زند
  (`manager.py` → `entry.strict()(title, artist, album, duration_ms)`).
- Registry هم `fetch` چهار-آرگومانی را ثبت می‌کند، که `video_id` ندارد.
- تنها استخراج‌کنندهٔ واقعیِ videoId (`stream/playback.py:98`) فقط یک
  مصرف‌کننده دارد — resolveِ استریم در `stream/playback.py:301` — و به متن
  کاری ندارد.

نتیجه: `fetch_strict(...)` بدونِ `video_id` **همیشه `None`** می‌دهد و هیچ
درخواستی نمی‌زند. یعنی این Provider در زنجیره بی‌اثر است، حتی اگر با
`MUSICBAZI_LYRICS_PROVIDER_SIMPMUSIC_ENABLED=1` روشن شود.

تصمیمِ محافظه‌کارانه: حدس‌زدنِ شناسه انجام **نمی‌شود** — یعنی گرفتنِ متنِ
آهنگِ کاملاً دیگری. **پیشنهاد (پیاده نشد):** اگر روزی فیلدِ `videoId` به
`Track` اضافه شود و `Manager` آن را عبور بدهد، این Provider کار می‌کند. این
تغییرِ مدل و امضاست و باید با کاربر تصمیم گرفته شود.
"""

from __future__ import annotations

import re

import httpx

from ..config import PROXY, SIMPMUSIC_API
from ..lyrics.matching import score_candidate
from ..lyrics.models import Lyrics
from ..lyrics.parsers import parse_enhanced_lrc, parse_lrc
from ..lyrics.registry import ProviderError

_NAME = "simpmusic"
_TIMEOUT = 8.0

_EMPTY_STATUSES = frozenset({404})

# شناسه‌ی ویدیوی یوتیوب: ۱۱ کاراکتر از الفبای URL-safe.
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def enabled() -> bool:
    return True


def _error_from(exc: Exception) -> ProviderError:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ProviderError(_NAME, "network", detail=exc.__class__.__name__)
    return ProviderError(_NAME, "body", detail=exc.__class__.__name__)


def video_id_of(track_id: str) -> str | None:
    """
    شناسه‌ی ویدیو از `Track.id`، فقط وقتی قطعی باشد.

    قالبِ شناسه‌های پروژه `source:type:key` است (مثل `youtube:video:abc…`).
    اگر دنباله‌ی نهاییِ شناسه یک videoId معتبر نبود، `None` — هیچ حدسی زده
    نمی‌شود.
    """
    tail = (track_id or "").rsplit(":", 1)[-1]
    return tail if _VIDEO_ID.match(tail) else None


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

    بدونِ `video_id` قطعی، `None` می‌دهد. این «رد شدن» است نه «خطا» — پس
    کشِ منفی را هم مسدود نمی‌کند (مدیر آن را «خالیِ معتبر» نمی‌شمارد چون
    همان‌جا نتیجه‌ای نداشته). رفتارِ درست این است که Provider بعدی برود.

    `isrc` پذیرفته می‌شود ولی **استفاده نمی‌شود**: این API فقط `videoId`
    می‌شناسد و مسیرِ جستجوی ISRC ندارد. پارامتر فقط برای یکدستیِ امضای
    Providerها هست تا `Manager` یک شکل صدا بزند.
    """
    if not title:
        return None
    if not video_id or not _VIDEO_ID.match(video_id):
        return None

    with httpx.Client(
        timeout=_TIMEOUT,
        follow_redirects=True,
        proxy=PROXY,
        headers={"accept": "application/json", "user-agent": "MusicBazi/1.4"},
    ) as client:
        try:
            res = client.get(f"{SIMPMUSIC_API}/v1/{video_id}")
        except Exception as exc:
            raise _error_from(exc) from exc

    if res.status_code in _EMPTY_STATUSES:
        return None
    if res.status_code >= 400:
        raise ProviderError(_NAME, "http", status=res.status_code)

    try:
        body = res.json()
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc

    if not isinstance(body, dict):
        raise ProviderError(_NAME, "body", detail="not-an-object")

    error = body.get("error")
    if isinstance(error, dict) and error.get("code") == 404:
        return None
    if body.get("success") is not True:
        # `success:false` بدونِ کدِ ۴۰۴ یعنی خطای سرویس، نه «ندارم».
        raise ProviderError(_NAME, "body", detail="unsuccessful")

    data = body.get("data")
    if not isinstance(data, dict):
        return None

    synced = data.get("richSyncLyrics") or data.get("syncedLyrics")
    if not isinstance(synced, str) or not synced.strip():
        return None

    score = score_candidate(
        want_title=title,
        want_artist=artist,
        got_title=data.get("songTitle"),
        got_artist=data.get("artistName"),
        candidate_duration_ms=_seconds_to_ms(data.get("durationSeconds")),
        wanted_duration_ms=duration_ms or None,
    )
    if not score.acceptable:
        return None

    try:
        found = parse_enhanced_lrc(synced) or parse_lrc(synced)
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc
    if not found:
        return None

    language = data.get("language")
    return Lyrics(
        plain=found.plain,
        synced=found.synced,
        format=found.format,
        sync_type=found.sync_type,
        lines=found.lines,
        language=language if isinstance(language, str) else None,
    )


def _seconds_to_ms(value: object) -> int | None:
    if isinstance(value, (int, float)) and value > 0:
        return int(round(float(value) * 1000))
    return None


def fetch(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    """
    قرارداد عمومی. بدونِ `video_id` همیشه `None` می‌دهد (بالا توضیح داده شد)،
    پس در عمل از این تابع صدا زده نمی‌شود؛ `fetch_strict` با کلیدواژه‌ی
    `video_id` مسیرِ واقعی است.
    """
    try:
        return fetch_strict(title, artist, album, duration_ms)
    except Exception:
        return None
