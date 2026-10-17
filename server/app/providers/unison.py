"""
متن آهنگ از Unison — بدون کلید، LRC یا TTML یا متنِ ساده می‌دهد.

**پیش‌فرض خاموش است** (`default_enabled=False`): سرویسِ ثالث با مجوزِ
بررسی‌نشده. با `MUSICBAZI_LYRICS_PROVIDER_UNISON_ENABLED=1` روشن می‌شود.

قرارداد از سورسِ عمومیِ خودِ سرویس و کلاینتِ مرجعش:

- `better-lyrics/unison` → `src/routes/lyrics.ts` (دو شاخه‌ی `?v=` و
  `?song=&artist=`، کدِ خطای `MISSING_QUERY`)،
  `src/routes/lyrics.transformers.ts` (`toResponse`: نامِ فیلدها)،
  `src/utils/errors.ts` و `src/utils/read-rate-limit.ts` (۴۲۹)، `README.md`.
- `ibratabian17/YouLyPlus` → `src/background/services/unisonService.js`
  (آدرسِ پایه، شکلِ `success`/`data`، تایم‌اوتِ ۸ ثانیه)،
  `src/background/utils/dataParser.js:parseUnisonFormat`.

تفاوتِ مهم با بقیه‌ی Providerها: **Unison متن را به‌صورت رشته می‌دهد نه آرایه.**
`data.lyrics` یک رشته است و `data.format` می‌گوید چه نوعی (`lrc`/`ttml`/`plain`).
پس این Provider اولین مصرف‌کننده‌ی واقعیِ `lyrics/parsers.py` است.
"""

from __future__ import annotations

import httpx

from ..config import PROXY, UNISON_API
from ..lyrics.matching import score_candidate
from ..lyrics.models import Lyrics
from ..lyrics.parsers import parse_enhanced_lrc, parse_lrc, parse_ttml
from ..lyrics.registry import ProviderError

_NAME = "unison"
_TIMEOUT = 8.0

_PATH = "/lyrics"

# ۴۰۴ (`code: "NOT_FOUND"`) یعنی «این ترک را ندارم».
_EMPTY_STATUSES = frozenset({404})

# `syncType` سرویس → `sync_type` ما. `richsync` یعنی کلمه‌ای.
_SYNC_TYPES = {"richsync": "word", "linesync": "line", "plain": "plain"}


def enabled() -> bool:
    return True


def _error_from(exc: Exception) -> ProviderError:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ProviderError(_NAME, "network", detail=exc.__class__.__name__)
    return ProviderError(_NAME, "body", detail=exc.__class__.__name__)


def _parse_payload(payload: str, fmt: str) -> Lyrics | None:
    """
    رشته‌ی خام → `Lyrics`، با پارسر مناسبِ خودش.

    `format` تعیین می‌کند، ولی اگر خودش نبود از محتوا حدس زده می‌شود: یک
    `<` در ابتدای رشته TTML است. هیچ‌وقت متن را «ساده» فرض نمی‌کنیم اگر
    تگِ زمان دارد — همان چیزی که ترکِ کاربر را از نسخه‌ی هم‌زمان محروم می‌کرد.
    """
    kind = (fmt or "").strip().lower()
    if kind == "ttml" or (not kind and payload.lstrip().startswith("<")):
        return parse_ttml(payload)
    if kind in ("lrc", "enhanced_lrc", "richsync"):
        return parse_enhanced_lrc(payload) or parse_lrc(payload)
    if kind == "plain":
        return None  # متنِ بی‌زمان برای این پروژه «هم‌زمان‌نشده» است
    # ناشناخته: هر دو را امتحان کن
    return parse_ttml(payload) or parse_enhanced_lrc(payload) or parse_lrc(payload)


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
    `video_id` و `isrc` پذیرفته می‌شوند ولی **استفاده نمی‌شوند**: این منبع
    کلیدش عنوان/هنرمند است. پارامترها فقط برای یکدستیِ امضای Providerها
    هستند تا `Manager` همه را با یک شکل صدا بزند.

    مثل `fetch`، ولی خطای گذرا را با `ProviderError` اعلام می‌کند.

    این سرویس شناسه‌ی ویدیو (`v=`) را ترجیح می‌دهد ولی ما آن را نداریم و
    از `song`+`artist` استفاده می‌کنیم (شاخه‌ی دومِ سورس). طبقه‌بندی خطا مثل
    بقیه: ۴۰۴ → `None`، بقیه‌ی ۴xx/۵xx و ۴۲۹ → `ProviderError(http)`.
    """
    if not title or not artist:
        return None

    params: dict[str, str] = {"song": title, "artist": artist}
    if album:
        params["album"] = album
    if duration_ms:
        params["duration"] = str(round(duration_ms / 1000))

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, proxy=PROXY) as client:
        try:
            res = client.get(f"{UNISON_API}{_PATH}", params=params)
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
    if body.get("success") is not True:
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        return None

    payload = data.get("lyrics")
    if not isinstance(payload, str) or not payload.strip():
        return None

    # تطبیق مشترک قبل از پذیرش: این سرویس ممکن است نسخه‌ی دیگری را برگرداند.
    score = score_candidate(
        want_title=title,
        want_artist=artist,
        got_title=data.get("song"),
        got_artist=data.get("artist"),
        candidate_duration_ms=_seconds_to_ms(data.get("duration")),
        wanted_duration_ms=duration_ms or None,
    )
    if not score.acceptable:
        return None

    try:
        found = _parse_payload(payload, data.get("format") or "")
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc
    if not found:
        return None

    language = data.get("language")
    return Lyrics(
        plain=found.plain,
        synced=found.synced,
        source=found.source,
        format=found.format,
        # برچسبِ هم‌زمانی را از خودِ سرویس ترجیح بده، ولی اگر با محتوا نخواند
        # محتوا برنده است — `syncType` فقط یک ادعاست.
        sync_type=_reconcile_sync(data.get("syncType"), found.sync_type),
        lines=found.lines,
        language=language if isinstance(language, str) else found.language,
    )


def _reconcile_sync(claimed: object, actual: str | None) -> str | None:
    """
    ادعای سرویس درباره‌ی نوعِ هم‌زمانی در برابر واقعیتِ محتوا.

    فایلی که `richsync` نامیده شده ولی هیچ تگِ کلمه ندارد نباید `word` برچسب
    بخورد؛ UI روی همین فیلد تصمیم می‌گیرد.
    """
    expected = _SYNC_TYPES.get(claimed if isinstance(claimed, str) else "", None)
    if expected is None:
        return actual
    if expected == "word" and actual != "word":
        return actual
    return expected


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
