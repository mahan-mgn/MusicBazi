"""
تست‌های واحد پایتون برای InnerTubeXResolver و YouTubeStreamResolver.
کاملاً ایزوله با Mock Transport بدون وابستگی به شبکه خارجی.
"""

from __future__ import annotations

import httpx
import pytest

from app.stream import (
    BridgeTimeoutError,
    BridgeUnavailableError,
    CipherError,
    ClientRejectedError,
    InnerTubeXResolver,
    InvalidResponseError,
    NoStreamError,
    POTokenError,
    ResolvedStream,
    YouTubeStreamResolver,
)


@pytest.fixture
def sample_bridge_stream_payload():
    return {
        "ok": True,
        "request_id": "req-123",
        "resolver": "innertubex",
        "stream": {
            "source": "youtube",
            "video_id": "dQw4w9WgXcQ",
            "url": "https://rr1---sn-abc.googlevideo.com/videoplayback?id=123&expire=1795000000",
            "mime_type": "audio/webm",
            "codec": "opus",
            "bitrate": 160000,
            "sample_rate": 48000,
            "channels": 2,
            "content_length": 3400000,
            "expires_at": 1795000000,
            "duration": 212.0,
            "headers": {"User-Agent": "Mozilla/5.0"},
            "requires_range": False,
            "resolver_metadata": {"client_name": "WEB_REMIX", "profile_id": "WEB_REMIX", "itag": "251"},
            "is_lossless": False,
            "bit_depth": None,
            "loudness_db": -7.5,
            "stream_type": "PROGRESSIVE",
        },
    }


class TestInnerTubeXResolver:
    @pytest.mark.asyncio
    async def test_successful_resolution(self, sample_bridge_stream_payload):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/resolve"
            return httpx.Response(200, json=sample_bridge_stream_payload)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        stream = await resolver.resolve_stream("dQw4w9WgXcQ", purpose="playback")

        assert isinstance(stream, ResolvedStream)
        assert stream.video_id == "dQw4w9WgXcQ"
        assert stream.source == "youtube"
        assert stream.bitrate == 160000
        assert stream.codec == "opus"
        assert stream.duration == 212.0
        assert stream.expires_at == 1795000000
        assert stream.stream_type == "PROGRESSIVE"
        assert stream.resolver_metadata["client_name"] == "WEB_REMIX"

    @pytest.mark.asyncio
    async def test_health_check_ready(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/health"
            return httpx.Response(200, json={"ok": True, "service": "musicbazi-innertubex", "ready": True})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        ready = await resolver.is_ready()
        assert ready is True

    @pytest.mark.asyncio
    async def test_health_check_not_ready(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        ready = await resolver.is_ready()
        assert ready is False

    @pytest.mark.asyncio
    async def test_connection_refused_maps_to_bridge_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        with pytest.raises(BridgeUnavailableError) as exc_info:
            await resolver.resolve_stream("dQw4w9WgXcQ")

        assert exc_info.value.retryable is True
        assert exc_info.value.video_id == "dQw4w9WgXcQ"

    @pytest.mark.asyncio
    async def test_timeout_maps_to_bridge_timeout(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        with pytest.raises(BridgeTimeoutError) as exc_info:
            await resolver.resolve_stream("dQw4w9WgXcQ")

        assert exc_info.value.retryable is True
        assert exc_info.value.code == "TIMEOUT"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bridge_code,expected_exc",
        [
            ("NO_STREAM", NoStreamError),
            ("UNAVAILABLE", NoStreamError),
            ("CLIENT_REJECTED", ClientRejectedError),
            ("AGE_RESTRICTED", ClientRejectedError),
            ("CIPHER_ERROR", CipherError),
            ("PO_TOKEN_ERROR", POTokenError),
        ],
    )
    async def test_typed_error_mapping(self, bridge_code, expected_exc):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={
                    "ok": False,
                    "error": {
                        "code": bridge_code,
                        "message": f"InnerTubeX failed with {bridge_code}",
                        "retryable": False,
                    },
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        with pytest.raises(expected_exc) as exc_info:
            await resolver.resolve_stream("sample_vid")

        assert exc_info.value.video_id == "sample_vid"
        assert exc_info.value.code == bridge_code

    @pytest.mark.asyncio
    async def test_invalid_json_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="Not a JSON body")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        with pytest.raises(InvalidResponseError):
            await resolver.resolve_stream("vid_1")

    @pytest.mark.asyncio
    async def test_refresh_visitor_data_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/visitor/refresh"
            return httpx.Response(200, json={"ok": True, "refreshed": True})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        success = await resolver.refresh_visitor_data()
        assert success is True

    @pytest.mark.asyncio
    async def test_refresh_visitor_data_failure_on_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Error")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        success = await resolver.refresh_visitor_data()
        assert success is False

    @pytest.mark.asyncio
    async def test_resolve_stream_passes_refresh_visitor_flag(self, sample_bridge_stream_payload):
        captured_payload = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json
            nonlocal captured_payload
            captured_payload = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json=sample_bridge_stream_payload)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        await resolver.resolve_stream("dQw4w9WgXcQ", refresh_visitor=True)
        assert captured_payload.get("refresh_visitor") is True

    @pytest.mark.asyncio
    async def test_report_refusal_success(self):
        captured_payload = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json
            nonlocal captured_payload
            assert request.url.path == "/refuse"
            captured_payload = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"ok": True, "handled": True})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        ok = await resolver.report_refusal(
            video_id="vid_123",
            status_code=403,
            client_name="WEB_REMIX",
            profile_id="WEB_REMIX__po",
            url="https://googlevideo.com/playback",
        )
        assert ok is True
        assert captured_payload["video_id"] == "vid_123"
        assert captured_payload["status_code"] == 403
        assert captured_payload["client_name"] == "WEB_REMIX"
        assert captured_payload["profile_id"] == "WEB_REMIX__po"

    @pytest.mark.asyncio
    async def test_report_refusal_empty_video_id(self):
        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765")
        ok = await resolver.report_refusal(video_id="", status_code=403)
        assert ok is False



    @pytest.mark.asyncio
    async def test_missing_stream_field(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True, "stream": None})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        with pytest.raises(InvalidResponseError):
            await resolver.resolve_stream("vid_2")

    @pytest.mark.asyncio
    async def test_empty_video_id_validation(self):
        resolver = InnerTubeXResolver()
        with pytest.raises(ValueError):
            await resolver.resolve_stream("   ")

    @pytest.mark.asyncio
    async def test_hls_stream_resolution(self, sample_bridge_stream_payload):
        payload = dict(sample_bridge_stream_payload)
        payload["stream"]["stream_type"] = "HLS"
        payload["stream"]["url"] = "https://manifest.googlevideo.com/api/manifest/hls/test.m3u8"
        payload["stream"]["mime_type"] = "application/x-mpegURL"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        stream = await resolver.resolve_stream("vid_hls", purpose="playback")

        assert stream.stream_type == "HLS"
        assert stream.mime_type == "application/x-mpegURL"

    @pytest.mark.asyncio
    async def test_youtube_stream_resolver_delegates_to_innertubex(self, sample_bridge_stream_payload):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=sample_bridge_stream_payload)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        itx_resolver = InnerTubeXResolver(base_url="http://127.0.0.1:8765", client=client)
        yt_resolver = YouTubeStreamResolver(primary_resolver=itx_resolver)

        stream = await yt_resolver.resolve("dQw4w9WgXcQ")
        assert stream.video_id == "dQw4w9WgXcQ"
        assert stream.bitrate == 160000
