"""
تست‌های کشِ درون‌حافظه‌ای URLهای رزولوشن‌شده (ResolvedURLCache) — بهبود زمان انتظار پخش (Latency).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models import Track
from app.stream.models import ResolvedStream
from app.stream.playback import LivePlaybackStreamer, ResolvedURLCache
from app.stream.resolver import YouTubeStreamResolver

FLAG_ON = {"MUSICBAZI_STREAM_V2": "1"}
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
        content_length=len(UPSTREAM_BODY),
        expires_at=int(time.time()) + 3600,
        headers={"User-Agent": "test-agent"},
        resolver_metadata={"client_name": "WEB_REMIX", "resolver": "innertubex"},
    )
    defaults.update(overrides)
    return ResolvedStream(video_id=video_id, **defaults)


def youtube_track(track_id: str = "dQw4w9WgXcQ") -> Track:
    return Track(
        id=track_id,
        title="Test Song",
        artist="Test Artist",
        durationMs=1000,
        source="youtube",
        sourceUrl=f"https://www.youtube.com/watch?v={track_id}",
    )


class TestResolvedURLCacheUnit:
    def test_cache_hit_and_ttl(self):
        fake_time = 1000.0
        cache = ResolvedURLCache(ttl_seconds=300.0, max_entries=10, clock=lambda: fake_time)
        key = cache.key("vid1", "opus", "user1")

        stream = make_stream("vid1", expires_at=int(fake_time + 1000))
        cache.put(key, stream)

        assert cache.get(key) is stream

        # گذر زمان بیشتر از TTL
        fake_time += 301.0
        assert cache.get(key) is None

    def test_cache_respects_url_expiration_with_skew(self):
        fake_time = 1000.0
        cache = ResolvedURLCache(ttl_seconds=300.0, max_entries=10, clock=lambda: fake_time)
        key = cache.key("vid1", None, "user1")

        # اگر تا انقضا کمتر از EXPIRY_SKEW_SECONDS (60s) مانده باشد، نباید در کش بنشیند
        stream_expiring_soon = make_stream("vid1", expires_at=int(fake_time + 50))
        cache.put(key, stream_expiring_soon)
        assert cache.get(key) is None

        # اگر منقضی شود، از کش حذف می‌شود
        stream_valid = make_stream("vid1", expires_at=int(fake_time + 200))
        cache.put(key, stream_valid)
        assert cache.get(key) is stream_valid

        fake_time += 150.0  # اکنون 50 ثانیه تا انقضا مانده (کمتر از 60s skew)
        assert cache.get(key) is None

    def test_cache_user_isolation(self):
        cache = ResolvedURLCache(ttl_seconds=300.0, max_entries=10)
        k1 = cache.key("vid1", None, "user1")
        k2 = cache.key("vid1", None, "user2")

        s1 = make_stream("vid1", headers={"User-Agent": "agent1"})
        s2 = make_stream("vid1", headers={"User-Agent": "agent2"})

        cache.put(k1, s1)
        cache.put(k2, s2)

        assert cache.get(k1) is s1
        assert cache.get(k2) is s2

    def test_cache_eviction_when_full(self):
        fake_time = 1000.0
        cache = ResolvedURLCache(ttl_seconds=300.0, max_entries=2, clock=lambda: fake_time)
        k1 = cache.key("vid1", None, "u")
        k2 = cache.key("vid2", None, "u")
        k3 = cache.key("vid3", None, "u")

        cache.put(k1, make_stream("vid1", expires_at=int(fake_time + 500)))
        fake_time += 10
        cache.put(k2, make_stream("vid2", expires_at=int(fake_time + 500)))
        fake_time += 10
        cache.put(k3, make_stream("vid3", expires_at=int(fake_time + 500)))

        # k1 که قدیمی‌ترین بود باید بیرون انداخته شده باشد
        assert cache.get(k1) is None
        assert cache.get(k2) is not None
        assert cache.get(k3) is not None


class TestLivePlaybackResolvedCacheIntegration:
    @pytest.mark.asyncio
    async def test_sequential_requests_reuse_resolved_stream(self):
        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        stream = make_stream()
        mock_resolver.resolve.return_value = stream

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver,
            http_transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=UPSTREAM_BODY)
            ),
            resolved_cache_ttl=300.0,
        )

        track = youtube_track()
        res1 = await streamer.stream_response(track, env=FLAG_ON)
        assert res1 is not None

        # بار دوم باید مستقیماً از کشِ درون‌حافظه سرو شود بدون فراخوانی مجدد resolver.resolve
        res2 = await streamer.stream_response(track, env=FLAG_ON)
        assert res2 is not None

        mock_resolver.resolve.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_session_change_clears_resolved_cache(self):
        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        stream = make_stream()
        mock_resolver.resolve.return_value = stream

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver,
            http_transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=UPSTREAM_BODY)
            ),
            resolved_cache_ttl=300.0,
        )

        track = youtube_track()
        await streamer.stream_response(track, env=FLAG_ON)
        assert mock_resolver.resolve.await_count == 1

        # رویداد تغییر نشست (مثلاً عوض شدن کوکی کاربر) کش را پاک می‌کند
        streamer.on_session_changed()

        await streamer.stream_response(track, env=FLAG_ON)
        assert mock_resolver.resolve.await_count == 2

    @pytest.mark.asyncio
    async def test_403_recovery_drops_cache_and_puts_fresh_stream(self):
        vid = "dQw4w9WgXcQ"
        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        stale_stream = make_stream(vid, url="https://googlevideo.com/stale?sig=OLD")
        fresh_stream = make_stream(vid, url="https://googlevideo.com/fresh?sig=NEW")

        mock_resolver.resolve.return_value = stale_stream

        call_count = 0

        def fake_transport(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if "stale" in str(request.url):
                return httpx.Response(403)
            return httpx.Response(200, content=UPSTREAM_BODY)

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver,
            http_transport=httpx.MockTransport(fake_transport),
            resolved_cache_ttl=300.0,
        )
        streamer.recovery = AsyncMock()
        streamer.recovery.recover_from_runtime_failure.return_value = fresh_stream

        track = youtube_track(vid)
        resp = await streamer.stream_response(track, env=FLAG_ON)
        assert resp is not None
        assert resp.status_code == 200

        # پس از ریکاوری، باید fresh_stream در کش نشسته باشد
        key = streamer._resolved.key(vid, None, "local")
        assert streamer._resolved.get(key) is fresh_stream

    @pytest.mark.asyncio
    async def test_warm_primes_resolved_cache(self, monkeypatch):
        # `warm` فلگ را از os.environ می‌خواند (نه از پارامتر env)، پس تست باید
        # آن را صریح روشن کند؛ وگرنه پیش‌فرض OFF مستندشده باعث بازگشت False می‌شود.
        monkeypatch.setenv("MUSICBAZI_STREAM_V2", "1")
        vid = "dQw4w9WgXcQ"
        mock_resolver = AsyncMock(spec=YouTubeStreamResolver)
        stream = make_stream(vid)
        mock_resolver.resolve.return_value = stream

        streamer = LivePlaybackStreamer(
            resolver=mock_resolver,
            resolved_cache_ttl=300.0,
        )

        track = youtube_track(vid)
        warmed = await streamer.warm(track)
        assert warmed is True
        mock_resolver.resolve.assert_awaited_once()

        # استریم در کش نشسته است
        key = streamer._resolved.key(vid, None, "local")
        assert streamer._resolved.get(key) is stream
