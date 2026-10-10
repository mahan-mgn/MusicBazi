"""
تست‌های Phase 14 — HLS Server-Side Proxy (Strategy B فاز ۱۳).

پوشش:
1. Manifest: بازنویسی media/master playlist، absolute/relative URIs، بدون هیچ
   signed upstream URL در body
2. Segment: relay بایت، Range/206، Content-Type، headers حساس relay نمی‌شوند
3. Security: googlevideo/sig/expire/cookie در body/log/error نیستند؛ SSRF بلاک
4. Expiration: manifest/segment 403 → دقیقاً یک recovery؛ persistent → توقف
5. No-loop: ۱۰ segment failure → حداکثر ۱ re-resolution
6. Concurrency: ۱۰ هم‌زمان same video → ۱ resolve و session مشترک
7. Registry: bounded، LRU eviction، TTL/expire cleanup
8. Progressive regression: مسیر progressive دست‌نخورده
9. Soak: ۵۰ attempt ترکیبی بدون leak/loop
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.stream.errors import (
    AllResolversFailedError,
    NoStreamError,
    StreamResolverError,
)
from app.stream.feature_flags import STREAM_V2_FLAG
from app.stream.hls_proxy import (
    MANIFEST_CONTENT_TYPE,
    HlsProxyController,
    HlsSessionRegistry,
)
from app.stream.models import ResolvedStream
from app.stream.playback import LivePlaybackStreamer
from app.stream.resolver import YouTubeStreamResolver

FLAG_ON = {STREAM_V2_FLAG: "1"}
SEG_BYTES = b"\x00\x01segment-bytes" * 8
# expire واقعی در آینده (برای session TTL)
FUTURE_EXPIRE = str(int(time.time()) + 21600)


def make_stream(video_id: str, url: str, stream_type: str = "HLS", **ov) -> ResolvedStream:
    defaults = dict(
        source="youtube",
        url=url,
        mime_type="application/x-mpegURL" if stream_type == "HLS" else "audio/webm",
        codec="opus",
        bitrate=140000,
        channels=2,
        duration=200.0,
        expires_at=int(time.time()) + 3600 if stream_type == "PROGRESSIVE" else None,
        headers={"User-Agent": "ua-hls-test"},
        resolver_metadata={"client_name": "VISIONOS", "resolver": "innertubex"},
        stream_type=stream_type,
    )
    defaults.update(ov)
    return ResolvedStream(video_id=video_id, **defaults)


def media_playlist(base: str, seg_status_markers: str = "") -> str:
    return (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:6\n"
        f"#EXTINF:5.0,\n{base}/seg0.ts?sig=SECRET_A&expire={FUTURE_EXPIRE}\n"
        f"#EXTINF:5.0,{seg_status_markers}\n{base}/seg1.ts?sig=SECRET_B&expire={FUTURE_EXPIRE}\n"
        "#EXTINF:5.0,\nseg2.ts?sig=SECRET_C\n"
        "#EXT-X-ENDLIST\n"
    )


MANIFEST_BASE = "https://rr1---sn-abc.googlevideo.com/api/manifest/hls_playlist/id/abc/it/96"
MASTER_PLAYLIST = (
    "#EXTM3U\n"
    '#EXT-X-STREAM-INF:BANDWIDTH=128000,CODECS="mp4a.40.2"\n'
    f"{MANIFEST_BASE}/variant.m3u8?sig=SECRET_V&expire={FUTURE_EXPIRE}\n"
)
VARIANT_PLAYLIST = media_playlist(MANIFEST_BASE)


class UpstreamRouter:
    """routing بر اساس نشانه URL — و ثبت درخواست‌ها برای ادعاها."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if "FORCE500" in url:
            return httpx.Response(500, content=b"")
        if "GONE" in url:
            return httpx.Response(410, content=b"")
        if "REJECT" in url:
            return httpx.Response(403, content=b"")
        if "seg" in url and ".ts" in url:
            headers = {"Content-Type": "video/mp4"}
            rng = request.headers.get("range")
            if rng:
                headers["Content-Range"] = "bytes 100-199/8000"
                return httpx.Response(206, content=SEG_BYTES[100:200], headers=headers)
            return httpx.Response(200, content=SEG_BYTES, headers=headers)
        if "variant.m3u8" in url:
            return httpx.Response(200, text=VARIANT_PLAYLIST)
        if "hls_playlist" in url:
            return httpx.Response(200, text=media_playlist(MANIFEST_BASE))
        return httpx.Response(404, content=b"")


