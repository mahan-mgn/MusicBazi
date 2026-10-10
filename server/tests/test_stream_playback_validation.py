"""
اعتبارسنجی عملی و یکپارچگی سناریوهای واقعی پخش صوتی پس از ممیزی فازهای ۱ تا ۳.
پوشش ۸ سناریوی خواسته شده:
1. پخش آهنگ از طریق InnerTubeX.
2. ادامه پخش در جریان چانک‌های متوالی (Sustained Continuous Playback).
3. Seek به ابتدا، میانه و انتهای آهنگ.
4. دریافت و پاسخ‌دهی دقیق به درخواست‌های HTTP Range (کدهای 206، Content-Range و تطابق بایت‌ها).
5. تداوم پخش Progressive Audio هنگام تغییر تنظیمات نشست (on_session_changed).
6. ادامه دریافت سگمنت‌های HLS برای نشست‌های فعال پس از تغییر کوکی (عدم بروز خطای 404).
7. امکان Resolve مجدد آهنگی که قبلاً خطای قطعی خورده بود پس از تغییر/بارگذاری کوکی جدید.
8. رفتار سیستم هنگام در دسترس نبودن موقت Bridge و عملکرد صحیح Fallback به yt-dlp.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models import Track
from app.stream.errors import (
    AllResolversFailedError,
    BridgeUnavailableError,
    ClientRejectedError,
    PermanentlyUnplayableError,
)
from app.stream.feature_flags import STREAM_V2_FLAG
from app.stream.models import ResolvedStream
from app.stream.playback import (
    DEFAULT_BOUNDED_CHUNK_SIZE,
    LivePlaybackStreamer,
    get_live_playback,
)
from app.stream.resolver import UnplayableCache, YouTubeStreamResolver

FLAG_ON = {STREAM_V2_FLAG: "1"}


def make_sample_stream(video_id: str = "dQw4w9WgXcQ", total_length: int = 2_000_000, **overrides) -> ResolvedStream:
    defaults = dict(
        source="youtube",
        url=f"https://rr1---sn-test.googlevideo.com/videoplayback?id={video_id}&clen={total_length}",
        mime_type="audio/webm",
        codec="opus",
        bitrate=160000,
        sample_rate=48000,
        channels=2,
        content_length=total_length,
        expires_at=int(time.time()) + 3600,
        headers={"User-Agent": "test-agent"},
        resolver_metadata={"client_name": "VISIONOS", "resolver": "innertubex", "profile_id": "VISIONOS_0_1__nopo"},
    )
    defaults.update(overrides)
    return ResolvedStream(video_id=video_id, **defaults)


def sample_track(track_id: str = "dQw4w9WgXcQ") -> Track:
    return Track(
        id=track_id,
        title="Sample Track",
        artist="Sample Artist",
        durationMs=213000,
        source="youtube",  # type: ignore[arg-type]
        sourceUrl=f"https://www.youtube.com/watch?v={track_id}",
    )


# ======================================================================
# سناریوهای ۱ و ۲: استخراج و پخش پیوسته
# ======================================================================


class TestPlaybackFlow:
    @pytest.mark.asyncio
    async def test_1_playback_via_innertubex(self):
        """سناریو ۱: استخراج و پخش موفق یک آهنگ از طریق InnerTubeX."""
        total_size = 100_000
        ref_data = bytes(i % 255 for i in range(total_size))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=ref_data)

        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        mock_resolver.resolve.return_value = make_sample_stream(total_length=total_size)

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        response = await streamer.stream_response(sample_track(), env=FLAG_ON)
        assert response is not None
        assert response.status_code == 200
        assert response.media_type == "audio/webm"
        body = b"".join([c async for c in response.body_iterator])
        assert len(body) == total_size
        assert body == ref_data
        mock_resolver.resolve.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_2_sustained_continuous_playback_multiple_chunks(self):
        """سناریو ۲: ادامه پخش در جریان چانک‌های متوالی با تاخیر شبیه‌سازی‌شده (پخش پیوسته بدون قطعی)."""
        total_size = 1_500_000  # حدود ۳ چانک ۵۱۲ کیلوبایتی
        ref_data = bytes((i * 7) % 256 for i in range(total_size))
        chunks_requested = []

        def handler(request: httpx.Request) -> httpx.Response:
            range_hdr = request.headers.get("range", "")
            chunks_requested.append(range_hdr)
            spec = range_hdr.replace("bytes=", "").split("-")
            start = int(spec[0])
            end = int(spec[1])
            chunk = ref_data[start : end + 1]
            return httpx.Response(
                206,
                content=chunk,
                headers={"Content-Range": f"bytes {start}-{end}/{total_size}"},
            )

        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        mock_resolver.resolve.return_value = make_sample_stream(total_length=total_size)

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        response = await streamer.stream_response(sample_track(), range_header=None, env=FLAG_ON)
        assert response is not None
        assert response.status_code == 200

        # خواندن تدریجی داده‌ها با تاخیر کوتاه برای شبیه‌سازی پخش در زمان
        received_bytes = bytearray()
        async for chunk in response.body_iterator:
            received_bytes.extend(chunk)
            await asyncio.sleep(0.001)

        assert len(received_bytes) == total_size
        assert bytes(received_bytes) == ref_data
        assert len(chunks_requested) >= 3


# ======================================================================
# سناریوهای ۳ و ۴: عملیات Seek و درخواست‌های HTTP Range
# ======================================================================


class TestSeekAndRange:
    @pytest.mark.asyncio
    async def test_3_seek_to_start_mid_end(self):
        """سناریو ۳: اعتبارسنجی عملیات Seek به ابتدا، میانه و انتهای آهنگ."""
        total_size = 2_000_000
        ref_data = bytes(i % 251 for i in range(total_size))

        def handler(request: httpx.Request) -> httpx.Response:
            range_hdr = request.headers.get("range", "")
            spec = range_hdr.replace("bytes=", "").split("-")
            start = int(spec[0])
            end = int(spec[1])
            chunk = ref_data[start : end + 1]
            return httpx.Response(
                206,
                content=chunk,
                headers={"Content-Range": f"bytes {start}-{end}/{total_size}"},
            )

        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        mock_resolver.resolve.return_value = make_sample_stream(total_length=total_size)

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        # ۱. ابتدا
        resp_start = await streamer.stream_response(sample_track(), range_header="bytes=0-4095", env=FLAG_ON)
        data_start = b"".join([c async for c in resp_start.body_iterator])
        assert data_start == ref_data[0:4096]

        # ۲. میانه
        resp_mid = await streamer.stream_response(sample_track(), range_header="bytes=1000000-1004095", env=FLAG_ON)
        data_mid = b"".join([c async for c in resp_mid.body_iterator])
        assert data_mid == ref_data[1000000:1004096]

        # ۳. انتها
        resp_end = await streamer.stream_response(sample_track(), range_header="bytes=1990000-1999999", env=FLAG_ON)
        data_end = b"".join([c async for c in resp_end.body_iterator])
        assert data_end == ref_data[1990000:2000000]

    @pytest.mark.asyncio
    async def test_4_exact_http_range_headers_and_status(self):
        """سناریو ۴: اعتبارسنجی وضعیت HTTP 206، هدرهای Content-Range، Content-Length و Accept-Ranges."""
        total_size = 500_000
        ref_data = bytes(i % 127 for i in range(total_size))

        def handler(request: httpx.Request) -> httpx.Response:
            range_hdr = request.headers.get("range", "")
            spec = range_hdr.replace("bytes=", "").split("-")
            start = int(spec[0])
            end = int(spec[1])
            chunk = ref_data[start : end + 1]
            return httpx.Response(
                206,
                content=chunk,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(len(chunk)),
                    "Accept-Ranges": "bytes",
                },
            )

        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        mock_resolver.resolve.return_value = make_sample_stream(total_length=total_size)

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        response = await streamer.stream_response(sample_track(), range_header="bytes=100-199", env=FLAG_ON)
        assert response.status_code == 206
        assert response.headers["content-range"] == f"bytes 100-199/{total_size}"
        assert response.headers["content-length"] == "100"
        assert response.headers["accept-ranges"] == "bytes"
        data = b"".join([c async for c in response.body_iterator])
        assert data == ref_data[100:200]


# ======================================================================
# سناریوهای ۵ و ۶: تداوم پخش هنگام تغییر نشست
# ======================================================================


class TestPlaybackDuringSessionChange:
    @pytest.mark.asyncio
    async def test_5_progressive_playback_continues_during_session_change(self):
        """سناریو ۵: تداوم پخش استریم Progressive هنگام فراخوانی on_session_changed در میانه استریم."""
        from unittest.mock import MagicMock

        total_size = 800_000
        ref_data = bytes(i % 256 for i in range(total_size))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=ref_data)

        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        mock_resolver.on_session_changed = MagicMock()
        mock_resolver.resolve.return_value = make_sample_stream(total_length=total_size)

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        response = await streamer.stream_response(sample_track(), range_header=None, env=FLAG_ON)
        assert response is not None
        assert response.status_code == 200

        read_bytes = bytearray()
        iterator = response.body_iterator.__aiter__()

        # خواندن چانک اول
        chunk1 = await iterator.__anext__()
        read_bytes.extend(chunk1)

        # تغییر نشست در میانه پخش فعال (مانند آپلود کوکی توسط کاربر)
        streamer.on_session_changed()

        # خواندن باقیمانده چانک‌ها تا پایان
        try:
            while True:
                chunk = await iterator.__anext__()
                read_bytes.extend(chunk)
        except StopAsyncIteration:
            pass

        assert len(read_bytes) == total_size
        assert bytes(read_bytes) == ref_data

    @pytest.mark.asyncio
    async def test_6_hls_active_session_segments_continue_after_cookie_change(self):
        """سناریو ۶: ادامه دریافت سگمنت‌های HLS برای نشست‌های فعال پس از تغییر کوکی (عدم بروز ۴۰۴)."""
        from unittest.mock import MagicMock

        video_id = "hls_vid_123"
        base_hls = "https://rr1---sn-test.googlevideo.com/api/manifest/hls"
        hls_stream = make_sample_stream(
            video_id=video_id,
            stream_type="HLS",
            url=f"{base_hls}/live.m3u8?expire=1999999999",
            mime_type="application/x-mpegURL",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "live.m3u8" in url_str:
                m3u8_text = (
                    "#EXTM3U\n"
                    "#EXTINF:10.0,\n"
                    f"{base_hls}/seg0.ts\n"
                    "#EXTINF:10.0,\n"
                    f"{base_hls}/seg1.ts\n"
                )
                return httpx.Response(200, content=m3u8_text.encode("utf-8"))
            if "seg0.ts" in url_str or "seg1.ts" in url_str:
                return httpx.Response(200, content=b"fake-ts-segment-data")
            return httpx.Response(404)

        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        mock_resolver.on_session_changed = MagicMock()

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        # ایجاد نشست فعال HLS
        session = streamer.hls.registry.get_or_create(video_id, hls_stream)
        # بارگذاری مانیفست
        manifest = await streamer.hls.load_manifest(session)
        assert b"/api/stream/hls/" in manifest

        # سگمنت اول دریافت می‌شود
        seg0 = await streamer.hls.serve_segment(session.session_id, index=0)
        assert seg0 is not None
        assert seg0.status_code == 200

        # تغییر کوکی و نشست حین پخش
        streamer.on_session_changed()

        # سگمنت دوم از همان نشست فعال دریافت می‌شود؛ نباید ۴۰۴ بدهد
        seg1 = await streamer.hls.serve_segment(session.session_id, index=1)
        assert seg1 is not None
        assert seg1.status_code == 200


# ======================================================================
# سناریوهای ۷ و ۸: ریکاوری کش و فال‌بک
# ======================================================================


class TestRecoveryAndFallback:
    @pytest.mark.asyncio
    async def test_7_unplayable_cached_track_reresolves_after_cookie_update(self):
        """سناریو ۷: امکان Resolve مجدد آهنگی که قبلاً خطای قطعی کش شده بود پس از بارگذاری کوکی جدید."""
        cache = UnplayableCache(ttl_seconds=600.0)
        mock_primary = AsyncMock()
        mock_fallback = AsyncMock()

        # ابتدا ترک به دلیل محدودیت سنی رد می‌شود
        mock_primary.resolve_stream.side_effect = ClientRejectedError(
            "This video is age restricted", code="AGE_RESTRICTED", video_id="age_vid"
        )
        mock_fallback.resolve_stream.side_effect = ClientRejectedError(
            "Sign in required", code="CLIENT_REJECTED", video_id="age_vid"
        )

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_primary,
            fallback_resolver=mock_fallback,
            unplayable_cache=cache,
        )

        # درخواست ۱: شکست و ثبت در کش قطعی
        with pytest.raises(AllResolversFailedError):
            await resolver.resolve("age_vid")

        # درخواست ۲: برخورد با کش Anti-Storm
        with pytest.raises(PermanentlyUnplayableError):
            await resolver.resolve("age_vid")

        assert mock_primary.resolve_stream.await_count == 1

        # رویداد آپلود کوکی و تغییر نشست
        mock_primary.notify_session_changed = AsyncMock(return_value=True)
        resolver.on_session_changed()

        # درخواست ۳: کش پاک شده و استخراج با کوکی جدید موفق می‌شود
        mock_primary.resolve_stream.side_effect = None
        mock_primary.resolve_stream.return_value = make_sample_stream("age_vid")

        stream = await resolver.resolve("age_vid")
        assert stream.video_id == "age_vid"
        assert mock_primary.resolve_stream.await_count == 2

    @pytest.mark.asyncio
    async def test_8_bridge_temporary_unavailable_falls_back_to_ytdlp(self):
        """سناریو ۸: هنگام در دسترس نبودن موقت Bridge، سیستم بدون شکست به yt-dlp سوئیچ می‌کند."""
        mock_primary = AsyncMock()
        mock_fallback = AsyncMock()

        # شبیه‌سازی در دسترس نبودن Bridge
        mock_primary.resolve_stream.side_effect = BridgeUnavailableError(
            "Connection refused on 127.0.0.1:8765", video_id="vid_fallback"
        )
        # yt-dlp با موفقیت استریم را رزولو می‌کند
        ytdlp_stream = make_sample_stream(
            video_id="vid_fallback",
            resolver_metadata={"resolver": "yt-dlp", "format_id": "251"},
        )
        mock_fallback.resolve_stream.return_value = ytdlp_stream

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_primary,
            fallback_resolver=mock_fallback,
        )

        stream = await resolver.resolve("vid_fallback")
        assert stream.video_id == "vid_fallback"
        assert stream.resolver_metadata["resolver"] == "yt-dlp"
        assert mock_primary.resolve_stream.await_count == 1
        assert mock_fallback.resolve_stream.await_count == 1
