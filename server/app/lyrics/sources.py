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
# ⚠️ `STATUS_EXPERIMENTAL` هیچ مصرف‌کنندهٔ تولیدی ندارد: P1 آزمایشی‌بودن را به
# فیلدِ جدا (`experimental`) برد تا با وضعیتِ کش قاطی نشود. عمداً حذف **نشد**
# چون یک ثابتِ نام‌دارِ مستندساز است و حذفش هیچ سودی ندارد.
STATUS_BLOCKED = "blocked"  # از نظرِ شرایطِ استفاده یا قرارداد قابلِ استفاده نیست


# منابعی که کد ندارند و **نخواهند داشت** — فقط برای نمایش در فهرست.
# «نبودنشان در فهرست» یعنی کاربر نمی‌فهمد چرا نیستند؛ «بودنشان با علت»
# یعنی تصمیم شفاف است. هیچ کدِ Providerی برای این‌ها وجود ندارد.
_PROHIBITED_SOURCES: tuple[ProviderEntry, ...] = (
    ProviderEntry(
        "kugou",
        lambda *a, **k: None,
        None,
        lambda *a, **k: None,
        label="KuGou",
        capabilities=frozenset(),
        terms_note="Not implemented: requires impersonating the mobile app.",
        blocked_reason="Requires bypassing the provider's app authentication.",
    ),
    ProviderEntry(
        "megalobiz",
        lambda *a, **k: None,
        None,
        lambda *a, **k: None,
        label="Megalobiz",
        capabilities=frozenset(),
        terms_note="Not implemented: robots.txt blocks this kind of client sitewide.",
        blocked_reason="The site's robots.txt disallows this client entirely.",
    ),
)


def _error_kind_of(kind: str, status: int | None) -> str:
    """
    `kind`ِ خامِ ProviderError → دسته‌ای که UI می‌فهمد.

    ۴۲۹ تنها حالتی است که جدا می‌شود: «بعداً دوباره امتحان کن» با «سرویس
    خراب است» یکی نیست و پیامِ درست برای کاربر فرق دارد.
    """
    return "rate_limited" if status == 429 else kind


