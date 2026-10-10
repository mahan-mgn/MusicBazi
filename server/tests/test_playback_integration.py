"""
تست‌های Phase 11 — اتصال کنترل‌شده معماری Stream جدید به مسیر Playback واقعی.

پوشش:
1. Feature Flag: OFF → مسیر legacy عیناً قبل، new resolver فراخوانی نمی‌شود؛
   ON → new resolver فراخوانی می‌شود؛ default همچنان OFF
2. PlaybackStreamAdapter: mapping خالص url/mime/headers/codec/bitrate/...
3. Live playback: resolve موفق → StreamingResponse؛ fallback موفق → پخش؛
   no stream → شکست امن با fall-through به legacy
4. Recovery در runtime: 403/410 → دقیقاً یک re-resolution؛ 500/unknown → بدون recovery؛
   بدون retry loop؛ شکست recovery به‌صورت امن propagate
5. Range: ارسال Range client به upstream و عبور Content-Range/206
6. Cache behavior: فایل آماده کتابخانه/کش هنوز اولویت دارد (find_ready_file)
7. امنیت: هیچ signed URL/cookie در لاگ‌ها/خطاها/state
"""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app import stream_cache
from app.models import Track
from app.stream.errors import (
    AllResolversFailedError,
    NetworkError,
    NoStreamError,
    StreamResolverError,
)
from app.stream.feature_flags import STREAM_V2_FLAG, is_stream_v2_enabled
from app.stream.models import ResolvedStream
from app.stream.playback import (
    LivePlaybackStreamer,
    PlaybackStreamAdapter,
    StreamRecoverySafe,
    extract_youtube_video_id,
    get_live_playback,
)
from app.stream.recovery import StreamRecovery
from app.stream.resolver import YouTubeStreamResolver

FLAG_ON = {STREAM_V2_FLAG: "1"}
FLAG_OFF = {STREAM_V2_FLAG: "0"}

UPSTREAM_BODY = b"\x00\x01\x02audio-bytes" * 4


def make_stream(video_id: str = "dQw4w9WgXcQ", **overrides) -> ResolvedStream:
    defaults = dict(
        source="youtube",
        url=f"https://rr1---sn-abc.googlevideo.com/videoplayback?id={video_id}&sig=SECRET_SIG",
        mime_type="audio/webm",
        codec="opus",
        bitrate=160000,
        sample_rate=48000,
        channels=2,
        content_length=3500000,
        expires_at=int(time.time()) + 3600,
        headers={"User-Agent": "test-agent"},
        resolver_metadata={"client_name": "WEB_REMIX", "resolver": "innertubex"},
    )
    defaults.update(overrides)
    return ResolvedStream(video_id=video_id, **defaults)


def youtube_track(track_id: str = "dQw4w9WgXcQ", source: str = "youtube") -> Track:
    return Track(
        id=track_id,
        title="t",
        artist="a",
        durationMs=1000,
        source=source,  # type: ignore[arg-type]
        sourceUrl=f"https://www.youtube.com/watch?v={track_id}",
    )


@pytest.fixture
def mock_resolver() -> AsyncMock:
    return AsyncMock(spec=YouTubeStreamResolver)


# ======================================================================
# Feature Flag
# ======================================================================


class TestFeatureFlagGating:
    def test_default_flag_is_off(self):
        import os

        env = {k: v for k, v in os.environ.items() if k != STREAM_V2_FLAG}
        assert is_stream_v2_enabled(env) is False

    @pytest.mark.asyncio
    async def test_flag_off_never_calls_new_resolver(self, mock_resolver):
        streamer = LivePlaybackStreamer(resolver=mock_resolver)
        result = await streamer.stream_response(
            youtube_track(), range_header=None, quality=None, env={}
        )
        assert result is None
        mock_resolver.resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_on_calls_new_resolver(self, mock_resolver):
        mock_resolver.resolve.return_value = make_stream()
        streamer = LivePlaybackStreamer(
            resolver=mock_resolver,
            http_transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=UPSTREAM_BODY)
            ),
        )
        result = await streamer.stream_response(
            youtube_track(), range_header=None, quality=None, env=FLAG_ON
        )
        assert result is not None
        mock_resolver.resolve.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_youtube_source_skips_live_path(self, mock_resolver):
        streamer = LivePlaybackStreamer(resolver=mock_resolver)
        result = await streamer.stream_response(
            youtube_track(source="spotify"), env=FLAG_ON
        )
        assert result is None
        mock_resolver.resolve.assert_not_called()


# ======================================================================
# video id extraction
# ======================================================================


