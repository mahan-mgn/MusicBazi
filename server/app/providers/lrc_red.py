"""
متن آهنگ از lrc.red — بدون کلید، TTML یا LRC.

**پیش‌فرض خاموش است** (`default_enabled=False`).

⚠️ **قرارداد فقط «جزئی» تأیید شده:** خودِ lrc.red سورسِ عمومی ندارد (مالکش
`w4v` فقط پروژه‌های بی‌ربط دارد). آن‌چه اینجا پیاده شده از *سه کلاینتِ
متن‌بازِ ثالث* بازسازی شده که هر سه به همین سرویس حرف می‌زنند:

- `binimum/am-lyrics` → `src/AmLyrics.ts` (`fetchLyricsFromLrcRed`: `/s/{isrc}.ttml`،
  `/match.json`، `/search.json`، `payload.hits[0].isrc`، تایم‌اوتِ ۳ ثانیه).
- `better-lyrics/api` → `services/providers/ttml/lrcred.go` (GET `/s/{isrc}.ttml`،
  `Accept: application/ttml+xml`، ۴۲۹ → احترام به `Retry-After`).
- `zoltrons/betterlyrics-picard` → `/s/{ISRC}.json`، `/search.json?q=&after=`،
  پوششِ `hits`/`next`.

پس این Provider طبقِ بندِ B.10 «قراردادِ تأییدنشده» نیست (سه منبعِ مستقلِ
قابل‌خواندن دارد) ولی «تأییدشده از سورسِ رسمی» هم نیست. تصمیم محافظه‌کارانه:
از دو مسیرِ کم‌ریسک‌تر استفاده می‌شود — `search.json` بعد فایل — و از
`/match.json` که شکلِ پاسخش **تأیید نشده** صرف‌نظر شده است.

متنِ TTML را از `/s/{ISRC}.ttml` می‌گیریم و به `lyrics/parsers.py` می‌دهیم.

**کلیدِ تطبیق:** این سرویس با ISRC کار می‌کند ولی `Track` هیچ ISRC ندارد.
پس تطبیق **با ISRC انجام نمی‌شود**؛ بلکه:

1. `GET /search.json?q=<artist> <title>` زده می‌شود (جستجوی متنی).
2. تطبیقِ مشترکِ `matching.py` روی `title`/`artist`/`duration` هر `hit`
   اجرا می‌شود و `acceptable` فقط برای همان‌ها قبول است.
3. برای بهترین hitِ قبول‌شده، `hit["isrc"]` **از خودِ پاسخ** خوانده
   می‌شود — ISRC ورودی است، نه چیزی که ما بدانیم.
4. فایل با `/s/{همان isrc}.ttml` گرفته می‌شود (و در ۴۰۴ به `.lrc` می‌افتد).

پس اگر `search.json` نتیجه‌ای بدونِ فیلدِ `isrc` بدهد، آن hit رد می‌شود
(تستِ `test_a_hit_without_an_isrc_is_skipped`) و هیچ درخواستِ دومی نمی‌رود.

---

### UNVERIFIED INFERENCE

مواردی که از کلاینتِ ثالث استنباط شده‌اند، نه از سندِ رسمی؛ اگر روزی رفتاری
غیرِ این دیدید، **اینجا** باید عوض شود:

- **شکلِ پاسخِ `/search.json`** (`{"hits": [...], "next": ...}`) — فقط در
  `zoltrons/betterlyrics-picard` دیده شده؛ سندِ رسمی ندارد.
- **نامِ فیلدهای داخلِ hit** (`isrc`, `title`, `artist`, `duration`) — از
  همان کلاینت استنباط شده، نه از پاسخِ مستندِ lrc.red.
- **دقیقاً کدام قالب اول است** (`.ttml` یا `.lrc` در مسیرِ `/s/`) — ترتیبِ
  TTML-اول یک انتخابِ این پیاده‌سازی است.
- **۴۰۴ روی `/s/{isrc}.ttml` یعنی «این قالب را ندارم»** — استنباط.
- **نوحه‌ی احرازِ هویت برای خواندن: هیچ** — در هر سه کلاینت خواندن بدونِ
  کلید است، ولی این «بدونِ کلید بودنش تضمین‌شده» نیست.
"""

