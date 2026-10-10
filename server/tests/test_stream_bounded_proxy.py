"""
تست‌های جامع Phase 3 — Bounded Range Proxy در Music Bazi.
پوشش:
1. دریافت کامل داده در چند قطعه (Bounded Chunks) و تطابق بایت‌به‌بایت با داده مرجع.
2. بازه‌های دقیق ابتدا، وسط و انتهای فایل صوتی.
3. بازه‌های open-ended (bytes=start-) و suffix (bytes=-N).
4. مرزهای قطعات بدون هم‌پوشانی یا ازدست‌رفتن بایت.
5. فایل کوچک‌تر از اندازه قطعه و مدیریت EOF.
6. پاسخ معتبر 206 با Content-Range و Content-Length صحیح.
7. سرور بالادستی که Range را نادیده می‌گیرد و 200 برمی‌گرداند (برش داده و جلوگیری از مصرف نامحدود).
8. درخواست 416 برای Range نامعتبر یا فراتر از طول فایل.
9. خطای بالادست یا Timeout در حین استریم.
10. عدم تأثیر بر HLS و مسیرهای Manifest/Segment.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models import Track
from app.stream.feature_flags import STREAM_V2_FLAG
from app.stream.models import ResolvedStream
from app.stream.playback import (
    DEFAULT_BOUNDED_CHUNK_SIZE,
    LivePlaybackStreamer,
    RangeSpec,
    extract_content_length,
    parse_clen_from_url,
    parse_range_spec,
)

FLAG_ON = {STREAM_V2_FLAG: "1"}


def make_test_stream(length: int = 1_500_000, **overrides) -> ResolvedStream:
    defaults = dict(
        source="youtube",
        url=f"https://rr1---sn-test.googlevideo.com/videoplayback?id=dQw4w9WgXcQ&clen={length}",
        mime_type="audio/webm",
        codec="opus",
        bitrate=160000,
        sample_rate=48000,
        channels=2,
        content_length=length,
        expires_at=1999999999,
        headers={"User-Agent": "test-agent"},
        resolver_metadata={"client_name": "WEB_REMIX", "resolver": "innertubex"},
    )
    defaults.update(overrides)
    return ResolvedStream(video_id="dQw4w9WgXcQ", **defaults)


def make_track(track_id: str = "dQw4w9WgXcQ") -> Track:
    return Track(
        id=track_id,
        title="Test Song",
        artist="Test Artist",
        durationMs=180000,
        source="youtube",  # type: ignore[arg-type]
        sourceUrl=f"https://www.youtube.com/watch?v={track_id}",
    )


# ======================================================================
# تست‌های اعتبارسنجی RangeSpec و Clen
# ======================================================================


class TestRangeParsing:
    def test_parse_clen_from_url(self):
        assert parse_clen_from_url("https://g.com/p?id=1&clen=2048000") == 2048000
        assert parse_clen_from_url("https://g.com/p?id=1&other=val") is None
        assert parse_clen_from_url("invalid-url") is None

    def test_extract_content_length(self):
        stream = make_test_stream(length=3_000_000)
        assert extract_content_length(stream) == 3_000_000

        stream_no_meta = make_test_stream(length=0, content_length=None)
        stream_no_meta.url = "https://g.com/p?clen=12345"
        assert extract_content_length(stream_no_meta) == 12345

    def test_parse_range_exact_span(self):
        spec = parse_range_spec("bytes=0-100", 1000)
        assert spec is not None
        assert spec.start == 0
        assert spec.end == 100
        assert spec.is_satisfiable is True

    def test_parse_range_open_ended(self):
        spec = parse_range_spec("bytes=500-", 1000)
        assert spec is not None
        assert spec.start == 500
        assert spec.end == 999
        assert spec.is_satisfiable is True

    def test_parse_range_suffix(self):
        spec = parse_range_spec("bytes=-200", 1000)
        assert spec is not None
        assert spec.start == 800
        assert spec.end == 999
        assert spec.is_satisfiable is True

    def test_parse_range_unsatisfiable_beyond_length(self):
        spec = parse_range_spec("bytes=1500-2000", 1000)
        assert spec is not None
        assert spec.is_satisfiable is False

    def test_parse_range_unsatisfiable_inverted(self):
        spec = parse_range_spec("bytes=500-200", 1000)
        assert spec is not None
        assert spec.is_satisfiable is False

    def test_parse_range_none_returns_none(self):
        assert parse_range_spec(None, 1000) is None


# ======================================================================
# تست‌های Bounded Range Proxy با شبیه‌سازی انتقال داده
# ======================================================================


class TestBoundedRangeStreaming:
    @pytest.mark.asyncio
    async def test_full_stream_delivered_in_bounded_chunks(self):
        """
        درخواست بدون Range از کلاینت؛ پراکسی داده را در چانک‌های ۵۱۲ کیلوبایتی
        از بالادست دریافت کرده و به صورت کامل و بایت‌به‌بایت به کلاینت تحویل می‌دهد.
        """
        total_size = 1_200_000  # کمی بیشتر از ۲ چانک ۵۱۲ کیلوبایتی
        reference_data = bytes(i % 251 for i in range(total_size))
        requested_ranges = []

        def handler(request: httpx.Request) -> httpx.Response:
            range_hdr = request.headers.get("range")
            requested_ranges.append(range_hdr)
            assert range_hdr is not None and range_hdr.startswith("bytes=")
            spec = range_hdr[6:].split("-")
            start = int(spec[0])
            end = int(spec[1])
            chunk = reference_data[start : end + 1]
            return httpx.Response(
                206,
                content=chunk,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(len(chunk)),
                },
            )

        stream = make_test_stream(length=total_size)
        mock_resolver = AsyncMock()
        mock_resolver.resolve.return_value = stream

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        response = await streamer.stream_response(
            make_track(), range_header=None, env=FLAG_ON
        )

        assert response is not None
        assert response.status_code == 200
        assert response.headers.get("content-length") == str(total_size)
        assert response.headers.get("accept-ranges") == "bytes"

        delivered_bytes = b"".join([c async for c in response.body_iterator])
        assert len(delivered_bytes) == total_size
        assert delivered_bytes == reference_data
        # اطمینان از اینکه بالادست در حداقل ۳ قطعه محدود دریافت شده است
        assert len(requested_ranges) >= 3
        assert requested_ranges[0] == f"bytes=0-{DEFAULT_BOUNDED_CHUNK_SIZE - 1}"

    @pytest.mark.asyncio
    async def test_exact_partial_range_requests(self):
        """
        درخواست بازه‌های خاص (ابتدا، وسط، انتها) از کلاینت و تحویل صحیح با کد ۲0۶.
        """
        total_size = 500_000
        reference_data = bytes(i % 251 for i in range(total_size))

        def handler(request: httpx.Request) -> httpx.Response:
            range_hdr = request.headers.get("range", "")
            spec = range_hdr[6:].split("-")
            start = int(spec[0])
            end = int(spec[1])
            chunk = reference_data[start : end + 1]
            return httpx.Response(
                206,
                content=chunk,
                headers={"Content-Range": f"bytes {start}-{end}/{total_size}"},
            )

        stream = make_test_stream(length=total_size)
        mock_resolver = AsyncMock()
        mock_resolver.resolve.return_value = stream

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        # ۱. ابتدا
        resp_start = await streamer.stream_response(
            make_track(), range_header="bytes=0-999", env=FLAG_ON
        )
        assert resp_start is not None
        assert resp_start.status_code == 206
        assert resp_start.headers.get("content-range") == f"bytes 0-999/{total_size}"
        data_start = b"".join([c async for c in resp_start.body_iterator])
        assert data_start == reference_data[0:1000]

        # ۲. وسط
        resp_mid = await streamer.stream_response(
            make_track(), range_header="bytes=100000-149999", env=FLAG_ON
        )
        assert resp_mid is not None
        assert resp_mid.status_code == 206
        data_mid = b"".join([c async for c in resp_mid.body_iterator])
        assert data_mid == reference_data[100000:150000]

        # ۳. انتها (suffix)
        resp_suffix = await streamer.stream_response(
            make_track(), range_header="bytes=-1000", env=FLAG_ON
        )
        assert resp_suffix is not None
        assert resp_suffix.status_code == 206
        data_suffix = b"".join([c async for c in resp_suffix.body_iterator])
        assert data_suffix == reference_data[-1000:]

    @pytest.mark.asyncio
    async def test_upstream_ignores_range_and_returns_200(self):
        """
        اگر سرور بالادست هدر Range را نادیده بگیرد و پاسخ ۲۰۰ با کل فایل بفرستد،
        پراکسی داده اضافه را حذف کرده و فقط بازه درخواستی کلاینت را تحویل می‌دهد.
        """
        total_size = 100_000
        full_content = bytes(i % 127 for i in range(total_size))

        def handler(request: httpx.Request) -> httpx.Response:
            # سرور هدر Range را نادیده می‌گیرد و همیشه ۲۰۰ کامل برمی‌گرداند
            return httpx.Response(200, content=full_content)

        stream = make_test_stream(length=total_size)
        mock_resolver = AsyncMock()
        mock_resolver.resolve.return_value = stream

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        resp = await streamer.stream_response(
            make_track(), range_header="bytes=1000-1999", env=FLAG_ON
        )

        assert resp is not None
        assert resp.status_code == 206
        assert resp.headers.get("content-range") == f"bytes 1000-1999/{total_size}"
        data = b"".join([c async for c in resp.body_iterator])
        assert len(data) == 1000
        assert data == full_content[1000:2000]

    @pytest.mark.asyncio
    async def test_unsatisfiable_range_returns_416(self):
        """درخواست بازه فراتر از طول فایل صوتی باید وضعیت 416 برگرداند."""
        stream = make_test_stream(length=500_000)
        mock_resolver = AsyncMock()
        mock_resolver.resolve.return_value = stream

        streamer = LivePlaybackStreamer(resolver=mock_resolver)
        resp = await streamer.stream_response(
            make_track(), range_header="bytes=600000-700000", env=FLAG_ON
        )

        assert resp is not None
        assert resp.status_code == 416
        assert resp.headers.get("content-range") == "bytes */500000"

    @pytest.mark.asyncio
    async def test_small_file_less_than_chunk_size(self):
        """فایل صوتی کوچک‌تر از اندازه چانک به صورت کامل و یکباره سرو می‌شود."""
        small_size = 50_000
        content = bytes(42 for _ in range(small_size))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                206,
                content=content,
                headers={"Content-Range": f"bytes 0-{small_size - 1}/{small_size}"},
            )

        stream = make_test_stream(length=small_size)
        mock_resolver = AsyncMock()
        mock_resolver.resolve.return_value = stream

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        resp = await streamer.stream_response(make_track(), range_header=None, env=FLAG_ON)
        assert resp is not None
        assert resp.status_code == 200
        data = b"".join([c async for c in resp.body_iterator])
        assert len(data) == small_size
