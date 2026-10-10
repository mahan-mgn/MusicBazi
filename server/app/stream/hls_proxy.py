"""
HLS Server-Side Proxy — Strategy B از Phase 13 (فاز ۱۴).

وقتی InnerTubeX نتیجه HLS (media playlist) برمی‌گرداند:
  /api/stream
    ↓ ResolvedStream(stream_type=HLS)
  fetch manifest از upstream (server-side)
    ↓ rewrite: هر segment/variant URI → مسیر داخلی «/api/stream/hls/{sid}/{idx}»
  rewritten manifest به client
    ↓ client همان URLهای داخلی را درخواست می‌کند
  segment endpoint → validate session/index → GET signed upstream → relay bytes

Invariants امنیتی:
  - signed upstream URL (sig/vprv/expire/ip/...) هرگز در body، header، log یا
    exception به client نمی‌رسد؛ فقط درون session (runtime، درون-پردازشی) زندگی می‌کند.
  - session id از secrets.token_urlsafe — opaque و بدون هیچ داده upstream.
  - SSRF: فقط HTTPS روی googlevideo.com/youtube.com (و زیردامنه‌ها) — هر URI
    خارج از allowlist کل manifest را «پشتیبانی‌نشده» می‌کند (نه skip خطی).
  - headers حساس upstream هرگز به پاسخ client relay نمی‌شوند.

Lifecycle:
  - sessionها in-memory و bounded (MAX_SESSIONS با حذف LRU + TTL از پارامتر
    expire در URL manifest، سقف ۶ ساعت). هیچ persistence و DB.
  - recovery: stream-level، حداکثر ۱ بار per session (flag)، با قفل session —
    ۱۰ segment failure هم‌زمان فقط یک re-resolution (بودجه فاز ۸، بدون loop).

SABR عمداً پیاده نشده (فاز ۱۴ ممنوع)؛ این ماژول آیندهٔ آن را نمی‌بندد.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from .errors import NetworkError, StreamResolverError
from .models import ResolvedStream
from .recovery import StreamRecovery, classify_runtime_failure

log = logging.getLogger(__name__)

# host allowlist مطابق isAllowedHlsUrl در InnerTubeX v0.7.4 (HTTPS فقط)
ALLOWED_UPSTREAM_HOSTS = ("googlevideo.com", "youtube.com")
MANIFEST_CONTENT_TYPE = "application/vnd.apple.mpegurl"

# CORS برای manifest/variant (لازمِ hls.js XHR و MediaElementSource در اپِ cross-origin)
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
}

MAX_SESSIONS = 64
MAX_SESSION_TTL_SECONDS = 6 * 3600
MAX_RESOURCES_PER_SESSION = 4096
# اندازه chunk برای relay بایت segment (سرور کل segment را در RAM نگه نمی‌دارد)
RELAY_CHUNK_SIZE = 64 * 1024

UPSTREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# statusهایی که طبق classification فاز ۸ evidence انقضا هستند
_EXPIRATION_EVIDENCE_STATUSES = (403, 410)

_URI_ATTRIBUTE_RE = re.compile(r'URI="([^"]+)"')


def _is_allowed_upstream_url(url: str) -> bool:
    """SSRF protection: فقط HTTPS، پورت 443، روی host allowlist یوتیوب."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    port_ok = parsed.port in (None, 443)
    host_ok = any(host == h or host.endswith("." + h) for h in ALLOWED_UPSTREAM_HOSTS)
    return parsed.scheme == "https" and port_ok and host_ok


def _extract_expire_epoch(url: str) -> float | None:
    """استخراج امن expire (epoch) از پارامتر URL — فقط عدد، بدون نگه‌داشتن URL."""
    try:
        values = parse_qs(urlparse(url).query).get("expire")
        if values and values[0].isdigit():
            return float(values[0])
    except Exception:
        pass
    return None


@dataclass
class _Resource:
    """یک URI بازنویسی‌شده در manifest: segment یا variant manifest."""
    url: str
    is_manifest: bool