from __future__ import annotations

import httpx

from ..config import LRC_RED_API, PROXY
from ..lyrics.matching import rank_candidates, score_candidate
from ..lyrics.models import Lyrics
from ..lyrics.parsers import parse_enhanced_lrc, parse_lrc, parse_ttml
from ..lyrics.registry import ProviderError

_NAME = "lrc_red"
_TIMEOUT = 8.0

_EMPTY_STATUSES = frozenset({404})

# حداکثر چند نتیجه‌ی جستجو دنبال شود.
_MAX_HITS = 3


def enabled() -> bool:
    return True


def _error_from(exc: Exception) -> ProviderError:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ProviderError(_NAME, "network", detail=exc.__class__.__name__)
    return ProviderError(_NAME, "body", detail=exc.__class__.__name__)


def _search(client: httpx.Client, title: str, artist: str) -> list[dict]:
    try:
        res = client.get(f"{LRC_RED_API}/search.json", params={"q": f"{artist} {title}".strip()})
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
    hits = body.get("hits")
    if not isinstance(hits, list):
        raise ProviderError(_NAME, "body", detail="no-hits-field")
    return [row for row in hits if isinstance(row, dict)]


def _rank(hits: list[dict], title: str, artist: str, duration_ms: int) -> list[dict]:
    scored = []
    for idx, row in enumerate(hits):
        score = score_candidate(
            want_title=title,
            want_artist=artist,
            got_title=row.get("title"),
            got_artist=row.get("artist"),
            candidate_duration_ms=_seconds_to_ms(row.get("duration")),
            wanted_duration_ms=duration_ms or None,
        )
        if score.acceptable:
            scored.append((idx, score))
    return [hits[idx] for idx in rank_candidates(scored)]


def _fetch_document(client: httpx.Client, isrc: str) -> Lyrics | None:
    """
    متنِ یک ISRC را بگیر.

    اول TTML (داده‌ی کلمه‌ای داریم) و بعد LRC به‌عنوان پشتیبان. ۴۰۴ یعنی این
    قالب برای این ترک نیست، نه خطا — پس می‌رود سراغ قالبِ بعدی.
    """
    for suffix, parser in (("ttml", parse_ttml), ("lrc", parse_enhanced_lrc)):
        try:
            res = client.get(
                f"{LRC_RED_API}/s/{isrc}.{suffix}",
                headers={"accept": "application/ttml+xml" if suffix == "ttml" else "text/plain"},
            )
        except Exception as exc:
            raise _error_from(exc) from exc
        if res.status_code in _EMPTY_STATUSES:
            continue
        if res.status_code >= 400:
            raise ProviderError(_NAME, "http", status=res.status_code)
        try:
            found = parser(res.text)
        except Exception as exc:
            raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc
        if found and found.lines:
            return found
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
    `video_id` و `isrc` پذیرفته می‌شوند ولی **استفاده نمی‌شوند**: این منبع
    کلیدش عنوان/هنرمند است. پارامترها فقط برای یکدستیِ امضای Providerها
    هستند تا `Manager` همه را با یک شکل صدا بزند.
مثل `fetch`، ولی خطای گذرا را با `ProviderError` اعلام می‌کند."""
    if not title or not artist:
        return None

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, proxy=PROXY) as client:
        hits = _search(client, title, artist)
        if not hits:
            return None
        for row in _rank(hits, title, artist, duration_ms)[:_MAX_HITS]:
            isrc = row.get("isrc")
            if not isinstance(isrc, str) or not isrc.strip():
                continue
            found = _fetch_document(client, isrc.strip())
            if found and found.lines:
                return Lyrics(
                    plain=found.plain,
                    synced=found.synced,
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
