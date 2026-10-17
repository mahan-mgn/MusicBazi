"""Shared, ordered lyrics provider manager."""

from __future__ import annotations

import inspect
import logging
import time
from dataclasses import replace
from typing import Callable

from ..config import LYRICS_ENABLED, LYRICS_MISS_TTL_S, LYRICS_PROVIDERS_ORDER
from ..models import Track
from ..providers import (
    betterlyrics,
    binilyrics,
    genius,
    lrclib,
    lrc_red,
    lyricsplus,
    musixmatch,
    paxsenix,
    simpmusic,
    unison,
)
from .models import Lyrics
from .registry import ProviderEntry, ProviderError, ProviderRegistry

log = logging.getLogger(__name__)

ProviderFetch = Callable[[str, str, str | None, int], Lyrics | None]
ProviderEnabled = Callable[[], bool]

# نامِ Provider روی خروجی، جدا از `source` که منبعِ ترک است.
# `fetch` عمومی برای سازگاری، `fetch_strict` برای تفکیک خطا از خالی.
#
# ترتیبِ پیش‌فرضِ عملی فقط دو تای اول را دارد (`LYRICS_PROVIDERS_ORDER` =
# `lrclib,genius`). بقیه **پیش‌فرض خاموش‌اند** و ثبتشان اینجا فقط یعنی
# «قابلِ روشن‌کردن با یک متغیر محیطی» — نه «در زنجیره هستند».
#
# ترتیبِ *پیشنهادی* برای بعد از روشن‌کردن (بالا = مستقیم‌تر/با‌کیفیت‌تر):
#   lrclib → genius → lyricsplus → unison → betterlyrics → binilyrics → lrc_red
# `simpmusic` عمداً ته است: کلیدش videoId است و بدونِ آن هیچ‌وقت نتیجه نمی‌دهد.
#
# دلیلِ خاموشیِ همه: سرویسِ ثالث با مجوزِ بررسی‌نشده، و بیرون از دسترسِ
# اینترانتِ ایران.
_PROVIDERS: tuple[ProviderEntry, ...] = (
    ProviderEntry(
        "lrclib",
        lrclib.fetch,
        None,
        lrclib.fetch_strict,
        label="LRCLIB",
        capabilities=frozenset({"plain", "line"}),
        terms_note="General public API, MIT-licensed project.",
    ),
    ProviderEntry(
        "genius",
        genius.fetch,
        genius.enabled,
        genius.fetch_strict,
        label="Genius",
        capabilities=frozenset({"plain"}),
        terms_note="Terms prohibit scraping/automated use. Manual selection only.",
        setup_hint="Set MUSICBAZI_GENIUS_ACCESS_TOKEN in the server environment.",
    ),
    ProviderEntry(
        "lyricsplus",
        lyricsplus.fetch,
        lyricsplus.enabled,
        lyricsplus.fetch_strict,
        default_enabled=False,
        label='lyricsplus',
        capabilities=frozenset({"line", "word", "rich"}),
        terms_note='Aggregator; free public API, no formal terms page.',
    ),
    ProviderEntry(
        "unison",
        unison.fetch,
        unison.enabled,
        unison.fetch_strict,
        default_enabled=False,
        label='unison',
        capabilities=frozenset({"line", "word", "ttml"}),
        terms_note='Free public API. Commercial reuse of the corpus needs a licence.',
    ),
    ProviderEntry(
        "betterlyrics",
        betterlyrics.fetch,
        betterlyrics.enabled,
        betterlyrics.fetch_strict,
        default_enabled=False,
        label='betterlyrics',
        experimental=True,
        capabilities=frozenset({"line", "word", "ttml"}),
        terms_note='GPL-3.0 client; endpoint contract partially inferred.',
    ),
    ProviderEntry(
        "binilyrics",
        binilyrics.fetch,
        binilyrics.enabled,
        binilyrics.fetch_strict,
        default_enabled=False,
        label='binilyrics',
        capabilities=frozenset({"line", "word", "ttml"}),
        terms_note='No public licence or terms found.',
    ),
    ProviderEntry(
        "lrc_red",
        lrc_red.fetch,
        lrc_red.enabled,
        lrc_red.fetch_strict,
        default_enabled=False,
        label='lrc_red',
        experimental=True,
        capabilities=frozenset({"line", "word", "ttml"}),
        terms_note='Docs say the API is free for public use. Contract partly inferred.',
    ),
    ProviderEntry(
        "simpmusic",
        simpmusic.fetch,
        simpmusic.enabled,
        simpmusic.fetch_strict,
        default_enabled=False,
        label='simpmusic',
        capabilities=frozenset({"line", "word", "rich"}),
        terms_note='Public API keyed by YouTube videoId.',
    ),
    ProviderEntry(
        "paxsenix",
        paxsenix.fetch,
        paxsenix.enabled,
        paxsenix.fetch_strict,
        default_enabled=False,
        label='paxsenix',
        experimental=True,
        capabilities=frozenset({"line", "word", "ttml"}),
        terms_note='No terms published. Keyed by track id.',
    ),
    ProviderEntry(
        "musixmatch",
        musixmatch.fetch,
        musixmatch.enabled,
        musixmatch.fetch_strict,
        default_enabled=False,
        label='musixmatch',
        capabilities=frozenset({"line"}),
        terms_note='Official API only; synchronised text needs a commercial plan.',
        setup_hint='Set MUSICBAZI_MUSIXMATCH_API_KEY in the server environment.',
    ),
)


def _make_registry() -> ProviderRegistry:
    return ProviderRegistry(list(_PROVIDERS), LYRICS_PROVIDERS_ORDER)


def _accepts_hints(fn) -> bool:
    """آیا این تابع پارامترهای راهنمای اختیاری (`video_id`/`isrc`) می‌پذیرد؟"""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "video_id" in params and "isrc" in params