class TestVideoIdExtraction:
    def test_watch_url(self):
        t = youtube_track("abc11charsX")
        assert extract_youtube_video_id(t) == "abc11charsX"

    def test_short_url(self):
        t = youtube_track()
        t = t.model_copy(update={"sourceUrl": "https://youtu.be/dQw4w9WgXcQ"})
        assert extract_youtube_video_id(t) == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        t = youtube_track().model_copy(
            update={"sourceUrl": "https://youtube.com/shorts/dQw4w9WgXcQ"}
        )
        assert extract_youtube_video_id(t) == "dQw4w9WgXcQ"

    def test_spotify_source_never_extracts(self):
        t = youtube_track().model_copy(update={"source": "spotify"})
        assert extract_youtube_video_id(t) is None

    def test_unparseable_youtube_track_returns_none(self):
        t = youtube_track("not-a-youtube-id")
        t = t.model_copy(update={"sourceUrl": "https://musicbazi.local/track/x"})
        assert extract_youtube_video_id(t) is None


# ======================================================================
# PlaybackStreamAdapter — mapping خالص
# ======================================================================


class TestPlaybackAdapterMapping:
    def test_full_mapping(self):
        stream = make_stream(
            mime_type="audio/mp4",
            codec="mp4a.40.2",
            bitrate=128000,
            sample_rate=44100,
            channels=2,
            content_length=123456,
            requires_range=True,
            headers={"User-Agent": "ua", "Cookie": "SID=runtime-only"},
        )
        adapter = PlaybackStreamAdapter()
        assert adapter.response_media_type(stream) == "audio/mp4"
        headers = adapter.upstream_request_headers(stream)
        assert headers["User-Agent"] == "ua"
        assert headers["Cookie"] == "SID=runtime-only"  # runtime pass-through
        facts = adapter.playback_facts(stream)
        assert facts["codec"] == "mp4a.40.2"
        assert facts["bitrate"] == 128000
        assert facts["sample_rate"] == 44100
        assert facts["channels"] == 2
        assert facts["content_length"] == 123456
        assert facts["requires_range"] is True
        # هیچ فیلد حساسی در facts نیست
        assert "url" not in facts and "headers" not in facts

    def test_media_type_mapping_uses_stream_mime(self):
        stream = make_stream(mime_type="audio/mp4")
        assert PlaybackStreamAdapter.response_media_type(stream) == "audio/mp4"


# ======================================================================
# Live playback + Range
# ======================================================================


class TestLivePlayback:
    @pytest.mark.asyncio
    async def test_successful_resolution_streams(self, mock_resolver):
        mock_resolver.resolve.return_value = make_stream()
        streamer = LivePlaybackStreamer(
            resolver=mock_resolver,
            http_transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=UPSTREAM_BODY)
            ),
        )
        response = await streamer.stream_response(youtube_track(), env=FLAG_ON)

        assert response is not None
        assert response.status_code == 200
        assert response.media_type == "audio/webm"
        assert response.headers["accept-ranges"] == "bytes"
        body = b"".join([chunk async for chunk in response.body_iterator])
        assert body == UPSTREAM_BODY

    @pytest.mark.asyncio
    async def test_range_header_forwarded_and_206_passthrough(self, mock_resolver):
        seen_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.update(dict(request.headers))
            return httpx.Response(
                206,
                content=UPSTREAM_BODY,
                headers={"Content-Range": "bytes 100-199/3500000"},
            )

        mock_resolver.resolve.return_value = make_stream()
        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )
        response = await streamer.stream_response(
            youtube_track(), range_header="bytes=100-", env=FLAG_ON
        )

        assert response.status_code == 206
        assert response.headers["content-range"] == "bytes 100-199/3500000"
        # Range کلاینت عیناً به upstream رسیده
        assert seen_headers.get("range") == "bytes=100-"

    @pytest.mark.asyncio
    async def test_upstream_user_agent_header_passed(self, mock_resolver):
        seen_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.update(dict(request.headers))
            return httpx.Response(200, content=UPSTREAM_BODY)

        mock_resolver.resolve.return_value = make_stream(
            headers={"User-Agent": "MusicBazi/1.0"}
        )
        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )
        await streamer.stream_response(youtube_track(), env=FLAG_ON)
        assert seen_headers.get("user-agent") == "MusicBazi/1.0"

    @pytest.mark.asyncio
    async def test_hls_stream_defers_to_legacy_path(self, mock_resolver):
        """قرارداد playback فعلی فایل مستقیم است؛ HLS باید به legacy واگذار شود."""
        mock_resolver.resolve.return_value = make_stream(stream_type="HLS")
        streamer = LivePlaybackStreamer(
            resolver=mock_resolver,
            http_transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"#EXTM3U")
            ),
        )
        result = await streamer.stream_response(youtube_track(), env=FLAG_ON)
        assert result is None  # → caller مسیر legacy را اجرا می‌کند

    @pytest.mark.asyncio
    async def test_resolver_failure_raises_for_legacy_fallthrough(self, mock_resolver):
        mock_resolver.resolve.side_effect = AllResolversFailedError(
            video_id="dQw4w9WgXcQ",
            primary_error=NoStreamError("no stream"),
            fallback_error=NetworkError("net"),
        )
        streamer = LivePlaybackStreamer(resolver=mock_resolver)

        with pytest.raises(AllResolversFailedError):
            await streamer.stream_response(youtube_track(), env=FLAG_ON)


