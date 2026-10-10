"""
مانیتور سلامت سبک و in-memory کلاینت‌های InnerTubeX (Phase 7).

مسئولیت: ثبت شکست‌های متوالی رزولوشن InnerTubeX در سطح ویدیو و خارج‌کردن موقت
(deprioritize) کلاینت از تلاش‌های بعدی تا پایان cooldown، بدون دورزدن سیاست فال‌بک.

Scope نگهداری state:
  کلید = (video_id, client)
  - روی موفقیت، نام کلاینت واقعی از resolver_metadata برمی‌گردد (مثلاً WEB_REMIX).
  - روی شکست، Bridge در پروتکل فعلی نام کلاینت را برنمی‌گرداند (انتخاب کلاینت داخلی
    InnerTubeX است)، بنابراین شکست با برچسب FAILUre_CLIENT_LABEL ثبت می‌شود.
    این یعنی باریک‌ترین scope قابل‌رصدِ راستین در لایه پایتون: سلامت رزولوشن
    InnerTubeXِ همان ویدیو. هیچ‌گاه شکست یک ویدیو باعث ناسالم اعلام‌شدن کلاینت‌ها
    برای ویدیوهای دیگر نمی‌شود.

نگاشت خطاها:
  - BRIDGE_UNAVAILABLE و INVALID_REQUEST شکست کلاینت یوتیوب نیستند (دسترس‌پذیری
    خود Bridge / درخواست خراب) و در health ثبت نمی‌شوند.
  - بقیه کدها (CLIENT_REJECTED، CIPHER_ERROR، PO_TOKEN_ERROR، NO_STREAM،
    INVALID_RESPONSE، TIMEOUT، NETWORK_ERROR، EXPIRED_STREAM، ...) وزن یکسان
    دارند؛ داده فعلی تمایز وزن‌دار معتبر بین آن‌ها نمی‌دهد و weight ساختگی جعل نمی‌شود.

امنیت: state فقط شامل شناسه ویدیو، برچسب کلاینت، شمارنده، مهر زمانی و کد دلیل است.
Signed URL، cookie، PO token، Authorization و هر داده session ذخیره یا لاگ نمی‌شود.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

# آستانه شکست متوالی تا ورود به حالت UNHEALTHY (قابل تنظیم برای تست/عملیات)
CLIENT_FAILURE_THRESHOLD = 2

# مدت cooldown پس از unhealthy؛ پس از آن کلاینت HALF-OPEN می‌شود و تلاش مجدد مجاز است
CLIENT_HEALTH_COOLDOWN_SECONDS = 300

# TTL حیات entry های health برای جلوگیری از رشد نامحدود حافظه
HEALTH_ENTRY_TTL_SECONDS = 3600

# سقف مطلق تعداد entry ها؛ در صورت پرشدن، قدیمی‌ترین‌ها حذف می‌شوند
MAX_HEALTH_ENTRIES = 10_000

# برچسب ثبت شکست وقتی Bridge نام کلاینت شکست‌خورده را برنمی‌گرداند (پروتکل فعلی)
FAILURE_CLIENT_LABEL = "unknown"

# کدهایی که شکستِ کلاینت یوتیوب محسوب نمی‌شوند و نباید health را خراب کنند
NON_CLIENT_FAILURE_CODES = frozenset({"BRIDGE_UNAVAILABLE", "INVALID_REQUEST"})

STATE_HEALTHY = "HEALTHY"
STATE_UNHEALTHY = "UNHEALTHY"
STATE_HALF_OPEN = "HALF_OPEN"


class _HealthEntry:
    """State فنی یک (video_id, client). هیچ داده حساسی نگه نمی‌دارد."""

    __slots__ = ("failure_count", "last_failure_at", "last_failure_reason", "unhealthy_until", "updated_at")

    def __init__(self) -> None:
        self.failure_count: int = 0
        self.last_failure_at: float = 0.0
        self.last_failure_reason: str = ""
        self.unhealthy_until: float = 0.0
        self.updated_at: float = 0.0


class ClientHealthMonitor:
    """
    مانیتور سلامت thread-safe و bounded برای رزولوشن‌های InnerTubeX.

    ماشین حالت:
      HEALTHY ──شکست متوالی تا آستانه──► UNHEALTHY (تا پایان cooldown)
      UNHEALTHY ──پایان cooldown──► HALF_OPEN (تلاش مجدد مجاز)
      HALF_OPEN ──موفقیت──► HEALTHY (شمارنده صفر)
      HALF_OPEN ──شکست──► UNHEALTHY (تمدید cooldown)
    """

    def __init__(
        self,
        failure_threshold: int = CLIENT_FAILURE_THRESHOLD,
        cooldown_seconds: float = CLIENT_HEALTH_COOLDOWN_SECONDS,
        entry_ttl_seconds: float = HEALTH_ENTRY_TTL_SECONDS,
        max_entries: int = MAX_HEALTH_ENTRIES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = float(cooldown_seconds)
        self.entry_ttl_seconds = float(entry_ttl_seconds)
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], _HealthEntry] = {}

    # ------------------------------------------------------------------
    # توابع داخلی (با فرض نگه‌داشتن lock صدا زده می‌شوند)
    # ------------------------------------------------------------------

    def _now(self) -> float:
        return self._clock()

    def _expired(self, entry: _HealthEntry, now: float) -> bool:
        return now - entry.updated_at > self.entry_ttl_seconds

    def _drop_expired_locked(self, now: float) -> int:
        expired_keys = [k for k, e in self._entries.items() if self._expired(e, now)]
        for k in expired_keys:
            del self._entries[k]
        if len(self._entries) >= self.max_entries:
            # حذف قدیمی‌ترین entry ها تا جای کافی برای entry تازه بماند
            ordered = sorted(self._entries.items(), key=lambda kv: kv[1].updated_at)
            excess = len(self._entries) - self.max_entries + 1
            for k, _ in ordered[:excess]:
                del self._entries[k]
        return len(expired_keys)

    def _get_entry_locked(self, key: tuple[str, str], now: float) -> _HealthEntry | None:
        entry = self._entries.get(key)
        if entry is not None and self._expired(entry, now):
            del self._entries[key]
            return None
        return entry

    # ------------------------------------------------------------------
    # API عمومی
    # ------------------------------------------------------------------

    def is_eligible(self, video_id: str, client: str = FAILURE_CLIENT_LABEL) -> bool:
        """آیا تلاش با InnerTubeX برای این (video_id, client) مجاز است؟"""
        now = self._now()
        with self._lock:
            entry = self._get_entry_locked((video_id, client), now)
            if entry is None:
                return True
            if entry.unhealthy_until <= 0.0:
                return True
            # پایان cooldown → HALF-OPEN: تلاش مجدد مجاز است
            return now >= entry.unhealthy_until

    def state_of(self, video_id: str, client: str = FAILURE_CLIENT_LABEL) -> str:
        """حالت فعلی برای تشخیص و تست: HEALTHY / UNHEALTHY / HALF_OPEN."""
        now = self._now()
        with self._lock:
            entry = self._get_entry_locked((video_id, client), now)
            if entry is None or entry.unhealthy_until <= 0.0:
                return STATE_HEALTHY
            return STATE_UNHEALTHY if now < entry.unhealthy_until else STATE_HALF_OPEN

    def record_failure(self, video_id: str, client: str = FAILURE_CLIENT_LABEL, reason: str = "UNKNOWN") -> None:
        """
        ثبت شکست رزولوشن InnerTubeX. کدهای غیرمرتبط با کلاینت (مانند
        BRIDGE_UNAVAILABLE) نادیده گرفته می‌شوند تا دسترس‌پذیری Bridge،
        سلامت کلاینت‌های یوتیوب را خراب نکند.
        """
        code = (reason or "UNKNOWN").upper()
        if code in NON_CLIENT_FAILURE_CODES:
            return

        now = self._now()
        with self._lock:
            self._drop_expired_locked(now)
            key = (video_id, client)
            entry = self._entries.get(key)
            if entry is None:
                entry = _HealthEntry()
                self._entries[key] = entry

            # شکستِ خیلی قدیمِ یک entry سالم، زنجیره «متوالی» را ادامه نمی‌دهد؛
            # اما شکست در حالت HALF-OPEN (پس از cooldown) بلافاصله دوباره UNHEALTHY می‌کند.
            if entry.unhealthy_until <= 0.0 and entry.failure_count > 0 and (
                now - entry.last_failure_at > self.cooldown_seconds
            ):
                entry.failure_count = 0

            entry.failure_count += 1
            entry.last_failure_at = now
            entry.last_failure_reason = code
            entry.updated_at = now

            if entry.failure_count >= self.failure_threshold:
                entry.unhealthy_until = now + self.cooldown_seconds
                log.warning(
                    "client=%s video_id=%s event=failure reason=%s failure_count=%d state=UNHEALTHY cooldown=%.0fs",
                    client,
                    video_id,
                    code,
                    entry.failure_count,
                    self.cooldown_seconds,
                )
            else:
                log.info(
                    "client=%s video_id=%s event=failure reason=%s failure_count=%d state=HEALTHY",
                    client,
                    video_id,
                    code,
                    entry.failure_count,
                )

    def record_success(self, video_id: str, client: str) -> None:
        """
        ثبت رزولوشن موفق InnerTubeX. فقط health همان ویدیو reset می‌شود:
        entry کلاینتِ موفق و entry برچسب‌خوردهٔ «نامشخص» (شکست‌های بدون انتساب
        کلاینتِ همین ویدیو). موفقیت یک ویدیو یا یک کلاینت دیگر هرگز state
        کلید اشتباه را reset نمی‌کند.
        """
        now = self._now()
        with self._lock:
            keys_to_reset = [
                (video_id, client),
                (video_id, FAILURE_CLIENT_LABEL),
            ]
            for key in keys_to_reset:
                entry = self._entries.get(key)
                if entry is None:
                    continue
                was_unhealthy = entry.unhealthy_until > 0.0
                del self._entries[key]
                if was_unhealthy:
                    log.info(
                        "client=%s video_id=%s event=recovered state=HEALTHY",
                        key[1],
                        video_id,
                    )

    def clear(self) -> None:
        """پاک‌سازی تمام entryهای وضعیت سلامت کلاینت‌ها (هنگام تغییر نشست/کوکی)."""
        with self._lock:
            self._entries.clear()

    def cleanup(self) -> int:
        """حذف entry های منقضی (TTL) و اعمال سقف حافظه؛ تعداد حذف‌شده‌ها برمی‌گردد."""
        now = self._now()
        with self._lock:
            return self._drop_expired_locked(now)

    def snapshot(self) -> dict[str, Any]:
        """
        نمای تشخیصی فقط-خواندنی از state. تنها فیلدهای فنیِ غیرحساس را
        برمی‌گرداند (بدون URL، cookie، token یا هر مقدار session).
        """
        now = self._now()
        with self._lock:
            clients: dict[str, Any] = {}
            for (video_id, client), entry in self._entries.items():
                if self._expired(entry, now):
                    continue
                state = STATE_HEALTHY
                if entry.unhealthy_until > 0.0:
                    state = STATE_UNHEALTHY if now < entry.unhealthy_until else STATE_HALF_OPEN
                clients.setdefault(video_id, {})[client] = {
                    "failure_count": entry.failure_count,
                    "last_failure_reason": entry.last_failure_reason,
                    "state": state,
                }
            return {"clients": clients, "entry_count": len(self._entries)}
