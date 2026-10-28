"""
متن آهنگ از LRCLIB — عمومی، بدون کلید، هم متن ساده می‌دهد هم هم‌زمان‌شده (LRC).

بلاک‌کننده است: از داخل thread دانلود صدا زده می‌شود، درست بعد از اینکه فایل
روی دیسک نشست و قبل از تگ‌گذاری.
"""

from __future__ import annotations

import httpx

from ..config import LRCLIB_API, PROXY
from ..lyrics.models import Lyrics
from ..lyrics.registry import ProviderError

# LRCLIB در راهنمایش می‌خواهد کلاینت خودش را معرفی کند
_HEADERS = {"user-agent": "MusicBazi/1.4 (https://github.com/mahan-mgn/MusicBazi)"}
_TIMEOUT = 8.0

_NAME = "lrclib"
# 404 «چیزی نیست» است نه خطا؛ بقیه‌ی کدهای >=400 یعنی درخواست نرسید یا رد شد.
_EMPTY_STATUSES = frozenset({404})


# بیشتر از این اختلاف یعنی احتمالاً نسخه‌ی دیگری‌ست: ریمیکس، لایو یا کاور.
_DURATION_TOLERANCE_S = 5


def _from_row(row: dict) -> Lyrics:
    plain = row.get("plainLyrics") or None
    synced = row.get("syncedLyrics") or None
    return Lyrics(
        plain=plain,
        synced=synced,
        format="lrc" if synced else "plain",
        sync_type="line" if synced else "plain",
    )


def _best(rows: list[dict]) -> dict:
    """متن هم‌زمان‌شده ارزش بیشتری دارد، پس اولِ لیست می‌نشیند."""
    rows.sort(key=lambda r: (not r.get("syncedLyrics"), not r.get("plainLyrics")))
    return rows[0]


def _pick_by_duration(rows: list[dict], seconds: int | None) -> dict | None:
    """
    ردیفِ مناسب را از میان نتایج جستجو انتخاب کن.

    قاعده: مدت‌زمان تنها سیگنالِ قابل‌اتکا برای تشخیص نسخه است، پس وقتی مدتِ
    خودمان را می‌دانیم فقط ردیف‌هایی پذیرفته می‌شوند که با آن بخوانند. «مدتِ
    نامعلوم» با «مدتِ متناقض» یکی نیست: ردیفی که اصلاً مدت اعلام نکرده چیزی
    را رد نکرده، ولی ردیفی که مدتِ دیگری اعلام کرده *شاهدِ مخالف* است.

    پس ترتیب: اول ردیف‌های هم‌مدت؛ اگر نبود، ردیف‌های بی‌مدت (fallback کنترل‌شده
    — دلیلی برای ردشان نداریم)؛ اگر همه مدت داشتند و هیچ‌کدام نخواند، هیچ.
    وقتی مدت خودمان نامعلوم است (۰) هیچ فیلتری معنا ندارد و رفتار قبلی می‌ماند.
    """
    if not seconds:
        return _best(rows)

    within = [
        r for r in rows
        if (d := r.get("duration")) and abs(d - seconds) <= _DURATION_TOLERANCE_S
    ]
    if within:
        return _best(within)

    unknown = [r for r in rows if not r.get("duration")]
    if unknown:
        return _best(unknown)

    return None


def _error_from(exc: Exception) -> ProviderError:
    """خطای httpx را به ProviderError با دسته‌ی درست تبدیل کن."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ProviderError(_NAME, "network", detail=exc.__class__.__name__)
    return ProviderError(_NAME, "body", detail=exc.__class__.__name__)


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

    تفکیک: `None` یعنی «جستجو شد و متنی نبود» (۴۰۴، لیست خالی، هیچ نتیجه‌ی
    همخوان) — و `ProviderError` یعنی «نتوانستم بپرسم». کشِ منفی فقط اولی را
    می‌گیرد؛ اگر دومی را هم می‌گرفت، یک قطعیِ گذرا متنِ موجود را مخفی می‌کرد.

    اول تطابق دقیق (که مدت‌زمان را هم چک می‌کند)، بعد جستجوی آزاد. مسیر دقیق
    ارزش امتحان جدا را دارد: وقتی جواب می‌دهد، همان نسخه‌ی درست است و لازم
    نیست بین چند نتیجه‌ی مشابه حدس بزنیم.
    """
    if not title:
        return None

    seconds = round(duration_ms / 1000) if duration_ms else None

    with httpx.Client(
        timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True, proxy=PROXY
    ) as client:
        params: dict[str, str] = {"track_name": title, "artist_name": artist}
        if album:
            params["album_name"] = album
        if seconds:
            params["duration"] = str(seconds)

        try:
            res = client.get(f"{LRCLIB_API}/api/get", params=params)
        except Exception as exc:
            raise _error_from(exc) from exc

        if res.status_code == 200:
            try:
                found = _from_row(res.json())
            except Exception as exc:
                raise ProviderError(
                    _NAME, "body", detail=exc.__class__.__name__
                ) from exc
            if found:
                return found
        elif res.status_code not in _EMPTY_STATUSES and res.status_code >= 400:
            raise ProviderError(_NAME, "http", status=res.status_code)

        try:
            res = client.get(
                f"{LRCLIB_API}/api/search",
                params={"track_name": title, "artist_name": artist},
            )
        except Exception as exc:
            raise _error_from(exc) from exc

        if res.status_code in _EMPTY_STATUSES:
            return None
        if res.status_code >= 400:
            raise ProviderError(_NAME, "http", status=res.status_code)

        try:
            rows = res.json()
        except Exception as exc:
            raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc

    if not isinstance(rows, list) or not rows:
        return None

    # JSON معتبر ولی ساختار غیرمنتظره: ردیفی که دیکشنری نیست، یا مدتِ غیرعددی.
    # اینها خطای *بدنه*اند نه «خالی» — اگر بی‌صدا رد شوند، یک پاسخِ خرابِ
    # پایدار مثل «این ترک را ندارم» به کشِ منفی می‌رود و متنِ موجود را پنهان
    # می‌کند. `_pick_by_duration` و `_from_row` هر دو فرضِ دیکشنری دارند.
    try:
        row = _pick_by_duration(rows, seconds)
        if row is None:
            return None
        return _from_row(row) or None
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc


def fetch(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    """
    قرارداد عمومی — دست‌نخورده: هر خطایی `None` می‌شود.

    فراخوان‌های قدیمی (و هر کدی که فقط «متن یا هیچ» می‌خواهد) همین را صدا
    می‌زنند. آن‌که باید خطا را ببیند، `fetch_strict` را صدا می‌زند.
    """
    try:
        return fetch_strict(title, artist, album, duration_ms)
    except Exception:
        return None