class ScenarioPrimary:
    """primary resolver شبیه‌سازی‌شده با سناریوی قابل تعویض."""

    def __init__(self) -> None:
        self.kind = "success"
        self.url = f"{MANIFEST_BASE}?expire={FUTURE_EXPIRE}&sig=SECRET_M"
        self.calls: dict[str, int] = {}
        self.total = 0

    async def resolve_stream(self, video_id: str, purpose: str = "playback", quality=None):
        self.total += 1
        self.calls[video_id] = self.calls.get(video_id, 0) + 1
        if self.kind == "fail":
            raise NoStreamError("no stream", video_id=video_id)
        if self.kind == "progfail":
            # progressive با OLD/FRESH برای شبیه‌سازی recovery فاز ۸
            n = self.calls[video_id]
            marker = "OLD" if n == 1 else "FRESH"
            return make_stream(
                video_id, f"https://rr1.example/{video_id}_{marker}", stream_type="PROGRESSIVE"
            )
        if self.kind == "f500":
            # progressive که upstream آن 500 می‌دهد
            return make_stream(
                video_id, f"https://rr1.example/{video_id}_FORCE500", stream_type="PROGRESSIVE"
            )
        if self.kind == "progressive":
            return make_stream(
                video_id,
                f"https://rr1---sn-abc.googlevideo.com/videoplayback?id={video_id}&sig=P",
                stream_type="PROGRESSIVE",
            )
        url = self.url
        if self.kind == "rotate":  # هر resolve URL تازه (expire جدید)
            url = f"{self.url}&rot={self.total}"
        return make_stream(video_id, url, stream_type="HLS")


def build(secondary_fails: bool = False):
    scenario = ScenarioPrimary()
    mock_ytdlp = AsyncMock(spec=object)
    mock_ytdlp.resolve_stream = AsyncMock(
        side_effect=NoStreamError("no stream") if secondary_fails else RuntimeError("should not be called")
    )
    resolver = YouTubeStreamResolver(
        primary_resolver=scenario, fallback_resolver=mock_ytdlp,
        client_health=__import__("app.stream.client_health", fromlist=["ClientHealthMonitor"]).ClientHealthMonitor(),
    )
    router = UpstreamRouter()
    streamer = LivePlaybackStreamer(
        resolver=resolver, http_transport=httpx.MockTransport(router.handler)
    )
    return streamer, scenario, mock_ytdlp, router


async def body_of(resp) -> bytes:
    if hasattr(resp, "body_iterator"):
        return b"".join([c async for c in resp.body_iterator])
    return resp.body


def extract_session_id(body: bytes) -> str:
    match = re.search(rb"/api/stream/hls/([A-Za-z0-9_-]+)/", body)
    assert match, "internal session URL not found in manifest"
    return match.group(1).decode()


# ======================================================================
# Manifest Proxy
# ======================================================================


