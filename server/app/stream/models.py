"""
قرارداد مشترک داده برای استریم‌های صوتی (ResolvedStream).

این مدل مرز مستقل بین اکسترکتورهای یوتیوب/ساندکلاد (InnerTubeX و yt-dlp)
و مصرف‌کنندگان صدا (stream_cache و downloader و پلیر اندروید) است.
اطلاعات حساس نظیر Signed URLها نباید در لاگ یا دیتابیس ماندگار شوند.
"""

from __future__ import annotations

import re
import time
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

StreamType = Literal["PROGRESSIVE", "HLS"]

# نگاشت پسوند فایل به MIME type استاندارد صوتی
EXT_TO_MIME: dict[str, str] = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "webm": "audio/webm",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "wav": "audio/wav",
}


def _redact_signed_url(url: str) -> str:
    """پالایش پارامترهای حساس امضا از آدرس برای نمایش امن در لاگ‌ها."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        # اگر آدرس CDN گوگل‌ویدیو یا ساندکلاد باشد، کوئری پارامترها را می‌پوشانیم
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?[signed parameters redacted]"
    except Exception:
        return "[redacted url]"


class ResolvedStream(BaseModel):
    """
    قرارداد واحد استریم استخراج‌شده صوتی برای Music Bazi.
    منطبق با مدل نیتیو اندروید ResolvedAudioStream.kt.
    """

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    source: str
    video_id: str
    url: str
    mime_type: str
    codec: str
    bitrate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    content_length: int | None = None
    expires_at: int | None = None
    duration: float | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    requires_range: bool = False
    resolver_metadata: dict[str, Any] = Field(default_factory=dict)
    is_lossless: bool = False
    bit_depth: int | None = None
    loudness_db: float | None = None
    stream_type: StreamType = "PROGRESSIVE"

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("url نمی‌تواند خالی باشد")
        if not (s.startswith("http://") or s.startswith("https://") or s.startswith("sabr://")):
            raise ValueError(f"طرح آدرس نامعتبر است: {s[:15]}")
        return s

    @field_validator("source", "video_id", "mime_type", "codec")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("فیلدهای هویتی استریم نمی‌توانند خالی باشند")
        return s

    @field_validator("bitrate", "sample_rate", "channels", "content_length", "expires_at", "bit_depth")
    @classmethod
    def validate_positive_optional(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("مقدار عددی نمی‌تواند منفی باشد")
        return v

    def is_expired(self, skew_seconds: int = 30) -> bool:
        """بررسی اینکه آیا مهلت دسترسی استریم به پایان رسیده است یا خیر."""
        if self.expires_at is None:
            return False
        return time.time() + skew_seconds >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """تبدیل به دیکشنری خالص برای سریال‌سازی و ترنسفر."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResolvedStream:
        """ساخت نمونه از دیکشنری."""
        return cls.model_validate(data)

    def to_android_payload(self) -> dict[str, Any]:
        """
        تبدیل به ساختار منطبق با ResolvedAudioStream در اندروید:
        app.musicbazi.client.audio.stream.ResolvedAudioStream.kt
        """
        duration_ms = int(self.duration * 1000) if self.duration is not None else None
        expires_at_ms = int(self.expires_at * 1000) if self.expires_at is not None else None
        return {
            "uri": self.url,
            "mimeType": self.mime_type,
            "codec": self.codec,
            "bitrateBps": self.bitrate,
            "sampleRateHz": self.sample_rate,
            "bitDepth": self.bit_depth,
            "channelCount": self.channels,
            "durationMs": duration_ms,
            "isLossless": self.is_lossless,
            "gainDb": self.loudness_db,
            "sourceId": self.video_id,
            "expiresAtMs": expires_at_ms,
            "streamType": self.stream_type,
            "headers": dict(self.headers),
        }

    @classmethod
    def from_ytdlp(
        cls,
        info: dict[str, Any],
        fmt: dict[str, Any] | None = None,
        source: str = "youtube",
        video_id: str | None = None,
    ) -> ResolvedStream:
        """
        مسیر سازگاری: تبدیل ساختار خام خروجی yt-dlp به قرارداد واحد ResolvedStream.
        بدون تغییر در ایمپلمنتیشن کنونی yt-dlp.
        """
        chosen_format = fmt or info
        url = chosen_format.get("url") or ""
        vid = video_id or str(info.get("id") or "")

        # تشخیص انقضای URL از پارامتر expire در صورت وجود
        expires_at: int | None = None
        if "expire=" in url:
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                if "expire" in params and params["expire"]:
                    expires_at = int(params["expire"][0])
            except Exception:
                pass

        ext = (chosen_format.get("ext") or "m4a").lower()
        mime = chosen_format.get("mime_type")
        if not mime:
            mime = EXT_TO_MIME.get(ext, f"audio/{ext}")
        if ";" in mime:
            mime = mime.split(";")[0].strip()

        codec = chosen_format.get("acodec") or ext
        if codec == "none":
            codec = ext

        abr = chosen_format.get("abr") or chosen_format.get("tbr")
        bitrate_bps: int | None = None
        if abr is not None:
            try:
                bitrate_bps = int(float(abr) * 1000)
            except (ValueError, TypeError):
                bitrate_bps = None

        sample_rate: int | None = None
        if asr := chosen_format.get("asr"):
            try:
                sample_rate = int(asr)
            except (ValueError, TypeError):
                sample_rate = None

        content_length: int | None = None
        fsize = chosen_format.get("filesize") or chosen_format.get("filesize_approx")
        if fsize:
            try:
                content_length = int(fsize)
            except (ValueError, TypeError):
                content_length = None

        duration: float | None = None
        if dur := (info.get("duration") or chosen_format.get("duration")):
            try:
                duration = float(dur)
            except (ValueError, TypeError):
                duration = None

        headers = dict(chosen_format.get("http_headers") or info.get("http_headers") or {})

        stream_type: StreamType = "PROGRESSIVE"
        proto = (chosen_format.get("protocol") or "").lower()
        if "m3u8" in proto or ".m3u8" in url:
            stream_type = "HLS"

        is_lossless = ext in ("flac", "wav") or "flac" in codec.lower()

        loudness: float | None = None
        if "loudness" in info:
            try:
                loudness = float(info["loudness"])
            except (ValueError, TypeError):
                loudness = None

        metadata = {
            "format_id": chosen_format.get("format_id"),
            "format_note": chosen_format.get("format_note"),
            "ext": ext,
            "vcodec": chosen_format.get("vcodec"),
            "protocol": chosen_format.get("protocol"),
            "asr": sample_rate,
            "abr": abr,
        }

        return cls(
            source=source,
            video_id=vid,
            url=url,
            mime_type=mime,
            codec=codec,
            bitrate=bitrate_bps,
            sample_rate=sample_rate,
            channels=chosen_format.get("audio_channels"),
            content_length=content_length,
            expires_at=expires_at,
            duration=duration,
            headers=headers,
            requires_range=False,
            resolver_metadata=metadata,
            is_lossless=is_lossless,
            bit_depth=None,
            loudness_db=loudness,
            stream_type=stream_type,
        )

    def __repr__(self) -> str:
        safe_url = _redact_signed_url(self.url)
        return (
            f"ResolvedStream(source='{self.source}', video_id='{self.video_id}', "
            f"url='{safe_url}', mime_type='{self.mime_type}', codec='{self.codec}', "
            f"bitrate={self.bitrate}, expires_at={self.expires_at}, stream_type='{self.stream_type}')"
        )

    def __str__(self) -> str:
        return self.__repr__()
