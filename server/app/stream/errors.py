"""
سیستم خطاهای کلاس‌بندی‌شده رزولورهای استریم در Music Bazi.
پوشش خطاهای InnerTubeX و yt-dlp و خطای ترکیبی AllResolversFailedError.
"""

from __future__ import annotations


class StreamResolverError(Exception):
    """کلاس پایه خطاهای رزولور استریم در Music Bazi."""

    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN",
        retryable: bool = False,
        video_id: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.video_id = video_id

    def __str__(self) -> str:
        vid_str = f" [videoId={self.video_id}]" if self.video_id else ""
        return f"{self.__class__.__name__}(code='{self.code}', retryable={self.retryable}{vid_str}): {self.message}"


# Alias برای حفظ سازگاری کامل کدهای فاز ۴
InnerTubeXResolverError = StreamResolverError


class BridgeUnavailableError(StreamResolverError):
    """سرویس لوکال JVM Bridge بالا نیست یا اتصال برقرار نمی‌شود."""

    def __init__(self, message: str = "InnerTubeX JVM Bridge unreachable", video_id: str = "") -> None:
        super().__init__(message=message, code="BRIDGE_UNAVAILABLE", retryable=True, video_id=video_id)


class BridgeTimeoutError(StreamResolverError):
    """مهلت زمانی ارتباط با Bridge به پایان رسید."""

    def __init__(self, message: str = "InnerTubeX Bridge timed out", video_id: str = "") -> None:
        super().__init__(message=message, code="TIMEOUT", retryable=True, video_id=video_id)


class NoStreamError(StreamResolverError):
    """هیچ استریم صوتی قابل پخشی توسط کلاینت‌ها/اکسترکتور پیدا نشد."""

    def __init__(
        self,
        message: str = "No playable audio stream found",
        video_id: str = "",
        code: str = "NO_STREAM",
    ) -> None:
        super().__init__(message=message, code=code, retryable=False, video_id=video_id)


class ClientRejectedError(StreamResolverError):
    """کلاینت یوتیوب مسدود شد یا محتوا محدودیت سنی/کپچا دارد."""

    def __init__(
        self,
        message: str = "Client rejected or content restricted",
        video_id: str = "",
        code: str = "CLIENT_REJECTED",
    ) -> None:
        super().__init__(message=message, code=code, retryable=False, video_id=video_id)


class CipherError(StreamResolverError):
    """رمزگشایی امضا یا چالش n ناموفق بود."""

    def __init__(self, message: str = "Cipher deobfuscation failed", video_id: str = "") -> None:
        super().__init__(message=message, code="CIPHER_ERROR", retryable=False, video_id=video_id)


class POTokenError(StreamResolverError):
    """توکن ضدربات BotGuard نامعتبر است یا تولید نشد."""

    def __init__(self, message: str = "Proof of Origin token failed", video_id: str = "") -> None:
        super().__init__(message=message, code="PO_TOKEN_ERROR", retryable=False, video_id=video_id)


class InvalidResponseError(StreamResolverError):
    """پاسخ ارسالی از اکسترکتور یا Bridge ساختار نامعتبر دارد."""

    def __init__(self, message: str = "Invalid response from resolver", video_id: str = "") -> None:
        super().__init__(message=message, code="INVALID_RESPONSE", retryable=False, video_id=video_id)


class UnsupportedFormatError(StreamResolverError):
    """فرمت بازگردانده‌شده در ساختار فعلی قابل پشتیبانی نیست."""

    def __init__(self, message: str = "Unsupported audio stream format", video_id: str = "") -> None:
        super().__init__(message=message, code="UNSUPPORTED_FORMAT", retryable=False, video_id=video_id)


class ExpiredStreamError(StreamResolverError):
    """استریم صوتی منقضی‌شده است."""

    def __init__(self, message: str = "Audio stream URL is expired", video_id: str = "") -> None:
        super().__init__(message=message, code="EXPIRED_STREAM", retryable=True, video_id=video_id)


class NetworkError(StreamResolverError):
    """خطای شبکه، اتصال یا DNS در حین استخراج."""

    def __init__(self, message: str = "Network error during stream extraction", video_id: str = "") -> None:
        super().__init__(message=message, code="NETWORK_ERROR", retryable=True, video_id=video_id)


