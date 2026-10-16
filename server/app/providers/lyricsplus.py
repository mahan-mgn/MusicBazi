"""
متن آهنگ از LyricsPlus (بک‌اندِ KpoeTools) — بدون کلید، خط و کلمه می‌دهد.

**پیش‌فرض خاموش است** (`default_enabled=False` در `lyrics/manager.py`): سرویسِ
ثالثی است که مجوز و شرایطِ استفاده‌اش بررسی نشده و تا کاربر تصمیم نگیرد
نباید در زنجیره‌ی خودکار بیاید. با `MUSICBAZI_LYRICS_PROVIDER_LYRICSPLUS_ENABLED=1`
روشن می‌شود.

قرارداد از سورسِ عمومیِ خودِ بک‌اند و کلاینتِ مرجعش استخراج شده، نه از حدس:

- `ibratabian17/LyricsPlus` → `docs/endpoints.md`، `internal/api/server.go`
  (جدولِ مسیرها)، `internal/api/handlers/lyrics.go` (پارسِ پارامترها)،
  `internal/api/openapi/openapi.yaml` (`Line.time` = میلی‌ثانیه).
- `ibratabian17/YouLyPlus` → `src/background/services/kpoeService.js` (ساختِ URL،
  رفتار ۴۰۴/۴۰۳، تایم‌اوتِ ۸ ثانیه)، `src/background/constants.js` (فهرستِ میزبان‌ها).

میزبان‌ها: کلاینتِ مرجع بین چند میزبان می‌چرخد. اینجا فقط یکی (قابلِ‌تنظیم با
`MUSICBAZI_LYRICSPLUS_API`) استفاده می‌شود — چرخشِ خودکار یعنی رفتارِ غیرقابلِ
پیش‌بینی و چند برابر درخواست به سرویسِ رایگان. میزبان‌های جایگزین در گزارش ثبت
شده‌اند تا کاربر خودش انتخاب کند.
"""

from __future__ import annotations

import httpx

from ..config import LYRICSPLUS_API, PROXY
from ..lyrics.matching import score_candidate
from ..lyrics.models import LyricLine, LyricWord, Lyrics
from ..lyrics.registry import ProviderError

_NAME = "lyricsplus"
_TIMEOUT = 8.0

# فقط مسیری که واقعاً استفاده می‌کنیم. سرویس `/v1/*` هم دارد ولی نسخه‌ی ۲
# ساختارِ خط/هجا را تمیزتر می‌دهد و همان چیزی است که کلاینتِ مرجع صدا می‌زند.
_PATH = "/v2/lyrics/get"

# ۴۰۴ یعنی «این ترک را ندارم» — تنها کدی که «خالی» حساب می‌شود.
_EMPTY_STATUSES = frozenset({404})

# نوعِ هم‌زمان‌سازیِ خودِ سرویس → `sync_type` مدل ما.
_SYNC_TYPES = {"word": "word", "syllable": "syllable", "line": "line", "none": "plain"}


def enabled() -> bool:
    """این Provider کلید نمی‌خواهد؛ روشن‌بودنش فقط از تنظیمات می‌آید."""
    return True


def _error_from(exc: Exception) -> ProviderError:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ProviderError(_NAME, "network", detail=exc.__class__.__name__)
    return ProviderError(_NAME, "body", detail=exc.__class__.__name__)


def _syllables(row: dict) -> tuple[LyricWord, ...]:
    """
    `syllabus[]` → کلمه/هجاهای زمان‌دار.

    فیلد در سورس `syllabus` است (نه `syllables`). هر عنصر `{time, duration,
    text}` با میلی‌ثانیه. عنصری که متنِ غیرخالی ندارد دور ریخته می‌شود، وگرنه
    یک کلمه‌ی خالی در UI یک بازه‌ی رنگِ بی‌متن می‌سازد.
    """
    out: list[LyricWord] = []
    for syllable in row.get("syllabus") or []:
        if not isinstance(syllable, dict):
            continue
        text = syllable.get("text")
        start = syllable.get("time")
        if not isinstance(text, str) or not text or not isinstance(start, int):
            continue
        duration = syllable.get("duration")
        end = start + duration if isinstance(duration, int) and duration >= 0 else None
        out.append(LyricWord(start_ms=start, text=text, end_ms=end))
    return tuple(out)


