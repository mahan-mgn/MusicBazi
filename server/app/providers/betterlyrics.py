"""
متن آهنگ از BetterLyrics — بدون کلید، همان میزبانِ Unisonِ خودش.

**پیش‌فرض خاموش است** (`default_enabled=False`).

قرارداد از سورسِ عمومیِ خودِ افزونه:

- `better-lyrics/better-lyrics` → `src/core/constants.ts`
  (میزبانِ `https://unison.betterlyrics.org`)،
  `src/modules/lyrics/providers/unison.ts` (ساختِ درخواست، ۴۰۴ = «ندارم»،
  `x-key-id` اختیاری)، `src/modules/lyrics/providers/shared.ts` (مدلِ داخلی).

⚠️ **هم‌پوشانیِ عمدی با `unison.py`:** این افزونه متن را از یک میزبانِ
*دیگر* ولی با *همان* قراردادِ Unison می‌گیرد (`data.lyrics` رشته‌ای با
`data.format`). پس دو Provider ثبت‌شده‌اند نه یکی: همان قرارداد، دو مبدأِ
داده. اگر روزی یکی از دو میزبان از کار بیفتد، دیگری مستقل کار می‌کند.

هزینه‌اش این است که وقتی هر دو روشن باشند یک ترک را دو بار از دو میزبان
می‌پرسند. چون هر دو **پیش‌فرض خاموش‌اند** این هزینه پرداخت نمی‌شود.

---

### UNVERIFIED INFERENCE

این موارد از سورسِ افزونه استنباط شده‌اند، نه از سندِ خودِ میزبان؛ اگر
رفتاری غیرِ این دیدید، **اینجا** باید عوض شود:

- **مسیرِ `/lyrics` روی میزبانِ betterlyrics** — سورسِ افزونه میزبانِ
  `unison.betterlyrics.org` را نشان می‌دهد، ولی مسیرِ دقیقِ همان میزبان
  جداگانه مستند نشده (از قراردادِ مشترکِ Unison استنباط شده).
- **شکلِ پاسخ** (`data.lyrics` رشته + `data.format`) — از سورسِ افزونه،
  نه از سندِ خودِ سرویس.
- **نبودنِ `success` در بعضی پاسخ‌ها** و اینکه بشود به آن وابسته نبود —
  استنباط.
- **پارامترهای `song`/`artist`/`album`/`duration`** — نامشان از قراردادِ
  مشترکِ Unison گرفته شده؛ رفتارِ خودِ میزبانِ betterlyrics سندی ندارد.
- **۴۰۴ = «ندارم»** — استنباط (در Unison دیده شده، اینجا فرض شده).
- **احرازِ هویت: هیچ** — سورس `x-key-id` اختیاری نشان می‌دهد؛ تضمینی نیست
  که بدونش همیشه کار کند.
"""

from __future__ import annotations

import httpx

from ..config import BETTERLYRICS_API, PROXY
from ..lyrics.matching import score_candidate
from ..lyrics.models import Lyrics
from ..lyrics.parsers import parse_enhanced_lrc, parse_lrc, parse_ttml
from ..lyrics.registry import ProviderError

_NAME = "betterlyrics"
_TIMEOUT = 10.0

_PATH = "/lyrics"
_EMPTY_STATUSES = frozenset({404})

_SYNC_TYPES = {"richsync": "word", "linesync": "line", "plain": "plain"}


def enabled() -> bool:
    return True


def _error_from(exc: Exception) -> ProviderError:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ProviderError(_NAME, "network", detail=exc.__class__.__name__)
    return ProviderError(_NAME, "body", detail=exc.__class__.__name__)


def _parse_payload(payload: str, fmt: str) -> Lyrics | None:
    kind = (fmt or "").strip().lower()
    if kind == "ttml" or (not kind and payload.lstrip().startswith("<")):
        return parse_ttml(payload)
    if kind in ("lrc", "enhanced_lrc", "richsync"):
        return parse_enhanced_lrc(payload) or parse_lrc(payload)
    if kind == "plain":
        return None
    return parse_ttml(payload) or parse_enhanced_lrc(payload) or parse_lrc(payload)


def _reconcile_sync(claimed: object, actual: str | None) -> str | None:
    expected = _SYNC_TYPES.get(claimed if isinstance(claimed, str) else "", None)
    if expected is None:
        return actual
    if expected == "word" and actual != "word":
        return actual
    return expected


def fetch_strict(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    """مثل `fetch`، ولی خطای گذرا را با `ProviderError` اعلام می‌کند."""
    if not title or not artist:
        return None

    params: dict[str, str] = {"song": title, "artist": artist}
    if album:
        params["album"] = album
    if duration_ms:
        params["duration"] = str(round(duration_ms / 1000))

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, proxy=PROXY) as client:
        try:
            res = client.get(f"{BETTERLYRICS_API}{_PATH}", params=params)
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

    # این میزبان هم همان پوششِ `data` را دارد؛ بعضی پاسخ‌ها بدونِ `success`
    # می‌آیند، پس اگر `data` بود قبول می‌کنیم و به `success` وابسته نمی‌شویم.
    data = body.get("data")
    if not isinstance(data, dict):
        return None

    payload = data.get("lyrics")
    if not isinstance(payload, str) or not payload.strip():
        return None

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
        format=found.format,
        sync_type=_reconcile_sync(data.get("syncType"), found.sync_type),
        lines=found.lines,
        language=language if isinstance(language, str) else found.language,
    )


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