@dataclass(frozen=True)
class SourceResult:
    """
    نتیجهٔ یک تلاشِ تک‌منبعی.

    `error` یک کدِ ماشین‌خوان است، نه متنِ خطا: `unknown-provider`،
    `needs-setup`، `disabled`، `blocked`، یا `kind`ِ خودِ ProviderError
    (`network`/`http`/`body`). `http_status` فقط وقتی پر می‌شود که عددی
    واقعی از Provider آمده باشد.
    """

    provider: str
    lyrics: Lyrics | None
    error: str | None = None  # کدِ ماشین‌خوان، بدونِ داده‌ی حساس
    http_status: int | None = None

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
        # کلید `(uid, track_id, name)` — کش در حافظه مشترک است و "کاربر X متن
        # ندارد" نباید برای کاربر Y هم صادق باشد.
        self._cache: dict[tuple[str, str, str], _Entry] = {}
        self._errors: dict[tuple[str, str, str], str] = {}
        # کدِ HTTPِ آخرین خطا، برای نمایشِ «HTTP 502» بدونِ لو دادنِ جزئیات
        self._error_status: dict[tuple[str, str, str], int | None] = {}
        self._lock = asyncio.Lock()
        self._pending: dict[tuple[str, str, str], asyncio.Task] = {}

    # ------------------------------------------------------------ فهرست

    def list_sources(self, track: Track, uid: str = "local") -> list[dict]:
        """
        متادیتای هر Provider ثبت‌شده + وضعیتِ کشِ آن برای این آهنگ.

        **هیچ درخواستی به Provider نمی‌زند.** فقط رجیستری و کشِ حافظه را
        می‌خواند.
        """
        out: list[dict] = []
        for entry in self._ordered_entries():
            key = (uid, track.id, entry.name)
            selectable = self._selectable(entry, uid)
            out.append(
                {
                    "id": entry.name,
                    "label": entry.display_label(),
                    "capabilities": sorted(entry.capabilities),
                    "in_auto_chain": self._in_auto_chain(entry),
                    "selectable": selectable,
                    "status": self._status_of(entry, key),
                    "terms_note": entry.terms_note,
                    "setup_hint": entry.setup_hint,
                    "experimental": entry.experimental,
                    # آخرین نتیجهٔ همین آهنگ — از کش و breaker، بدونِ شبکه
                    "last_outcome": self._last_outcome(entry, key),
                    "last_error_kind": self._last_error_kind(key),
                    "http_status": self._last_http_status(key),
                    # چرا قابلِ انتخاب نیست — UI به‌جای خاکستریِ بی‌توضیح،
                    # همان دلیل را نشان می‌دهد. برای منابعِ قابلِ انتخاب خالی است.
                    "unavailable_reason": None if selectable else self._reason_of(entry),
                }
            )
        return out

    def _reason_of(self, entry: ProviderEntry, uid: str = "local") -> str:
        """متنِ *نمایشی* برای ردیفِ غیرقابلِ‌انتخاب (می‌تواند راهنمای راه‌اندازی باشد)."""
        if entry.blocked_reason:
            return entry.blocked_reason
        if entry.needs_key(uid):
            return entry.setup_hint or "needs_setup"
        return "disabled"

    @staticmethod
    def _code_of(entry: ProviderEntry, uid: str = "local") -> str:
        """
        کدِ *ماشین‌خوانِ* علتِ غیرقابلِ‌انتخاب بودن — جدا از متنِ نمایشی.

        `disabled` یعنی «با یک سوئیچ روشن می‌شود»؛ `needs_setup` یعنی «کلید
        لازم دارد»؛ `blocked` یعنی «هرگز». فرانت برای هرکدام پیامِ متفاوتی
        نشان می‌دهد، پس نمی‌شود همه را یک رشته کرد.
        """
        if entry.blocked_reason:
            return "blocked"
        if entry.needs_key(uid):
            return "needs_setup"
        return "disabled"

    def _is_blocked_name(self, name: str) -> bool:
        return any(e.name == name and e.blocked_reason for e in self._blocked_entries())

    def _blocked_entries(self) -> list[ProviderEntry]:
        """
        منابعی که کد ندارند (ممنوع) ولی باید در فهرست دیده شوند.

        جدا از رجیستری نگه داشته می‌شوند: رجیستری فقط چیزهایی را دارد که
        واقعاً قابلِ‌صدا‌زدن‌اند. این‌ها صرفاً متادیتا هستند — **هیچ کد
        Providerی برایشان وجود ندارد و اضافه هم نمی‌شود**.
        """
        return list(_PROHIBITED_SOURCES)

    def _ordered_entries(self) -> list[ProviderEntry]:
        live = [
            self._manager.registry.get(name)
            for name in self._manager.registry.order
            if self._manager.registry.get(name) is not None
        ]
        return live + self._blocked_entries()

    def _in_auto_chain(self, entry: ProviderEntry, uid: str = "local") -> bool:
        return any(
            e.name == entry.name for e in self._manager.registry.available(uid)
        )

    def _selectable(self, entry: ProviderEntry, uid: str = "local") -> bool:
        """
        قابلِ‌انتخابِ دستی؟

        Providerی که در زنجیره نیست (Genius زیر `manual_only`) یا پیش‌فرض
        خاموش است، همچنان قابلِ‌انتخاب است. منابعِ ممنوع (بدونِ کد) هرگز.
        """
        if entry.blocked_reason:
            return False
        return self._manager.registry.is_selectable(entry.name, uid)

    def _status_of(self, entry: ProviderEntry, key: tuple[str, str, str]) -> str:
        if entry.blocked_reason:
            return STATUS_BLOCKED
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

    def _last_outcome(self, entry: ProviderEntry, key: tuple[str, str, str]) -> str:
        """
        آخرین نتیجهٔ شناخته‌شدهٔ این منبع برای این آهنگ — بدونِ هیچ درخواستی.

        چهار مقدار: `cached` (متن دارد)، `not_found` («خالیِ معتبر»)، `error`
        (خطا)، `never_tried`. UI با این می‌تواند «Not tried» و «Failed – retry»
        را از هم جدا کند، چیزی که قبلاً ممکن نبود.
        """
        if entry.blocked_reason or not self._selectable(entry):
            return "never_tried"
        cached = self._cache.get(key)
        if cached is not None and cached.expires > self._clock():
            return "cached" if cached.value is not None else "not_found"
        if key in self._errors:
            return "error"
        return "never_tried"

    def _last_error_kind(self, key: tuple[str, str, str]) -> str | None:
        return self._errors.get(key)

    def _last_http_status(self, key: tuple[str, str, str]) -> int | None:
        return self._error_status.get(key)

    # ------------------------------------------------------------ واکشی

    async def fetch_from(
        self, name: str, track: Track, uid: str = "local", *, force: bool = False
    ) -> SourceResult:
        """
        فقط همین Provider را صدا بزن.

        `force=True` کشِ «نتیجه‌ای نیست» را دور می‌زند (دکمهٔ «تلاش دوباره»).
        خطا **هرگز** کش نمی‌شود — فقط «خالیِ معتبر».
        """
        entry = self._manager.registry.get(name)
        if entry is None:
            # منابعِ ممنوع در رجیستری نیستند ولی ثبت‌شده‌اند — «ناشناس» با
            # «ممنوع» یکی نیست و پیامِ درست برای کاربر فرق دارد.
            if self._is_blocked_name(name):
                return SourceResult(provider=name, lyrics=None, error="blocked")
            return SourceResult(provider=name, lyrics=None, error="unknown-provider")
        if not self._selectable(entry, uid):
            return SourceResult(provider=name, lyrics=None, error=self._code_of(entry, uid))

        key = (uid, track.id, name)
        if force:
            self._cache.pop(key, None)
            self._errors.pop(key, None)
            self._error_status.pop(key, None)

        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached.expires > self._clock():
                if cached.value is None and not force:
                    return SourceResult(provider=name, lyrics=None)
                if cached.value is not None:
                    return SourceResult(provider=name, lyrics=cached.value)
            task = self._pending.get(key)
            if task is None:
                task = asyncio.create_task(asyncio.to_thread(self._run, entry, track, uid))
                self._pending[key] = task

        try:
            result = await task
        finally:
            async with self._lock:
                if self._pending.get(key) is task:
                    self._pending.pop(key, None)
        return result

    def _run(self, entry: ProviderEntry, track: Track, uid: str = "local") -> SourceResult:
        """کارِ بلاک‌کننده‌ی شبکه — در thread جدا."""
        key = (uid, track.id, entry.name)
        try:
            from .manager import _invoke

            found = _invoke(entry.strict(), track, uid)
        except ProviderError as exc:
            # خطا کش نمی‌شود؛ فقط برای نمایشِ وضعیت نگه داشته می‌شود.
            self._errors[key] = _error_kind_of(exc.kind, exc.status)
            self._error_status[key] = exc.status
            log.warning(
                "lyrics source %s failed (%s%s)", exc.provider, exc.kind,
                f" {exc.status}" if exc.status is not None else "",
            )
            return SourceResult(
                provider=entry.name, lyrics=None, error=exc.kind, http_status=exc.status
            )
        except Exception as exc:  # noqa: BLE001
            self._errors[key] = exc.__class__.__name__
            self._error_status.pop(key, None)
            log.warning("lyrics source %s failed (unexpected)", entry.name, exc_info=True)
            return SourceResult(provider=entry.name, lyrics=None, error=exc.__class__.__name__)

        self._errors.pop(key, None)
        self._error_status.pop(key, None)
        if found is None and self._miss_ttl_s > 0:
            # «خالیِ معتبر» کش می‌شود تا زدنِ مکرر دکمه، سرویس را نکوبد.
            self._cache[key] = _Entry(None, self._clock() + self._miss_ttl_s)
            return SourceResult(provider=entry.name, lyrics=None)
        if found is not None:
            self._cache[key] = _Entry(found, float("inf"))
        return SourceResult(provider=entry.name, lyrics=found)

    # ------------------------------------------------------------ تکراری

    def duplicate_of(self, name: str, track: Track, other: str, uid: str = "local") -> bool:
        """
        آیا نتیجه‌ی این Provider با نتیجه‌ی Providerِ دیگری یکی است؟

        `lrc_red` و `binilyrics` از یک مبدأ می‌خوانند (سنجیده شد: روی یک آهنگ
        عیناً یک نتیجه). این متد مقایسه را در اختیارِ UI می‌گذارد بدونِ اینکه
        چیزی را خودکار حذف کند — کاربر باید بداند دو گزینه عملاً یکی‌اند.

        فقط از کشِ حافظه می‌خواند؛ هیچ درخواستی نمی‌زند.
        """
        left = self._cached_text(name, track, uid)
        right = self._cached_text(other, track, uid)
        if left is None or right is None:
            return False
        return content_fingerprint(left) == content_fingerprint(right)

    def _cached_text(self, name: str, track: Track, uid: str = "local") -> str | None:
        entry = self._cache.get((uid, track.id, name))
        if entry is None or entry.value is None:
            return None
        return entry.value.plain or entry.value.synced

    # ------------------------------------------------------------ کمکی

    def forget(self, track_id: str, name: str | None = None) -> None:
        """کشِ یک آهنگ (یا یک Providerِ آن) را دور بریز."""
        for key in [
            k for k in self._cache if k[1] == track_id and (name is None or k[2] == name)
        ]:
            self._cache.pop(key, None)
        for key in [
            k for k in self._errors if k[1] == track_id and (name is None or k[2] == name)
        ]:
            self._errors.pop(key, None)
            self._error_status.pop(key, None)


lyrics_sources = LyricsSources()