@dataclass
class HlsSession:
    """State runtime یک playback HLS — بدون هیچ داده حساس client-visible."""

    session_id: str
    video_id: str
    upstream_manifest_url: str
    upstream_headers: dict[str, str]
    expires_at: float | None
    resources: list[_Resource] = field(default_factory=list)
    manifest_body: bytes | None = None
    recovery_used: bool = False
    updated_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class HlsSessionRegistry:
    """Registry bounded درون-پردازشی: video_id → session و session_id → session."""

    def __init__(
        self,
        max_sessions: int = MAX_SESSIONS,
        default_ttl: float = MAX_SESSION_TTL_SECONDS,
        clock=None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._max_sessions = max(1, int(max_sessions))
        self._default_ttl = float(default_ttl)
        self._by_video: dict[str, HlsSession] = {}
        self._by_id: dict[str, HlsSession] = {}

    def _expired(self, session: HlsSession) -> bool:
        now = self._clock()
        if now - session.updated_at > self._default_ttl:
            return True
        return session.expires_at is not None and now >= session.expires_at

    def _cleanup(self) -> None:
        expired = [sid for sid, s in self._by_id.items() if self._expired(s)]
        for sid in expired:
            s = self._by_id.pop(sid)
            self._by_video.pop(s.video_id, None)
        while len(self._by_id) > self._max_sessions:
            oldest_sid = min(self._by_id, key=lambda sid: self._by_id[sid].updated_at)
            s = self._by_id.pop(oldest_sid)
            self._by_video.pop(s.video_id, None)

    def get_or_create(self, video_id: str, stream: ResolvedStream) -> HlsSession:
        """
        session برای این ویدیو (share بین consumerهای هم‌زمان — فاز ۱۲).
        اگر manifest URL عوض شده باشد (re-resolution)، session تازه جایگزین می‌شود.
        """
        self._cleanup()
        existing = self._by_video.get(video_id)
        if existing is not None and not self._expired(existing) \
                and existing.upstream_manifest_url == stream.url:
            return existing

        expire_epoch = _extract_expire_epoch(stream.url)
        session = HlsSession(
            session_id=secrets.token_urlsafe(12),
            video_id=video_id,
            upstream_manifest_url=stream.url,
            upstream_headers=dict(stream.headers or {}),
            expires_at=self._clock() + self._default_ttl,
            updated_at=self._clock(),
        )
        # expire epoch مطلقِ URL به «باقیمانده» روی clock مونوتونیک تبدیل می‌شود؛
        # expire گذشته یعنی session بلافاصله منقضی
        if expire_epoch is not None:
            remaining = expire_epoch - time.time()
            session.expires_at = self._clock() + max(0.0, remaining)
        self._by_video[video_id] = session
        self._by_id[session.session_id] = session
        self._cleanup()  # پس از insert هم سقف دقیقاً رعایت می‌شود
        return session

    def get(self, session_id: str) -> HlsSession | None:
        self._cleanup()
        session = self._by_id.get(session_id)
        if session is None or self._expired(session):
            return None
        return session


class _UpstreamRejected(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"upstream status {status_code}")
        self.status_code = status_code


class _ManifestUnsupported(Exception):
    """manifest/URI خارج از policy (SSRF، host ناشناس، malformed) — rollback path."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HlsProxyController:
    """منطق manifest/segment proxy + session recovery (بودجه فاز ۸)."""

    def __init__(
        self,
        recovery: StreamRecovery,
        registry: HlsSessionRegistry | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        max_resources: int = MAX_RESOURCES_PER_SESSION,
    ) -> None:
        self.recovery = recovery
        self.registry = registry or HlsSessionRegistry()
        self._http_transport = http_transport
        self._max_resources = max(1, int(max_resources))

    # ------------------------------------------------------------------
    # ورودی از LivePlaybackStreamer (مسیر /api/stream)
    # ------------------------------------------------------------------

    async def load_manifest_response(self, session: HlsSession) -> Response:
        """manifest بازنویسی‌شده سطح بالا برای /api/stream."""
        body = await self.load_manifest(session)
        return Response(body, media_type=MANIFEST_CONTENT_TYPE, headers=_CORS_HEADERS)

    # ------------------------------------------------------------------
    # endpointهای داخلی (main.py)
    # ------------------------------------------------------------------

    async def serve_manifest(self, session_id: str) -> Response | None:
        """پاسخ manifest بازنویسی‌شده برای session موجود (بدون resolve جدید)."""
        session = self.registry.get(session_id)
        if session is None or session.manifest_body is None:
            return None
        return Response(session.manifest_body, media_type=MANIFEST_CONTENT_TYPE, headers=_CORS_HEADERS)

    async def serve_segment(
        self, session_id: str, index: int, range_header: str | None = None
    ) -> Response | StreamingResponse | None:
        """relay بایت segment/variant با Range؛ با stream-level recovery (بودجه ۱)."""
        session = self.registry.get(session_id)
        if session is None:
            return None
        if index < 0 or index >= len(session.resources):
            return None
        resource = session.resources[index]

        try:
            if resource.is_manifest:
                body = await self.load_manifest(session, index)
                return Response(body, media_type=MANIFEST_CONTENT_TYPE, headers=_CORS_HEADERS)
            return await self._relay(session, resource, range_header)
        except _UpstreamRejected as rejected:
            if rejected.status_code not in _EXPIRATION_EVIDENCE_STATUSES:
                raise classify_runtime_failure(
                    http_status=rejected.status_code, video_id=session.video_id
                ) from rejected
            # stream-level recovery: حداکثر یک بار در عمر session (قفل session)
            fresh = await self.recover_session(session, rejected.status_code)
            if fresh is None:
                raise classify_runtime_failure(
                    http_status=rejected.status_code, video_id=session.video_id
                ) from rejected
            # نمایه‌ها بعد از repoint به mapping جدید اشاره می‌کنند
            if index >= len(session.resources):
                return None
            fresh_resource = session.resources[index]
            try:
                if fresh_resource.is_manifest:
                    body = await self.load_manifest(session, index)
                    return Response(body, media_type=MANIFEST_CONTENT_TYPE, headers=_CORS_HEADERS)
                return await self._relay(session, fresh_resource, range_header)
            except _UpstreamRejected as second:
                raise classify_runtime_failure(
                    http_status=second.status_code, video_id=session.video_id
                ) from second

    # ------------------------------------------------------------------
    # داخلی: manifest parse/rewrite
    # ------------------------------------------------------------------

    def _map_uri(self, session: HlsSession, url: str, is_manifest: bool) -> str:
        if not _is_allowed_upstream_url(url):
            raise _ManifestUnsupported(f"upstream URI outside allowlist (scheme/host)")
        if len(session.resources) >= self._max_resources:
            raise _ManifestUnsupported("resource cap exceeded")
        index = len(session.resources)
        session.resources.append(_Resource(url=url, is_manifest=is_manifest))
        # مسیر مطلق root-relative: از هر عمقی (manifest اصلی یا variant) resolve می‌شود
        return f"/api/stream/hls/{session.session_id}/{index}"

    def _rewrite_manifest(self, session: HlsSession, base_url: str, text: str) -> str:
        """بازنویسی قطعی manifest: URIهای segment/variant/attribute → مسیر داخلی."""
        out: list[str] = []
        expect: str | None = None  # 'segment' | 'variant'
        has_media_tag = False
        has_variant_tag = False
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                out.append(line)
                continue
            if stripped.startswith("#"):
                if stripped.startswith("#EXTINF") or stripped.startswith("#EXT-X-PART"):
                    expect = "segment"
                    has_media_tag = True
                elif stripped.startswith("#EXT-X-STREAM-INF"):
                    expect = "variant"
                    has_variant_tag = True
                elif stripped.startswith("#EXT-X-TARGETDURATION"):
                    has_media_tag = True
                if "URI=\"" in stripped:
                    rewritten = _URI_ATTRIBUTE_RE.sub(
                        lambda m: 'URI="' + self._map_uri(
                            session, urljoin_url(base_url, m.group(1)), False
                        ) + '"',
                        stripped,
                    )
                    out.append(rewritten)
                else:
                    out.append(stripped)
                continue
            # خط URI
            kind = expect or "segment"
            expect = None
            out.append(self._map_uri(session, urljoin_url(base_url, stripped), kind == "variant"))
        if not session.resources:
            raise _ManifestUnsupported("manifest contains no segment or variant URIs")
        if not has_media_tag and not has_variant_tag:
            raise _ManifestUnsupported("not an HLS playlist (no EXT-X tags)")
        return "\n".join(out) + "\n"

    async def _fetch_text(self, session: HlsSession, url: str) -> str:
        """fetch متن manifest از upstream (کوچک است؛ کامل خوانده می‌شود)."""
        client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT, transport=self._http_transport)
        try:
            request = client.build_request("GET", url, headers=dict(session.upstream_headers))
            response = await client.send(request)
        except httpx.RequestError:
            await client.aclose()
            raise NetworkError(
                message="Upstream manifest connection failed", video_id=session.video_id
            )
        if response.status_code >= 400:
            status = response.status_code
            await response.aclose()
            await client.aclose()
            raise _UpstreamRejected(status)
        text = response.text
        await response.aclose()
        await client.aclose()
        return text

    async def load_manifest(self, session: HlsSession, resource_index: int | None = None) -> bytes:
        """fetch manifest از upstream + rewrite. سطح بالا cache می‌شود."""
        if resource_index is None and session.manifest_body is not None:
            return session.manifest_body

        url = (
            session.upstream_manifest_url
            if resource_index is None
            else session.resources[resource_index].url
        )
        body_text = await self._fetch_text(session, url)
        rewritten = self._rewrite_manifest(session, url, body_text)
        body = rewritten.encode("utf-8")
        if resource_index is None:
            session.manifest_body = body
        return body

    # ------------------------------------------------------------------
    # داخلی: relay و recovery
    # ------------------------------------------------------------------

    async def _relay(
        self, session: HlsSession, resource: _Resource, range_header: str | None
    ):
        if resource.is_manifest:
            body = await self.load_manifest(session)
            return Response(body, media_type=MANIFEST_CONTENT_TYPE)

        headers = dict(session.upstream_headers)
        if range_header:
            headers["Range"] = range_header
        client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT, transport=self._http_transport)
        try:
            request = client.build_request("GET", resource.url, headers=headers)
            response = await client.send(request, stream=True)
        except httpx.RequestError:
            await client.aclose()
            raise NetworkError(
                message="Upstream segment connection failed", video_id=session.video_id
            )
        if response.status_code >= 400:
            status = response.status_code
            await response.aclose()
            await client.aclose()
            raise _UpstreamRejected(status)

        relay_headers = {
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": (
                "Content-Range, Accept-Ranges, Content-Length, Content-Disposition"
            ),
        }
        for name in ("Content-Length", "Content-Range", "Content-Type"):
            value = response.headers.get(name)
            if value:
                relay_headers[name] = value
        media_type = response.headers.get("content-type") or "application/octet-stream"

        async def _close() -> None:
            await response.aclose()
            await client.aclose()

        return StreamingResponse(
            response.aiter_bytes(RELAY_CHUNK_SIZE),
            status_code=response.status_code,
            media_type=media_type,
            headers=relay_headers,
            background=BackgroundTask(_close),
        )

    async def recover_session(
        self,
        session: HlsSession,
        status_code: int,
        allow_type_change: bool = False,
    ) -> ResolvedStream | None:
        """
        stream-level recovery با بودجه ۱ per session و قفل session (فاز ۸ reuse):
        ۱۰ segment failure هم‌زمان → دقیقاً یک re-resolution (بقیه بلافاصله رد می‌شوند).
        بازگشت:
          ResolvedStream (HLS جدید) → session repoint شده و manifest تازه لود شده
          ResolvedStream (progressive) → فقط اگر allow_type_change=True
          None → بودجه تمام یا recovery به نوع غیرقابل‌سرو رسید
        """
        async with session.lock:
            if session.recovery_used:
                return None
            session.recovery_used = True
        fresh = await self.recovery.recover_from_runtime_failure(
            session.video_id,
            http_status=status_code,
            purpose="playback",
        )
        if fresh.stream_type != "HLS":
            if allow_type_change:
                return fresh
            # recovery به progressive رسید و session HLS نمی‌تواند ادامه دهد
            return None
        # repoint session به manifest تازه — session id و URLهای client ثابت می‌مانند
        session.upstream_manifest_url = fresh.url
        session.upstream_headers = dict(fresh.headers or {})
        session.resources = []
        session.manifest_body = None
        session.updated_at = time.monotonic()
        try:
            await self.load_manifest(session)
        except _UpstreamRejected:
            # manifest تازه هم رد شد — بودجه تمام؛ caller classified می‌کند
            return None
        return fresh


def urljoin_url(base: str, uri: str) -> str:
    """resolve قطعی URI (absolute/relative) نسبت به playlist؛ بدون رفتن روی شبکه."""
    if uri.startswith("https://") or uri.startswith("http://"):
        return uri
    from urllib.parse import urljoin

    return urljoin(base, uri)
