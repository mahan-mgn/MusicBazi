"""
ارکستراتور رزولور استریم یوتیوب در Music Bazi.
مسئولیت: ارکستراسیون قطعی با سیاست InnerTubeX (PRIMARY) و yt-dlp (SECONDARY / FALLBACK).
ماتریس خطاها، سقف ۱ تلاش برای هر رزولور (جلوگیری از لوپ)، حفظ علت ریشه‌ای و لاگ امن.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable

from .client_health import ClientHealthMonitor, FAILURE_CLIENT_LABEL
from .errors import (
    AllResolversFailedError,
    BridgeTimeoutError,
    BridgeUnavailableError,
    CipherError,
    ClientRejectedError,
    ClientUnhealthyError,
    ExpiredStreamError,
    InvalidResponseError,
    NetworkError,
    NoStreamError,
    POTokenError,
    PermanentlyUnplayableError,
    StreamResolverError,
    UnsupportedFormatError,
)
from .innertubex import InnerTubeXResolver
from .models import ResolvedStream
from .ytdlp import YtDlpResolver

log = logging.getLogger(__name__)

# مدت زمان پیش‌فرض نگهداری خطاهای قطعی در کش (۱۰ دقیقه مطابق با BitChord)
DEFAULT_UNPLAYABLE_CACHE_TTL_SECONDS = 600.0

# عبارات کلیدی نشان‌دهنده خطای قطعی در محتوا (حذف ویدیو، محتوای خصوصی، محدودیت سنی یا منطقه‌ای)
PERMANENT_UNPLAYABLE_KEYWORDS: tuple[str, ...] = (
    "private video",
    "video unavailable",
    "not available in your country",
    "has been removed",
    "terms of service",
    "age-restricted",
    "age restricted",
    "account terminated",
    "community guidelines",
    "members-only",
    "paid content",
)


def classify_permanent_unplayable(error: StreamResolverError | None) -> tuple[str, str] | None:
    """
    تشخیص قطعی بودن خطا جهت ذخیره در کش Anti-Storm (Phase 3).
    خطاهای موقت، قطعی شبکه، تایم‌اوت، ۵xx، شکست پروب یک کلاینت یا انقضای URL هرگز قطعی تلقی نمی‌شوند.
    """
    if error is None:
        return None
    if isinstance(error, PermanentlyUnplayableError):
        return error.code, error.message
    if isinstance(error, AllResolversFailedError):
        p_res = classify_permanent_unplayable(error.primary_error)
        if p_res is not None:
            return p_res
        f_res = classify_permanent_unplayable(error.fallback_error)
        if f_res is not None:
            return f_res
        return None

    # خطاهای موقت زیرساختی و شبکه نباید کش شوند
    if isinstance(
        error,
        (
            BridgeUnavailableError,
            BridgeTimeoutError,
            NetworkError,
            ExpiredStreamError,
            ClientUnhealthyError,
        ),
    ):
        return None

    code = error.code
    msg = (error.message or "").lower()

    if code == "AGE_RESTRICTED":
        return "AGE_RESTRICTED", error.message

    if code in ("UNAVAILABLE", "CLIENT_REJECTED", "NO_STREAM"):
        if any(keyword in msg for keyword in PERMANENT_UNPLAYABLE_KEYWORDS):
            return "UNAVAILABLE", error.message

    return None


class UnplayableCache:
    """
    کش کوتاه‌مدت خطاهای قطعی و غیرقابل‌پخش یوتیوب برای جلوگیری از طوفان درخواست (Phase 3).
    پیش‌فرض TTL: ۱۰ دقیقه (۶۰۰ ثانیه).
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_UNPLAYABLE_CACHE_TTL_SECONDS,
        max_entries: int = 1000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._clock = clock
        self._entries: dict[str, tuple[str, str, float]] = {}  # vid -> (code, message, timestamp)
        self._lock = threading.RLock()

    def get_unplayable(self, video_id: str) -> tuple[str, str] | None:
        clean_vid = (video_id or "").strip()
        if not clean_vid:
            return None
        now = self._clock()
        with self._lock:
            entry = self._entries.get(clean_vid)
            if entry is None:
                return None
            code, message, timestamp = entry
            if now - timestamp < self.ttl_seconds:
                return code, message
            del self._entries[clean_vid]
            return None

    def remember_unplayable(self, video_id: str, code: str, message: str) -> None:
        clean_vid = (video_id or "").strip()
        if not clean_vid:
            return
        now = self._clock()
        with self._lock:
            if len(self._entries) >= self.max_entries:
                expired = [
                    k
                    for k, (_, _, ts) in self._entries.items()
                    if now - ts >= self.ttl_seconds
                ]
                for k in expired:
                    del self._entries[k]
                if len(self._entries) >= self.max_entries:
                    self._entries.clear()
            self._entries[clean_vid] = (code, message, now)

    def remove(self, video_id: str) -> None:
        clean_vid = (video_id or "").strip()
        with self._lock:
            self._entries.pop(clean_vid, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

# ماتریس صریح خطاهای InnerTubeX که مجاز به فال‌بک به yt-dlp هستند
FALLBACK_ALLOWED_ERRORS: tuple[type[StreamResolverError], ...] = (
    BridgeUnavailableError,
    BridgeTimeoutError,
    NoStreamError,
    ClientRejectedError,
    ClientUnhealthyError,
    CipherError,
    POTokenError,
    InvalidResponseError,
    ExpiredStreamError,
    UnsupportedFormatError,
    NetworkError,
)


def _classify_error(exc: Exception, video_id: str) -> StreamResolverError:
    """دسته‌بندی و نرمال‌سازی قطعی خطاها به مدل تایپ‌شده StreamResolverError."""
    if isinstance(exc, StreamResolverError):
        return exc
    # خطاهای پیش‌بینی‌نشده عمومی را با کد استاندارد کپسوله می‌کنیم
    return StreamResolverError(
        message=f"Unexpected resolution error: {exc}",
        code="UNKNOWN_ERROR",
        retryable=False,
        video_id=video_id,
    )


class YouTubeStreamResolver:
    """
    ارکستراتور متمرکز استخراج استریم یوتیوب.
    معماری:
      ClientHealthMonitor (فاز ۷)
           │ eligible؟
      InnerTubeX (PRIMARY)
           │
           ├── موفق ───────────────► ResolvedStream (record_success)
           │
           └── ناموفق (رده‌بندی) ──► yt-dlp (FALLBACK) — فقط ۱ بار
                                        │
                                        ├── موفق ──► ResolvedStream
                                        └── ناموفق ─► AllResolversFailedError
    """

    def __init__(
        self,
        primary_resolver: InnerTubeXResolver | None = None,
        fallback_resolver: YtDlpResolver | None = None,
        client_health: ClientHealthMonitor | None = None,
        unplayable_cache: UnplayableCache | None = None,
    ) -> None:
        self.primary = primary_resolver or InnerTubeXResolver()
        self.fallback = fallback_resolver or YtDlpResolver()
        self.client_health = client_health if client_health is not None else ClientHealthMonitor()
        self.unplayable_cache = unplayable_cache if unplayable_cache is not None else UnplayableCache()

    def on_session_changed(self) -> None:
        """
        ابطال کامل کش خطاهای قطعی و بازنشانی وضعیت سلامت کلاینت‌ها هنگام
        تغییر نشست، آپلود کوکی‌های جدید یوتیوب یا تغییر احراز هویت (مشابه onSessionChanged در BitChord).
        """
        self.unplayable_cache.clear()
        if hasattr(self.client_health, "clear"):
            self.client_health.clear()
        if hasattr(self.primary, "notify_session_changed"):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.primary.notify_session_changed())
            except RuntimeError:
                pass
        log.info("YouTube resolver: session changed, unplayable cache and client health cleared")

    async def resolve(
        self,
        video_id: str,
        purpose: str = "playback",
        quality: str | None = None,
    ) -> ResolvedStream:
        """
        رزولو کردن استریم ویدیو از یوتیوب با اعمال دقیق خط مشی فال‌بک.
        حداکثر ۱ بار تلاش با رزولور اصلی و ۱ بار با رزولور پشتیبان.
        سلامت InnerTubeX فقط تصمیم می‌گیرد که تلاش اصلی انجام شود یا مستقیم
        به سیاست فال‌بک موجود سپرده شود؛ سیاست فال‌بک خودش تغییر نمی‌کند.
        کش Anti-Storm (Phase 3) از تکرار بیهوده استخراج ویدیوهای غیرقابل‌پخش جلوگیری می‌کند.
        """
        clean_vid = video_id.strip()
        if not clean_vid:
            raise ValueError("video_id cannot be empty")

        # بررسی کش Anti-Storm خطاهای قطعی
        cached_unplayable = self.unplayable_cache.get_unplayable(clean_vid)
        if cached_unplayable is not None:
            c_code, c_msg = cached_unplayable
            log.warning(
                "YouTube resolver anti-storm cache hit [vid=%s, code=%s]",
                clean_vid,
                c_code,
            )
            raise PermanentlyUnplayableError(
                message=c_msg,
                video_id=clean_vid,
                code=c_code,
            )

        # -------------------------------------------------------------
        # 1. تلاش با رزولور اصلی: InnerTubeX (PRIMARY)
        #    در حالت UNHEALTHYِ همان ویدیو، تلاش اصلی صرف‌نظر می‌شود
        #    (ClientUnhealthyError) تا فال‌بک موجود بدون تأخیر اضافه اجرا شود.
        # -------------------------------------------------------------
        primary_error: StreamResolverError | None = None
        if not self.client_health.is_eligible(clean_vid):
            primary_error = ClientUnhealthyError(
                message=(
                    "InnerTubeX skipped for this video: consecutive recent client failures "
                    "(cooldown active, retry allowed after half-open)"
                ),
                video_id=clean_vid,
            )
            log.warning(
                "YouTube resolver primary skipped by health [vid=%s, resolver=innertubex, state=UNHEALTHY]",
                clean_vid,
            )
        else:
            try:
                stream = await self.primary.resolve_stream(
                    video_id=clean_vid,
                    purpose=purpose,
                    quality=quality,
                )
                # اعتبارسنجی انقضای لحظه رزولوشن (Resolution-time expiration check)
                if stream.is_expired():
                    raise ExpiredStreamError(
                        message="InnerTubeX returned an already-expired stream URL",
                        video_id=clean_vid,
                    )

                # ثبت موفقیت فقط برای همین ویدیو؛ کلاینت واقعی از متادیتای Bridge
                self.client_health.record_success(
                    clean_vid,
                    str(stream.resolver_metadata.get("client_name") or FAILURE_CLIENT_LABEL),
                )

                self.unplayable_cache.remove(clean_vid)

                log.info(
                    "YouTube resolver success [vid=%s, resolver=innertubex, codec=%s, bitrate=%s]",
                    clean_vid,
                    stream.codec,
                    stream.bitrate,
                )
                return stream

            except Exception as exc:
                primary_error = _classify_error(exc, clean_vid)
                self.client_health.record_failure(clean_vid, reason=primary_error.code)
                log.warning(
                    "YouTube resolver primary failed [vid=%s, resolver=innertubex, error_type=%s, code=%s]: %s",
                    clean_vid,
                    primary_error.__class__.__name__,
                    primary_error.code,
                    primary_error.message,
                )

        # -------------------------------------------------------------
        # 2. ارزیابی خط مشی فال‌بک (Fallback Policy Check)
        # -------------------------------------------------------------
        is_fallback_allowed = isinstance(primary_error, FALLBACK_ALLOWED_ERRORS)
        if not is_fallback_allowed:
            perm_check = classify_permanent_unplayable(primary_error)
            if perm_check is not None:
                p_code, p_msg = perm_check
                self.unplayable_cache.remember_unplayable(clean_vid, p_code, p_msg)
            log.error(
                "YouTube resolver fallback forbidden for error %s [vid=%s]",
                primary_error.__class__.__name__,
                clean_vid,
            )
            raise primary_error

        # -------------------------------------------------------------
        # 3. تلاش با رزولور ثانویه: yt-dlp (SECONDARY / FALLBACK)
        # -------------------------------------------------------------
        log.info(
            "YouTube resolver engaging fallback [vid=%s, from=innertubex, to=yt-dlp, reason=%s]",
            clean_vid,
            primary_error.code,
        )

        fallback_error: StreamResolverError | None = None
        try:
            stream = await self.fallback.resolve_stream(
                video_id=clean_vid,
                purpose=purpose,
                quality=quality,
            )
            if stream.is_expired():
                raise ExpiredStreamError(
                    message="yt-dlp returned an already-expired stream URL",
                    video_id=clean_vid,
                )

            # افزودن متادیتای تشخیصی غیرحساس برای شفافیت لایه‌های بالاتر
            updated_meta: dict[str, Any] = dict(stream.resolver_metadata)
            updated_meta["resolver"] = "yt-dlp"
            updated_meta["fallback_from"] = "innertubex"
            updated_meta["primary_failure"] = primary_error.code

            fallback_stream = stream.model_copy(update={"resolver_metadata": updated_meta})

            self.unplayable_cache.remove(clean_vid)

            log.info(
                "YouTube resolver fallback success [vid=%s, resolver=yt-dlp, codec=%s, bitrate=%s, primary_failure=%s]",
                clean_vid,
                fallback_stream.codec,
                fallback_stream.bitrate,
                primary_error.code,
            )
            return fallback_stream

        except Exception as exc:
            fallback_error = _classify_error(exc, clean_vid)
            log.error(
                "YouTube resolver fallback failed [vid=%s, resolver=yt-dlp, error_type=%s, code=%s]: %s",
                clean_vid,
                fallback_error.__class__.__name__,
                fallback_error.code,
                fallback_error.message,
            )

        # -------------------------------------------------------------
        # 4. شکست هر دو رزولور: اعلام خطای نهایی با حفظ هر دو علت
        # -------------------------------------------------------------
        all_err = AllResolversFailedError(
            video_id=clean_vid,
            primary_error=primary_error,
            fallback_error=fallback_error,
        )
        perm = classify_permanent_unplayable(all_err)
        if perm is not None:
            perm_code, perm_msg = perm
            self.unplayable_cache.remember_unplayable(clean_vid, perm_code, perm_msg)
            log.warning(
                "YouTube resolver cached permanent unplayable [vid=%s, code=%s]",
                clean_vid,
                perm_code,
            )
        raise all_err