class TestManifestProxy:
    @pytest.mark.asyncio
    async def test_hls_manifest_rewritten_no_upstream_urls(self):
        streamer, scenario, _, router = build()
        resp = await streamer.stream_response(youtube_track := _track("vidM1"), env=FLAG_ON)

        assert resp is not None
        assert resp.media_type == MANIFEST_CONTENT_TYPE
        body = resp.body
        # فقط URLهای داخلی — هیچ اثر upstream
        assert b"/api/stream/hls/" in body
        for forbidden in (b"googlevideo", b"sig=", b"SECRET", b"expire=", b"vprv"):
            assert forbidden not in body
        # سه segment مپ شده
        assert len(re.findall(rb"/api/stream/hls/[A-Za-z0-9_-]+/\d+", body)) == 3
        assert scenario.calls[_tid("vidM1")] == 1

    @pytest.mark.asyncio
    async def test_manifest_endpoint_serves_same_session(self):
        streamer, scenario, _, router = build()
        resp = await streamer.stream_response(_track("vidM2"), env=FLAG_ON)
        sid = extract_session_id(resp.body)

        served = await streamer.hls.serve_manifest(sid)
        assert served is not None
        assert served.media_type == MANIFEST_CONTENT_TYPE
        # unknown session → None
        assert await streamer.hls.serve_manifest("bogus-session") is None

    @pytest.mark.asyncio
    async def test_relative_uris_resolved_to_absolute_upstream(self):
        streamer, scenario, _, router = build()
        resp = await streamer.stream_response(_track("vidM3"), env=FLAG_ON)
        sid = extract_session_id(resp.body)

        # seg2.ts نسبت به دایرکتوری manifest حل شده (آدرس مطلق upstream)
        session = streamer.hls.registry.get(sid)
        urls = [r.url for r in session.resources]
        assert all(u.startswith("https://") for u in urls)
        assert any("/seg2.ts" in u for u in urls)  # urljoin نسبت به base manifest

    @pytest.mark.asyncio
    async def test_master_playlist_variant_nested_rewrite(self):
        streamer, scenario, _, router = build()
        scenario.url = f"{MANIFEST_BASE}/master.m3u8?expire={FUTURE_EXPIRE}&sig=SECRET_M"
        # routing: master → MASTER_PLAYLIST
        router_handler = router.handler

        def handler(request: httpx.Request) -> httpx.Response:
            if "master.m3u8" in str(request.url):
                return httpx.Response(200, text=MASTER_PLAYLIST)
            return router_handler(request)

        streamer.hls._http_transport = httpx.MockTransport(handler)
        resp = await streamer.stream_response(_track("vidM4"), env=FLAG_ON)
        sid = extract_session_id(resp.body)
        # variant URI به index 0 مپ شده
        assert b"/api/stream/hls/" in resp.body and b"googlevideo" not in resp.body

        # گرفتن variant از segment endpoint → manifest بازنویسی‌شده بعدی
        variant = await streamer.hls.serve_segment(sid, 0)
        assert variant.media_type == MANIFEST_CONTENT_TYPE
        vbody = variant.body
        assert b"seg0.ts" not in vbody and b"googlevideo" not in vbody
        # segmentهای variant هم از طریق همان session قابل دریافت‌اند
        seg = await streamer.hls.serve_segment(sid, 1)
        assert (await body_of(seg)) == SEG_BYTES

    @pytest.mark.asyncio
    async def test_malformed_manifest_falls_back_to_legacy(self):
        streamer, scenario, _, router = build()

        def handler(request: httpx.Request) -> httpx.Response:
            if "hls_playlist" in str(request.url):
                return httpx.Response(200, text="random text not a playlist\n")
            return router.handler(request)

        streamer.hls._http_transport = httpx.MockTransport(handler)
        result = await streamer.stream_response(_track("vidM5"), env=FLAG_ON)
        assert result is None  # rollback path → legacy

    @pytest.mark.asyncio
    async def test_ssrf_attempt_blocked_and_no_upstream_call(self):
        streamer, scenario, _, router = build()
        evil_manifest = (
            "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:5.0,\n"
            "https://evil.example.com/seg.ts\n"
            "#EXTINF:5.0,\nhttp://169.254.169.254/latest/meta-data\n"
            "#EXT-X-ENDLIST\n"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            self_requests = str(request.url)
            assert "evil.example.com" not in self_requests
            assert "169.254" not in self_requests
            if "hls_playlist" in self_requests:
                return httpx.Response(200, text=evil_manifest)
            return router.handler(request)

        streamer.hls._http_transport = httpx.MockTransport(handler)
        result = await streamer.stream_response(_track("vidM6"), env=FLAG_ON)
        assert result is None  # unsupported → legacy rollback


def _tid(vid: str) -> str:
    return vid.ljust(11, "0")


def _track(vid: str):
    """شناسه به ۱۱ کاراکتر معتبر YouTube پد می‌شود (extractor دقیقاً ۱۱ می‌پذیرد)."""
    from app.models import Track

    vid = vid.ljust(11, "0")
    return Track(
        id=vid, title="t", artist="a", durationMs=1000,
        source="youtube", sourceUrl=f"https://www.youtube.com/watch?v={vid}",
    )


# ======================================================================
# Segment Proxy
# ======================================================================


class TestSegmentProxy:
    @pytest.mark.asyncio
    async def test_segment_relay_streams_bytes_and_content_type(self):
        streamer, _, _, _ = build()
        resp = await streamer.stream_response(_track("vidS1"), env=FLAG_ON)
        sid = extract_session_id(resp.body)

        seg = await streamer.hls.serve_segment(sid, 0)
        assert seg.status_code == 200
        assert seg.media_type == "video/mp4"
        assert (await body_of(seg)) == SEG_BYTES

    @pytest.mark.asyncio
    async def test_segment_range_forwarded_and_206_relayed(self):
        seen = {}

        streamer, _, _, router = build()
        base_handler = router.handler

        def handler(request: httpx.Request) -> httpx.Response:
            seen["range"] = request.headers.get("range")
            return base_handler(request)

        streamer.hls._http_transport = httpx.MockTransport(handler)
        resp = await streamer.stream_response(_track("vidS2"), env=FLAG_ON)
        sid = extract_session_id(resp.body)

        seg = await streamer.hls.serve_segment(sid, 0, range_header="bytes=100-199")
        assert seg.status_code == 206
        assert seg.headers.get("content-range") == "bytes 100-199/8000"
        assert seen["range"] == "bytes=100-199"
        assert (await body_of(seg)) == SEG_BYTES[100:200]

    @pytest.mark.asyncio
    async def test_sensitive_upstream_headers_never_relayed(self):
        streamer, _, _, router = build()
        base_handler = router.handler

        def handler(request: httpx.Request) -> httpx.Response:
            resp = base_handler(request)
            resp.headers["set-cookie"] = "SID=secret-session"
            resp.headers["authorization"] = "Bearer leaked"
            return resp

        streamer.hls._http_transport = httpx.MockTransport(handler)
        resp = await streamer.stream_response(_track("vidS3"), env=FLAG_ON)
        sid = extract_session_id(resp.body)
        seg = await streamer.hls.serve_segment(sid, 0)
        raw = json.dumps(dict(seg.headers)).lower()
        assert "secret-session" not in raw and "bearer" not in raw
        assert "set-cookie" not in raw and "authorization" not in raw

    @pytest.mark.asyncio
    async def test_unknown_session_or_index_returns_none(self):
        streamer, _, _, _ = build()
        resp = await streamer.stream_response(_track("vidS4"), env=FLAG_ON)
        sid = extract_session_id(resp.body)
        assert await streamer.hls.serve_segment("bogus", 0) is None
        assert await streamer.hls.serve_segment(sid, 9999) is None
        assert await streamer.hls.serve_segment(sid, -1) is None

    @pytest.mark.asyncio
    async def test_upstream_user_agent_forwarded_to_googlevideo(self):
        seen = {}
        streamer, _, _, router = build()
        base_handler = router.handler

        def handler(request: httpx.Request) -> httpx.Response:
            if "seg" in str(request.url):
                seen["ua"] = request.headers.get("user-agent")
            return base_handler(request)

        streamer.hls._http_transport = httpx.MockTransport(handler)
        resp = await streamer.stream_response(_track("vidS5"), env=FLAG_ON)
        sid = extract_session_id(resp.body)
        await streamer.hls.serve_segment(sid, 0)
        assert seen["ua"] == "ua-hls-test"  # runtime pass-through به upstream


# ======================================================================
# Expiration / Recovery (فاز ۸ reuse)
# ======================================================================


class TestHlsExpirationRecovery:
    @pytest.mark.asyncio
    async def test_manifest_403_recovery_repoints_session(self):
        streamer, scenario, _, router = build()
        attempt = {"n": 0}
        base_handler = router.handler
        scenario.kind = "rotate"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "hls_playlist" in url:
                attempt["n"] += 1
                if attempt["n"] == 1:
                    return httpx.Response(403, content=b"")
                assert "rot=2" in url  # manifest تازه از recovery
            return base_handler(request)

        streamer.hls._http_transport = httpx.MockTransport(handler)
        resp = await streamer.stream_response(_track("vidR1"), env=FLAG_ON)
        assert resp.media_type == MANIFEST_CONTENT_TYPE
        assert scenario.calls[_tid("vidR1")] == 2  # ۱ رزولوشن + ۱ recovery

    @pytest.mark.asyncio
    async def test_manifest_403_recovery_to_progressive(self):
        streamer, scenario, _, router = build()
        base_handler = router.handler
        scenario.kind = "rotate"

        def handler(request: httpx.Request) -> httpx.Response:
            if "hls_playlist" in str(request.url):
                return httpx.Response(403, content=b"")
            if "videoplayback" in str(request.url):
                return httpx.Response(200, content=SEG_BYTES)
            return base_handler(request)

        # recovery به progressive می‌رسد
        async def progressive_stream(video_id, purpose="playback", quality=None):
            return make_stream(
                video_id,
                f"https://rr1---sn-abc.googlevideo.com/videoplayback?id={video_id}&sig=P",
                stream_type="PROGRESSIVE",
            )

        scenario.resolve_stream = progressive_stream
        prog_transport = httpx.MockTransport(handler)
        streamer.hls._http_transport = prog_transport
        streamer._http_transport = prog_transport

        resp = await streamer.stream_response(_track("vidR2"), env=FLAG_ON)
        assert resp.status_code == 200  # پروکسی progressive، نه manifest
        assert resp.media_type != MANIFEST_CONTENT_TYPE

    @pytest.mark.asyncio
    async def test_persistent_403_budget_stops(self):
        streamer, scenario, _, router = build()
        scenario.kind = "rotate"

        def handler(request: httpx.Request) -> httpx.Response:
            if "hls_playlist" in str(request.url):
                return httpx.Response(403, content=b"")
            return router.handler(request)

        streamer.hls._http_transport = httpx.MockTransport(handler)

        with pytest.raises(StreamResolverError):
            await streamer.stream_response(_track("vidR3"), env=FLAG_ON)
        assert scenario.calls[_tid("vidR3")] == 2  # بودجه تمام

        # درخواست playback تازه: resolve جدید + حداکثر یک recovery — رشد خطی نه loop
        with pytest.raises(StreamResolverError):
            await streamer.stream_response(_track("vidR3"), env=FLAG_ON)
        assert scenario.calls[_tid("vidR3")] == 4  # ۲ per request، هرگز بیشتر

    @pytest.mark.asyncio
    async def test_segment_403_recovery_once_then_stop(self):
        streamer, scenario, _, router = build()
        scenario.kind = "rotate"
        # همه segmentها (حتی تازه‌ها) 403 می‌دهند؛ فقط manifest 200
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/api/stream/hls/" in url:
                return httpx.Response(403, content=b"")  # این مسیر داخلی است! نه
            return httpx.Response(403, content=b"")

        # upstream: manifest 200، همه segmentها 403
        def handler2(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if ".ts" in url:
                return httpx.Response(403, content=b"")
            if "hls_playlist" in url:
                return httpx.Response(200, text=media_playlist(MANIFEST_BASE))
            return httpx.Response(404, content=b"")

        streamer.hls._http_transport = httpx.MockTransport(handler2)
        resp = await streamer.stream_response(_track("vidR4"), env=FLAG_ON)
        sid = extract_session_id(resp.body)

        # اولین segment 403 → recovery (resolve دوم) → تلاش مجدد → باز 403 → خطا
        with pytest.raises(StreamResolverError):
            await streamer.hls.serve_segment(sid, 0)
        assert scenario.calls[_tid("vidR4")] == 2

        # segmentهای بعدی: بودجه تمام → بدون resolve جدید فوراً خطا
        with pytest.raises(StreamResolverError):
            await streamer.hls.serve_segment(sid, 1)
        with pytest.raises(StreamResolverError):
            await streamer.hls.serve_segment(sid, 2)
        assert scenario.calls[_tid("vidR4")] == 2  # بدون loop و بدون recovery سوم

    @pytest.mark.asyncio
    async def test_ten_concurrent_segment_failures_single_recovery(self):
        streamer, scenario, _, router = build()
        scenario.kind = "rotate"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if ".ts" in url:
                return httpx.Response(403, content=b"")  # همه segmentها رد می‌شوند
            if "hls_playlist" in url:
                return httpx.Response(200, text=media_playlist(MANIFEST_BASE))
            return httpx.Response(404, content=b"")

        streamer.hls._http_transport = httpx.MockTransport(handler)
        resp = await streamer.stream_response(_track("vidR5"), env=FLAG_ON)
        sid = extract_session_id(resp.body)

        results = await asyncio.gather(
            *[streamer.hls.serve_segment(sid, i, None) for i in range(10)],
            return_exceptions=True,
        )
        # هیچ recovery loop ای رخ نداده: دقیقاً ۲ resolve
        assert scenario.calls[_tid("vidR5")] == 2
        errors = [r for r in results if isinstance(r, Exception)]
        successes = [r for r in results if not isinstance(r, Exception) and r is not None]
        nones = [r for r in results if r is None]
        # indexes 3..9 خارج از mapping هستند → None؛ هیچ crash و هیچ recovery loop
        assert len(errors) + len(successes) + len(nones) == 10
        assert len(nones) == 7


# ======================================================================
# Concurrency
# ======================================================================


class TestHlsConcurrency:
    @pytest.mark.asyncio
    async def test_ten_concurrent_same_video_one_resolve_shared_session(self):
        streamer, scenario, _, router = build()
        gate = asyncio.Event()
        inner = streamer.resolver.primary

        async def gated(video_id, purpose="playback", quality=None):
            await gate.wait()
            return await inner.resolve_stream(video_id, purpose, quality)

        class Gated:
            resolve_stream = staticmethod(gated)

        streamer.resolver.primary = Gated()

        async def one():
            return await streamer.stream_response(_track("vidC1"), env=FLAG_ON)

        tasks = [asyncio.create_task(one()) for _ in range(10)]
        await asyncio.sleep(0.05)
        gate.set()
        results = await asyncio.gather(*tasks)

        assert all(r is not None and r.media_type == MANIFEST_CONTENT_TYPE for r in results)
        assert scenario.calls[_tid("vidC1")] == 1  # single-flight
        # همه همان session را دارند
        sids = {extract_session_id(r.body) for r in results}
        assert len(sids) == 1

    @pytest.mark.asyncio
    async def test_concurrent_different_videos_independent_sessions(self):
        streamer, scenario, _, router = build()
        results = await asyncio.gather(
            *[streamer.stream_response(_track(f"vidD{i}"), env=FLAG_ON) for i in range(5)]
        )
        sids = {extract_session_id(r.body) for r in results}
        assert len(sids) == 5  # sessionهای مستقل
        assert scenario.total == 5


# ======================================================================
# Registry Bounds
# ======================================================================


class TestRegistryBounds:
    @pytest.mark.asyncio
    async def test_max_sessions_lru_eviction(self):
        streamer, scenario, _, router = build()
        registry = streamer.hls.registry
        ids = []
        for i in range(70):
            resp = await streamer.stream_response(_track(f"vidE{i:02d}"), env=FLAG_ON)
            ids.append(extract_session_id(resp.body))
        # قدیمی‌ترین‌ها حذف شده‌اند
        assert registry.get(ids[0]) is None
        assert registry.get(ids[-1]) is not None
        assert len(registry._by_id) <= 64

    def test_expired_session_cleaned(self):
        registry = HlsSessionRegistry(clock=lambda: 1000.0)
        stream = make_stream("vidZ", f"{MANIFEST_BASE}?expire=1&sig=S")  # expire گذشته
        session = registry.get_or_create("vidZ", stream)
        assert registry.get(session.session_id) is None  # منقضی → پاک

    def test_session_id_is_opaque(self):
        registry = HlsSessionRegistry()
        stream = make_stream("vidY", f"{MANIFEST_BASE}?expire={FUTURE_EXPIRE}&sig=SECRET_Y")
        session = registry.get_or_create("vidY", stream)
        # session id هیچ داده upstream ندارد
        assert "sig" not in session.session_id and "SECRET" not in session.session_id
        assert len(session.session_id) >= 16


# ======================================================================
# Security
# ======================================================================


class TestHlsSecurity:
    @pytest.mark.asyncio
    async def test_no_secrets_in_logs_or_errors(self, caplog):
        streamer, scenario, _, router = build()
        scenario.kind = "fail"

        def handler(request: httpx.Request) -> httpx.Response:
            if "hls_playlist" in str(request.url):
                return httpx.Response(403, content=b"")
            return router.handler(request)

        streamer.hls._http_transport = httpx.MockTransport(handler)

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(StreamResolverError):
                await streamer.stream_response(_track("vidSec"), env=FLAG_ON)

        combined = " ".join(r.getMessage() for r in caplog.records).lower()
        for forbidden in ("googlevideo", "sig=", "secret_m", "expire=", "cookie", "visitor", "authorization"):
            assert forbidden not in combined

    @pytest.mark.asyncio
    async def test_rewritten_manifest_has_no_upstream_trace(self):
        streamer, _, _, _ = build()
        resp = await streamer.stream_response(_track("vidSec2"), env=FLAG_ON)
        raw = json.dumps(dict(resp.headers)).lower() + resp.body.decode("utf-8", "ignore").lower()
        for forbidden in ("googlevideo", "sig=", "vprv", "expire=", "secret", "visitor"):
            assert forbidden not in raw


# ======================================================================
# Progressive Regression (فاز ۱۱ دست‌نخورده)
# ======================================================================


class TestProgressiveRegression:
    @pytest.mark.asyncio
    async def test_progressive_still_proxies_with_range(self):
        streamer, scenario, _, router = build()
        scenario.kind = "progressive"

        def prog_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "videoplayback" in url:
                rng = request.headers.get("range")
                if rng:
                    return httpx.Response(206, content=b"prog", headers={"Content-Range": "bytes 0-3/8000"})
                return httpx.Response(200, content=SEG_BYTES, headers={"Content-Type": "audio/webm"})
            return router.handler(request)

        streamer._http_transport = httpx.MockTransport(prog_handler)

        async def progressive(video_id, purpose="playback", quality=None):
            return make_stream(
                video_id,
                f"https://rr1---sn-abc.googlevideo.com/videoplayback?id={video_id}&sig=P",
                stream_type="PROGRESSIVE",
                headers={"User-Agent": "ua-prog"},
            )

        scenario.resolve_stream = progressive
        resp = await streamer.stream_response(_track("vidP1"), env=FLAG_ON, range_header="bytes=0-99")
        assert resp.status_code == 206  # Range → 206 مثل قبل
        assert resp.media_type == "audio/webm"
        assert resp.headers.get("accept-ranges") == "bytes"


# ======================================================================
# Soak — ۵۰ attempt ترکیبی HLS
# ======================================================================


class TestHlsSoak:
    @pytest.mark.asyncio
    async def test_hls_soak_50_attempts(self, caplog):
        streamer, scenario, _, router = build()
        monitor = streamer.resolver.client_health

        with caplog.at_level(logging.DEBUG):
            kinds = []
            for i in range(10):
                # A: HLS موفق کامل (manifest + یک segment)
                scenario.kind = "rotate"
                r = await streamer.stream_response(_track(f"sk_ok_{i}"), env=FLAG_ON)
                assert r.media_type == MANIFEST_CONTENT_TYPE
                sid = extract_session_id(r.body)
                seg = await streamer.hls.serve_segment(sid, 0)
                assert seg is not None and seg.status_code == 200
                kinds.append("ok")

                # B: manifest failure → recovery → توقف در persistent
                def handler(request: httpx.Request) -> httpx.Response:
                    if "hls_playlist" in str(request.url):
                        return httpx.Response(403, content=b"")
                    return router.handler(request)

                streamer.hls._http_transport = httpx.MockTransport(handler)
                scenario.kind = "rotate"
                with pytest.raises(StreamResolverError):
                    await streamer.stream_response(_track(f"sk_mf_{i}"), env=FLAG_ON)
                streamer.hls._http_transport = httpx.MockTransport(router.handler)
                kinds.append("mf")

                # C: unsupported manifest → legacy rollback (None)
                def bad_handler(request: httpx.Request) -> httpx.Response:
                    if "hls_playlist" in str(request.url):
                        return httpx.Response(200, text="not a playlist\n")
                    return router.handler(request)

                streamer.hls._http_transport = httpx.MockTransport(bad_handler)
                assert await streamer.stream_response(_track(f"sk_un_{i}"), env=FLAG_ON) is None
                streamer.hls._http_transport = httpx.MockTransport(router.handler)
                kinds.append("un")

                # D: 500 → classified → exception (بدون recovery)
                scenario.kind = "fail500url"
                def f500_handler(request: httpx.Request) -> httpx.Response:
                    if ".ts" in str(request.url):
                        return httpx.Response(500, content=b"")
                    if "hls_playlist" in str(request.url):
                        return httpx.Response(200, text=media_playlist(MANIFEST_BASE))
                    return httpx.Response(404, content=b"")

                streamer.hls._http_transport = httpx.MockTransport(f500_handler)
                with pytest.raises(StreamResolverError):
                    r = await streamer.stream_response(_track(f"sk_5_{i}"), env=FLAG_ON)
                    sid5 = extract_session_id(r.body)
                    await streamer.hls.serve_segment(sid5, 0)
                streamer.hls._http_transport = httpx.MockTransport(router.handler)
                kinds.append("f500")

                # E: دو consumer هم‌زمان همان ویدیو → یک resolve
                results = await asyncio.gather(*[
                    streamer.stream_response(_track(f"sk_cc_{i}"), env=FLAG_ON) for _ in range(2)
                ])
                assert len({extract_session_id(r.body) for r in results}) == 1
                kinds.append("cc")

        assert len(kinds) == 50
        # bounds
        assert len(streamer.hls.registry._by_id) <= 64
        pending = [t for t in asyncio.all_tasks() if not t.done()]
        assert len(pending) <= 1
        assert streamer._inflight == {}
        # security در کل soak
        combined = " ".join(r.getMessage() for r in caplog.records).lower()
        for forbidden in ("googlevideo", "sig=", "secret", "expire=", "cookie", "visitor"):
            assert forbidden not in combined


# ======================================================================
# Phase 15 — Soak ۱۰۰ attemptی (Progressive/HLS/Legacy/recovery/seek mix)
# ======================================================================


class TestPhase15Soak100:
    @pytest.mark.asyncio
    async def test_soak_100_mixed_attempts(self, caplog):
        """۱۰۰ attempt ترکیبی: HLS(success/recovery/failure) + Progressive + seek simulation."""
        streamer, scenario, _, router = build()
        monitor = streamer.resolver.client_health

        # transport همه‌کاره: OLD→403، .ts→200، FORCE500→500، videoplayback→200
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "FORCE500" in url:
                return httpx.Response(500, content=b"")
            if "OLD" in url:
                return httpx.Response(403, content=b"")
            if "FRESH" in url:
                return httpx.Response(200, content=SEG_BYTES, headers={"Content-Type": "audio/webm"})
            if ".ts" in url:
                return httpx.Response(200, content=SEG_BYTES)
            if "hls_playlist" in url:
                return httpx.Response(200, text=media_playlist(MANIFEST_BASE))
            if "videoplayback" in url:
                return httpx.Response(200, content=SEG_BYTES, headers={"Content-Type": "audio/webm"})
            return httpx.Response(404, content=b"")

        streamer.hls._http_transport = httpx.MockTransport(handler)
        streamer._http_transport = httpx.MockTransport(handler)

        with caplog.at_level(logging.DEBUG):
            for i in range(25):
                # 1) HLS کامل + seek simulation (سه segment پشت‌سرهم مثل seek)
                scenario.kind = "rotate"
                r = await streamer.stream_response(_track(f"s15_hls_{i:02d}"), env=FLAG_ON)
                assert r.media_type == MANIFEST_CONTENT_TYPE
                sid = extract_session_id(r.body)
                for idx in (0, 1, 2):  # seek simulation: segmentهای مختلف
                    seg = await streamer.hls.serve_segment(sid, idx)
                    assert seg is not None and seg.status_code == 200

                # 2) Progressive با runtime 403 → recovery → استریم تازه
                scenario.kind = "progfail"
                r = await streamer.stream_response(_track(f"s15_rec_{i:02d}"), env=FLAG_ON)
                assert r.status_code == 200
                assert scenario.calls[_tid(f"s15_rec_{i:02d}")] == 2

                # 3) Progressive کامل (regression واقعی هر iteration)
                scenario.kind = "progressive"
                r = await streamer.stream_response(
                    _track(f"s15_prog_{i:02d}"), env=FLAG_ON, range_header="bytes=0-99"
                )
                assert r.status_code in (200, 206)
                assert r.media_type == "audio/webm"

                # 4) 500 upstream → classified (بدون recovery)
                scenario.kind = "f500"
                with pytest.raises(StreamResolverError):
                    await streamer.stream_response(_track(f"s15_f5_{i:02d}"), env=FLAG_ON)
                assert scenario.calls[_tid(f"s15_f5_{i:02d}")] == 1

        # --- ادعاهای نهایی ---
        # resolve: 25×(1 hls + 2 recovery + 1 progressive + 1 f500) = 125
        assert scenario.total == 125
        # sessions bounded
        assert len(streamer.hls.registry._by_id) <= 64
        # task leak
        pending = [t for t in asyncio.all_tasks() if not t.done()]
        assert len(pending) <= 1
        assert streamer._inflight == {}
        # امنیت در کل soak
        combined = " ".join(r.getMessage() for r in caplog.records).lower()
        for forbidden in ("googlevideo", "sig=", "secret", "expire=", "cookie", "visitor", "authorization"):
            assert forbidden not in combined
        # health محدود
        assert monitor.snapshot()["entry_count"] <= 64

    @pytest.mark.asyncio
    async def test_concurrent_ten_users_hls_same_and_different(self):
        """۱۰ کاربر هم‌ویدیو → یک resolve/session؛ ۱۰ ویدیو مختلف → مستقل."""
        streamer, scenario, _, router = build()

        # هم‌ویدیو
        gate = asyncio.Event()
        inner = streamer.resolver.primary

        async def gated(video_id, purpose="playback", quality=None):
            await gate.wait()
            return await inner.resolve_stream(video_id, purpose, quality)

        class Gated:
            resolve_stream = staticmethod(gated)

        streamer.resolver.primary = Gated()
        tasks = [asyncio.create_task(streamer.stream_response(_track("ccHLS"), env=FLAG_ON)) for _ in range(10)]
        await asyncio.sleep(0.05)
        gate.set()
        results = await asyncio.gather(*tasks)
        assert all(r.media_type == MANIFEST_CONTENT_TYPE for r in results)
        assert len({extract_session_id(r.body) for r in results}) == 1  # session مشترک
        assert scenario.calls[_tid("ccHLS")] == 1  # بدون duplicate resolve

        # ویدیوهای مختلف
        results2 = await asyncio.gather(*[
            streamer.stream_response(_track(f"ccD{i:02d}"), env=FLAG_ON) for i in range(10)
        ])
        assert len({extract_session_id(r.body) for r in results2}) == 10  # بدون قاطی شدن
        # segmentهای هر session مستقل‌اند
        sid0 = extract_session_id(results2[0].body)
        seg = await streamer.hls.serve_segment(sid0, 0)
        assert seg.status_code == 200
