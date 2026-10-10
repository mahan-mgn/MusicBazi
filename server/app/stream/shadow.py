"""
Shadow Mode معماری جدید Stream Resolution (Phase 9).

وقتی MUSICBAZI_STREAM_V2 فعال باشد، به‌ازای هر نتیجه Production می‌توان یک
Shadow Resolution با همان video_id اجرا کرد و نتیجه را فقط برای Diagnostic
با Production مقایسه کرد.

Invariants سخت:
  - Shadow هرگز نتیجه Production را جایگزین، mutate یا override نمی‌کند.
  - خطای Shadow هرگز به Production نشت نمی‌کند (isolation کامل) و retry loop
    یا fallback policy جدیدی نمی‌سازد — Shadow از همان orchestration فاز ۶
    (InnerTubeX → yt-dlp) و همان Client Health فاز ۷ عبور می‌کند.
  - Shadow playback/downloader/cache را کنترل نمی‌کند؛ خروجی این ماژول صرفاً
    یک ShadowComparison تشخیصی است.
  - StreamRecovery فاز ۸ در این فاز به مسیر Shadow وصل نشده (نیاز نبود:
    خروجی orchestration فاز ۶ هم‌اکنون استریم منقضی را reject می‌کند)؛ در صورت
    اتصال آینده، فقط Diagnostic و با همان بودجه یک‌تلاشی خواهد بود.

مقایسه فقط روی Safe Metadata (فهرست بسته SHADOW_COMPARE_FIELDS) انجام و
ثبت می‌شود؛ Signed URL، headers، cookie، token و هر داده session هرگز وارد
comparison، state یا log نمی‌شوند. پیام استثناها هم log نمی‌شود — فقط
کلاس خطا و کد استاندارد آن.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from .feature_flags import is_stream_v2_enabled
from .models import ResolvedStream
from .resolver import YouTubeStreamResolver
from .shadow_metrics import ShadowMetrics

log = logging.getLogger(__name__)

# فیلدهای Safe Metadata مجاز برای مقایسه Production ↔ Shadow.
# عمداً url/headers/expires_at در این فهرست نیستند (حاوی داده حساس/امضا هستند).
SHADOW_COMPARE_FIELDS: tuple[str, ...] = (
    "source",
    "video_id",
    "mime_type",
    "codec",
    "bitrate",
    "sample_rate",
    "channels",
    "duration",
    "content_length",
    "stream_type",
    "is_lossless",
)

# سقف Taskهای shadow در حال اجرا (جلوگیری از Task بی‌نهایت درون-پردازشی)
MAX_INFLIGHT_SHADOW_TASKS = 8

# نمونه مشترک metrics برای همه ShadowStreamResolver ها (In-Process، بدون persistence)
DEFAULT_SHADOW_METRICS = ShadowMetrics()


def get_shadow_metrics() -> dict[str, Any]:
    """snapshot امن از metrics نمونه مشترک (فقط aggregate های safe)."""
    return DEFAULT_SHADOW_METRICS.snapshot()


def reset_shadow_metrics() -> None:
    """پاک‌کردن metrics نمونه مشترک (In-Memory فقط؛ برای تست و توسعه)."""
    DEFAULT_SHADOW_METRICS.reset()


@dataclass(frozen=True)
class ShadowComparison:
    """
    نتیجه ساختاریافته و تست‌پذیر مقایسه Production و Shadow.
    فقط Safe Metadata و outcome ها — هرگز URL/token/session data.
    """

    video_id: str
    production_outcome: str  # "success" | "failure"
    shadow_outcome: str      # "success" | "failure"
    shadow_path: str         # "innertubex" | "yt-dlp-fallback" | "unknown" | ""
    matches: bool = False
    differences: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    production_error_code: str | None = None
    shadow_error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "production_outcome": self.production_outcome,
            "shadow_outcome": self.shadow_outcome,
            "shadow_path": self.shadow_path,
            "matches": self.matches,
            "differences": {k: list(v) for k, v in self.differences.items()},
            "production_error_code": self.production_error_code,
            "shadow_error_code": self.shadow_error_code,
        }


def compare_streams(
    video_id: str,
    production_stream: ResolvedStream | None,
    shadow_stream: ResolvedStream | None,
    production_error: str | None = None,
    shadow_error_code: str | None = None,
) -> ShadowComparison:
    """
    مقایسه امن روی فیلدهای SHADOW_COMPARE_FIELDS. production_error فقط کد
    استاندارد (نه پیام) است. خروجی هیچ فیلد حساسی ندارد.
    """
    production_outcome = "success" if production_stream is not None else "failure"
    shadow_outcome = "success" if shadow_stream is not None else "failure"

    differences: dict[str, tuple[Any, Any]] = {}
    if production_stream is not None and shadow_stream is not None:
        for field_name in SHADOW_COMPARE_FIELDS:
            prod_val = getattr(production_stream, field_name, None)
            shadow_val = getattr(shadow_stream, field_name, None)
            if prod_val != shadow_val:
                differences[field_name] = (prod_val, shadow_val)

    if shadow_stream is not None:
        resolver_name = str(shadow_stream.resolver_metadata.get("resolver") or "unknown")
        fallback_from = shadow_stream.resolver_metadata.get("fallback_from")
        shadow_path = (
            "yt-dlp-fallback" if fallback_from else resolver_name
        )
    else:
        shadow_path = "unknown"

    return ShadowComparison(
        video_id=video_id,
        production_outcome=production_outcome,
        shadow_outcome=shadow_outcome,
        shadow_path=shadow_path,
        matches=(production_outcome == shadow_outcome and not differences),
        differences=differences,
        production_error_code=production_error or None,
        shadow_error_code=shadow_error_code,
    )


class ShadowStreamResolver:
    """
    اجرای تشخیصی معماری جدید در سایه Production. نتیجه Production به‌صورت
    read-only دریافت می‌شود؛ این کلاس فقط یک ShadowComparison برمی‌گرداند.
    """

    def __init__(
        self,
        shadow_resolver: YouTubeStreamResolver | None = None,
        metrics: ShadowMetrics | None = None,
    ) -> None:
        self.shadow_resolver = shadow_resolver or YouTubeStreamResolver()
        # پیش‌فرض: نمونه مشترک in-process؛ تست‌ها می‌توانند نمونه مجزا تزریق کنند
        self.metrics = metrics if metrics is not None else DEFAULT_SHADOW_METRICS
        self._inflight: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # API عمومی
    # ------------------------------------------------------------------

    async def observe(
        self,
        video_id: str,
        production_stream: ResolvedStream | None = None,
        production_error_code: str | None = None,
        purpose: str = "playback",
        quality: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ShadowComparison | None:
        """
        اجرای Shadow Resolution و مقایسه. خروجی:
          None          → flag خاموش (هیچ کاری انجام نشده)
          ShadowComparison → نتیجه تشخیصی (خطای Shadow اینجا swallow شده)

        production_stream فقط خوانده می‌شود و هیچ‌گاه mutate یا بازگردانده نمی‌شود.
        """
        clean_vid = (video_id or "").strip()
        if not clean_vid:
            raise ValueError("video_id cannot be empty")

        if not is_stream_v2_enabled(env):
            return None

        shadow_stream: ResolvedStream | None = None
        shadow_error_code: str | None = None
        resolve_started = time.monotonic()
        try:
            shadow_stream = await self.shadow_resolver.resolve(
                video_id=clean_vid,
                purpose=purpose,
                quality=quality,
            )
        except Exception as exc:
            # Isolation: خطای Shadow فقط Diagnostic می‌شود؛ هرگز به Production نشت نمی‌کند.
            # پیام استثنا عمداً log/ذخیره نمی‌شود تا هیچ داده حساسی وارد diagnostics نشود.
            shadow_error_code = getattr(exc, "code", None) or exc.__class__.__name__
            log.warning(
                "shadow resolution failed [vid=%s, error_class=%s, error_code=%s]",
                clean_vid,
                exc.__class__.__name__,
                shadow_error_code,
            )
        latency_ms = max(0.0, (time.monotonic() - resolve_started) * 1000.0)

        comparison = compare_streams(
            video_id=clean_vid,
            production_stream=production_stream,
            shadow_stream=shadow_stream,
            production_error=production_error_code,
            shadow_error_code=shadow_error_code,
        )

        # ثبت metrics امن (Phase 10) — فقط aggregate و بدون هیچ داده حساس
        try:
            self.metrics.record_observation(comparison, latency_ms)
        except Exception:  # metrics هرگز نباید مسیر observation را خراب کند
            log.warning("shadow metrics recording failed [vid=%s]", clean_vid)

        log.info(
            "shadow compare [vid=%s, production=%s, shadow=%s, shadow_path=%s, matches=%s, diffs=%s, latency_ms=%.1f]",
            comparison.video_id,
            comparison.production_outcome,
            comparison.shadow_outcome,
            comparison.shadow_path,
            comparison.matches,
            ",".join(sorted(comparison.differences.keys())) or "-",
            latency_ms,
        )
        return comparison

    def spawn_observation(
        self,
        video_id: str,
        production_stream: ResolvedStream | None = None,
        production_error_code: str | None = None,
        purpose: str = "playback",
        quality: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> asyncio.Task | None:
        """
        نسخه غیرمسدودکننده برای اتصال آینده (Phase 10): Production را block
        نمی‌کند؛ Task با drain-callback ساخته می‌شود تا هیچ exception ای
        un_handler نماند. سقف MAX_INFLIGHT_SHADOW_TASKS رعایت می‌شود.
        """
        if not is_stream_v2_enabled(env):
            return None
        if len(self._inflight) >= MAX_INFLIGHT_SHADOW_TASKS:
            log.warning(
                "shadow observation skipped [vid=%s, reason=inflight_cap]",
                (video_id or "").strip(),
            )
            return None

        task = asyncio.ensure_future(
            self.observe(
                video_id=video_id,
                production_stream=production_stream,
                production_error_code=production_error_code,
                purpose=purpose,
                quality=quality,
                env=env,
            )
        )
        self._inflight.add(task)

        def _drain(done: asyncio.Task) -> None:
            self._inflight.discard(done)
            if done.cancelled():
                log.info("shadow observation cancelled [vid=%s]", (video_id or "").strip())
                return
            exc = done.exception()
            if exc is not None:
                # آخرین خط دفاعی: exception هر Shadow هرگز unhandled نمی‌ماند
                log.warning(
                    "shadow observation task error [error_class=%s]",
                    exc.__class__.__name__,
                )

        task.add_done_callback(_drain)
        return task
