"""
متن آهنگ از BiniLyrics — بدون کلید، جستجو + فایلِ TTML جدا.

**پیش‌فرض خاموش است** (`default_enabled=False`).

قرارداد از سورسِ عمومیِ وب‌سایت خودش (تنها منبعِ موجود؛ SDK رسمی ندارد):

- `binimum/bini-lyrics-website` → `src/routes/api/lookup/+server.ts` (ساختِ
  `https://lyrics-api.binimum.org/?${params}`)، `src/lib/search.ts` (پارامترها)،
  `src/lib/types.ts` (شکلِ پاسخ)، `src/lib/server/api.ts` (۴۲۹ → ۴۲۹، بقیه → ۵۰۲،
  تایم‌اوتِ ۱۲ ثانیه).
- مستنداتِ عمومی: `https://binimum.github.io`.

جریانِ دو مرحله‌ای: `GET /?track=&artist=` یک فهرست می‌دهد و هر نتیجه یک
`lyricsUrl` دارد که به فایلِ **TTML** روی `lyrics-storage.binimum.org` اشاره
می‌کند. متن در پاسخِ جستجو نیست، پس برای هر نتیجه یک درخواستِ دوم لازم است.

محدودیتِ تعدادِ درخواست: حداکثر `_MAX_DOCS` فایلِ TTML در هر fetch خوانده
می‌شود. یک جستجوی بی‌ربط می‌تواند ده‌ها نتیجه بدهد و خواندنِ همه‌شان یعنی
حمله به یک سرویسِ رایگان — و کندیِ پخش.
"""

from __future__ import annotations

import httpx

from ..config import BINILYRICS_API, PROXY
from ..lyrics.matching import rank_candidates, score_candidate
from ..lyrics.models import Lyrics
from ..lyrics.parsers import parse_ttml
from ..lyrics.registry import ProviderError

_NAME = "binilyrics"
_TIMEOUT = 12.0

# نتیجه‌ای نیست.
_EMPTY_STATUSES = frozenset({404})

# سقفِ درخواستِ فایلِ TTML در هر fetch. اولویت‌دارترین نتایج اول خوانده می‌شوند.
_MAX_DOCS = 3


def enabled() -> bool:
    return True


def _error_from(exc: Exception) -> ProviderError:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ProviderError(_NAME, "network", detail=exc.__class__.__name__)
    return ProviderError(_NAME, "body", detail=exc.__class__.__name__)


def _search(client: httpx.Client, title: str, artist: str, album: str | None, duration_ms: int) -> list[dict]:
    params: dict[str, str] = {"track": title, "artist": artist}
    if album:
        params["album"] = album
    if duration_ms:
        params["duration"] = str(round(duration_ms / 1000))

    try:
        res = client.get(BINILYRICS_API, params=params)  # مسیرِ ریشه
    except Exception as exc:
        raise _error_from(exc) from exc

    if res.status_code in _EMPTY_STATUSES:
        return []
    if res.status_code >= 400:
        raise ProviderError(_NAME, "http", status=res.status_code)

    try:
        body = res.json()
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc

    if not isinstance(body, dict):
        raise ProviderError(_NAME, "body", detail="not-an-object")
    results = body.get("results")
    if not isinstance(results, list):
        raise ProviderError(_NAME, "body", detail="no-results-field")
    return [row for row in results if isinstance(row, dict)]


def _rank(rows: list[dict], title: str, artist: str, duration_ms: int) -> list[dict]:
    """
    نتایج را با منطقِ مشترک مرتب کن.

    این Provider چهارده سیگنالِ نسخه ندارد، ولی مدت را در هر نتیجه می‌دهد
    (که Genius ندارد). پس همان `matching.py` هم فیلترِ ناهمخوان را می‌دهد و
    هم ترتیبِ «هم‌مدت اول».
    """
    scored = []
    for idx, row in enumerate(rows):
        score = score_candidate(
            want_title=title,
            want_artist=artist,
            got_title=row.get("track_name"),
            got_artist=row.get("artist_name"),
            candidate_duration_ms=_seconds_to_ms(row.get("duration")),
            wanted_duration_ms=duration_ms or None,
        )
        if score.acceptable:
            scored.append((idx, score))
    return [rows[idx] for idx in rank_candidates(scored)]


def _fetch_ttml(client: httpx.Client, url: str) -> Lyrics | None:
    try:
        res = client.get(url)
    except Exception as exc:
        raise _error_from(exc) from exc
    if res.status_code in _EMPTY_STATUSES:
        return None
    if res.status_code >= 400:
        raise ProviderError(_NAME, "http", status=res.status_code)
    try:
        return parse_ttml(res.text)
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc


def fetch_strict(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    """
    مثل `fetch`، ولی خطای گذرا را با `ProviderError` اعلام می‌کند.

    تطبیقِ مشترک **قبل** از خواندنِ فایلِ TTML اجرا می‌شود: بی‌آن، یک جستجوی
    بی‌ربط چند درخواستِ اضافه می‌زند و بعد هم متنِ آهنگِ دیگری را برمی‌گرداند.

    خطای یک فایلِ TTML بقیه را از بین نمی‌برد: اگر اولی خراب بود، بعدی
    امتحان می‌شود. ولی خطای *شبکه* در جستجو `ProviderError` می‌دهد، چون
    یعنی «نتوانستم بپرسم» نه «ندارم».
    """
    if not title or not artist:
        return None

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, proxy=PROXY) as client:
        rows = _search(client, title, artist, album, duration_ms)
        if not rows:
            return None

        ranked = _rank(rows, title, artist, duration_ms)
        for row in ranked[:_MAX_DOCS]:
            url = row.get("lyricsUrl")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            found = _fetch_ttml(client, url)
            if found and found.lines:
                return Lyrics(
                    plain=found.plain,
                    format=found.format,
                    sync_type=found.sync_type,
                    lines=found.lines,
                    language=found.language,
                )
    return None


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
