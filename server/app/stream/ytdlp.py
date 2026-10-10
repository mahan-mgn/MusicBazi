"""
رزولور استریم یوتیوب بر پایه yt-dlp برای Music Bazi.
نقش: SECONDARY / FALLBACK در معماری چندرزولوری.
استفاده مستقیم و کامل از زیرساخت فعلی ydl.py بدون بازنویسی یا تکرار استک.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import (
    DownloadError,
    ExtractorError,
    GeoRestrictedError,
    UnavailableVideoError,
)

from .. import ydl
from .errors import (
    ClientRejectedError,
    ExpiredStreamError,
    InvalidResponseError,
    NetworkError,
    NoStreamError,
    StreamResolverError,
)
from .models import EXT_TO_MIME, ResolvedStream, StreamType

log = logging.getLogger(__name__)


def _is_direct_audio_format(f: dict[str, Any]) -> bool:
    """بررسی اینکه فرمت حتماً صوت استریم مستقیم (HTTP/HTTPS) باشد نه پلی‌لیست متنی HLS/DASH."""
    proto = (f.get("protocol") or "").lower()
    url = f.get("url") or ""
    if not (url.startswith("http://") or url.startswith("https://")):
        return False
    if proto and proto not in ("http", "https"):
        return False
    if ".m3u8" in url or "manifest" in url or ".mpd" in url:
        return False
    if f.get("acodec") == "none":
        return False
    return True


def _format_quality_score(f: dict[str, Any]) -> float:
    """محاسبه امتیاز کیفیت صوتی فرمت منطبق بر الگوریتم بهینه stream_cache."""
    is_audio_only = 1 if f.get("vcodec") in ("none", None) else 0

    abr = f.get("abr") or (f.get("tbr") if is_audio_only else 0) or 0
    try:
        abr = float(abr)
    except (ValueError, TypeError):
        abr = 0.0

    acodec = (f.get("acodec") or "").lower()
    ext = (f.get("ext") or "").lower()

    codec_weight = 1.0
    if "flac" in acodec or ext == "flac" or "wav" in acodec:
        codec_weight = 3.0
    elif "opus" in acodec or ext in ("opus", "webm"):
        codec_weight = 1.6
    elif "mp4a" in acodec or "aac" in acodec or ext == "m4a":
        codec_weight = 1.3
    elif "mp3" in acodec or ext == "mp3":
        codec_weight = 1.0

    score = (is_audio_only * 500.0) + (abr * codec_weight)
    if abr <= 0 and is_audio_only:
        score += 100.0

    try:
        asr = float(f.get("asr") or 0)
    except (ValueError, TypeError):
        asr = 0.0
    score += asr / 1000.0

    return score


class YtDlpResolver:
    """
    رزولور ثانویه (Fallback) برای استخراج استریم از یوتیوب بر پایه yt-dlp.
    از تمام تنظیمات ydl.opts (کوکی، bgutil PO token، JS runtime، پروکسی) استفاده می‌کند.
    """

    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def _build_ydl_opts(self) -> dict[str, Any]:
        """پیکربندی بهینه yt-dlp با بهره‌گیری از زیرساخت رسمی ydl.opts."""
        return ydl.opts(
            skip_download=True,
            format="bestaudio/best",
            format_sort=["abr", "asr"],
            noplaylist=True,
            quiet=True,
            no_warnings=True,
            noprogress=True,
            check_formats=False,
            youtube_include_dash_manifest=False,
            youtube_include_hls_manifest=False,
            socket_timeout=self.timeout_seconds,
        )

    def _extract_sync(self, video_id: str, quality: str | None = None) -> ResolvedStream:
        clean_vid = video_id.strip()
        if not clean_vid:
            raise ValueError("video_id cannot be empty")

        url = f"https://www.youtube.com/watch?v={clean_vid}"
        opts = self._build_ydl_opts()

        info: dict[str, Any] | None = None
        try:
            with YoutubeDL(opts) as y:
                info = y.extract_info(url, download=False)
        except (UnavailableVideoError, GeoRestrictedError) as exc:
            log.warning("yt-dlp: video %s is unavailable or restricted: %s", clean_vid, exc)
            raise ClientRejectedError(f"Video unavailable or restricted: {exc}", video_id=clean_vid) from exc
        except DownloadError as exc:
            msg = str(exc).lower()
            if "unavailable" in msg or "private video" in msg:
                raise ClientRejectedError(f"Video unavailable: {exc}", video_id=clean_vid) from exc
            if "sign in to confirm you're not a bot" in msg or "bot" in msg or "captcha" in msg:
                log.warning("yt-dlp: bot check detected for %s", clean_vid)
                raise ClientRejectedError("YouTube bot-check triggered", video_id=clean_vid) from exc
            if "network" in msg or "timed out" in msg or "connection refused" in msg or "incompleteread" in msg:
                log.warning("yt-dlp: network failure on %s: %s", clean_vid, exc)
                raise NetworkError(f"Network error during extraction: {exc}", video_id=clean_vid) from exc
            log.warning("yt-dlp extraction error on %s: %s", clean_vid, exc)
            raise StreamResolverError(f"yt-dlp extraction failed: {exc}", code="EXTRACTION_FAILED", video_id=clean_vid) from exc
        except Exception as exc:
            msg = str(exc).lower()
            if "unavailable" in msg or "private video" in msg:
                raise ClientRejectedError(f"Video unavailable: {exc}", video_id=clean_vid) from exc
            if "timeout" in msg:
                raise NetworkError(f"Extraction timed out: {exc}", video_id=clean_vid) from exc
            # تلاش ثانویه بدون کوکی و اکستراکتور آرگس (رفتار نجات‌بخش ydl)
            log.warning("استخراج yt-dlp با تنظیمات جاری ناموفق بود (%s) — تلاش مجدد بدون کوکی", exc)
            try:
                fallback_opts = {
                    k: v for k, v in opts.items() if k not in ("cookiesfrombrowser", "extractor_args", "cookiefile")
                }
                with YoutubeDL(fallback_opts) as y:
                    info = y.extract_info(url, download=False)
            except Exception as inner_exc:
                inner_msg = str(inner_exc).lower()
                if "unavailable" in inner_msg or "private video" in inner_msg:
                    raise ClientRejectedError(f"Video unavailable: {inner_exc}", video_id=clean_vid) from inner_exc
                raise StreamResolverError(f"yt-dlp fallback extraction failed: {inner_exc}", video_id=clean_vid) from inner_exc

        if not info:
            raise InvalidResponseError("yt-dlp returned empty info dict", video_id=clean_vid)

        all_formats = info.get("formats") or []
        if not all_formats and _is_direct_audio_format(info):
            all_formats = [info]

        valid_formats = [f for f in all_formats if _is_direct_audio_format(f)]
        if not valid_formats:
            if _is_direct_audio_format(info):
                valid_formats = [info]
            else:
                log.warning("yt-dlp: no direct audio formats found for %s", clean_vid)
                raise NoStreamError("No playable direct audio formats found", video_id=clean_vid)

        if quality in ("m4a", "opus", "flac", "mp3"):
            q_norm = quality.lower()
            matching = [
                f
                for f in valid_formats
                if q_norm in (f.get("ext") or "").lower() or q_norm in (f.get("acodec") or "").lower()
            ]
            if matching:
                valid_formats = matching

        valid_formats.sort(key=_format_quality_score, reverse=True)
        chosen = valid_formats[0]

        stream_url = chosen.get("url") or ""
        if not stream_url:
            raise NoStreamError("Chosen format has no media URL", video_id=clean_vid)

        # استخراج و بررسی زمان انقضا
        expires_at: int | None = None
        if "expire=" in stream_url:
            try:
                parsed = urlparse(stream_url)
                params = parse_qs(parsed.query)
                if "expire" in params and params["expire"]:
                    expires_at = int(params["expire"][0])
            except Exception:
                pass

        # متادیتای پاکسازی‌شده (اکیداً بدون کوکی، توکن یا اطلاعات احراز هویت)
        safe_metadata = {
            "resolver": "yt-dlp",
            "format_id": str(chosen.get("format_id") or ""),
            "format_note": str(chosen.get("format_note") or ""),
            "ext": str(chosen.get("ext") or "m4a").lower(),
            "protocol": str(chosen.get("protocol") or "https"),
            "extractor": str(info.get("extractor") or "youtube"),
        }

        # پالایش هدرهای انتقالی (حذف هدرهای خصوصی یا کوکی در صورت وجود)
        raw_headers = dict(chosen.get("http_headers") or info.get("http_headers") or {})
        safe_headers: dict[str, str] = {}
        for h_key, h_val in raw_headers.items():
            low_k = h_key.lower()
            if low_k in ("cookie", "authorization", "x-youtube-identity-token"):
                continue
            safe_headers[h_key] = str(h_val)

        ext = safe_metadata["ext"]
        mime = chosen.get("mime_type")
        if not mime:
            mime = EXT_TO_MIME.get(ext, f"audio/{ext}")
        if ";" in mime:
            mime = mime.split(";")[0].strip()

        codec = chosen.get("acodec") or ext
        if codec == "none":
            codec = ext

        abr = chosen.get("abr") or chosen.get("tbr")
        bitrate_bps: int | None = None
        if abr is not None:
            try:
                bitrate_bps = int(float(abr) * 1000)
            except (ValueError, TypeError):
                bitrate_bps = None

        sample_rate: int | None = None
        if asr := chosen.get("asr"):
            try:
                sample_rate = int(asr)
            except (ValueError, TypeError):
                sample_rate = None

        content_length: int | None = None
        fsize = chosen.get("filesize") or chosen.get("filesize_approx")
        if fsize:
            try:
                content_length = int(fsize)
            except (ValueError, TypeError):
                content_length = None

        duration: float | None = None
        if dur := (info.get("duration") or chosen.get("duration")):
            try:
                duration = float(dur)
            except (ValueError, TypeError):
                duration = None

        loudness: float | None = None
        if "loudness" in info:
            try:
                loudness = float(info["loudness"])
            except (ValueError, TypeError):
                loudness = None

        stream = ResolvedStream(
            source="youtube",
            video_id=clean_vid,
            url=stream_url,
            mime_type=mime,
            codec=codec,
            bitrate=bitrate_bps,
            sample_rate=sample_rate,
            channels=chosen.get("audio_channels"),
            content_length=content_length,
            expires_at=expires_at,
            duration=duration,
            headers=safe_headers,
            requires_range=False,
            resolver_metadata=safe_metadata,
            is_lossless=ext in ("flac", "wav") or "flac" in codec.lower(),
            bit_depth=None,
            loudness_db=loudness,
            stream_type="PROGRESSIVE",
        )

        if stream.is_expired():
            log.warning("yt-dlp: extracted stream for %s is already expired", clean_vid)
            raise ExpiredStreamError("Extracted stream URL is already expired", video_id=clean_vid)

        log.info(
            "yt-dlp resolved [vid=%s, format=%s, codec=%s, bitrate=%s]",
            clean_vid,
            safe_metadata.get("format_id"),
            stream.codec,
            stream.bitrate,
        )

        return stream

    async def resolve_stream(
        self,
        video_id: str,
        purpose: str = "playback",
        quality: str | None = None,
    ) -> ResolvedStream:
        """
        استخراج غیرمسدودکننده آدرس استریم صوتی و متادیتا از طریق yt-dlp.
        عملیات استخراج در thread pool اجرا می‌شود.
        """
        return await asyncio.to_thread(self._extract_sync, video_id, quality)