# ======================================================================
# Runtime Recovery (فاز ۸ با بودجه ۱)
# ======================================================================


class TestRuntimeRecovery:
    def _streamer(self, mock_resolver, statuses: list[int]):
        """upstream که به‌ترتیب status ها را برمی‌گرداند."""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            status = statuses[min(calls["n"], len(statuses) - 1)]
            calls["n"] += 1
            return httpx.Response(status, content=UPSTREAM_BODY)

        return LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

    @pytest.mark.asyncio
    async def test_403_then_success_recovers_once(self, mock_resolver):
        # resolve اول استریم می‌دهد؛ upstream 403؛ recovery یک‌بار resolve مجدد
        mock_resolver.resolve.side_effect = [
            make_stream(url="https://g.example/old"),
            make_stream(url="https://g.example/fresh"),
        ]
        streamer = self._streamer(mock_resolver, statuses=[403, 200])

        response = await streamer.stream_response(youtube_track(), env=FLAG_ON)

        assert response is not None
        assert mock_resolver.resolve.await_count == 2  # دقیقاً یک re-resolution

    @pytest.mark.asyncio
    async def test_403_reports_refusal_to_bridge(self, mock_resolver):
        mock_resolver.primary = AsyncMock()
        mock_resolver.primary.report_refusal = AsyncMock(return_value=True)
        mock_resolver.resolve.side_effect = [
            make_stream(
                url="https://g.example/old",
                resolver_metadata={
                    "resolver": "innertubex",
                    "client_name": "WEB_REMIX",
                    "profile_id": "WEB_REMIX__po",
                },
            ),
            make_stream(url="https://g.example/fresh"),
        ]
        streamer = self._streamer(mock_resolver, statuses=[403, 200])

        response = await streamer.stream_response(youtube_track(), env=FLAG_ON)
        assert response is not None
        mock_resolver.primary.report_refusal.assert_awaited_once_with(
            video_id="dQw4w9WgXcQ",
            status_code=403,
            client_name="WEB_REMIX",
            profile_id="WEB_REMIX__po",
            url="https://g.example/old",
        )

    @pytest.mark.asyncio
    async def test_410_triggers_recovery(self, mock_resolver):
        mock_resolver.resolve.side_effect = [
            make_stream(),
            make_stream(),
        ]
        streamer = self._streamer(mock_resolver, statuses=[410, 200])
        response = await streamer.stream_response(youtube_track(), env=FLAG_ON)
        assert response is not None
        assert mock_resolver.resolve.await_count == 2

    @pytest.mark.asyncio
    async def test_500_does_not_recover(self, mock_resolver):
        mock_resolver.resolve.return_value = make_stream()
        streamer = self._streamer(mock_resolver, statuses=[500])

        with pytest.raises(NetworkError):
            await streamer.stream_response(youtube_track(), env=FLAG_ON)

        mock_resolver.resolve.assert_awaited_once()  # بدون recovery

    @pytest.mark.asyncio
    async def test_unknown_status_does_not_recover(self, mock_resolver):
        mock_resolver.resolve.return_value = make_stream()
        streamer = self._streamer(mock_resolver, statuses=[404])

        with pytest.raises(StreamResolverError) as exc_info:
            await streamer.stream_response(youtube_track(), env=FLAG_ON)
        assert exc_info.value.code == "RUNTIME_FAILURE"
        mock_resolver.resolve.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_retry_loop_when_fresh_stream_also_rejected(self, mock_resolver):
        mock_resolver.resolve.side_effect = [
            make_stream(),
            make_stream(),  # recovery
        ]
        streamer = self._streamer(mock_resolver, statuses=[410, 410])

        with pytest.raises(StreamRecoverySafe):
            await streamer.stream_response(youtube_track(), env=FLAG_ON)

        assert mock_resolver.resolve.await_count == 2  # بودجه ۱ — بدون loop سوم

    @pytest.mark.asyncio
    async def test_recovery_failure_propagates_safely(self, mock_resolver):
        mock_resolver.resolve.return_value = make_stream()
        recovery = AsyncMock(spec=StreamRecovery)
        recovery.recover_from_runtime_failure.side_effect = AllResolversFailedError(
            video_id="dQw4w9WgXcQ",
            primary_error=NoStreamError("no stream"),
            fallback_error=NoStreamError("no stream"),
        )
        streamer = LivePlaybackStreamer(
            resolver=mock_resolver,
            recovery=recovery,
            http_transport=httpx.MockTransport(
                lambda request: httpx.Response(403, content=b"")
            ),
        )

        with pytest.raises(AllResolversFailedError):
            await streamer.stream_response(youtube_track(), env=FLAG_ON)

    @pytest.mark.asyncio
    async def test_recovery_uses_same_resolver_instance(self, mock_resolver):
        """فاز ۷/۶: recovery باید از همان resolver (health مشترک) عبور کند."""
        streamer = LivePlaybackStreamer(resolver=mock_resolver)
        assert streamer.recovery.resolver is streamer.resolver


