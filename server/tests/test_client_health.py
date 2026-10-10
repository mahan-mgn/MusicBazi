"""
تست‌های Phase 7 — سلامت کلاینت InnerTubeX و مدارشکن (Circuit Breaker) سبک.

پوشش:
1. کلاینت تازه → HEALTHY
2. شکست اول → همچنان مجاز
3. رسیدن به آستانه → UNHEALTHY
4. Cooldown: قبل از انقضا skip، بعد از انقضا HALF-OPEN (تلاش مجدد مجاز)
5. بازیابی: رزولوشن موفق → HEALTHY و reset شمارنده
6. ایزوله‌سازی ویدیوها: شکست video A نباید video B را ناسالم کند
7. استقلال کلاینت‌ها: X ناسالم، Y سالم
8. BRIDGE_UNAVAILABLE نباید health کلاینت را خراب کند
9. همزمانی (Thread Safety)
10. پاک‌سازی entry های منقضی (TTL) و سقف حافظه
11. یکپارچگی با YouTubeStreamResolver: skip تلاش اصلی بدون دورزدن سیاست فال‌بک
12. امنیت: هیچ secret/signed URL در state و snapshot ذخیره نمی‌شود
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest

from app.stream import (
    AllResolversFailedError,
    BridgeUnavailableError,
    ClientUnhealthyError,
    InnerTubeXResolver,
    NoStreamError,
    ResolvedStream,
    YouTubeStreamResolver,
    YtDlpResolver,
)
from app.stream.client_health import (
    CLIENT_FAILURE_THRESHOLD,
    ClientHealthMonitor,
    STATE_HALF_OPEN,
    STATE_HEALTHY,
    STATE_UNHEALTHY,
)


class FakeClock:
    """ساعت تزریق‌پذیر برای تست قطعی cooldown و TTL."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def monitor(clock: FakeClock) -> ClientHealthMonitor:
    return ClientHealthMonitor(clock=clock)


def make_stream(video_id: str, client_name: str = "WEB_REMIX") -> ResolvedStream:
    return ResolvedStream(
        source="youtube",
        video_id=video_id,
        url="https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=SECRET_SIG",
        mime_type="audio/webm",
        codec="opus",
        bitrate=160000,
        expires_at=9999999999,
        resolver_metadata={"client_name": client_name},
    )


@pytest.fixture
def sample_innertubex_stream_factory():
    def _make(video_id: str) -> ResolvedStream:
        return ResolvedStream(
            source="youtube",
            video_id=video_id,
            url="https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=ITX_SIG",
            mime_type="audio/webm",
            codec="opus",
            bitrate=160000,
            expires_at=9999999999,
            resolver_metadata={"client_name": "WEB_REMIX", "itag": "251", "resolver": "innertubex"},
        )

    return _make


@pytest.fixture
def sample_ytdlp_stream_factory():
    def _make(video_id: str) -> ResolvedStream:
        return ResolvedStream(
            source="youtube",
            video_id=video_id,
            url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=x&sig=YTDLP_SIG",
            mime_type="audio/mp4",
            codec="mp4a.40.2",
            bitrate=128000,
            expires_at=9999999999,
            resolver_metadata={"resolver": "yt-dlp", "format_id": "140"},
        )

    return _make


class TestClientHealthMonitorBasics:
    def test_new_client_is_healthy(self, monitor: ClientHealthMonitor):
        assert monitor.is_eligible("vidA") is True
        assert monitor.state_of("vidA") == STATE_HEALTHY

    def test_first_failure_still_eligible(self, monitor: ClientHealthMonitor):
        monitor.record_failure("vidA", reason="CLIENT_REJECTED")
        assert monitor.is_eligible("vidA") is True
        assert monitor.state_of("vidA") == STATE_HEALTHY

    def test_threshold_reached_marks_unhealthy(self, monitor: ClientHealthMonitor):
        monitor.record_failure("vidA", reason="CLIENT_REJECTED")
        monitor.record_failure("vidA", reason="CLIENT_REJECTED")
        assert monitor.is_eligible("vidA") is False
        assert monitor.state_of("vidA") == STATE_UNHEALTHY

    def test_threshold_constant_is_two(self):
        assert CLIENT_FAILURE_THRESHOLD == 2

    def test_custom_threshold_respected(self, clock: FakeClock):
        monitor = ClientHealthMonitor(failure_threshold=3, clock=clock)
        monitor.record_failure("vidA", reason="NO_STREAM")
        monitor.record_failure("vidA", reason="NO_STREAM")
        assert monitor.is_eligible("vidA") is True
        monitor.record_failure("vidA", reason="NO_STREAM")
        assert monitor.is_eligible("vidA") is False