class ClientUnhealthyError(StreamResolverError):
    """
    کلاینت InnerTubeX به‌دلیل شکست‌های متوالی اخیر موقتاً از دور خارج شده (Phase 7).
    این خطا نشانه خرابی لحظه‌ای نیست؛ سیاست health تصمیم گرفته تلاش با InnerTubeX
    برای این ویدیو فعلاً صرف‌نظر شود تا فال‌بک بدون تأخیر اضافه اجرا شود.
    """

    def __init__(
        self,
        message: str = "InnerTubeX temporarily deprioritized due to consecutive recent failures",
        video_id: str = "",
        reason_code: str = "UNKNOWN",
    ) -> None:
        super().__init__(message=message, code="CLIENT_UNHEALTHY", retryable=True, video_id=video_id)
        self.reason_code = reason_code


class AllResolversFailedError(StreamResolverError):
    """
    خطای نهایی زمانی که هر دو رزولور InnerTubeX و yt-dlp ناموفق بودند.
    علت‌های ریشه‌ای (Root Causes) هر دو رزولور را بدون نشت اطلاعات حساس نگه‌داری می‌کند.
    """

    def __init__(
        self,
        video_id: str,
        primary_error: StreamResolverError,
        fallback_error: StreamResolverError,
    ) -> None:
        super().__init__(
            message=(
                f"All resolvers failed for videoId={video_id}. "
                f"Primary ({primary_error.__class__.__name__}): {primary_error.message}. "
                f"Fallback ({fallback_error.__class__.__name__}): {fallback_error.message}"
            ),
            code="ALL_RESOLVERS_FAILED",
            retryable=False,
            video_id=video_id,
        )
        self.primary_error = primary_error
        self.fallback_error = fallback_error
        self.primary_code = primary_error.code
        self.fallback_code = fallback_error.code


class PermanentlyUnplayableError(StreamResolverError):
    """
    خطای قطعی غیرقابل‌پخش بودن ویدیو (محدودیت سنی، حریم خصوصی، حذف ویدیو، مسدودیت منطقه‌ای).
    این خطا نشانه شکست قطعی محتوا است و برای جلوگیری از طوفان درخواست کش می‌شود (Phase 3).
    """

    def __init__(
        self,
        message: str = "This video is permanently unplayable",
        video_id: str = "",
        code: str = "PERMANENTLY_UNPLAYABLE",
    ) -> None:
        super().__init__(message=message, code=code, retryable=False, video_id=video_id)


class StreamRecoveryError(StreamResolverError):
    """
    شکست بازیابی استریم منقضی/رد‌شده (Phase 8).
    علت اصلیِ ورود به recovery (مثلاً EXPIRED_STREAM) و علت شکست رزولوشن مجدد
    را بدون نشت داده حساس (URL/توکن) حفظ می‌کند.
    """

    def __init__(
        self,
        message: str = "Stream re-resolution failed",
        video_id: str = "",
        original_reason: str = "",
        recovery_error: StreamResolverError | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="STREAM_RECOVERY_FAILED",
            retryable=False,
            video_id=video_id,
        )
        self.original_reason = original_reason
        self.recovery_error = recovery_error


def map_bridge_error(code: str, message: str, retryable: bool = False, video_id: str = "") -> StreamResolverError:
    """نگاشت کد خطای ارسالی از Bridge به استثنای مشخص Music Bazi."""
    c = code.upper()
    if c in ("NO_STREAM", "UNAVAILABLE"):
        return NoStreamError(message, video_id=video_id, code=c)
    if c in ("CLIENT_REJECTED", "AGE_RESTRICTED", "EXPLICIT_UNSUPPORTED"):
        return ClientRejectedError(message, video_id=video_id, code=c)
    if c == "CIPHER_ERROR":
        return CipherError(message, video_id=video_id)
    if c == "PO_TOKEN_ERROR":
        return POTokenError(message, video_id=video_id)
    if c == "UNSUPPORTED_FORMAT":
        return UnsupportedFormatError(message, video_id=video_id)
    if c == "NETWORK_ERROR":
        return NetworkError(message, video_id=video_id)
    return StreamResolverError(message, code=code, retryable=retryable, video_id=video_id)
