"""
اتصال کنترل‌شده معماری Stream جدید به مسیر واقعی Playback (Phase 11).

مسیر Production فعلی (audit فاز ۱۱):
  Web و Android هر دو از GET /api/stream تغذیه می‌شوند:
    /api/stream → stream_cache.get_stream_response → get_or_fetch
      ۱. فایل کتابخانه (db) → FileResponse
      ۲. فایل کش استریم روی دیسک → FileResponse
      ۳. دانلود به کش با yt-dlp (candidate search مسیر دانلود) → FileResponse
  Android فقط همان URL بک‌اند را از لایه JS/Capacitor می‌گیرد و Media3 آن را
  پخش می‌کند — Android هیچ resolver مستقلی ندارد و در این فاز تغییری نمی‌کند.

مسیر جدید (فقط وقتی MUSICBAZI_STREAM_V2=ON):
  /api/stream
    ├─ فایل کتابخانه / کش دیسک (بدون تغییر — همیشه اول)
    └─ ترک یوتیوبِ مستقیم (video_id قابل استخراج):
         YouTubeStreamResolver (فاز ۶ + Client Health فاز ۷)
           ↓ ResolvedStream
         PlaybackStreamAdapter (mapping خالص — بدون resolve/retry/modify)
           ↓
         پروکسی بایت‌به‌بایت با پشتیبانی Range (signed URL فقط در runtime سرور)
           ↓ 403/410 در runtime
         StreamRecovery فاز ۸ (بودجه ۱ تلاش، فقط با evidence انقضا)
           ↓
         StreamingResponse

قواعد:
  - Flag خاموش → این ماژول اصلاً اجرا نمی‌شود؛ مسیر legacy عیناً قبل.
  - شکست مسیر جدید → caller به مسیر legacy برمی‌گردد؛ playback هرگز بدتر از قبل نمی‌شود.
  - Signed URL هرگز در DB/state/log/error message نمی‌نشیند؛ فقط runtime pass-through.
  - برای منابع غیر-یوتیوب (spotify/apple/deezer/soundcloud) video_id بدون ورود به
    Search/Candidate Scoring قابل استخراج نیست؛ آن مسیر عمداً دست‌نخورده می‌ماند.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, AsyncIterator, Callable
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from ..models import Track
from .errors import NetworkError, StreamResolverError
from .feature_flags import is_stream_v2_enabled
from .hls_proxy import (
    MANIFEST_CONTENT_TYPE,
    HlsProxyController,
    _ManifestUnsupported,
    _UpstreamRejected,
)
from .models import ResolvedStream
from .recovery import StreamRecovery, classify_runtime_failure
from .resolver import YouTubeStreamResolver

log = logging.getLogger(__name__)

# ------------------------------------------------------------------
# httpx در سطح INFO خط «HTTP Request: GET <url کامل>» لاگ می‌کند؛ با signed
# URL این یعنی نشت مستقیم به لاگ‌ها. این filter فقط URLهای googlevideo را
# redact می‌کند (بقیه لاگ‌های httpx دست‌نخورده می‌مانند).
# ------------------------------------------------------------------
_GOOGLEVIDEO_URL_RE = re.compile(r"https?://[^\s\"']*googlevideo\.com[^\s\"']*")


class _GoogleVideoURLRedactor(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "googlevideo" in message:
            record.msg = _GOOGLEVIDEO_URL_RE.sub("[signed url redacted]", message)
            record.args = None
        return True


logging.getLogger("httpx").addFilter(_GoogleVideoURLRedactor())

# فاصله خواندن از upstream در پروکسی (بایت)
_PROXY_CHUNK_SIZE = 64 * 1024

# الگوهای استخراج video_id از URL یوتیوب (بدون هیچ تماس شبکه)
_YT_ID_PATTERNS = (
    re.compile(r"[?&]v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})"),
)
_YT_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# وضعیت‌هایی که طبق classification فاز ۸ evidence انقضا هستند
_EXPIRATION_EVIDENCE_STATUSES = (403, 410)


def extract_youtube_video_id(track: Track) -> str | None:
    """استخراج قطعی video_id از ترک یوتیوب یا یوتیوب موزیک (sourceUrl یا شکل id). بدون حدس."""
    if track.source not in ("youtube", "youtube_music"):
        return None
    url = (track.sourceUrl or "").strip()
    for pattern in _YT_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    candidate_id = (track.id or "").strip()
    if candidate_id.startswith(("yt:track:", "ytm:track:")):
        vid = candidate_id.split(":")[-1]
        if _YT_BARE_ID.match(vid):
            return vid
    if _YT_BARE_ID.match(candidate_id):
        return candidate_id
    return None


def extract_video_id_from_url(url: str) -> str | None:
    """استخراج شناسه ۱۱ رقمی یوتیوب از هر لینک وب."""
    if not url:
        return None
    s = url.strip()
    for pattern in _YT_ID_PATTERNS:
        match = pattern.search(s)
        if match:
            return match.group(1)
    if _YT_BARE_ID.match(s):
        return s
    return None


class CacheFileWriter:
    """ذخیره‌سازی هم‌زمان چانک‌های استریم روی دیسک (Cache-as-you-stream)."""

    def __init__(self, tmp_path: Path, final_path: Path, expected_size: int | None):
        self.tmp_path = tmp_path
        self.final_path = final_path
        self.expected_size = expected_size
        self.written = 0
        self._file = None
        self._committed = False
        try:
            self._file = open(self.tmp_path, "wb")
        except Exception as exc:
            log.warning("عدم امکان ایجاد فایل موقت کش استریم: %s", exc)
            self._file = None

    def write(self, chunk: bytes) -> None:
        if self._file and not self._committed:
            try:
                self._file.write(chunk)
                self.written += len(chunk)
            except Exception as exc:
                log.warning("خطا در نوشتن چانک کش استریم: %s", exc)
                self.close(commit=False)

    def close(self, commit: bool = True) -> None:
        if self._file:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
            self._file = None
            if (
                commit
                and not self._committed
                and self.written > 1024
                and (self.expected_size is None or self.written >= self.expected_size)
            ):
                self._committed = True
                try:
                    self.tmp_path.replace(self.final_path)
                    try:
                        from .. import stream_cache
                        stream_cache.note_file_written(self.final_path)
                    except Exception:
                        pass
                    log.info(
                        "استریم صوتی با موفقیت در کش دیسک ذخیره شد: %s (%d بایت)",
                        self.final_path.name,
                        self.written,
                    )
                    return
                except Exception as exc:
                    log.warning("خطا در نهایی‌سازی فایل کش استریم: %s", exc)
            self.tmp_path.unlink(missing_ok=True)


def _create_cache_writer(
    track: Track | None,
    quality: str | None,
    media_type: str,
    total_length: int | None,
) -> CacheFileWriter | None:
    if track is None:
        return None
    try:
        from .. import stream_cache
        from ..config import STREAM_CACHE_DIR

        cache_key = stream_cache.cache_key_for(track.id, quality=quality)
        cached = stream_cache._find_cached_audio(cache_key)
        if cached and cached.exists():
            return None

        STREAM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ext = "m4a"
        if "mpeg" in media_type or "mp3" in media_type:
            ext = "mp3"
        elif "ogg" in media_type or "opus" in media_type:
            ext = "opus"
        elif "webm" in media_type:
            ext = "webm"
        elif "flac" in media_type:
            ext = "flac"

        tmp_path = STREAM_CACHE_DIR / f"{cache_key}.{time.time_ns()}.tmp"
        final_path = STREAM_CACHE_DIR / f"{cache_key}.{ext}"
        return CacheFileWriter(tmp_path, final_path, total_length)
    except Exception as exc:
        log.warning("خطا در آماده‌سازی کش استریم: %s", exc)
        return None


# پنجره بازه محدود جهت جلوگیری از محدودسازی سرعت توسط CDN گوگل‌ویدیو (512 KiB)
DEFAULT_BOUNDED_CHUNK_SIZE = 512 * 1024


@dataclass(frozen=True)
class RangeSpec:
    start: int
    end: int | None
    is_satisfiable: bool = True


def parse_clen_from_url(url: str) -> int | None:
    """استخراج طول محتوا از پارامتر clen در کوئری آدرس گوگل‌ویدیو."""
    try:
        qs = parse_qs(urlparse(url).query)
        if "clen" in qs and qs["clen"]:
            val = int(qs["clen"][0])
            if val > 0:
                return val
    except Exception:
        pass
    return None


def extract_content_length(stream: ResolvedStream) -> int | None:
    """طول کل فایل صوتی از متادیتا یا کوئری clen."""
    if stream.content_length is not None and stream.content_length > 0:
        return stream.content_length
    return parse_clen_from_url(stream.url)


def parse_range_spec(
    range_header: str | None,
    total_length: int | None,
) -> RangeSpec | None:
    """
    تحلیل دقیق Range header ارسالی از کلاینت (RFC 7233):
      - bytes=start-end
      - bytes=start- (open-ended)
      - bytes=-N (suffix)
      - None (بدون Range)
    """
    if range_header is None:
        return None

    range_str = range_header.strip()
    if not range_str.lower().startswith("bytes="):
        return None

    raw_spec = range_str[6:].split(",")[0].strip()

    # Suffix range: bytes=-N
    if raw_spec.startswith("-"):
        try:
            suffix_len = int(raw_spec[1:])
        except ValueError:
            return RangeSpec(start=0, end=None, is_satisfiable=False)
        if suffix_len <= 0:
            return RangeSpec(start=0, end=None, is_satisfiable=False)
        if total_length is not None:
            if total_length == 0:
                return RangeSpec(start=0, end=0, is_satisfiable=False)
            start = max(0, total_length - suffix_len)
            end = total_length - 1
            return RangeSpec(start=start, end=end, is_satisfiable=True)
        else:
            return RangeSpec(start=0, end=None, is_satisfiable=False)

    if "-" not in raw_spec:
        return RangeSpec(start=0, end=None, is_satisfiable=False)

    start_str, _, end_str = raw_spec.partition("-")
    try:
        start = int(start_str.strip())
    except ValueError:
        return RangeSpec(start=0, end=None, is_satisfiable=False)

    if start < 0:
        return RangeSpec(start=0, end=None, is_satisfiable=False)

    if total_length is not None and start >= total_length:
        return RangeSpec(start=start, end=None, is_satisfiable=False)

    end: int | None = None
    if end_str.strip():
        try:
            end_val = int(end_str.strip())
            if end_val < start:
                return RangeSpec(start=start, end=end_val, is_satisfiable=False)
            end = min(end_val, total_length - 1) if total_length is not None else end_val
        except ValueError:
            return RangeSpec(start=start, end=None, is_satisfiable=False)
    else:
        end = total_length - 1 if total_length is not None else None

    return RangeSpec(start=start, end=end, is_satisfiable=True)


class PlaybackStreamAdapter:
    """
    mapping خالص ResolvedStream → قرارداد Playback. هیچ resolve/retry/modify
    و cache ای انجام نمی‌دهد؛ headers فقط runtime pass-through هستند و عیناً
    نباید log شوند.
    """

    @staticmethod
    def upstream_request_headers(stream: ResolvedStream) -> dict[str, str]:
        """headers لازم برای GET روی signed URL — فقط runtime، هرگز log نکنید."""
        return dict(stream.headers or {})

    @staticmethod
    def response_media_type(stream: ResolvedStream, fallback: str = "audio/mpeg") -> str:
        """MIME پاسخ به client (سازگار با قرارداد `<audio>` و Media3)."""
        return stream.mime_type or fallback

    @staticmethod
    def playback_facts(stream: ResolvedStream) -> dict[str, Any]:
        """متادیتای امن برای log/diagnostic — عمداً بدون url/headers/expires_at."""
        return {
            "source": stream.source,
            "mime_type": stream.mime_type,
            "codec": stream.codec,
            "bitrate": stream.bitrate,
            "sample_rate": stream.sample_rate,
            "channels": stream.channels,
            "duration": stream.duration,
            "content_length": stream.content_length,
            "requires_range": stream.requires_range,
            "stream_type": stream.stream_type,
        }


class ResolvedURLCache:
    """
    کشِ کوتاه‌مدتِ URLِ استریمِ رزولوشن‌شده (درون‌حافظه، بدون دوام).

    هر پلی که کش بخورد یک دور رزولوشن InnerTubeX/yt-dlp کمتر می‌خورد — همین
    دور، فاصله‌ی محسوسِ بینِ «زدن روی ترک» و «شنیدن صدا» است.

    قاعده‌ی امنیتی همان قاعده‌ی `ResolvedStream` است: URL فقط در حافظه‌ی همین
    پروسه می‌ماند؛ نه در DB، نه در log، نه در متنِ خطا. `__repr__` هم ندارد.
    """

    # فاصله‌ی امنِ بیشتر از skew پیش‌فرض (۳۰ ثانیه): این URL باید کلِ یک
    # دانلودِ چانک‌چانک را زنده بماند، نه فقط اولین درخواست را.
    EXPIRY_SKEW_SECONDS = 60

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int = 256,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._entries: dict[tuple[str, str, str], tuple[ResolvedStream, float]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def key(video_id: str, quality: str | None, user_id: str) -> tuple[str, str, str]:
        return (video_id, quality or "", user_id or "local")

    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    def get(self, key: tuple[str, str, str]) -> ResolvedStream | None:
        if not self.enabled():
            return None
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stream, stored_at = entry
            if now - stored_at >= self.ttl_seconds or stream.is_expired(
                self.EXPIRY_SKEW_SECONDS, now=now
            ):
                del self._entries[key]
                return None
            return stream

    def put(self, key: tuple[str, str, str], stream: ResolvedStream) -> None:
        if not self.enabled() or stream.is_expired(
            self.EXPIRY_SKEW_SECONDS, now=self._clock()
        ):
            return
        now = self._clock()
        with self._lock:
            self._entries[key] = (stream, now)
            if len(self._entries) <= self.max_entries:
                return
            # اول منقضی‌ها؛ اگر باز هم سرریز بود، قدیمی‌ترین‌ها
            stale = [
                k
                for k, (s, ts) in self._entries.items()
                if now - ts >= self.ttl_seconds or s.is_expired(self.EXPIRY_SKEW_SECONDS, now=now)
            ]
            for k in stale:
                self._entries.pop(k, None)
            if len(self._entries) > self.max_entries:
                ordered = sorted(self._entries.items(), key=lambda kv: kv[1][1])
                for k, _ in ordered[: len(self._entries) - self.max_entries]:
                    self._entries.pop(k, None)

    def drop(self, key: tuple[str, str, str]) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class LivePlaybackStreamer:
    """
    پروکسی live استریم یوتیوب با قرارداد Range سازگار با FileResponse فعلی.
    signed URL فقط درون این کلاس و در runtime زندگی می‌کند.
    """

    def __init__(
        self,
        resolver: YouTubeStreamResolver | None = None,
        recovery: StreamRecovery | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        adapter: PlaybackStreamAdapter | None = None,
        resolved_cache_ttl: float | None = None,
    ) -> None:
        self.resolver = resolver or YouTubeStreamResolver()
        # recovery باید از همان resolver instance عبور کند تا Client Health فاز ۷
        # و سیاست فال‌بک فاز ۶ یک source of truth بمانند (state موازی ممنوع)
        self.recovery = recovery or StreamRecovery(resolver=self.resolver)
        self._http_transport = http_transport
        self.adapter = adapter or PlaybackStreamAdapter()
        # HLS server-side proxy (فاز ۱۴، Strategy B فاز ۱۳) — همان recovery
        # مشترک تا Client Health فاز ۷ و بودجه فاز ۸ یک source of truth بمانند
        self.hls = HlsProxyController(
            recovery=self.recovery, http_transport=http_transport
        )
        if resolved_cache_ttl is None:
            from ..config import RESOLVED_URL_CACHE_MAX, RESOLVED_URL_CACHE_TTL

            resolved_cache_ttl = RESOLVED_URL_CACHE_TTL
            max_entries = RESOLVED_URL_CACHE_MAX
        else:
            max_entries = 256
        self._resolved = ResolvedURLCache(resolved_cache_ttl, max_entries=max_entries)
        # کلاینتِ اشتراکی برای پروکسی: باز کردن و بستنِ مکرر TCP+TLS برای هر
        # رکوئست و هر چانک صوتی تاخیر چشمگیر ایجاد می‌کرد. با استفاده از connection pool
        # اشتراکی، ارتباطات برقرار می‌مانند و اسکراب یا پخش آهنگ بعدی فوری می‌شود.
        self._client: httpx.AsyncClient | None = None
        # single-flight درون-پردازشی (فاز ۱۲): چند consumer هم‌زمان برای یک ویدیو
        # فقط یک resolve اشتراکی ایجاد می‌کنند — قفل سبک asyncio، بدون infra
        self._inflight: dict[tuple[str, str], asyncio.Task] = {}
        self._inflight_lock = asyncio.Lock()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
                limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
                follow_redirects=True,
                transport=self._http_transport,
            )
        return self._client

    async def aclose(self) -> None:
        """بستن ایمن کلاینت اشتراکی هنگام متوقف شدن اپلیکیشن."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # -------------------------------------------------------------
    # API
    # -------------------------------------------------------------

    def on_session_changed(self) -> None:
        """انتقال رویداد تغییر نشست به رزولور (نشست‌های فعال HLS مختل نمی‌شوند)."""
        self._resolved.clear()
        self.resolver.on_session_changed()

    async def stream_response(
        self,
        track: Track,
        range_header: str | None = None,
        quality: str | None = None,
        env: dict[str, str] | None = None,
        user_id: str = "local",
    ) -> Response | None:
        """
        اگر flag روشن و video_id قابل استخراج بود، Response (یا StreamingResponse) برمی‌گرداند؛
        در غیر این صورت None (یعنی «این مسیر اعمال نمی‌شود»). هر خطای resolve/
        recovery/proxy به‌صورت StreamResolverError با پیام امن (بدون URL) پرتاب
        می‌شود تا caller به مسیر legacy برگردد.
        """
        if not is_stream_v2_enabled(env):
            return None
        from .. import resolver

        is_yt_video = resolver.is_youtube_video(track)
        if is_yt_video:
            # بخش Videos یوتیوب: دقیقاً صدای همان ویدیو بدون اورراید یا تغییر منبع
            video_id = extract_youtube_video_id(track)
            candidates = []
        else:
            override = resolver._canonical_override(track)
            if override:
                if override.source in ("youtube", "youtube_music"):
                    video_id = extract_video_id_from_url(override.url)
                else:
                    video_id = None
                candidates = [override]
            else:
                video_id = extract_youtube_video_id(track)
                candidates = []

        if not video_id:
            try:
                if not candidates:
                    # جست‌وجوی کاندیدا در yt-dlp است و همگام — روی event loop
                    # نمی‌نشیند، وگرنه هر پلی همه‌ی استریم‌های هم‌زمان را متوقف می‌کند.
                    candidates = await asyncio.to_thread(
                        resolver.resolve,
                        track,
                        user_id=user_id,
                        use_cache=True,
                        sources=("youtube_music", "youtube", "soundcloud"),
                    )
                    for c in candidates:
                        if c.source in ("youtube", "youtube_music"):
                            vid = extract_video_id_from_url(c.url)
                            if vid:
                                video_id = vid
                                break
                if not video_id:
                    for c in candidates:
                        if c.source == "soundcloud":
                            from .. import stream_cache
                            direct_info = await asyncio.to_thread(
                                stream_cache._extract_direct_stream_info,
                                c.url,
                                quality=quality,
                                user_id=user_id,
                            )
                            if direct_info and direct_info.get("url"):
                                from .models import EXT_TO_MIME
                                ext = direct_info.get("ext") or "mp3"
                                mime = EXT_TO_MIME.get(f".{ext}", "audio/mpeg")
                                sc_stream = ResolvedStream(
                                    source="soundcloud",
                                    video_id=c.url,
                                    url=direct_info["url"],
                                    mime_type=mime,
                                    codec=direct_info.get("acodec") or "mp3",
                                    bitrate=int(direct_info.get("abr") or 128) * 1000,
                                    content_length=direct_info.get("filesize"),
                                    headers=direct_info.get("http_headers") or {},
                                    stream_type="PROGRESSIVE",
                                )
                                return await self._proxy(
                                    sc_stream, range_header, track=track, quality=quality
                                )
            except Exception as exc:
                log.warning("failed to resolve candidates for live stream: %s", exc)
                return None

        if not video_id:
            return None

        try:
            stream = await self._resolve_shared(
                video_id, purpose="playback", quality=quality, user_id=user_id
            )
        except Exception as exc:
            if not is_yt_video:
                log.warning(
                    "primary resolution for video %s failed: %s — trying live fallback",
                    video_id,
                    exc,
                )
                fallback = await self._resolve_live_fallback(
                    track,
                    failed_video_id=video_id,
                    range_header=range_header,
                    quality=quality,
                    user_id=user_id,
                )
                if fallback is not None:
                    return fallback
            raise

        if stream.stream_type == "HLS":
            # فاز ۱۴: proxy سمت سرور HLS — manifest بازنویسی‌شده به client می‌رود
            # و signed URLها server-side می‌مانند. اگر proxy پشتیبانی نکرد
            # (manifest غیرمجاز/malformed) → None یعنی rollback به legacy
            # (همان guard فاز ۱۱ به‌عنوان مسیر rollback حفظ شده است).
            session = self.hls.registry.get_or_create(video_id, stream)
            try:
                return await self.hls.load_manifest_response(session)
            except _ManifestUnsupported as exc:
                log.info(
                    "live playback hls unsupported [vid=%s, reason=%s, path=legacy]",
                    video_id,
                    exc.reason,
                )
                return None
            except _UpstreamRejected as rejected:
                if rejected.status_code not in (403, 410):
                    if not is_yt_video:
                        fallback = await self._resolve_live_fallback(
                            track, failed_video_id=video_id, range_header=range_header, quality=quality, user_id=user_id
                        )
                        if fallback is not None:
                            return fallback
                    raise classify_runtime_failure(
                        http_status=rejected.status_code, video_id=video_id
                    ) from rejected
                # evidence انقضا → recovery فاز ۸ (بودجه ۱، single-flight)
                log.info(
                    "live playback hls recovering [vid=%s, status=%d, attempt=1]",
                    video_id,
                    rejected.status_code,
                )
                # Phase 2: انتقال بازخورد رد شدن به Bridge
                primary = getattr(self.resolver, "primary", None)
                if primary is not None and hasattr(primary, "report_refusal"):
                    try:
                        await primary.report_refusal(
                            video_id=video_id,
                            status_code=rejected.status_code,
                            client_name=session.stream.resolver_metadata.get("client_name"),
                            profile_id=session.stream.resolver_metadata.get("profile_id"),
                            url=session.stream.url,
                        )
                    except Exception as exc:
                        log.warning("failed to report hls stream refusal to bridge: %s", exc)

                # URLِ کش‌شده منقضی شده — قبل از recovery دورش می‌اندازیم تا
                # «دقیقاً یک بار رزولوشن مجدد» حفظ شود و URL کهنه دوباره ننشیند.
                cache_key = self._resolved.key(video_id, quality, user_id)
                self._resolved.drop(cache_key)
                fresh = await self.hls.recover_session(
                    session, rejected.status_code, allow_type_change=True
                )
                if fresh is not None:
                    self._resolved.put(cache_key, fresh)
                if fresh is not None and fresh.stream_type != "HLS":
                    # بازیابی به progressive رسید → همان پروکسی progressive
                    log.info(
                        "hls recovery switched to progressive [vid=%s]", video_id
                    )
                    return await self._proxy(fresh, range_header, track=track, quality=quality)
                if fresh is not None:
                    try:
                        return await self.hls.load_manifest_response(session)
                    except _UpstreamRejected as second:
                        if not is_yt_video:
                            fallback = await self._resolve_live_fallback(
                                track, failed_video_id=video_id, range_header=range_header, quality=quality, user_id=user_id
                            )
                            if fallback is not None:
                                return fallback
                        raise classify_runtime_failure(
                            http_status=second.status_code, video_id=video_id
                        ) from second
                # بودجه recovery تمام (recovery_used) → classified → legacy
                if not is_yt_video:
                    fallback = await self._resolve_live_fallback(
                        track, failed_video_id=video_id, range_header=range_header, quality=quality, user_id=user_id
                    )
                    if fallback is not None:
                        return fallback
                raise classify_runtime_failure(
                    http_status=rejected.status_code, video_id=video_id
                )

        try:
            return await self._proxy(stream, range_header, track=track, quality=quality)
        except _UpstreamRejected as rejected:
            if rejected.status_code not in _EXPIRATION_EVIDENCE_STATUSES:
                if not is_yt_video:
                    fallback = await self._resolve_live_fallback(
                        track, failed_video_id=video_id, range_header=range_header, quality=quality, user_id=user_id
                    )
                    if fallback is not None:
                        return fallback
                # بند ۹: بدون evidence انقضا، recovery انجام نمی‌شود
                raise classify_runtime_failure(
                    http_status=rejected.status_code, video_id=video_id
                ) from rejected

            log.info(
                "live playback recovering [vid=%s, status=%d, attempt=1]",
                video_id,
                rejected.status_code,
            )
            # Phase 2: انتقال بازخورد رد شدن به Bridge
            primary = getattr(self.resolver, "primary", None)
            if primary is not None and hasattr(primary, "report_refusal"):
                try:
                    await primary.report_refusal(
                        video_id=video_id,
                        status_code=rejected.status_code,
                        client_name=stream.resolver_metadata.get("client_name"),
                        profile_id=stream.resolver_metadata.get("profile_id"),
                        url=stream.url,
                    )
                except Exception as exc:
                    log.warning("failed to report stream refusal to bridge: %s", exc)

            # مثل شاخه‌ی HLS: URL کهنه اول از کش می‌رود، بعد recovery، و
            # نتیجه‌ی تازه زیر همان کلید (همراه user_id) برمی‌گردد.
            cache_key = self._resolved.key(video_id, quality, user_id)
            self._resolved.drop(cache_key)
            fresh = await self.recovery.recover_from_runtime_failure(
                video_id,
                http_status=rejected.status_code,
                purpose="playback",
                quality=quality,
            )
            self._resolved.put(cache_key, fresh)
            try:
                # بودجه فاز ۸: دقیقاً یک تلاش مجدد؛ شکست دوباره بدون loop به بالا می‌رود
                return await self._proxy(fresh, range_header, track=track, quality=quality)
            except _UpstreamRejected as second:
                if not is_yt_video:
                    fallback = await self._resolve_live_fallback(
                        track, failed_video_id=video_id, range_header=range_header, quality=quality, user_id=user_id
                    )
                    if fallback is not None:
                        return fallback
                raise StreamRecoverySafe(rejected=second.status_code, video_id=video_id) from second

    async def warm(
        self,
        track: Track,
        quality: str | None = None,
        user_id: str = "local",
    ) -> bool:
        """
        گرم‌کردنِ کشِ استریم برای ترک‌های آینده‌ی صف (بدون دانلود کل فایل).
        فقط مرحله‌ی استخراج/رزولوشن URL را انجام می‌دهد تا وقتی نوبت پخش شد،
        آهنگ فوراً و بدون تاخیر از CDN خوانده شود.
        """
        if not is_stream_v2_enabled():
            return False
        from .. import resolver

        video_id = extract_youtube_video_id(track)
        if not video_id:
            override = resolver._canonical_override(track)
            if override and override.source in ("youtube", "youtube_music"):
                video_id = extract_video_id_from_url(override.url)
            else:
                try:
                    candidates = await asyncio.to_thread(
                        resolver.resolve,
                        track,
                        user_id=user_id,
                        use_cache=True,
                        sources=("youtube_music", "youtube", "soundcloud"),
                    )
                    for c in candidates:
                        if c.source in ("youtube", "youtube_music"):
                            vid = extract_video_id_from_url(c.url)
                            if vid:
                                video_id = vid
                                break
                except Exception as exc:
                    log.warning("warm candidate resolution failed for %s: %s", track.id, exc)
                    return False

        if not video_id:
            return False
        try:
            await self._resolve_shared(
                video_id=video_id,
                purpose="playback",
                quality=quality,
                user_id=user_id,
            )
            return True
        except Exception as exc:
            log.warning("stream warm failed for track %s: %s", track.id, exc.__class__.__name__)
            return False

    # -------------------------------------------------------------
    # مسیر داخلی
    # ------------------------------------------------------------------

    async def _resolve_shared(
        self, video_id: str, purpose: str, quality: str | None, user_id: str = "local"
    ) -> ResolvedStream:
        """
        resolve با single-flight per video_id: درخواست‌های هم‌زمان نتیجه یک
        Task مشترک را می‌گیرند (فاز ۱۲، §۴). اگر caller غیرمالک کنسل شود،
        resolve برای بقیه ادامه می‌یابد (asyncio.shield).
        """
        # کلید شاملِ کاربر است: استخراج با کوکیِ او انجام می‌شود و نتیجه‌ی یک
        # حساب نباید به درخواستِ حسابِ دیگر وصل شود.
        cache_key = self._resolved.key(video_id, quality, user_id)
        cached = self._resolved.get(cache_key)
        if cached is not None:
            return cached
        slot = (video_id, user_id)
        async with self._inflight_lock:
            task = self._inflight.get(slot)
            owner = task is None
            if owner:
                task = asyncio.ensure_future(
                    self.resolver.resolve(
                        video_id=video_id,
                        purpose=purpose,
                        quality=quality,
                        user_id=user_id,
                    )
                )
                self._inflight[slot] = task
        try:
            stream = await asyncio.shield(task)
        finally:
            if owner:
                async with self._inflight_lock:
                    if self._inflight.get(slot) is task:
                        del self._inflight[slot]
        if owner:
            self._resolved.put(cache_key, stream)
        return stream

    async def _resolve_live_fallback(
        self,
        track: Track,
        failed_video_id: str | None = None,
        range_header: str | None = None,
        quality: str | None = None,
        user_id: str = "local",
    ) -> Response | None:
        """
        فال‌بک چندمنبعی بلادرنگ: اگر ویدیوی اصلی یوتیوب ناموفق شد (DRM، خطای بات‌چک، مسدودیت)،
        سایر منابع (SoundCloud و ویدیوهای جایگزین یوتیوب) را جستجو و بلادرنگ استریم می‌کند.
        """
        try:
            from .. import resolver, stream_cache
            from .models import EXT_TO_MIME

            tried: set[str] = {"youtube_music"} if track.source == "youtube_music" else {"youtube"}
            candidates = await asyncio.to_thread(
                resolver.resolve_fallback, track, frozenset(tried), user_id
            )
            for c in candidates:
                if c.source == "soundcloud":
                    direct_info = await asyncio.to_thread(
                        stream_cache._extract_direct_stream_info,
                        c.url,
                        quality=quality,
                        user_id=user_id,
                    )
                    if direct_info and direct_info.get("url"):
                        ext = direct_info.get("ext") or "mp3"
                        mime = EXT_TO_MIME.get(f".{ext}", "audio/mpeg")
                        sc_stream = ResolvedStream(
                            source="soundcloud",
                            video_id=c.url,
                            url=direct_info["url"],
                            mime_type=mime,
                            codec=direct_info.get("acodec") or "mp3",
                            bitrate=int(direct_info.get("abr") or 128) * 1000,
                            content_length=direct_info.get("filesize"),
                            headers=direct_info.get("http_headers") or {},
                            stream_type="PROGRESSIVE",
                        )
                        log.info(
                            "live playback fallback engaged [failed_vid=%s, fallback_source=soundcloud, url=%s]",
                            failed_video_id,
                            c.url,
                        )
                        return await self._proxy(
                            sc_stream, range_header, track=track, quality=quality
                        )
                elif c.source in ("youtube", "youtube_music"):
                    alt_vid = extract_video_id_from_url(c.url)
                    if alt_vid and alt_vid != failed_video_id:
                        try:
                            alt_stream = await self._resolve_shared(
                                alt_vid, purpose="playback", quality=quality, user_id=user_id
                            )
                            if alt_stream.stream_type != "HLS":
                                log.info(
                                    "live playback fallback engaged [failed_vid=%s, fallback_vid=%s]",
                                    failed_video_id,
                                    alt_vid,
                                )
                                return await self._proxy(
                                    alt_stream, range_header, track=track, quality=quality
                                )
                        except Exception:
                            continue
        except Exception as exc:
            log.warning("live playback fallback failed for track %s: %s", track.id, exc)
        return None

    async def _proxy(
        self,
        stream: ResolvedStream,
        range_header: str | None,
        bounded_chunk_size: int = DEFAULT_BOUNDED_CHUNK_SIZE,
        track: Track | None = None,
        quality: str | None = None,
    ) -> Response:
        total_length = extract_content_length(stream)
        range_spec = parse_range_spec(range_header, total_length)

        # 1. مدیریت درخواست‌های Range نامعتبر یا خارج از محدوده (HTTP 416)
        if range_header is not None and range_spec is not None and not range_spec.is_satisfiable:
            err_headers = {
                "Content-Range": f"bytes */{total_length if total_length is not None else '*'}",
                "Accept-Ranges": "bytes",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges",
            }
            log.warning(
                "live playback unsatisfiable range [vid=%s, range=%s, total=%s]",
                stream.video_id,
                range_header,
                str(total_length),
            )
            return Response(status_code=416, headers=err_headers)

        base_headers = self.adapter.upstream_request_headers(stream)

        client = self._get_client()

        media_type = self.adapter.response_media_type(
            stream, fallback="audio/mpeg"
        )

        response_headers: dict[str, str] = {
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Expose-Headers": (
                "Content-Range, Accept-Ranges, Content-Length, Content-Disposition"
            ),
        }

        can_cache = (range_spec is None or range_spec.start == 0)
        cache_writer = _create_cache_writer(track, quality, media_type, total_length) if can_cache else None

        # -------------------------------------------------------------
        # حالت اول: کلاینت درخواست Range معتبر فرستاده است (206 Partial Content)
        # -------------------------------------------------------------
        if range_spec is not None:
            req_headers = dict(base_headers)
            if range_header.strip().lower().startswith("bytes=-") and range_spec.end is not None:
                req_headers["Range"] = f"bytes={range_spec.start}-{range_spec.end}"
            else:
                req_headers["Range"] = range_header

            try:
                request = client.build_request("GET", stream.url, headers=req_headers)
                response = await client.send(request, stream=True)
            except httpx.RequestError:
                if cache_writer:
                    cache_writer.close(commit=False)
                raise NetworkError(
                    message="Upstream stream connection failed", video_id=stream.video_id
                )

            if response.status_code >= 400:
                status = response.status_code
                if cache_writer:
                    cache_writer.close(commit=False)
                await response.aclose()
                raise _UpstreamRejected(status)

            # اگر سرور بالادست Range را رعایت کرد و 206 داد
            if response.status_code == 206:
                cr = response.headers.get("Content-Range")
                if cr:
                    response_headers["Content-Range"] = cr
                elif total_length is not None and range_spec.end is not None:
                    response_headers["Content-Range"] = (
                        f"bytes {range_spec.start}-{range_spec.end}/{total_length}"
                    )

                cl = response.headers.get("Content-Length")
                if cl:
                    response_headers["Content-Length"] = cl
                elif range_spec.end is not None:
                    response_headers["Content-Length"] = str(
                        range_spec.end - range_spec.start + 1
                    )

                async def _close_206() -> None:
                    if cache_writer:
                        cache_writer.close(commit=False)
                    await response.aclose()

                async def _stream_206() -> AsyncIterator[bytes]:
                    try:
                        async for chunk in response.aiter_bytes(_PROXY_CHUNK_SIZE):
                            if cache_writer:
                                cache_writer.write(chunk)
                            yield chunk
                        if cache_writer:
                            cache_writer.close(commit=True)
                    except Exception:
                        if cache_writer:
                            cache_writer.close(commit=False)
                        raise

                log.info(
                    "live playback streaming 206 [vid=%s, mime=%s, codec=%s, bitrate=%s]",
                    stream.video_id,
                    media_type,
                    stream.codec,
                    stream.bitrate,
                )
                return StreamingResponse(
                    _stream_206(),
                    status_code=206,
                    media_type=media_type,
                    headers=response_headers,
                    background=BackgroundTask(_close_206),
                )

            # اگر سرور بالادست Range را نادیده گرفت و 200 OK برگرداند:
            # الزامات فاز ۳: جلوگیری از تحویل داده اشتباه یا مصرف نامحدود پهنای باند
            if response.status_code == 200:
                target_start = range_spec.start
                target_end = (
                    range_spec.end
                    if range_spec.end is not None
                    else (total_length - 1 if total_length is not None else None)
                )
                tot_str = str(total_length) if total_length is not None else "*"
                if target_end is not None:
                    response_headers["Content-Range"] = (
                        f"bytes {target_start}-{target_end}/{tot_str}"
                    )
                    response_headers["Content-Length"] = str(
                        target_end - target_start + 1
                    )
                else:
                    response_headers["Content-Range"] = f"bytes {target_start}-*/{tot_str}"

                async def _sliced_stream() -> AsyncIterator[bytes]:
                    try:
                        bytes_skipped = 0
                        bytes_yielded = 0
                        bytes_needed = (
                            (target_end - target_start + 1)
                            if target_end is not None
                            else None
                        )

                        async for chunk in response.aiter_bytes(_PROXY_CHUNK_SIZE):
                            chunk_len = len(chunk)
                            if bytes_skipped < target_start:
                                to_skip = min(chunk_len, target_start - bytes_skipped)
                                bytes_skipped += to_skip
                                chunk = chunk[to_skip:]
                                chunk_len = len(chunk)
                                if chunk_len == 0:
                                    continue

                            if bytes_needed is not None:
                                remaining = bytes_needed - bytes_yielded
                                if remaining <= 0:
                                    break
                                to_send = chunk[:remaining]
                                if cache_writer and target_start == 0:
                                    cache_writer.write(to_send)
                                yield to_send
                                bytes_yielded += len(to_send)
                                if bytes_yielded >= bytes_needed:
                                    break
                            else:
                                if cache_writer and target_start == 0:
                                    cache_writer.write(chunk)
                                yield chunk
                        if cache_writer and target_start == 0:
                            cache_writer.close(commit=True)
                    finally:
                        if cache_writer:
                            cache_writer.close(commit=False)
                        await response.aclose()

                log.info(
                    "live playback slicing 200->206 [vid=%s, range=%d-%s, mime=%s]",
                    stream.video_id,
                    target_start,
                    str(target_end),
                    media_type,
                )
                return StreamingResponse(
                    _sliced_stream(),
                    status_code=206,
                    media_type=media_type,
                    headers=response_headers,
                )

        # -------------------------------------------------------------
        # حالت دوم: کلاینت بدون Range درخواست داده است (200 OK)
        # Bounded Range Proxy: خواندن بالادست در قطعات محدود (512 KiB)
        # جهت مهار کاهش سرعت توسط CDN گوگل‌ویدیو به ۱۵ کیلوبایت بر ثانیه
        # -------------------------------------------------------------
        first_chunk_end = (
            min(bounded_chunk_size - 1, total_length - 1)
            if total_length is not None
            else (bounded_chunk_size - 1)
        )
        first_headers = dict(base_headers)
        first_headers["Range"] = f"bytes=0-{first_chunk_end}"
        first_headers["Accept-Encoding"] = "identity"

        try:
            req0 = client.build_request("GET", stream.url, headers=first_headers)
            resp0 = await client.send(req0, stream=True)
        except httpx.RequestError:
            if cache_writer:
                cache_writer.close(commit=False)
            raise NetworkError(
                message="Upstream stream connection failed", video_id=stream.video_id
            )

        if resp0.status_code >= 400:
            status = resp0.status_code
            if cache_writer:
                cache_writer.close(commit=False)
            await resp0.aclose()
            raise _UpstreamRejected(status)

        if total_length is not None:
            response_headers["Content-Length"] = str(total_length)
        elif resp0.headers.get("Content-Length") and resp0.status_code == 200:
            response_headers["Content-Length"] = resp0.headers["Content-Length"]

        # اگر سرور بالادست Range را کلاً پشتیبانی نکرد و کل فایل را یکجا با 200 فرستاد
        if resp0.status_code == 200:
            async def _close_direct_200() -> None:
                if cache_writer:
                    cache_writer.close(commit=False)
                await resp0.aclose()

            async def _stream_direct_200() -> AsyncIterator[bytes]:
                try:
                    async for chunk in resp0.aiter_bytes(_PROXY_CHUNK_SIZE):
                        if cache_writer:
                            cache_writer.write(chunk)
                        yield chunk
                    if cache_writer:
                        cache_writer.close(commit=True)
                finally:
                    if cache_writer:
                        cache_writer.close(commit=False)
                    await resp0.aclose()

            log.info(
                "live playback direct 200 stream [vid=%s, mime=%s, codec=%s]",
                stream.video_id,
                media_type,
                stream.codec,
            )
            return StreamingResponse(
                _stream_direct_200(),
                status_code=200,
                media_type=media_type,
                headers=response_headers,
                background=BackgroundTask(_close_direct_200),
            )

        # سرور بالادست 206 داد؛ چانک‌های بعدی را با پایپ‌لاین پیش‌گیرانه (Lookahead=1)
        # دریافت و پیوسته استریم می‌کنیم تا تاخیر شبکه بین چانک‌های ۵۱۲ کیلوبایتی حذف شود.
        async def _bounded_range_stream() -> AsyncIterator[bytes]:
            async def _fetch_chunk(start: int) -> httpx.Response | None:
                if total_length is not None and start >= total_length:
                    return None
                chunk_end = start + bounded_chunk_size - 1
                if total_length is not None:
                    chunk_end = min(chunk_end, total_length - 1)
                sub_headers = dict(base_headers)
                sub_headers["Range"] = f"bytes={start}-{chunk_end}"
                sub_headers["Accept-Encoding"] = "identity"
                sub_req = client.build_request("GET", stream.url, headers=sub_headers)
                return await client.send(sub_req, stream=True)

            current_resp: httpx.Response | None = resp0
            next_task: asyncio.Task[httpx.Response | None] | None = None
            current_start = 0

            try:
                while current_resp is not None:
                    bytes_in_chunk = 0
                    lookahead_scheduled = False

                    async for data in current_resp.aiter_bytes(_PROXY_CHUNK_SIZE):
                        # هم‌زمان با استریم چانک جاری، درخواست چانک بعدی را در پس‌زمینه
                        # می‌زنیم. قبل از `yield` — نه بعدش: بعد از yield کنترل به
                        # کلاینت می‌رود و تا درخواست بعدی، پیش‌واکشی شروع نشده است.
                        if not lookahead_scheduled and next_task is None:
                            lookahead_scheduled = True
                            next_start = current_start + bounded_chunk_size
                            if total_length is None or next_start < total_length:
                                next_task = asyncio.create_task(_fetch_chunk(next_start))

                        bytes_in_chunk += len(data)
                        if cache_writer:
                            cache_writer.write(data)
                        yield data

                    await current_resp.aclose()
                    current_resp = None
                    current_start += bytes_in_chunk

                    if bytes_in_chunk == 0:
                        break
                    if total_length is not None and current_start >= total_length:
                        break

                    # دریافت چانک بعدی که از قبل در پس‌زمینه در حال واکشی بوده است
                    if next_task is not None:
                        sub_resp = await next_task
                        next_task = None
                        if sub_resp is None:
                            break
                        if sub_resp.status_code >= 400:
                            sub_status = sub_resp.status_code
                            await sub_resp.aclose()
                            if sub_status == 416 and current_start > 0:
                                break
                            raise _UpstreamRejected(sub_status)
                        current_resp = sub_resp

                if cache_writer:
                    cache_writer.close(commit=True)
            finally:
                if cache_writer:
                    cache_writer.close(commit=False)
                if current_resp is not None:
                    await current_resp.aclose()
                if next_task is not None and not next_task.done():
                    next_task.cancel()
                    try:
                        t_resp = await next_task
                        if t_resp is not None:
                            await t_resp.aclose()
                    except (asyncio.CancelledError, Exception):
                        pass
                elif next_task is not None and next_task.done():
                    try:
                        t_resp = next_task.result()
                        if t_resp is not None:
                            await t_resp.aclose()
                    except Exception:
                        pass
                await resp0.aclose()

        log.info(
            "live playback bounded range proxy 200 [vid=%s, mime=%s, total=%s]",
            stream.video_id,
            media_type,
            str(total_length),
        )
        return StreamingResponse(
            _bounded_range_stream(),
            status_code=200,
            media_type=media_type,
            headers=response_headers,
        )


class StreamRecoverySafe(StreamResolverError):
    """پروکسی روی استریم تازه نیز rejected شد — بودجه recovery تمام (بدون loop)."""

    def __init__(self, rejected: int, video_id: str = "") -> None:
        super().__init__(
            message=f"Fresh stream also rejected upstream (status {rejected}); recovery budget exhausted",
            code="STREAM_RECOVERY_FAILED",
            retryable=False,
            video_id=video_id,
        )


# singleton in-process تا Client Health فاز ۷ بین درخواست‌ها مشترک بماند
_live_playback: LivePlaybackStreamer | None = None


def get_live_playback() -> LivePlaybackStreamer:
    global _live_playback
    if _live_playback is None:
        _live_playback = LivePlaybackStreamer()
    return _live_playback