class TestCooldown:
    def test_unhealthy_within_cooldown_is_skipped(self, monitor: ClientHealthMonitor, clock: FakeClock):
        monitor.record_failure("vidA", reason="CIPHER_ERROR")
        monitor.record_failure("vidA", reason="CIPHER_ERROR")
        clock.advance(100)
        assert monitor.is_eligible("vidA") is False

    def test_after_cooldown_retry_allowed(self, monitor: ClientHealthMonitor, clock: FakeClock):
        monitor.record_failure("vidA", reason="CIPHER_ERROR")
        monitor.record_failure("vidA", reason="CIPHER_ERROR")
        clock.advance(301)
        assert monitor.is_eligible("vidA") is True
        assert monitor.state_of("vidA") == STATE_HALF_OPEN

    def test_half_open_failure_remarks_unhealthy(self, monitor: ClientHealthMonitor, clock: FakeClock):
        monitor.record_failure("vidA", reason="CIPHER_ERROR")
        monitor.record_failure("vidA", reason="CIPHER_ERROR")
        clock.advance(301)
        assert monitor.is_eligible("vidA") is True
        monitor.record_failure("vidA", reason="CIPHER_ERROR")
        assert monitor.is_eligible("vidA") is False
        assert monitor.state_of("vidA") == STATE_UNHEALTHY


class TestRecovery:
    def test_success_recovers_and_resets_counter(self, monitor: ClientHealthMonitor):
        monitor.record_failure("vidA", reason="PO_TOKEN_ERROR")
        monitor.record_failure("vidA", reason="PO_TOKEN_ERROR")
        assert monitor.is_eligible("vidA") is False

        monitor.record_success("vidA", "WEB_REMIX")
        assert monitor.is_eligible("vidA") is True
        assert monitor.state_of("vidA") == STATE_HEALTHY

        # شمارنده باید از صفر شروع شود: یک شکست جدید نباید فوراً ناسالم کند
        monitor.record_failure("vidA", reason="PO_TOKEN_ERROR")
        assert monitor.is_eligible("vidA") is True
        assert monitor.state_of("vidA") == STATE_HEALTHY

    def test_success_of_other_video_does_not_reset_wrong_entry(self, monitor: ClientHealthMonitor):
        monitor.record_failure("vidA", reason="CLIENT_REJECTED")
        monitor.record_failure("vidA", reason="CLIENT_REJECTED")
        monitor.record_success("vidB", "WEB_REMIX")
        assert monitor.is_eligible("vidA") is False

    def test_success_of_other_client_does_not_reset_wrong_client(self, monitor: ClientHealthMonitor):
        monitor.record_failure("vidA", "TVHTML5", reason="CLIENT_REJECTED")
        monitor.record_failure("vidA", "TVHTML5", reason="CLIENT_REJECTED")
        monitor.record_success("vidA", "WEB_REMIX")
        # کلاینت TVHTML5 برای همان ویدیو باید ناسالم بماند
        assert monitor.is_eligible("vidA", "TVHTML5") is False
        # اما موفقیت، شکست‌های بدون‌انتسابِ همان ویدیو را reset می‌کند
        assert monitor.is_eligible("vidA") is True


