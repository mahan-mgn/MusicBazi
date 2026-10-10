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
import re
from typing import Any, AsyncIterator
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
        # single-flight درون-پردازشی (فاز ۱۲): چند consumer هم‌زمان برای یک ویدیو
        # فقط یک resolve اشتراکی ایجاد می‌کنند — قفل سبک asyncio، بدون infra
        self._inflight: dict[str, asyncio.Task] = {}
        self._inflight_lock = asyncio.Lock()

    # -------------------------------------------------------------
    # API
    # -------------------------------------------------------------

    def on_session_changed(self) -> None:
        """انتقال رویداد تغییر نشست به رزولور (نشست‌های فعال HLS مختل نمی‌شوند)."""
        self.resolver.on_session_changed()

    async def stream_response(
        self,
        track: Track,
        range_header: str | None = None,
        quality: str | None = None,
        env: dict[str, str] | None = None,
    ) -> Response | None:
        """
        اگر flag روشن و video_id قابل استخراج بود، Response (یا StreamingResponse) برمی‌گرداند؛
        در غیر این صورت None (یعنی «این مسیر اعمال نمی‌شود»). هر خطای resolve/
        recovery/proxy به‌صورت StreamResolverError با پیام امن (بدون URL) پرتاب
        می‌شود تا caller به مسیر legacy برگردد.
        """
        if not is_stream_v2_enabled(env):
            return None
        video_id = extract_youtube_video_id(track)
        if not video_id:
            return None

        stream = await self._resolve_shared(video_id, purpose="playback", quality=quality)

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

                fresh = await self.hls.recover_session(
                    session, rejected.status_code, allow_type_change=True
                )
                if fresh is not None and fresh.stream_type != "HLS":
                    # بازیابی به progressive رسید → همان پروکسی progressive
                    log.info(
                        "hls recovery switched to progressive [vid=%s]", video_id
                    )
                    return await self._proxy(fresh, range_header)
                if fresh is not None:
                    try:
                        return await self.hls.load_manifest_response(session)
                    except _UpstreamRejected as second:
                        raise classify_runtime_failure(
                            http_status=second.status_code, video_id=video_id
                        ) from second
                # بودجه recovery تمام (recovery_used) → classified → legacy
                raise classify_runtime_failure(
                    http_status=rejected.status_code, video_id=video_id
                )

        try:
            return await self._proxy(stream, range_header)
        except _UpstreamRejected as rejected:
            if rejected.status_code not in _EXPIRATION_EVIDENCE_STATUSES:
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

            fresh = await self.recovery.recover_from_runtime_failure(
                video_id,
                http_status=rejected.status_code,
                purpose="playback",
                quality=quality,
            )
            try:
                # بودجه فاز ۸: دقیقاً یک تلاش مجدد؛ شکست دوباره بدون loop به بالا می‌رود
                return await self._proxy(fresh, range_header)
            except _UpstreamRejected as second:
                raise StreamRecoverySafe(rejected=second.status_code, video_id=video_id) from second

    # ------------------------------------------------------------------
    # مسیر داخلی
    # ------------------------------------------------------------------

    async def _resolve_shared(self, video_id: str, purpose: str, quality: str | None) -> ResolvedStream:
        """
        resolve با single-flight per video_id: درخواست‌های هم‌زمان نتیجه یک
        Task مشترک را می‌گیرند (فاز ۱۲، §۴). اگر caller غیرمالک کنسل شود،
        resolve برای بقیه ادامه می‌یابد (asyncio.shield).
        """
        async with self._inflight_lock:
            task = self._inflight.get(video_id)
            owner = task is None
            if owner:
                task = asyncio.ensure_future(
                    self.resolver.resolve(
                        video_id=video_id, purpose=purpose, quality=quality
                    )
                )
                self._inflight[video_id] = task
        try:
            return await asyncio.shield(task)
        finally:
            if owner:
                async with self._inflight_lock:
                    if self._inflight.get(video_id) is task:
                        del self._inflight[video_id]

    async def _proxy(
        self,
        stream: ResolvedStream,
        range_header: str | None,
        bounded_chunk_size: int = DEFAULT_BOUNDED_CHUNK_SIZE,
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

        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
            follow_redirects=True,
            transport=self._http_transport,
        )

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
                await client.aclose()
                raise NetworkError(
                    message="Upstream stream connection failed", video_id=stream.video_id
                )

            if response.status_code >= 400:
                status = response.status_code
                await response.aclose()
                await client.aclose()
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
                    await response.aclose()
                    await client.aclose()

                log.info(
                    "live playback streaming 206 [vid=%s, mime=%s, codec=%s, bitrate=%s]",
                    stream.video_id,
                    media_type,
                    stream.codec,
                    stream.bitrate,
                )
                return StreamingResponse(
                    response.aiter_bytes(_PROXY_CHUNK_SIZE),
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
                                yield to_send
                                bytes_yielded += len(to_send)
                                if bytes_yielded >= bytes_needed:
                                    break
                            else:
                                yield chunk
                    finally:
                        await response.aclose()
                        await client.aclose()

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
            await client.aclose()
            raise NetworkError(
                message="Upstream stream connection failed", video_id=stream.video_id
            )

        if resp0.status_code >= 400:
            status = resp0.status_code
            await resp0.aclose()
            await client.aclose()
            raise _UpstreamRejected(status)

        if total_length is not None:
            response_headers["Content-Length"] = str(total_length)
        elif resp0.headers.get("Content-Length") and resp0.status_code == 200:
            response_headers["Content-Length"] = resp0.headers["Content-Length"]

        # اگر سرور بالادست Range را کلاً پشتیبانی نکرد و کل فایل را یکجا با 200 فرستاد
        if resp0.status_code == 200:
            async def _close_direct_200() -> None:
                await resp0.aclose()
                await client.aclose()

            log.info(
                "live playback direct 200 stream [vid=%s, mime=%s, codec=%s]",
                stream.video_id,
                media_type,
                stream.codec,
            )
            return StreamingResponse(
                resp0.aiter_bytes(_PROXY_CHUNK_SIZE),
                status_code=200,
                media_type=media_type,
                headers=response_headers,
                background=BackgroundTask(_close_direct_200),
            )

        # سرور بالادست 206 داد؛ چانک‌های بعدی را قطعه‌قطعه با Bounded Range دریافت و پیوسته استریم می‌کنیم
        async def _bounded_range_stream() -> AsyncIterator[bytes]:
            try:
                # 1. ارسال داده‌های چانک اول
                chunk0_bytes = 0
                async for data in resp0.aiter_bytes(_PROXY_CHUNK_SIZE):
                    chunk0_bytes += len(data)
                    yield data
                await resp0.aclose()

                # 2. دریافت و ارسال پیوسته چانک‌های بعدی
                current_start = chunk0_bytes
                while True:
                    if total_length is not None and current_start >= total_length:
                        break

                    chunk_end = current_start + bounded_chunk_size - 1
                    if total_length is not None:
                        chunk_end = min(chunk_end, total_length - 1)

                    sub_headers = dict(base_headers)
                    sub_headers["Range"] = f"bytes={current_start}-{chunk_end}"
                    sub_headers["Accept-Encoding"] = "identity"

                    sub_req = client.build_request("GET", stream.url, headers=sub_headers)
                    sub_resp = await client.send(sub_req, stream=True)

                    if sub_resp.status_code >= 400:
                        sub_status = sub_resp.status_code
                        await sub_resp.aclose()
                        if sub_status == 416 and current_start > 0:
                            # به انتهای فایل رسیدیم
                            break
                        raise _UpstreamRejected(sub_status)

                    bytes_in_chunk = 0
                    try:
                        async for data in sub_resp.aiter_bytes(_PROXY_CHUNK_SIZE):
                            bytes_in_chunk += len(data)
                            yield data
                    finally:
                        await sub_resp.aclose()

                    if bytes_in_chunk == 0:
                        break
                    current_start += bytes_in_chunk
            finally:
                await resp0.aclose()
                await client.aclose()

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