def _invoke(fn, track: Track) -> Lyrics | None:
    """
    Provider را با راهنماهای در دسترس صدا بزن — ولی فقط اگر بپذیرد.

    `video_id`/`isrc` روی بعضی Providerها هست و روی بعضی نه؛ پاس‌کردنِ
    بی‌قیدِ کلیدواژه به تابعی که آن را نمی‌شناسد `TypeError` می‌دهد که
    Manager آن را «خطای غیرمنتظره» می‌شمرد و Provider را بیهوده اخراج
    می‌کرد. پس یک بار امضا خوانده می‌شود.
    """
    if _accepts_hints(fn):
        return fn(
            track.title,
            track.artist,
            track.album,
            track.durationMs,
            video_id=getattr(track, "videoId", None),
            isrc=getattr(track, "isrc", None),
        )
    return fn(track.title, track.artist, track.album, track.durationMs)


class LyricsManager:
    """
    Providerهای روشن را به‌ترتیب امتحان کن و اولین نتیجه‌ی قابل‌استفاده را برگردان.

    دو تصمیم اینجا نیست و از تنظیمات می‌آید: ترتیب (`LYRICS_PROVIDERS_ORDER`)
    و خاموش‌کردنِ تک‌تک Providerها. پیش‌فرضش دقیقاً همان لرکلیب‌بعد‌گینیوسِ
    قبلی است.

    کشِ منفی: اگر همه‌ی Providerها *معتبر* جواب خالی دادند، آن جواب چند ثانیه
    نگه داشته می‌شود تا جستجوهای پشت‌سرهمِ یک ترکِ بی‌متن کل زنجیره را دوباره
    نزنند. فقط و فقط این حالت کش می‌شود: خطای شبکه و تایم‌اوت نباید کش شوند،
    وگرنه یک قطعیِ یک‌ثانیه‌ای متنِ موجود را چند دقیقه پنهان می‌کند.
    """

    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        miss_ttl_s: int = LYRICS_MISS_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry or _make_registry()
        self._miss_ttl_s = miss_ttl_s
        self._clock = clock
        # کلید ترک → لحظه‌ی انقضا. در حافظه، هم‌شکل با `_pending_lyrics`
        # (`stream_cache.py`)، پس روی دیسک هیچ فرمت تازه‌ای ساخته نمی‌شود.
        self._misses: dict[str, float] = {}

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    def _miss_cached(self, key: str) -> bool:
        expires = self._misses.get(key)
        if expires is None:
            return False
        if self._clock() >= expires:
            self._misses.pop(key, None)
            return False
        return True

    def forget(self, key: str) -> None:
        """کشِ منفیِ یک ترک را دور بریز — مثلاً وقتی کاربر دوباره درخواست می‌کند."""
        self._misses.pop(key, None)

    def _record_failure(self, name: str) -> None:
        """
        شکست را به قطع‌کننده بگو — فقط اگر برای این Provider اعمال شود.

        `lrclib`/`genius` پیش‌فرض از قطع‌کننده مستثنا هستند تا رفتارِ قبل از
        ۲B.4 عیناً حفظ شود (`config.lyrics_breaker_enabled`).
        """
        if self._registry.breaker_applies(name):
            self._registry.breaker.record_failure(name)

    def fetch(self, track: Track) -> Lyrics | None:
        if not LYRICS_ENABLED or not track.title.strip():
            return None

        if self._miss_ttl_s > 0 and self._miss_cached(track.id):
            return None

        # اگر یک Provider خطا بدهد ولی دیگری جواب بدهد، این «یافت شد» است.
        # فقط وقتی *همه* بی‌نتیجه و بی‌خطا باشند کشِ منفی معنا دارد.
        #
        # Providerی که قطع‌کننده اخراجش کرده «خطا» است نه «خالی»: از
        # `available()` غایب است، پس بدونِ این چک مثلِ خالی شمرده می‌شد و یک
        # کشِ منفیِ نادرست نوشته می‌شد — همان باگِ ۲B.0.1 از راهِ breaker.
        errored = any(
            self._registry.is_evicted(name) for name in self._registry.order
        )
        for entry in self._registry.available():
            try:
                result = _invoke(entry.strict(), track)
            except ProviderError as exc:
                # قابلِ‌عیب‌یابی، ولی بدون توکن و بدون URL حاوی کلید.
                log.warning(
                    "lyrics provider %s failed (%s%s): %s",
                    exc.provider,
                    exc.kind,
                    f" {exc.status}" if exc.status is not None else "",
                    exc.detail or "",
                )
                self._record_failure(entry.name)
                errored = True
                continue
            except Exception:
                log.warning("lyrics provider %s failed (unexpected)", entry.name, exc_info=True)
                self._record_failure(entry.name)
                errored = True
                continue
            # یک پاسخ (حتی خالی) یعنی سرویس سالم است؛ شمارنده‌ی خطا صفر می‌شود
            # تا خطاهای پراکنده یک Providerِ ناپایدار را اخراج نکنند.
            if self._registry.breaker_applies(entry.name):
                self._registry.breaker.record_success(entry.name)
            if result:
                self._misses.pop(track.id, None)
                return replace(
                    result, source=result.source or entry.name, provider_id=entry.name
                )

        # Providerی که رد شده (غیرفعال/بدون توکن) اینجا نیست، پس مانع کش نمی‌شود.
        if not errored and self._miss_ttl_s > 0:
            self._misses[track.id] = self._clock() + self._miss_ttl_s
        return None


lyrics_manager = LyricsManager()


def fetch(track: Track) -> Lyrics | None:
    """Public shared entry point used by download and stream code."""

    return lyrics_manager.fetch(track)
