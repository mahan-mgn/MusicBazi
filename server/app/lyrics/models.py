"""Canonical lyrics data shared by providers, downloads, and streaming."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SyncType = Literal["plain", "line", "word", "syllable"]


@dataclass(frozen=True)
class LyricWord:
    """A precisely timed text fragment, including a whole word or syllable."""

    start_ms: int
    text: str
    end_ms: int | None = None


@dataclass(frozen=True)
class LyricLine:
    """One lyric line and any finer-grained timing it contains."""

    start_ms: int
    text: str
    end_ms: int | None = None
    words: tuple[LyricWord, ...] = ()
    # ترتیب صریح در منبع. ترتیبِ تاپل هم آن را می‌رساند، ولی TTML می‌تواند
    # خط‌ها را شماره‌دار بدهد و ترجمه/زمینه هم‌شماره‌ی خط اصلی را بخواهد.
    index: int | None = None
    # "main" / "translation" / "background" — TTML چند ردیفِ هم‌زمان دارد.
    role: str | None = None


@dataclass(frozen=True)
class Lyrics:
    """Normalized result while retaining the existing plain/synced contract."""

    plain: str | None = None
    synced: str | None = None
    source: str | None = None
    format: str | None = None
    sync_type: SyncType | None = None
    lines: tuple[LyricLine, ...] = field(default_factory=tuple)
    # BCP-47 مثل "fa" یا "en". Providerها فعلاً نمی‌دهند؛ برای TTML و برای
    # اینکه UI بتواند خطِ اشتباه را کنار بگذارد لازم می‌شود.
    language: str | None = None
    # شناسه‌ی خودِ Provider، جدا از `source` که منبعِ *ترک* است. وقتی یک منبع
    # چند آداپتر داشته باشد (مثلاً LRCLIB.com و یک آیینه‌ی محلی) لازم می‌شود.
    provider_id: str | None = None

    def __bool__(self) -> bool:
        return bool(self.plain or self.synced or self.lines)
