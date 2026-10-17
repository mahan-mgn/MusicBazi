"""
رابط مشترکِ Providerهای متن و رجیستریِ آن‌ها.

قبلاً `LyricsManager` یک تاپلِ سخت‌کدشده در سازنده‌ی خودش داشت
(`lyrics/manager.py:24-27`): ترتیب و فعال‌بودن هر Provider داخل کد بود، پس
افزودن Provider بعدی یعنی ویرایشِ Manager و تستِ دستیِ دوباره‌ی همه‌چیز.

اینجا آن دو تصمیم به تنظیمات منتقل می‌شوند، با این تضمین که **پیش‌فرض دقیقاً
همان رفتار قبلی است**: LRCLIB سپس Genius.

آداپترها عمداً نازک‌اند. منطق داخلیِ هر Provider (پارس HTML گینس، فیلتر مدت
LRCLIB) دست‌نخورده می‌ماند — این لایه فقط شکلِ صدا زدن را یکسان می‌کند.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from ..config import (
    LYRICS_BREAKER_COOLDOWN_S,
    LYRICS_BREAKER_THRESHOLD,
    lyrics_auto_enabled,
    lyrics_breaker_enabled,
    lyrics_provider_enabled,
)
from .models import Lyrics


class ProviderError(Exception):
    """
    خطای گذرای یک Provider — یعنی «نمی‌دانم»، نه «ندارم».

    تفکیکی که بدونش کشِ منفی خطرناک می‌شود: اگر Provider قطعیِ شبکه را هم
    مثل «متنی نداشتم» گزارش کند، Manager آن را کش می‌کند و یک قطعیِ سه‌ثانیه‌ای
    متنِ موجود را پنج دقیقه پنهان نگه می‌دارد.

    `kind` دسته‌ی خطاست (`network` / `http` / `body`) و `status` کد HTTP اگر
    بود. `detail` متنِ کوتاهِ خطاست — عمداً از استثنای اصلی ساخته می‌شود و
    **هرگز نباید توکن یا URL حاوی کلید را در خود داشته باشد**.
    """

    def __init__(
        self,
        provider: str,
        kind: str,
        *,
        status: int | None = None,
        detail: str | None = None,
    ) -> None:
        self.provider = provider
        self.kind = kind
        self.status = status
        self.detail = detail
        parts = [provider, kind]
        if status is not None:
            parts.append(str(status))
        if detail:
            parts.append(detail)
        super().__init__(": ".join(parts))


@runtime_checkable
class LyricsProvider(Protocol):
    """
    قراردادی که هر منبعِ متن باید داشته باشد.

    `fetch` عمداً همان امضای فعلیِ Providerهاست (`title, artist, album,
    duration_ms`) تا آداپتر لازم نباشد. `None` یعنی «این Provider متنی
    نداشت» — چه به‌خاطر نبودِ نتیجه، چه خطای شبکه؛ تفکیکشان کارِ Provider
    است نه این قرارداد.

    نسخه‌ی دقیق‌ترِ همین قرارداد `fetch_strict` است که خطا را با
    `ProviderError` اعلام می‌کند. `fetch` عمومی روی آن یک wrapper نازک است و
    قرارداد و امضایش دست‌نخورده مانده.
    """

    name: str

    def fetch(
        self, title: str, artist: str, album: str | None, duration_ms: int
    ) -> Lyrics | None: ...


StrictFetchFn = Callable[[str, str, str | None, int], Lyrics | None]


FetchFn = Callable[[str, str, str | None, int], Lyrics | None]
EnabledFn = Callable[[], bool]


@dataclass(frozen=True)
class ProviderEntry:
    """
    یک Provider ثبت‌شده.

    `enabled` اختیاری است و برای Providerهایی است که خودشان می‌دانند چه وقت
    کار می‌کنند (Genius بدون توکن). نبودنش یعنی «همیشه روشن».
    `config_key` نامی است که در `MUSICBAZI_LYRICS_PROVIDER_<NAME>_ENABLED`
    استفاده می‌شود؛ عمداً جدا از `name` نگه داشته شده تا Providerهای آینده
    بتوانند آداپترهای چندگانه با کلیدهای خاموش‌کردنِ مشترک داشته باشند.
    """

    name: str
    fetch: FetchFn
    enabled: EnabledFn | None = None
    fetch_strict: StrictFetchFn | None = None
    default_enabled: bool = True
    # ---- متادیتای نمایشی (S2) ----
    # `label` نامِ خوانا برای UI است؛ `name` شناسهٔ پایدارِ ماشینی می‌ماند.
    label: str | None = None
    # قابلیت‌های فرمت — UI با اینها نشان می‌دهد هر منبع چه می‌دهد.
    # زیرمجموعه‌ی {"plain", "line", "word", "ttml", "rich"}
    capabilities: frozenset[str] = frozenset()
    # یادداشتِ شرایطِ استفاده؛ در UI به‌عنوان هشدار نشان داده می‌شود.
    terms_note: str | None = None
    # اگر Provider برای کار کردن به راه‌اندازیِ کاربر نیاز دارد (توکن)، این
    # متنِ راهنما نشان داده می‌شود. متنِ خودِ کلید هرگز اینجا نمی‌آید.
    setup_hint: str | None = None
    # قرارداد یا کارکردش کامل تأیید نشده — UI برچسبِ «آزمایشی» می‌زند.
    experimental: bool = False
    # Providerی که اصلاً کد ندارد (ممنوع) — فقط برای اینکه در فهرست با علت
    # دیده شود، نه اینکه بی‌صدا غایب باشد.
    blocked_reason: str | None = None

    def display_label(self) -> str:
        return self.label or self.name

    def strict(self) -> StrictFetchFn:
        """نسخه‌ی strict، یا `fetch` عمومی اگر Provider نسخه‌ی strict ندارد."""
        return self.fetch_strict or self.fetch

    def is_available(self) -> bool:
        """
        هم کلیدِ دستی/پیش‌فرض روشن است، هم Provider خودش آماده است.

        متغیر محیطی بر `default_enabled` غلبه می‌کند، پس Providerی که با
        `default_enabled=False` ثبت شده با `MUSICBAZI_LYRICS_PROVIDER_X_ENABLED=1`
        قابلِ روشن‌کردن است.
        """
        if not lyrics_provider_enabled(self.name, default=self.default_enabled):
            return False
        return self.enabled() if self.enabled is not None else True


class CircuitBreaker:
    """
    قطع‌کننده‌ی مدارِ سبک: Providerی که پشت‌سرهم خطا می‌دهد موقتاً کنار می‌رود.

    چرا لازم است: با روشن‌کردنِ چند Providerِ ثالث، اگر یکی قطع شود هر ترکِ
    کاربر یک تایم‌اوتِ کامل به زنجیره اضافه می‌کند. پخش و دانلود کند می‌شود
    بدونِ اینکه چیزی «خطا» نشان بدهد. پس بعد از N خطای *پیاپی* آن Provider
    تا T ثانیه کنار می‌رود و خودش برمی‌گردد.

    فقط خطا شمارش می‌شود، نه «نتیجه نداشتم»: پاسخِ خالیِ معتبر یعنی سرویس
    سالم است، فقط این ترک را ندارد. موفقیت شمارنده را صفر می‌کند، چون یک
    سرویسِ ناپایدار که گاهی جواب می‌دهد نباید به‌خاطرِ خطاهای پراکنده اخراج
    شود.
    """

    def __init__(
        self,
        threshold: int = LYRICS_BREAKER_THRESHOLD,
        cooldown_s: float = LYRICS_BREAKER_COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = max(1, threshold)
        self._cooldown_s = max(0.0, cooldown_s)
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, name: str) -> bool:
        """آیا این Provider همین حالا کنار گذاشته شده؟"""
        until = self._open_until.get(name)
        if until is None:
            return False
        if self._clock() >= until:
            # دوره‌ی خنک‌شدن تمام شد — نصف‌باز: اجازه می‌دهیم دوباره امتحان شود
            self._open_until.pop(name, None)
            self._failures.pop(name, None)
            return False
        return True

    def record_success(self, name: str) -> None:
        self._failures.pop(name, None)
        self._open_until.pop(name, None)

    def record_failure(self, name: str) -> None:
        if self._cooldown_s <= 0:
            return  # صفر یعنی خاموش
        count = self._failures.get(name, 0) + 1
        self._failures[name] = count
        if count >= self._threshold:
            self._open_until[name] = self._clock() + self._cooldown_s

    def failures(self, name: str) -> int:
        return self._failures.get(name, 0)


class ProviderRegistry:
    """
    فهرستِ Providerها به‌ترتیبِ اولویت.

    ترتیب از `LYRICS_PROVIDERS_ORDER` می‌آید. اسمی که در فهرست نیست ولی
    ثبت شده، **آخرِ صف** می‌افتد (نه حذف): Provider تازه‌ثبت‌شده باید بدون
    ویرایشِ تنظیمات هم کار کند، وگرنه افزودنش یک قدم اضافه و پنهان دارد.
    """

    def __init__(
        self,
        entries: list[ProviderEntry],
        order: tuple[str, ...],
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._by_name = {entry.name: entry for entry in entries}
        self._order = self._resolve(order)
        # پیش‌فرض یک قطع‌کننده‌ی تازه می‌سازیم تا Registry همیشه خودکفا باشد و
        # تست‌ها بتوانند ساعت تزریق کنند.
        self.breaker = breaker if breaker is not None else CircuitBreaker()

    def _resolve(self, order: tuple[str, ...]) -> tuple[str, ...]:
        known = [name for name in order if name in self._by_name]
        rest = [name for name in self._by_name if name not in known]
        return tuple(known + rest)

    @property
    def order(self) -> tuple[str, ...]:
        return self._order

    def breaker_applies(self, name: str) -> bool:
        """قطع‌کننده برای این Provider اعمال شود؟ (lrclib/genius: پیش‌فرض نه)"""
        return lyrics_breaker_enabled(name)

    def is_evicted(self, name: str) -> bool:
        """
        Provider به‌خاطرِ قطع‌کننده کنار گذاشته شده؟

        جدا از `available` لازم است: `LyricsManager` باید «ردشده» را از
        «خالی» تفکیک کند، وگرنه وقتی همه‌ی Providerها یا رد شده‌اند یا خالی،
        یک کشِ منفیِ نادرست می‌نویسد و متنِ موجود را پنهان می‌کند.
        """
        if not self.breaker_applies(name):
            return False
        return self.breaker.is_open(name)

    def available(self) -> list[ProviderEntry]:
        """
        Providerهایی که همین حالا در **زنجیرهٔ خودکار** صدا زده می‌شوند.

        سه شرط: روشن باشد، در زنجیرهٔ خودکار باشد (`lyrics_auto_enabled`)، و
        قطع‌کننده اخراجش نکرده باشد.

        Providerی که از زنجیرهٔ خودکار بیرون است (Genius زیر
        `manual_only`) همچنان از `get()` قابلِ‌دسترسی است تا فراخوانِ دستی
        کار کند — فقط خودبه‌خود اجرا نمی‌شود.

        Providerِ کنارگذاشته‌شده اینجا نیست، پس `LyricsManager` هم نمی‌بیندش
        و خودبه‌خود از چرخه بیرون می‌ماند — بدونِ اینکه لازم باشد مدیر از
        وجودِ قطع‌کننده بداند. مدیر فقط برای *تفکیکِ کشِ منفی* از
        `is_evicted` استفاده می‌کند.
        """
        return [
            self._by_name[name]
            for name in self._order
            if self._by_name[name].is_available()
            and lyrics_auto_enabled(name)
            and not self.is_evicted(name)
        ]

    def get(self, name: str) -> ProviderEntry | None:
        return self._by_name.get(name)

    def is_selectable(self, name: str) -> bool:
        """
        آیا این Provider برای انتخابِ دستی در دسترس است؟

        قاعده (P1): انتخابِ دستی به `default_enabled` و عضویت در زنجیرهٔ
        خودکار **وابسته نیست**. `env` فقط دو نقش دارد: kill-switch برای
        خاموش‌کردنِ صریح (`..._ENABLED=0`)، و روشن‌کردنِ Providerی که
        خودش به کلید نیاز ندارد.

        پس یک Providerِ «پیش‌فرض خاموش» **قابلِ انتخاب** است — تا کاربر
        بتواند آگاهانه از آن استفاده کند بدونِ اینکه به زنجیرهٔ خودکار
        اضافه شود. تنها چیزی که مانع می‌شود: خاموشیِ صریح با env، یا
        نبودِ پیش‌نیازِ خودِ Provider (مثلِ توکنِ Genius).
        """
        entry = self._by_name.get(name)
        if entry is None:
            return False
        # kill-switch صریح: `default=True` صرفاً برای اینکه «ست‌نشده» یعنی
        # روشن؛ خودِ مقدارِ پیش‌فرضِ زنجیره اینجا نقشی ندارد.
        if not lyrics_provider_enabled(name, default=True):
            return False
        return entry.enabled() if entry.enabled is not None else True
