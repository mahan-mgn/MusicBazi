"""
Metrics جمع‌آوری Shadow Mode Validation (Phase 10).

ساختار بسیار سبک و In-Process برای پاسخ به سؤالات اعتبارسنجی rollout:
  - چند Shadow Resolution اجرا شده؟ چند موفق/شکست؟
  - InnerTubeX چند بار مستقیم حل کرده و چند بار به yt-dlp fallback رفته؟
  - چند نتیجه با Production match بوده و چه فیلدهایی mismatch داشته؟
  - Failure codeهای اصلی چه بوده‌اند؟
  - Latency رزولوشن Shadow چقدر بوده؟

قواعد:
  - هیچ Database/Redis/Prometheus/endpoint عمومی — فقط counter های in-memory
    با یک threading.Lock ساده (thread-safe و async-safe؛ snapshot consistent).
  - هیچ video ID، URL (حتی redacted)، header، cookie یا token وارد metrics
    نمی‌شود؛ failure فقط با error code استاندارد فازهای قبلی aggregate می‌شود
    (taxonomy جدیدی ساخته نشده) و پیام استثنا هرگز اینجا نمی‌رسد.
  - latency با monotonic clock در ShadowStreamResolver اندازه‌گیری می‌شود و
    فقط به‌صورت aggregate (total/count/avg/max) نگه داشته می‌شود.
  - دیکشنری‌های by_code/by_field bounded هستند تا رشد نامحدود نداشته باشند.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # import چرخه‌ای فقط برای تایپ
    from .shadow import ShadowComparison

# سقف تعداد کد/فیلد متمایز در aggregate ها (جلوگیری از رشد نامحدود)
MAX_DISTINCT_FAILURE_CODES = 32
MAX_DISTINCT_MISMATCH_FIELDS = 16

# برچسب bucket برای مقادیر مازاد از سقف
_OVERFLOW_LABEL = "other"


class ShadowMetrics:
    """Counter های امن و thread-safe برای اعتبارسنجی Shadow Mode."""

    def __init__(
        self,
        max_failure_codes: int = MAX_DISTINCT_FAILURE_CODES,
        max_mismatch_fields: int = MAX_DISTINCT_MISMATCH_FIELDS,
    ) -> None:
        self._lock = threading.Lock()
        self._max_failure_codes = max(1, int(max_failure_codes))
        self._max_mismatch_fields = max(1, int(max_mismatch_fields))
        self.reset()

    # ------------------------------------------------------------------
    # ثبت
    # ------------------------------------------------------------------

    def record_observation(self, comparison: "ShadowComparison", latency_ms: float) -> None:
        """
        ثبت یک Shadow observation از روی ShadowComparison فاز ۹ (فقط فیلدهای
        امن آن خوانده می‌شود) و latency اندازه‌گیری‌شده با monotonic clock.
        """
        code = (comparison.shadow_error_code or "UNKNOWN").upper()
        with self._lock:
            self.total += 1
            self.latency_total_ms += max(0.0, float(latency_ms))
            self.latency_count += 1
            if float(latency_ms) > self.latency_max_ms:
                self.latency_max_ms = float(latency_ms)

            if comparison.shadow_outcome == "success":
                self.success += 1
                if comparison.shadow_path == "innertubex":
                    self.innertubex_success += 1
                elif comparison.shadow_path == "yt-dlp-fallback":
                    self.ytdlp_fallback += 1
            else:
                self.failure += 1
                bucket = code if code in self.failure_by_code or len(self.failure_by_code) < self._max_failure_codes else _OVERFLOW_LABEL
                self.failure_by_code[bucket] = self.failure_by_code.get(bucket, 0) + 1

            # مقایسه metadata فقط وقتی هر دو موفق هستند معنا دارد
            if (
                comparison.production_outcome == "success"
                and comparison.shadow_outcome == "success"
            ):
                if comparison.matches:
                    self.metadata_match += 1
                else:
                    self.metadata_mismatch += 1
                    for field_name in sorted(comparison.differences.keys()):
                        bucket = (
                            field_name
                            if field_name in self.mismatch_by_field
                            or len(self.mismatch_by_field) < self._max_mismatch_fields
                            else _OVERFLOW_LABEL
                        )
                        self.mismatch_by_field[bucket] = self.mismatch_by_field.get(bucket, 0) + 1

    # ------------------------------------------------------------------
    # خواندن / پاک‌کردن
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """نمای consistent فقط-خواندنی از aggregate های امن (بدون هیچ secret)."""
        with self._lock:
            avg = (
                self.latency_total_ms / self.latency_count
                if self.latency_count > 0
                else 0.0
            )
            return {
                "total": self.total,
                "success": self.success,
                "failure": self.failure,
                "innertubex_success": self.innertubex_success,
                "ytdlp_fallback": self.ytdlp_fallback,
                "metadata_match": self.metadata_match,
                "metadata_mismatch": self.metadata_mismatch,
                "latency_total_ms": round(self.latency_total_ms, 3),
                "latency_count": self.latency_count,
                "latency_avg_ms": round(avg, 3),
                "latency_max_ms": round(self.latency_max_ms, 3),
                "failure_by_code": dict(sorted(self.failure_by_code.items())),
                "mismatch_by_field": dict(sorted(self.mismatch_by_field.items())),
            }

    def reset(self) -> None:
        """پاک‌کردن کامل counters (In-Memory فقط؛ برای تست و توسعه)."""
        with self._lock:
            self.total = 0
            self.success = 0
            self.failure = 0
            self.innertubex_success = 0
            self.ytdlp_fallback = 0
            self.metadata_match = 0
            self.metadata_mismatch = 0
            self.latency_total_ms = 0.0
            self.latency_count = 0
            self.latency_max_ms = 0.0
            self.failure_by_code: dict[str, int] = {}
            self.mismatch_by_field: dict[str, int] = {}