# ======================================================================
# Cache behavior حفظ می‌شود
# ======================================================================


class TestCacheBehavior:
    @pytest.mark.asyncio
    async def test_find_ready_file_prefers_library(self, tmp_path, monkeypatch, fresh_db, track):
        lib_file = tmp_path / "lib.mp3"
        lib_file.write_bytes(b"lib")

        class FakeRow(dict):
            pass

        monkeypatch.setattr(
            stream_cache.db,
            "find_any_ready",
            lambda track_id, preferred_quality=None: {"path": str(lib_file)},
        )
        result = await stream_cache.find_ready_file(track, quality=None)
        assert result == lib_file

    @pytest.mark.asyncio
    async def test_find_ready_file_returns_none_when_nothing_cached(
        self, tmp_path, monkeypatch, fresh_db, track
    ):
        monkeypatch.setattr(stream_cache.db, "find_any_ready", lambda *a, **k: None)
        monkeypatch.setattr(
            stream_cache, "STREAM_CACHE_DIR", tmp_path
        )
        result = await stream_cache.find_ready_file(track, quality=None)
        assert result is None


# ======================================================================
# Security
# ======================================================================


class TestSecurity:
    @pytest.mark.asyncio
    async def test_no_signed_url_in_logs_or_errors(self, mock_resolver, caplog):
        mock_resolver.resolve.return_value = make_stream()
        streamer = LivePlaybackStreamer(
            resolver=mock_resolver,
            http_transport=httpx.MockTransport(
                lambda request: httpx.Response(500, content=b"")
            ),
        )

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(StreamResolverError) as exc_info:
                await streamer.stream_response(youtube_track(), env=FLAG_ON)

        combined_logs = " ".join(r.getMessage() for r in caplog.records).lower()
        for forbidden in ("googlevideo", "https://", "sig=", "secret_sig", "cookie", "authorization"):
            assert forbidden not in combined_logs
        assert "googlevideo" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connection_error_message_has_no_url(self, mock_resolver):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        mock_resolver.resolve.return_value = make_stream()
        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        with pytest.raises(NetworkError) as exc_info:
            await streamer.stream_response(youtube_track(), env=FLAG_ON)
        assert "googlevideo" not in str(exc_info.value)
        assert "https://" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upstream_headers_not_logged(self, mock_resolver, caplog):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(dict(request.headers))
            return httpx.Response(200, content=UPSTREAM_BODY)

        mock_resolver.resolve.return_value = make_stream(
            headers={"Cookie": "SID=secret-session; VISITOR=tok"}
        )
        streamer = LivePlaybackStreamer(
            resolver=mock_resolver, http_transport=httpx.MockTransport(handler)
        )

        with caplog.at_level(logging.DEBUG):
            await streamer.stream_response(youtube_track(), env=FLAG_ON)

        # header عیناً به upstream رسیده (runtime pass-through)...
        assert "secret-session" in seen.get("cookie", "")
        # ...اما در هیچ لاگی نیست
        combined = " ".join(r.getMessage() for r in caplog.records).lower()
        assert "secret-session" not in combined
        assert "sid=" not in combined


# ======================================================================
# Singleton
# ======================================================================


class TestSingleton:
    def test_get_live_playback_returns_same_instance(self):
        a = get_live_playback()
        b = get_live_playback()
        assert a is b
        assert a.recovery.resolver is a.resolver

    @pytest.mark.asyncio
    async def test_on_session_changed_preserves_active_hls_sessions(self, mock_resolver):
        from unittest.mock import MagicMock
        mock_resolver.on_session_changed = MagicMock()
        streamer = LivePlaybackStreamer(resolver=mock_resolver)
        stream = make_stream(stream_type="HLS")
        session = streamer.hls.registry.get_or_create("vid_hls", stream)
        assert streamer.hls.registry.get(session.session_id) is not None

        # اجرای on_session_changed
        streamer.on_session_changed()

        # نشست فعال همچنان در دسترس است تا دانلود سگمنت‌ها با ۴۰۴ قطع نشود
        assert streamer.hls.registry.get(session.session_id) is not None
        mock_resolver.on_session_changed.assert_called_once()