class TestIsolation:
    def test_failure_of_video_a_does_not_affect_video_b(self, monitor: ClientHealthMonitor):
        monitor.record_failure("vidA", reason="CLIENT_REJECTED")
        monitor.record_failure("vidA", reason="CLIENT_REJECTED")
        assert monitor.is_eligible("vidB") is True
        assert monitor.state_of("vidB") == STATE_HEALTHY

    def test_different_clients_have_independent_state(self, monitor: ClientHealthMonitor):
        monitor.record_failure("vidA", "VISIONOS", reason="CLIENT_REJECTED")
        monitor.record_failure("vidA", "VISIONOS", reason="CLIENT_REJECTED")
        assert monitor.is_eligible("vidA", "VISIONOS") is False
        assert monitor.is_eligible("vidA", "WEB_REMIX") is True
        assert monitor.is_eligible("vidB", "VISIONOS") is True


class TestFailurePolicy:
    def test_bridge_unavailable_is_not_counted(self, monitor: ClientHealthMonitor):
        for _ in range(5):
            monitor.record_failure("vidA", reason="BRIDGE_UNAVAILABLE")
        assert monitor.is_eligible("vidA") is True
        assert monitor.state_of("vidA") == STATE_HEALTHY

    def test_client_failure_codes_are_counted(self, monitor: ClientHealthMonitor):
        codes = ["CLIENT_REJECTED", "CIPHER_ERROR", "PO_TOKEN_ERROR", "NO_STREAM",
                 "INVALID_RESPONSE", "TIMEOUT", "NETWORK_ERROR", "EXPIRED_STREAM"]
        for code in codes[:2]:
            monitor.record_failure("vidA", reason=code)
        assert monitor.is_eligible("vidA") is False

    def test_stale_failure_does_not_chain_with_fresh_one(self, monitor: ClientHealthMonitor, clock: FakeClock):
        monitor.record_failure("vidA", reason="NO_STREAM")
        clock.advance(400)  # بیش‌تر از پنجره زنجیره (cooldown)
        monitor.record_failure("vidA", reason="NO_STREAM")
        # شکست قدیم نباید با شکست تازه زنجیر شود → هنوز سالم
        assert monitor.is_eligible("vidA") is True


class TestConcurrency:
    def test_concurrent_failures_are_thread_safe(self, monitor: ClientHealthMonitor):
        def hammer(n: int) -> None:
            for _ in range(50):
                monitor.record_failure("vidA", reason="NO_STREAM")
                assert monitor.is_eligible("vidA") in (True, False)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: hammer(i), range(8)))

        # state باید سازگار باشد: با آستانه ۲، ناسالم شده باشد
        assert monitor.is_eligible("vidA") is False

    def test_concurrent_mixed_traffic_no_crash(self, monitor: ClientHealthMonitor):
        def worker(i: int) -> None:
            for n in range(30):
                vid = f"vid{i % 5}"
                monitor.record_failure(vid, reason="NO_STREAM")
                monitor.record_success(vid, "WEB_REMIX")
                monitor.is_eligible(vid)
                monitor.cleanup()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = monitor.snapshot()
        assert isinstance(snap["clients"], dict)


class TestCleanupAndMemoryBound:
    def test_expired_entries_removed(self, monitor: ClientHealthMonitor, clock: FakeClock):
        monitor.record_failure("vidA", reason="NO_STREAM")
        assert monitor.snapshot()["entry_count"] == 1
        clock.advance(3601)
        removed = monitor.cleanup()
        assert removed == 1
        assert monitor.snapshot()["entry_count"] == 0
        assert monitor.is_eligible("vidA") is True

    def test_max_entries_eviction(self, clock: FakeClock):
        monitor = ClientHealthMonitor(max_entries=10, clock=clock)
        for i in range(20):
            monitor.record_failure(f"vid{i}", reason="NO_STREAM")
        assert monitor.snapshot()["entry_count"] <= 10
        # قدیمی‌ترین‌ها حذف شده‌اند
        assert monitor.is_eligible("vid0") is True
        # تازه‌ها حفظ شده‌اند (آستانه ۲ برای vid19 تکمیل می‌شود)
        monitor.record_failure("vid19", reason="NO_STREAM")
        assert monitor.is_eligible("vid19") is False

    def test_expired_entry_ignored_on_read(self, monitor: ClientHealthMonitor, clock: FakeClock):
        monitor.record_failure("vidA", reason="NO_STREAM")
        monitor.record_failure("vidA", reason="NO_STREAM")
        clock.advance(3601)
        assert monitor.is_eligible("vidA") is True