def _to_lines(rows: list) -> tuple[LyricLine, ...]:
    lines: list[LyricLine] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start = row.get("time")
        text = row.get("text")
        if not isinstance(start, int) or not isinstance(text, str):
            continue
        words = _syllables(row)
        duration = row.get("duration")
        lines.append(
            LyricLine(
                start_ms=start,
                text=text,
                end_ms=start + duration if isinstance(duration, int) and duration >= 0 else None,
                words=words,
                index=len(lines),
            )
        )
    return tuple(lines)


def _to_lyrics(body: dict, title: str, artist: str, duration_ms: int) -> Lyrics | None:
    """
    پاسخ → `Lyrics`، با تطبیقِ مشترک قبل از پذیرش.

    عنوان/هنرمندی که خودِ سرویس در `metadata` می‌دهد در برابر درخواست سنجیده
    می‌شود: جستجوهای این سرویس هم می‌توانند نسخه‌ی دیگری را برگردانند و
    قاعده‌ی پروژه این است که نتیجه‌ی ناهمخوان پذیرفته نشود.
    """
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    lyrics_rows = body.get("lyrics")
    if not isinstance(lyrics_rows, list) or not lyrics_rows:
        return None

    score = score_candidate(
        want_title=title,
        want_artist=artist,
        got_title=metadata.get("title"),
        got_artist=metadata.get("artist"),
        candidate_duration_ms=_seconds_to_ms(metadata.get("totalDuration")),
        wanted_duration_ms=duration_ms or None,
    )
    # سرویس مدت را در `totalDuration` می‌دهد که *ثانیه* است (نه ms) — برخلافِ
    # `Line.time` که میلی‌ثانیه است. تفاوتِ واحدها همین‌جا عادی می‌شود.
    if not score.acceptable:
        return None

    lines = _to_lines(lyrics_rows)
    if not lines:
        return None

    raw_type = body.get("type")
    sync_type = _SYNC_TYPES.get(raw_type if isinstance(raw_type, str) else "", None)
    if sync_type is None:
        sync_type = "word" if any(line.words for line in lines) else "line"

    language = metadata.get("language")
    return Lyrics(
        plain="\n".join(line.text for line in lines),
        format="lrc" if sync_type == "line" else "rich",
        sync_type=sync_type,
        lines=lines,
        language=language if isinstance(language, str) else None,
    )


def _seconds_to_ms(value: object) -> int | None:
    """`totalDuration` ثانیه است و ممکن است اعشاری باشد."""
    if isinstance(value, (int, float)) and value > 0:
        return int(round(float(value) * 1000))
    return None


def fetch_strict(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    """
    مثل `fetch`، ولی خطای گذرا را با `ProviderError` اعلام می‌کند.

    طبقه‌بندی: ۴۰۴ → `None` («ندارم»). ۴۲۹ (محدودیت نرخ) و ۵۰۳ (سرویس
    مشغول) و ۵xx و ۴xx دیگر → `ProviderError(http)` — یعنی «نمی‌دانم»، پس
    کشِ منفی نمی‌شود. هیچ تلاشِ مجددی درونِ همین تابع انجام نمی‌شود؛ مدیر
    در درخواستِ بعدیِ کاربر دوباره امتحان می‌کند، که یعنی احترام به
    `Retry-After` بدونِ حلقه‌ی بی‌پایان.
    """
    if not title or not artist:
        return None

    params: dict[str, str] = {"title": title, "artist": artist}
    if album:
        params["album"] = album
    if duration_ms:
        params["duration"] = str(round(duration_ms / 1000))

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, proxy=PROXY) as client:
        try:
            res = client.get(f"{LYRICSPLUS_API}{_PATH}", params=params)
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
    if (body.get("type") or "").lower() == "none" and not body.get("lyrics"):
        return None

    try:
        return _to_lyrics(body, title, artist, duration_ms)
    except Exception as exc:
        raise ProviderError(_NAME, "body", detail=exc.__class__.__name__) from exc


def fetch(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    """قرارداد عمومی — هر خطایی `None` می‌شود."""
    try:
        return fetch_strict(title, artist, album, duration_ms)
    except Exception:
        return None
