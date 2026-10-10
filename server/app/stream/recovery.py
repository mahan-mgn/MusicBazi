"""
قرارداد بازیابی (Recovery) و رزولوشن مجدد استریم‌های منقضی یوتیوب — Phase 8.

مسئولیت: تشخیص انقضا/رد شدن signed URL و گرفتن استریم تازه از طریق
YouTubeStreamResolver.resolve(video_id) — بدون استفاده مجدد از URL قدیمی.

قواعد قطعی:
  - refresh فقط با video_id انجام می‌شود؛ URL قدیمی هرگز retry نمی‌شود.
  - بودجه recovery: حداکثر MAX_RERESOLVE_ATTEMPTS (پیش‌فرض ۱) رزولوشن مجدد
    در هر فراخوانی recovery — حلقه resolve/expired/resolve ممنوع.
  - re-resolution از همان سیاست فاز ۶ (InnerTubeX PRIMARY → yt-dlp FALLBACK)
    و همان ClientHealthMonitor فاز ۷ عبور می‌کند؛ هیچ state موازی‌ای ساخته نمی‌شود.
  - classification خطای runtime محافظه‌کارانه است: فقط ۴۱۰، ۴۰۳ (رد امضای
    signed URL در googlevideo) و شواهد متنی صریح («expire»/«signature») به
    EXPIRED_STREAM نگاشت می‌شوند؛ مثلاً ۵۰۰ شبکه/سرور است نه انقضا.
  - single-flight per video_id: اگر چند consumer هم‌زمان متوجه انقضا شوند،
    فقط یک resolve اجرا می‌شود و بقیه نتیجه‌اش را share می‌کنند (قفل درون-پردازنده،
    بدون Redis یا lock توزیع‌شده).

امنیت: در این لایه هیچ URL (حتی redacted)، cookie، PO token یا داده session
persist یا log نمی‌شود. لاگ فقط video_id، resolver، reason و attempt دارد.
Stream تازه همیشه authoritative است؛ metadata قدیمی روی آن merge نمی‌شود.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from .errors import (
    ExpiredStreamError,
    NetworkError,
    StreamRecoveryError,
    StreamResolverError,
)
from .models import ResolvedStream
from .resolver import YouTubeStreamResolver

log = logging.getLogger(__name__)

# سقف رزولوشن مجدد در هر فراخوانی recovery (جلوگیری قطعی از حلقه)
MAX_RERESOLVE_ATTEMPTS = 1

# شواهد متنی صریح انقضا در reason خطای runtime (case-insensitive)
EXPIRATION_REASON_KEYWORDS = ("expire", "signature")


def classify_runtime_failure(
    http_status: int | None = None,
    reason: str = "",
    video_id: str = "",
) -> StreamResolverError:
    """
    نگاشت قطعی failure لایه playback/HTTP به مدل خطای استاندارد.

    شواهد انقضا (EXPIRED_STREAM):
      - HTTP 410: منبع دیگر معتبر نیست.
      - HTTP 403: امضای signed URL توسط CDN رد شده است (رفتار استاندارد
        googlevideo برای URL منقضی‌شده).
      - reason متنی حاوی «expire» یا «signature».

    غیر-انقضا:
      - 5xx → NetworkError (خطای سرور upstream، لزوماً انقضای URL نیست).
      - بقیه → خطای عمومی RUNTIME_FAILURE با retryable=True؛ بدون حدس گسترده.
    """
    reason_text = (reason or "").lower()

    if http_status == 410:
        return ExpiredStreamError(
            message="HTTP 410 Gone: stream URL is no longer valid",
            video_id=video_id,
        )
    if http_status == 403:
        return ExpiredStreamError(
            message="HTTP 403: signed stream URL rejected by CDN (expired signature)",
            video_id=video_id,
        )
    if any(keyword in reason_text for keyword in EXPIRATION_REASON_KEYWORDS):
        return ExpiredStreamError(
            message="Runtime failure evidence indicates an expired stream signature",
            video_id=video_id,
        )
    if http_status is not None and 500 <= http_status <= 599:
        return NetworkError(
            message="Upstream server error during stream access (not an expiration signal)",
            video_id=video_id,
        )
    return StreamResolverError(
        message="Unclassified runtime stream failure with insufficient expiration evidence",
        code="RUNTIME_FAILURE",
        retryable=True,
        video_id=video_id,
    )


class StreamRecovery:
    """
    Abstraction مستقل و تست‌پذیر بازیابی استریم — playback-agnostic.

    معماری:
      Expired / Rejected Stream
              ↓
         StreamRecovery  (تشخیص انقضا + بودجه ۱ تلاش + single-flight)
              ↓
      YouTubeStreamResolver.resolve(video_id)   [سیاست فاز ۶ + health فاز ۷]
              ↓
         InnerTubeX (PRIMARY) ──► yt-dlp (FALLBACK) در صورت مجاز بودن
              ↓
         Fresh ResolvedStream
    """

    def __init__(
        self,
        resolver: YouTubeStreamResolver | None = None,
        max_reresolve_attempts: int = MAX_RERESOLVE_ATTEMPTS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.resolver = resolver or YouTubeStreamResolver()
        self.max_reresolve_attempts = max(0, int(max_reresolve_attempts))
        self._clock = clock
        # single-flight درون-پردازنده: فقط asyncio.Task در حال اجرا نگه داشته می‌شود
        self._inflight: dict[str, asyncio.Task] = {}
        self._inflight_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # API عمومی
    # ------------------------------------------------------------------

    async def ensure_fresh(
        self,
        stream: ResolvedStream,
        purpose: str = "playback",
        quality: str | None = None,
    ) -> ResolvedStream:
        """
        Pre-check انقضا (ResolvedStream.is_expired با skew پیش‌فرض ۳۰ ثانیه).
        استریم سالم بدون هیچ resolve بازگردانده می‌شود؛ استریم منقضی/نزدیک‌انقضا
        با video_id مجدداً resolve می‌شود.
        """
        if stream is None:
            raise ValueError("stream cannot be None")
        if not stream.is_expired():
            return stream
        return await self._re_resolve_once(
            video_id=stream.video_id,
            original_reason="EXPIRED_STREAM",
            purpose=purpose,
            quality=quality,
        )

    async def recover_from_runtime_failure(
        self,
        video_id: str,
        http_status: int | None = None,
        reason: str = "",
        purpose: str = "playback",
        quality: str | None = None,
    ) -> ResolvedStream:
        """
        دریافت failure زمانِ استفاده (مثلاً 403/410 از playback layer) و
        رزولوشن مجدد فقط در صورت شواهد کافی انقضا. خطای غیر-انقضا عیناً
        به بالا پرتاب می‌شود تا consumer مسیر خودش را برود؛ recovery حدسی انجام نمی‌شود.
        """
        clean_vid = (video_id or "").strip()
        if not clean_vid:
            raise ValueError("video_id cannot be empty")

        classified = classify_runtime_failure(
            http_status=http_status,
            reason=reason,
            video_id=clean_vid,
        )
        if not isinstance(classified, ExpiredStreamError):
            log.info(
                "stream recovery declined [vid=%s, reason=%s, status=%s]",
                clean_vid,
                classified.code,
                http_status,
            )
            raise classified

        return await self._re_resolve_once(
            video_id=clean_vid,
            original_reason=classified.code,
            purpose=purpose,
            quality=quality,
        )

    # ------------------------------------------------------------------
    # مسیر داخلی رزولوشن مجدد
    # ------------------------------------------------------------------

    async def _re_resolve_once(
        self,
        video_id: str,
        original_reason: str,
        purpose: str,
        quality: str | None,
    ) -> ResolvedStream:
        if self.max_reresolve_attempts < 1:
            raise StreamRecoveryError(
                message=f"Re-resolution budget is zero for videoId={video_id}",
                video_id=video_id,
                original_reason=original_reason,
                recovery_error=StreamResolverError(
                    message="Re-resolution disabled",
                    code="RECOVERY_DISABLED",
                    retryable=False,
                    video_id=video_id,
                ),
            )

        log.info(
            "stream recovery started [vid=%s, reason=%s, attempt=1]",
            video_id,
            original_reason,
        )

        async def factory() -> ResolvedStream:
            fresh = await self.resolver.resolve(
                video_id=video_id,
                purpose=purpose,
                quality=quality,
            )
            # درج تشخیصی غیرحساس؛ هیچ فیلد authoritative استریم تازه بازنویسی نمی‌شود
            meta = dict(fresh.resolver_metadata)
            meta["recovered_from"] = original_reason
            meta["recovery_attempt"] = 1
            return fresh.model_copy(update={"resolver_metadata": meta})

        try:
            fresh = await self._single_flight(video_id, factory)
        except StreamResolverError as exc:
            # علت اصلی (دلیل ورود به recovery) + علت شکست رزولوشن مجدد حفظ می‌شود
            raise StreamRecoveryError(
                message=f"Re-resolution failed for videoId={video_id} (original reason: {original_reason})",
                video_id=video_id,
                original_reason=original_reason,
                recovery_error=exc,
            ) from exc

        if fresh.is_expired():
            # بودجه recovery تمام است؛ استریم منقضی بازگردانده نمی‌شود
            raise StreamRecoveryError(
                message=(
                    f"Re-resolved stream for videoId={video_id} is already expired; "
                    f"recovery budget of {self.max_reresolve_attempts} attempt(s) exhausted"
                ),
                video_id=video_id,
                original_reason=original_reason,
                recovery_error=ExpiredStreamError(
                    message="Fresh stream is already expired", video_id=video_id
                ),
            )

        log.info(
            "stream recovery success [vid=%s, resolver=%s, attempt=1]",
            video_id,
            fresh.resolver_metadata.get("resolver") or "unknown",
        )
        return fresh

    async def _single_flight(
        self,
        video_id: str,
        factory: Callable[[], Awaitable[ResolvedStream]],
    ) -> ResolvedStream:
        """
        یک resolve در حالِ اجرا per video_id: سایر caller های هم‌زمان منتظر همان
        Task می‌مانند و نتیجه (یا شکست) مشترک را دریافت می‌کنند. اگر caller غیرمالک
        کنسل شود، Task اصلی ادامه می‌یابد (asyncio.shield).
        """
        async with self._inflight_lock:
            task = self._inflight.get(video_id)
            owner = task is None
            if owner:
                task = asyncio.ensure_future(factory())
                self._inflight[video_id] = task

        try:
            return await asyncio.shield(task)
        finally:
            if owner:
                async with self._inflight_lock:
                    if self._inflight.get(video_id) is task:
                        del self._inflight[video_id]