class TestSecurity:
    def test_snapshot_contains_no_secrets(self, monitor: ClientHealthMonitor):
        monitor.record_failure("vidA", reason="CLIENT_REJECTED")
        monitor.record_success("vidA", "WEB_REMIX")
        monitor.record_failure("vidA", reason="PO_TOKEN_ERROR")

        raw = json.dumps(monitor.snapshot(), default=str)
        for forbidden in ("googlevideo", "sig=", "signature", "po_token=", "cookie",
                          "authorization", "visitor", "session", "https://"):
            assert forbidden.lower() not in raw.lower()

    def test_reason_stored_is_error_code_only(self, monitor: ClientHealthMonitor):
        # حتی اگر پیام خطا طولانی/حساس باشد، فقط کد استاندارد ذخیره می‌شود
        monitor.record_failure("vidA", reason="CLIENT_REJECTED")
        snap = monitor.snapshot()
        entry = snap["clients"]["vidA"]["unknown"]
        assert entry["last_failure_reason"] == "CLIENT_REJECTED"
        assert set(entry.keys()) == {"failure_count", "last_failure_reason", "state"}


# ======================================================================
# یکپارچگی با YouTubeStreamResolver
# ======================================================================


class TestOrchestratorHealthIntegration:
    @pytest.mark.asyncio
    async def test_unhealthy_video_skips_primary_and_uses_fallback_once(
        self, sample_ytdlp_stream_factory
    ):
        monitor = ClientHealthMonitor()
        monitor.record_failure("vid_health", reason="CLIENT_REJECTED")
        monitor.record_failure("vid_health", reason="CLIENT_REJECTED")

        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream_factory("vid_health")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp, client_health=monitor
        )
        result = await resolver.resolve("vid_health")

        mock_itx.resolve_stream.assert_not_called()
        assert mock_ytdlp.resolve_stream.call_count == 1
        assert result.resolver_metadata["fallback_from"] == "innertubex"
        assert result.resolver_metadata["primary_failure"] == "CLIENT_UNHEALTHY"

    @pytest.mark.asyncio
    async def test_unhealthy_and_fallback_failure_raises_all_resolvers_failed(
        self, sample_ytdlp_stream_factory
    ):
        monitor = ClientHealthMonitor()
        monitor.record_failure("vid_health", reason="NO_STREAM")
        monitor.record_failure("vid_health", reason="NO_STREAM")

        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.side_effect = RuntimeError("yt-dlp also failed")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp, client_health=monitor
        )
        with pytest.raises(AllResolversFailedError) as exc_info:
            await resolver.resolve("vid_health")

        mock_itx.resolve_stream.assert_not_called()
        # علت ریشه‌ایِ primary باید حفظ شود
        assert exc_info.value.primary_code == "CLIENT_UNHEALTHY"
        assert isinstance(exc_info.value.primary_error, ClientUnhealthyError)

    @pytest.mark.asyncio
    async def test_two_consecutive_primary_failures_skip_third_primary_attempt(
        self, sample_ytdlp_stream_factory
    ):
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = NoStreamError("InnerTubeX found no stream")
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream_factory("vid_streak")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp
        )

        # دو بار: primary تلاش می‌شود و شکست می‌خورد، فال‌بک نجات می‌دهد
        await resolver.resolve("vid_streak")
        await resolver.resolve("vid_streak")
        assert mock_itx.resolve_stream.call_count == 2

        # بار سوم: primary به‌خاطر health کلاً skip می‌شود
        await resolver.resolve("vid_streak")
        assert mock_itx.resolve_stream.call_count == 2
        assert mock_ytdlp.resolve_stream.call_count == 3

    @pytest.mark.asyncio
    async def test_single_failure_does_not_skip_next_primary_attempt(
        self, sample_ytdlp_stream_factory
    ):
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = NoStreamError("InnerTubeX found no stream")
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream_factory("vid_one")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp
        )
        await resolver.resolve("vid_one")
        await resolver.resolve("vid_one")
        # هر دو بار primary تلاش شده (آستانه ۲ هنوز پر نشده بود در تلاش دوم)
        assert mock_itx.resolve_stream.call_count == 2

    @pytest.mark.asyncio
    async def test_cooldown_expiry_allows_primary_retry(
        self, sample_ytdlp_stream_factory
    ):
        clock = FakeClock()
        monitor = ClientHealthMonitor(clock=clock)
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = NoStreamError("InnerTubeX found no stream")
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream_factory("vid_cd")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp, client_health=monitor
        )
        await resolver.resolve("vid_cd")
        await resolver.resolve("vid_cd")
        assert mock_itx.resolve_stream.call_count == 2

        clock.advance(301)  # cooldown تمام شده → HALF-OPEN
        await resolver.resolve("vid_cd")
        assert mock_itx.resolve_stream.call_count == 3

    @pytest.mark.asyncio
    async def test_primary_success_resets_health(
        self, sample_innertubex_stream_factory, sample_ytdlp_stream_factory
    ):
        clock = FakeClock()
        monitor = ClientHealthMonitor(clock=clock)
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        # دو شکست سپس موفقیت در حالت HALF-OPEN (پس از پایان cooldown)
        mock_itx.resolve_stream.side_effect = [
            NoStreamError("InnerTubeX found no stream"),
            NoStreamError("InnerTubeX found no stream"),
            sample_innertubex_stream_factory("vid_rec"),
        ]
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream_factory("vid_rec")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp, client_health=monitor
        )
        await resolver.resolve("vid_rec")
        await resolver.resolve("vid_rec")
        assert monitor.is_eligible("vid_rec") is False

        clock.advance(301)  # cooldown تمام شد → HALF-OPEN → تلاش مجدد مجاز
        await resolver.resolve("vid_rec")  # موفقیت → record_success → بازیابی

        assert monitor.state_of("vid_rec") == STATE_HEALTHY
        # بعد از بازیابی، یک شکست دیگر نباید فوراً skip کند
        mock_itx.resolve_stream.side_effect = NoStreamError("InnerTubeX found no stream")
        await resolver.resolve("vid_rec")
        assert mock_itx.resolve_stream.await_count == 4

    @pytest.mark.asyncio
    async def test_fallback_success_does_not_reset_health(self, sample_ytdlp_stream_factory):
        monitor = ClientHealthMonitor()
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = NoStreamError("InnerTubeX found no stream")
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream_factory("vid_fb")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp, client_health=monitor
        )
        await resolver.resolve("vid_fb")
        await resolver.resolve("vid_fb")
        assert monitor.is_eligible("vid_fb") is False

        # موفقیت yt-dlp نباید health مسیر InnerTubeX را reset کند
        await resolver.resolve("vid_fb")
        assert mock_itx.resolve_stream.await_count == 2  # بدون تلاش جدید
        assert monitor.is_eligible("vid_fb") is False

    @pytest.mark.asyncio
    async def test_bridge_unavailable_never_skips_primary(
        self, sample_ytdlp_stream_factory
    ):
        monitor = ClientHealthMonitor()
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = BridgeUnavailableError("bridge down")
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream_factory("vid_bridge")

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp, client_health=monitor
        )
        for _ in range(6):
            await resolver.resolve("vid_bridge")
        # Bridge پایین است، نه کلاینت یوتیوب → primary همیشه تلاش می‌شود
        assert mock_itx.resolve_stream.call_count == 6

    @pytest.mark.asyncio
    async def test_health_isolation_between_videos_in_orchestrator(
        self, sample_ytdlp_stream_factory
    ):
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = NoStreamError("InnerTubeX found no stream")
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.side_effect = (
            lambda video_id, purpose="playback", quality=None: sample_ytdlp_stream_factory(video_id)
        )

        resolver = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp
        )
        await resolver.resolve("vidX")
        await resolver.resolve("vidX")

        # ویدیوی دیگر کاملاً سالم است و primary برایش تلاش می‌شود
        await resolver.resolve("vidY")
        assert mock_itx.resolve_stream.call_count == 3
