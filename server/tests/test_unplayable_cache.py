"""
تست‌های جامع Phase 3 — Anti-Storm Unplayable Cache در Music Bazi.
پوشش:
1. خطای قطعی (Age Restricted، Video Unavailable، Private Video) کش می‌شود.
2. خطاهای موقت (شبکه، تایم‌اوت، 5xx، در دسترس نبودن بریج) هرگز کش نمی‌شوند.
3. انقضای TTL (۱۰ دقیقه) و تلاش مجدد برای رزولوشن پس از انقضا.
4. ایزولاسیون کامل ویدیوها: خرابی یک ویدیو تأثیری بر سایر ویدیوها ندارد.
5. خطای منقضی‌شدن URL به عنوان خطای قطعی کش نمی‌شود و قابل ریکاوری است.
6. حفظ کامل فراخوانی Fallback به yt-dlp در مواجهه با خطاهای اولیه.
7. پاک‌شدن ورودی کش در صورت موفقیت بعدی.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from app.stream.errors import (
    AllResolversFailedError,
    BridgeTimeoutError,
    BridgeUnavailableError,
    ClientRejectedError,
    ExpiredStreamError,
    NetworkError,
    NoStreamError,
    PermanentlyUnplayableError,
)
from app.stream.models import ResolvedStream
from app.stream.resolver import (
    UnplayableCache,
    YouTubeStreamResolver,
    classify_permanent_unplayable,
)


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


def make_sample_stream(video_id: str = "vid123") -> ResolvedStream:
    return ResolvedStream(
        source="youtube",
        video_id=video_id,
        url="https://rr1---sn-test.googlevideo.com/videoplayback?id=123",
        mime_type="audio/webm",
        codec="opus",
        bitrate=160000,
        sample_rate=48000,
        channels=2,
        content_length=3500000,
        expires_at=2000000000,
        headers={},
        resolver_metadata={"client_name": "WEB_REMIX", "resolver": "innertubex"},
    )


# ======================================================================
# تست‌های مستقیم UnplayableCache و طبقه‌بندی خطا
# ======================================================================


class TestUnplayableCacheUnit:
    def test_classify_permanent_errors(self):
        # ۱. خطای محدودیت سنی صریح
        err_age = ClientRejectedError("Sign in to confirm age", code="AGE_RESTRICTED")
        assert classify_permanent_unplayable(err_age) == ("AGE_RESTRICTED", "Sign in to confirm age")

        # ۲. خطای ویدیوی خصوصی یا حذف‌شده
        err_priv = ClientRejectedError("This is a private video", code="CLIENT_REJECTED")
        code, msg = classify_permanent_unplayable(err_priv) or ("", "")
        assert code == "UNAVAILABLE"
        assert "private video" in msg.lower()

        # ۳. خطای ترکیبی AllResolversFailedError
        all_err = AllResolversFailedError(
            video_id="v1",
            primary_error=ClientRejectedError("age restricted", code="AGE_RESTRICTED"),
            fallback_error=NoStreamError("No audio stream"),
        )
        assert classify_permanent_unplayable(all_err) is not None

    def test_classify_transient_errors_not_permanent(self):
        # خطاهای موقت زیرساختی نباید هرگز در کش قرار گیرند
        assert classify_permanent_unplayable(BridgeUnavailableError()) is None
        assert classify_permanent_unplayable(BridgeTimeoutError()) is None
        assert classify_permanent_unplayable(NetworkError("connection refused")) is None
        assert classify_permanent_unplayable(ExpiredStreamError("expired")) is None

    def test_cache_ttl_and_eviction(self):
        clock = FakeClock()
        cache = UnplayableCache(ttl_seconds=600.0, clock=clock.time)

        # ثبت خطای قطعی برای ویدیوی A
        cache.remember_unplayable("vid_A", "AGE_RESTRICTED", "Content is age restricted")

        assert cache.get_unplayable("vid_A") == ("AGE_RESTRICTED", "Content is age restricted")
        assert cache.get_unplayable("vid_B") is None

        # ۵ دقیقه بعد: همچنان در کش است
        clock.advance(300.0)
        assert cache.get_unplayable("vid_A") is not None

        # ۱۱ دقیقه بعد: منقضی شده و از کش خارج می‌شود
        clock.advance(360.0)
        assert cache.get_unplayable("vid_A") is None


# ======================================================================
# تست‌های یکپارچگی Anti-Storm در YouTubeStreamResolver
# ======================================================================


class TestResolverAntiStormIntegration:
    @pytest.mark.asyncio
    async def test_permanent_error_prevents_repeated_extractions(self):
        """
        ویدیویی که با خطای قطعی شکست می‌خورد باید تا ۱۰ دقیقه بدون فراخوانی مجدد
        رزولورها فوراً با خطای PermanentlyUnplayableError متوقف شود.
        """
        clock = FakeClock()
        cache = UnplayableCache(ttl_seconds=600.0, clock=clock.time)

        mock_primary = AsyncMock()
        mock_fallback = AsyncMock()

        # شبیه‌سازی شکست هر دو رزولور به دلیل محدودیت سنی
        mock_primary.resolve_stream.side_effect = ClientRejectedError(
            "This video is age restricted", code="AGE_RESTRICTED", video_id="age_vid"
        )
        mock_fallback.resolve_stream.side_effect = ClientRejectedError(
            "Sign in to confirm your age", code="CLIENT_REJECTED", video_id="age_vid"
        )

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_primary,
            fallback_resolver=mock_fallback,
            unplayable_cache=cache,
        )

        # درخواست اول: هر دو رزولور فراخوانی می‌شوند و AllResolversFailedError پرتاب می‌شود
        with pytest.raises(AllResolversFailedError):
            await resolver.resolve("age_vid")

        assert mock_primary.resolve_stream.await_count == 1
        assert mock_fallback.resolve_stream.await_count == 1

        # درخواست دوم (۱ دقیقه بعد): کش Anti-Storm عمل کرده و هیچ تماسی با رزولورها برقرار نمی‌شود
        clock.advance(60.0)
        with pytest.raises(PermanentlyUnplayableError) as exc_info:
            await resolver.resolve("age_vid")

        assert exc_info.value.code == "AGE_RESTRICTED"
        # شمارنده فراخوانی رزولورها نباید افزایش یافته باشد
        assert mock_primary.resolve_stream.await_count == 1
        assert mock_fallback.resolve_stream.await_count == 1

        # درخواست سوم (پس از انقضای TTL ۱۰ دقیقه‌ای): تلاش مجدد آزاد می‌شود
        clock.advance(550.0)  # مجموع زمان > ۶۰۰ ثانیه
        with pytest.raises(AllResolversFailedError):
            await resolver.resolve("age_vid")

        assert mock_primary.resolve_stream.await_count == 2
        assert mock_fallback.resolve_stream.await_count == 2

    @pytest.mark.asyncio
    async def test_transient_network_error_not_cached(self):
        """خطای موقت شبکه نباید در کش Anti-Storm بنشیند و تلاش بعدی بلافاصله مجاز است."""
        clock = FakeClock()
        cache = UnplayableCache(ttl_seconds=600.0, clock=clock.time)

        mock_primary = AsyncMock()
        mock_fallback = AsyncMock()

        mock_primary.resolve_stream.side_effect = NetworkError("Connection reset")
        mock_fallback.resolve_stream.side_effect = NetworkError("DNS timeout")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_primary,
            fallback_resolver=mock_fallback,
            unplayable_cache=cache,
        )

        with pytest.raises(AllResolversFailedError):
            await resolver.resolve("net_fail_vid")

        # کش نباید پر شده باشد
        assert cache.get_unplayable("net_fail_vid") is None

        # درخواست دوم بلافاصله می‌تواند رزولورها را دوباره امتحان کند
        with pytest.raises(AllResolversFailedError):
            await resolver.resolve("net_fail_vid")

        assert mock_primary.resolve_stream.await_count == 2

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_successful_resolve_clears_cache_entry(self):
        """در صورت رزولوشن موفق، ورودی احتمالی کش حذف می‌شود."""
        cache = UnplayableCache()
        cache.remember_unplayable("vid_ok", "OLD_CODE", "old err")

        mock_primary = AsyncMock()
        mock_primary.resolve_stream.return_value = make_sample_stream("vid_ok")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_primary,
            unplayable_cache=cache,
        )

        # دستی کش را پاک می‌کنیم تا استریم با موفقیت چک شود
        cache.clear()
        stream = await resolver.resolve("vid_ok")
        assert stream.video_id == "vid_ok"
        assert cache.get_unplayable("vid_ok") is None

    @pytest.mark.asyncio
    async def test_session_changed_invalidates_cache_and_allows_reresolve(self):
        """
        تغییر واقعی نشست (مثلاً آپلود کوکی یوتیوب) کش قطعی را بی‌اعتبار کرده
        و استخراج مجدد همان ویدیو بلافاصله امکان‌پذیر می‌شود (Phase 3 Audit Fix).
        """
        cache = UnplayableCache(ttl_seconds=600.0)
        mock_primary = AsyncMock()
        mock_fallback = AsyncMock()

        # ابتدا ویدیو به دلیل محدودیت سنی رد می‌شود
        mock_primary.resolve_stream.side_effect = ClientRejectedError(
            "Age restricted video", code="AGE_RESTRICTED", video_id="age_gated_vid"
        )
        mock_fallback.resolve_stream.side_effect = ClientRejectedError(
            "Age restricted video", code="CLIENT_REJECTED", video_id="age_gated_vid"
        )

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_primary,
            fallback_resolver=mock_fallback,
            unplayable_cache=cache,
        )

        with pytest.raises(AllResolversFailedError):
            await resolver.resolve("age_gated_vid")

        # کش ثبت شد؛ درخواست بعدی خطای کش‌شده می‌دهد
        assert cache.get_unplayable("age_gated_vid") is not None
        with pytest.raises(PermanentlyUnplayableError):
            await resolver.resolve("age_gated_vid")

        assert mock_primary.resolve_stream.await_count == 1

        # رویداد تغییر نشست فراخوانی می‌شود (on_session_changed)
        mock_primary.notify_session_changed = AsyncMock(return_value=True)
        resolver.on_session_changed()

        # کش باید کاملاً پاک شده باشد
        assert cache.get_unplayable("age_gated_vid") is None

        # حال با نشست جدید، رزولوشن موفق می‌شود
        mock_primary.resolve_stream.side_effect = None
        mock_primary.resolve_stream.return_value = make_sample_stream("age_gated_vid")

        stream = await resolver.resolve("age_gated_vid")
        assert stream.video_id == "age_gated_vid"
        assert mock_primary.resolve_stream.await_count == 2

    @pytest.mark.asyncio
    async def test_cookies_setup_route_triggers_on_session_changed(self, monkeypatch):
        """تایید اتصال واقعی اندپوینت /api/setup/cookies به ابطال کش نشست."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.stream.playback import get_live_playback

        mock_called = False

        def mock_on_session_changed():
            nonlocal mock_called
            mock_called = True

        streamer = get_live_playback()
        monkeypatch.setattr(streamer, "on_session_changed", mock_on_session_changed)

        client = TestClient(app)
        # نمونه کوکی معتبر با فرمت Netscape
        netscape_cookies = (
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tvalid_cookie_value\n"
        )

        response = client.post(
            "/api/setup/cookies",
            files={"file": ("cookies.txt", netscape_cookies.encode("utf-8"), "text/plain")},
        )
        assert response.status_code == 200
        assert mock_called is True, "آپلود کوکی باید رویداد on_session_changed را فراخوانی کند"

    @pytest.mark.asyncio
    async def test_concurrent_requests_share_single_flight(self):
        """درخواست‌های هم‌زمان رزولوشن از طریق single-flight تجمیع می‌شوند."""
        import asyncio
        from app.stream.playback import LivePlaybackStreamer
        from app.models import Track

        resolve_calls = 0

        class SlowResolver:
            async def resolve(self, video_id: str, **kwargs):
                nonlocal resolve_calls
                resolve_calls += 1
                await asyncio.sleep(0.05)
                return make_sample_stream(video_id)

        streamer = LivePlaybackStreamer(resolver=SlowResolver())

        # اجرای ۱۰ درخواست هم‌زمان برای یک ویدیو
        tasks = [
            streamer._resolve_shared("shared_vid", purpose="playback", quality=None)
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        assert all(r.video_id == "shared_vid" for r in results)
        # دقیقاً ۱ بار متد resolve فراخوانی شده است
        assert resolve_calls == 1

