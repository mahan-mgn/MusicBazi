"""
سرویسِ منابعِ متن — فهرست‌کردن و واکشیِ تک‌منبعی.

دو عملیات، عمداً جدا:

- `list_sources(track)` → متادیتای هر Provider + وضعیتِ کشِ آن برای این آهنگ.
  **هیچ درخواستِ شبکه‌ای نمی‌زند.** فرانت هنگام باز کردنِ منو این را صدا
  می‌زند، پس اگر یک درخواست به Provider می‌زد، باز کردنِ منو به ازای هر
  منبع یک رفت‌وبرگشت می‌شد.
- `fetch_from(name, track, force=False)` → **فقط همان** Provider را صدا
  می‌زند. انتخابِ دستی نباید Provider را به زنجیرهٔ خودکار اضافه کند.

چرا ماژولِ جدا و نه روی `Manager`: `Manager` زنجیرهٔ خودکار را می‌چرخاند و
اولین نتیجه را برمی‌گرداند. «کاربر منبعِ X را می‌خواهد» سؤالِ دیگری است —
ممکن است X پیش‌فرض خاموش باشد یا حتی در زنجیره نباشد. قاطی‌کردنشان یعنی
انتخابِ دستی به‌طور پنهان زنجیره را عوض کند.

کش: نتایجِ Provider-محور **فقط در حافظه** می‌مانند. مسیرِ کشِ روی دیسک
(`cache_key_for` + `<key>.lrc`) قراردادِ قفل‌شده‌ای است و کلیدِ دومی که همان
فضای نام را شریک شود، `clean_stream_cache` را می‌شکند. همچنین «ترجیحِ
کاربر» جایی دیگر (DB) ذخیره می‌شود، نه اینجا.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from ..config import LYRICS_MISS_TTL_S
from ..models import Track
from .manager import LyricsManager, lyrics_manager
from .matching import content_fingerprint
from .models import Lyrics
from .registry import ProviderEntry, ProviderError

log = logging.getLogger(__name__)

# وضعیت‌های ممکنِ یک منبع برای یک آهنگ — همان چیزی که UI نشان می‌دهد.
STATUS_AVAILABLE = "available"  # قابلِ‌صدا‌زدن، هنوز امتحان نشده
STATUS_NEEDS_SETUP = "needs_setup"  # خودش کلید/تنظیم لازم دارد
STATUS_DISABLED = "disabled"  # فقط پیش‌فرض خاموش است؛ با یک سوئیچ روشن می‌شود
STATUS_CACHED = "cached"  # نتیجه برای همین آهنگ در حافظه هست
STATUS_EMPTY = "empty"  # امتحان شد، متنی نداشت
STATUS_ERROR = "error"  # آخرین تلاش خطا داد
STATUS_EXPERIMENTAL = "experimental"  # قراردادش کامل تأیید نشده


@dataclass(frozen=True)
class SourceResult:
    """نتیجهٔ یک تلاشِ تک‌منبعی."""

    provider: str
    lyrics: Lyrics | None
    error: str | None = None  # نامِ کلاسِ خطا یا kind، بدونِ داده‌ی حساس

    @property
    def ok(self) -> bool:
        return self.lyrics is not None


class _Entry:
    """کشِ درون‌حافظه‌ایِ یک (آهنگ، Provider)."""

    __slots__ = ("value", "expires")

    def __init__(self, value: Lyrics | None, expires: float) -> None:
        self.value = value
        self.expires = expires


class LyricsSources:
    """
    فهرست و واکشیِ تک‌منبعی.

    هم‌زمانی: `_pending` درخواست‌های هم‌زمانِ *همان* (آهنگ، Provider) را
    ادغام می‌کند — همان الگویی که `stream_cache` برای مسیرِ پیش‌فرض دارد، تا
    دو تبِ بازِ یک آهنگ دو درخواست به یک سرویسِ رایگان نزنند.
    """

    def __init__(
        self,
        manager: LyricsManager | None = None,
        miss_ttl_s: int = LYRICS_MISS_TTL_S,
        clock=time.monotonic,
    ) -> None:
        self._manager = manager or lyrics_manager
        self._miss_ttl_s = miss_ttl_s
        self._clock = clock
        self._cache: dict[tuple[str, str], _Entry] = {}
        self._errors: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()
        self._pending: dict[tuple[str, str], asyncio.Task] = {}

    # ------------------------------------------------------------ فهرست

    def list_sources(self, track: Track) -> list[dict]:
        """
        متادیتای هر Provider ثبت‌شده + وضعیتِ کشِ آن برای این آهنگ.

        **هیچ درخواستی به Provider نمی‌زند.** فقط رجیستری و کشِ حافظه را
        می‌خواند.
        """
        out: list[dict] = []
        for entry in self._ordered_entries():
            key = (track.id, entry.name)
            out.append(
                {
                    "id": entry.name,
                    "label": entry.display_label(),
                    "capabilities": sorted(entry.capabilities),
                    "in_auto_chain": self._in_auto_chain(entry),
                    "selectable": self._selectable(entry),
                    "status": self._status_of(entry, key),
                    "terms_note": entry.terms_note,
                    "setup_hint": entry.setup_hint,
                }
            )
        return out

    def _ordered_entries(self) -> list[ProviderEntry]:
        return [
            self._manager.registry.get(name)
            for name in self._manager.registry.order
            if self._manager.registry.get(name) is not None
        ]

    def _in_auto_chain(self, entry: ProviderEntry) -> bool:
        return any(e.name == entry.name for e in self._manager.registry.available())

    def _selectable(self, entry: ProviderEntry) -> bool:
        """
        قابلِ‌انتخابِ دستی؟ یعنی روشن است و کلید/تنظیمش هم آماده.

        Providerی که در زنجیره نیست (Genius زیر `manual_only`) همچنان
        قابلِ‌انتخاب است — تفاوتش این است که خودبه‌خود اجرا نمی‌شود.
        """
        return self._manager.registry.is_selectable(entry.name)

    def _status_of(self, entry: ProviderEntry, key: tuple[str, str]) -> str:
        if not self._selectable(entry):
            # دو علتِ متفاوت که کاربر باید تفکیکشان کند: Providerی که خودش
            # کلید/تنظیم می‌خواهد (Genius، Musixmatch) با Providerی که فقط
            # پیش‌فرض خاموش است (بقیه) یکی نیست.
            if entry.enabled is not None and not entry.enabled():
                return STATUS_NEEDS_SETUP
            return STATUS_DISABLED
        if (cached := self._cache.get(key)) is not None:
            if cached.expires > self._clock():
                return STATUS_CACHED if cached.value is not None else STATUS_EMPTY
            self._cache.pop(key, None)
        if key in self._errors:
            return STATUS_ERROR
        return STATUS_AVAILABLE

    # ------------------------------------------------------------ واکشی

    async def fetch_from(self, name: str, track: Track, *, force: bool = False) -> SourceResult:
        """
        فقط همین Provider را صدا بزن.

        `force=True` کشِ «نتیجه‌ای نیست» را دور می‌زند (دکمهٔ «تلاش دوباره»).
        خطا **هرگز** کش نمی‌شود — فقط «خالیِ معتبر».
        """
        entry = self._manager.registry.get(name)
        if entry is None:
            return SourceResult(provider=name, lyrics=None, error="unknown-provider")
        if not self._selectable(entry):
            return SourceResult(provider=name, lyrics=None, error="needs-setup")

        key = (track.id, name)
        if force:
            self._cache.pop(key, None)
            self._errors.pop(key, None)

        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached.expires > self._clock():
                if cached.value is None and not force:
                    return SourceResult(provider=name, lyrics=None)
                if cached.value is not None:
                    return SourceResult(provider=name, lyrics=cached.value)
            task = self._pending.get(key)
            if task is None:
                task = asyncio.create_task(asyncio.to_thread(self._run, entry, track))
                self._pending[key] = task

        try:
            result = await task
        finally:
            async with self._lock:
                if self._pending.get(key) is task:
                    self._pending.pop(key, None)
        return result

    def _run(self, entry: ProviderEntry, track: Track) -> SourceResult:
        """کارِ بلاک‌کننده‌ی شبکه — در thread جدا."""
        key = (track.id, entry.name)
        try:
            from .manager import _invoke

            found = _invoke(entry.strict(), track)
        except ProviderError as exc:
            # خطا کش نمی‌شود؛ فقط برای نمایشِ وضعیت نگه داشته می‌شود.
            self._errors[key] = exc.kind
            log.warning(
                "lyrics source %s failed (%s%s)", exc.provider, exc.kind,
                f" {exc.status}" if exc.status is not None else "",
            )
            return SourceResult(provider=entry.name, lyrics=None, error=exc.kind)
        except Exception as exc:  # noqa: BLE001
            self._errors[key] = exc.__class__.__name__
            log.warning("lyrics source %s failed (unexpected)", entry.name, exc_info=True)
            return SourceResult(provider=entry.name, lyrics=None, error=exc.__class__.__name__)

        self._errors.pop(key, None)
        if found is None and self._miss_ttl_s > 0:
            # «خالیِ معتبر» کش می‌شود تا زدنِ مکرر دکمه، سرویس را نکوبد.
            self._cache[key] = _Entry(None, self._clock() + self._miss_ttl_s)
            return SourceResult(provider=entry.name, lyrics=None)
        if found is not None:
            self._cache[key] = _Entry(found, float("inf"))
        return SourceResult(provider=entry.name, lyrics=found)

    # ------------------------------------------------------------ تکراری

    def duplicate_of(self, name: str, track: Track, other: str) -> bool:
        """
        آیا نتیجه‌ی این Provider با نتیجه‌ی Providerِ دیگری یکی است؟

        `lrc_red` و `binilyrics` از یک مبدأ می‌خوانند (سنجیده شد: روی یک آهنگ
        عیناً یک نتیجه). این متد مقایسه را در اختیارِ UI می‌گذارد بدونِ اینکه
        چیزی را خودکار حذف کند — کاربر باید بداند دو گزینه عملاً یکی‌اند.

        فقط از کشِ حافظه می‌خواند؛ هیچ درخواستی نمی‌زند.
        """
        left = self._cached_text(name, track)
        right = self._cached_text(other, track)
        if left is None or right is None:
            return False
        return content_fingerprint(left) == content_fingerprint(right)

    def _cached_text(self, name: str, track: Track) -> str | None:
        entry = self._cache.get((track.id, name))
        if entry is None or entry.value is None:
            return None
        return entry.value.plain or entry.value.synced

    # ------------------------------------------------------------ کمکی

    def forget(self, track_id: str, name: str | None = None) -> None:
        """کشِ یک آهنگ (یا یک Providerِ آن) را دور بریز."""
        for key in [k for k in self._cache if k[0] == track_id and (name is None or k[1] == name)]:
            self._cache.pop(key, None)
        for key in [k for k in self._errors if k[0] == track_id and (name is None or k[1] == name)]:
            self._errors.pop(key, None)


lyrics_sources = LyricsSources()
