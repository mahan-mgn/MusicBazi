"""
تست‌های Phase 12 — Rollout Matrix و Soak Validation برای Playback V2.

هیچ production code ای به‌جز افزودن single-flight به مسیر resolve اولیه
(الزام §۴) تغییر نکرده است. این فایل رفتار فازهای ۶-۱۱ را اعتبارسنجی می‌کند:

  A  Flag OFF → legacy، صفر call به resolver جدید
  B  V2 + ready cache → بدون هیچ resolve، سریع‌ترین مسیر
  C  V2 + InnerTubeX=HLS → HLS guard → legacy (بدون loop، بدون proxy روی manifest)
  D  InnerTubeX failure → classification فاز ۶ → دقیقاً یک yt-dlp fallback
  E  runtime 403 → StreamRecovery فاز ۸ → دقیقاً یک re-resolution؛ URL منقضی retry نمی‌شود
  F  500 → بدون recovery → legacy

Soak: ۵۰ attempt ترکیبی + assertions برای task leak، duplicate resolution/recovery،
unbounded health/metrics state و نشت لاگی. Concurrency: ۱۰ هم‌زمان هم‌ویدیو → یک resolve.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app import main, stream_cache
from app.models import Track
from app.stream.client_health import ClientHealthMonitor
from app.stream.errors import (
    BridgeUnavailableError,
    NetworkError,
    NoStreamError,
    StreamRecoveryError,
)
from app.stream.feature_flags import STREAM_V2_FLAG
from app.stream.models import ResolvedStream
from app.stream.playback import LivePlaybackStreamer
from app.stream.resolver import YouTubeStreamResolver
from app.stream.shadow import DEFAULT_SHADOW_METRICS

FLAG_ON = {STREAM_V2_FLAG: "1"}
UPSTREAM_BODY = b"audio-bytes-here" * 16
# فاز ۱۴: manifest HLS واقعی‌نما برای مسیر پروکسی
HLS_MANIFEST_BASE = "https://rr1---sn-abc.googlevideo.com/api/manifest/hls_playlist/id/abc/it/96"
HLS_MANIFEST_TEXT = chr(10).join([
    "#EXTM3U",
    "#EXT-X-VERSION:3",
    "#EXT-X-TARGETDURATION:6",
    "#EXTINF:5.0,",
    HLS_MANIFEST_BASE + "/seg0.ts?sig=SECRET_A",
    "#EXTINF:5.0,",
    HLS_MANIFEST_BASE + "/seg1.ts?sig=SECRET_B",
    "#EXT-X-ENDLIST",
]) + chr(10)


def make_stream(video_id: str = "vidA", stream_type: str = "PROGRESSIVE", **ov) -> ResolvedStream:
    defaults = dict(
        source="youtube",
        url=f"https://rr1---sn-abc.googlevideo.com/videoplayback?id={video_id}&sig=SIG_{video_id}",
        mime_type="audio/webm",
        codec="opus",
        bitrate=160000,
        channels=2,
        duration=200.0,
        expires_at=int(time.time()) + 3600,
        headers={"User-Agent": "ua-test"},
        resolver_metadata={"client_name": "WEB_REMIX", "resolver": "innertubex"},
        stream_type=stream_type,
    )
    defaults.update(ov)
    return ResolvedStream(video_id=video_id, **defaults)


def ytid(name: str) -> str:
    """شناسه ۱۱ کاراکتری معتبر یوتیوب (extractor دقیقاً ۱۱ کاراکتر می‌پذیرد)."""
    return name.ljust(11, "0")


def youtube_track(vid: str = "vidA") -> Track:
    vid = ytid(vid)
    return Track(
        id=vid, title="t", artist="a", durationMs=1000,
        source="youtube", sourceUrl=f"https://www.youtube.com/watch?v={vid}",
    )


class ScriptedUpstream:
    """
    upstream تعیین‌کننده بر اساس نشانه URL (دeterministic و مستقل از ترتیب):
      OLD*      → 403 (شبیه‌سازی انقضای runtime)
      FORCE500* → 500
      بقیه      → 200
    """

    def __init__(self) -> None:
        self.request_urls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.request_urls.append(url)
        if "OLD" in url:
            return httpx.Response(403, content=b"")
        if "FORCE500" in url:
            return httpx.Response(500, content=b"")
        if "hls_playlist" in url and ".ts" in url:
            return httpx.Response(200, content=UPSTREAM_BODY)  # segment
        if "hls_playlist" in url:
            return httpx.Response(200, text=HLS_MANIFEST_TEXT)  # manifest
        return httpx.Response(200, content=UPSTREAM_BODY)


class ScenarioResolver:
    """
   primary resolver شبیه‌سازی‌شده با سناریوی قابل‌تعویض per attempt.
    قرارداد همان YouTubeStreamResolver.resolve است؛ شمارش دقیق نگه می‌دارد.
    """

    def __init__(self) -> None:
        self.kind = "success"
        self.calls: dict[str, int] = {}
        self.total = 0

    async def resolve_stream(self, video_id: str, purpose: str = "playback", quality=None):
        self.total += 1
        self.calls[video_id] = self.calls.get(video_id, 0) + 1
        kind = self.kind
        if kind == "hls":
            return make_stream(
                video_id,
                url=f"{HLS_MANIFEST_BASE}?expire=9999999999&sig=M_{video_id}",
                stream_type="HLS",
            )
        if kind == "itxfail":
            raise BridgeUnavailableError("bridge down", video_id=video_id)
        if kind == "clientfail":
            raise NoStreamError("InnerTubeX found no stream", video_id=video_id)
        if kind == "recovery":
            n = self.calls[video_id]
            if n == 1:
                return make_stream(video_id, url=f"https://rr1.example/{video_id}_OLD")
            return make_stream(video_id, url=f"https://rr1.example/{video_id}_FRESH")
        if kind == "fail500":
            return make_stream(video_id, url=f"https://rr1.example/{video_id}_FORCE500")
        return make_stream(video_id)


def build_stack(monitor: ClientHealthMonitor | None = None):
    """(streamer, scenario, ytdlp_mock, upstream) با orchestration واقعی فاز ۶."""
    monitor = monitor or ClientHealthMonitor()
    scenario = ScenarioResolver()
    mock_ytdlp = AsyncMock(spec=object)
    mock_ytdlp.resolve_stream = AsyncMock(
        return_value=make_stream("fallback", resolver_metadata={"resolver": "yt-dlp", "fallback_from": "innertubex"})
    )
    resolver = YouTubeStreamResolver(
        primary_resolver=scenario, fallback_resolver=mock_ytdlp, client_health=monitor
    )
    upstream = ScriptedUpstream()
    streamer = LivePlaybackStreamer(
        resolver=resolver, http_transport=httpx.MockTransport(upstream.handler)
    )
    return streamer, scenario, mock_ytdlp, upstream, monitor


def handler_call(track: Track, **kwargs):
    return main.stream_audio(
        track_id=track.id, title="t", artist="a", request=None,
        source="youtube", source_url=track.sourceUrl, **kwargs,
    )


def patch_legacy(monkeypatch, ready_file=None):
    calls = {"legacy": 0}

    async def _find_ready(track, quality=None):
        return ready_file

    async def _legacy(track, range_header=None, quality=None):
        calls["legacy"] += 1
        return ("LEGACY_SENTINEL", track.id)

    monkeypatch.setattr(stream_cache, "find_ready_file", _find_ready)
    monkeypatch.setattr(stream_cache, "get_stream_response", _legacy)
    return calls


# ======================================================================
# Rollout Matrix
# ======================================================================


class TestRolloutMatrix:
    @pytest.mark.asyncio
    async def test_a_flag_off_legacy_zero_resolver_calls(self, monkeypatch):
        monkeypatch.delenv(STREAM_V2_FLAG, raising=False)
        monkeypatch.setattr(main, "is_stream_v2_enabled", lambda *a, **k: False)
        streamer, scenario, mock_ytdlp, upstream, _ = build_stack()
        monkeypatch.setattr(main, "get_live_playback", lambda: streamer)
        calls = patch_legacy(monkeypatch)

        result = await handler_call(youtube_track("vidOFF"))

        assert result == ("LEGACY_SENTINEL", ytid("vidOFF"))
        assert calls["legacy"] == 1
        assert scenario.total == 0
        assert mock_ytdlp.resolve_stream.await_count == 0

    @pytest.mark.asyncio
    async def test_b_v2_ready_cache_fastest_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv(STREAM_V2_FLAG, "1")
        monkeypatch.setattr(main, "is_stream_v2_enabled", lambda *a, **k: True)
        calls = patch_legacy(monkeypatch, ready_file=object())  # فایل آماده
        streamer, scenario, mock_ytdlp, upstream, _ = build_stack()
        monkeypatch.setattr(main, "get_live_playback", lambda: streamer)

        t0 = time.perf_counter()
        result = await handler_call(youtube_track("vidB"))
        elapsed = time.perf_counter() - t0

        assert result == ("LEGACY_SENTINEL", ytid("vidB"))
        assert scenario.total == 0  # هیچ resolve ای برای فایل آماده
        assert mock_ytdlp.resolve_stream.await_count == 0
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_c_v2_hls_guard_to_legacy_no_loop(self, monkeypatch):
        """Phase 14: HLS دیگر به legacy نمی‌رود — manifest پروکسی می‌شود؛
        rollback فقط برای unsupported (تست‌های test_hls_proxy)."""
        monkeypatch.setenv(STREAM_V2_FLAG, "1")
        monkeypatch.setattr(main, "is_stream_v2_enabled", lambda *a, **k: True)
        calls = patch_legacy(monkeypatch)
        streamer, scenario, mock_ytdlp, upstream, _ = build_stack()
        scenario.kind = "hls"
        monkeypatch.setattr(main, "get_live_playback", lambda: streamer)

        result = await handler_call(youtube_track("vidC"))

        # manifest بازنویسی‌شده HLS به client می‌رود (نه legacy، نه URL واقعی)
        assert not isinstance(result, tuple)
        assert result.media_type == "application/vnd.apple.mpegurl"
        assert scenario.calls[ytid("vidC")] == 1  # بدون تلاش مجدد
        assert mock_ytdlp.resolve_stream.await_count == 0
        # upstream فقط یک بار برای خود manifest صدا زده شده
        assert len(upstream.request_urls) == 1

    @pytest.mark.asyncio
    async def test_d_innertubex_failure_one_ytdlp_fallback(self, monkeypatch):
        monkeypatch.setenv(STREAM_V2_FLAG, "1")
        monkeypatch.setattr(main, "is_stream_v2_enabled", lambda *a, **k: True)
        calls = patch_legacy(monkeypatch)
        streamer, scenario, mock_ytdlp, upstream, _ = build_stack()
        scenario.kind = "itxfail"
        monkeypatch.setattr(main, "get_live_playback", lambda: streamer)

        result = await handler_call(youtube_track("vidD"))

        # فال‌بک موفق → مستقیماً StreamingResponse (نه legacy)
        assert not isinstance(result, tuple)
        assert result.status_code == 200
        assert scenario.calls[ytid("vidD")] == 1
        assert mock_ytdlp.resolve_stream.await_count == 1  # دقیقاً یک فال‌بک
        assert len(upstream.request_urls) == 1
        assert calls["legacy"] == 0

    @pytest.mark.asyncio
    async def test_e_runtime_403_recovery_one_reresolve_never_retry_old_url(self, monkeypatch):
        monkeypatch.setenv(STREAM_V2_FLAG, "1")
        monkeypatch.setattr(main, "is_stream_v2_enabled", lambda *a, **k: True)
        patch_legacy(monkeypatch)
        streamer, scenario, mock_ytdlp, upstream, _ = build_stack()
        scenario.kind = "recovery"
        monkeypatch.setattr(main, "get_live_playback", lambda: streamer)

        result = await handler_call(youtube_track("vidE"))

        assert result.status_code == 200
        assert scenario.calls[ytid("vidE")] == 2  # ۱ رزولوشن + ۱ recovery
        assert len(upstream.request_urls) == 2
        assert "OLD" in upstream.request_urls[0]
        assert "OLD" not in upstream.request_urls[1]  # URL منقضی retry نشد

    @pytest.mark.asyncio
    async def test_f_500_no_recovery_legacy_fallback(self, monkeypatch):
        monkeypatch.setenv(STREAM_V2_FLAG, "1")
        monkeypatch.setattr(main, "is_stream_v2_enabled", lambda *a, **k: True)
        calls = patch_legacy(monkeypatch)
        streamer, scenario, mock_ytdlp, upstream, _ = build_stack()
        scenario.kind = "fail500"
        monkeypatch.setattr(main, "get_live_playback", lambda: streamer)

        result = await handler_call(youtube_track("vidF"))

        assert result == ("LEGACY_SENTINEL", ytid("vidF"))
        assert scenario.calls[ytid("vidF")] == 1  # بدون recovery
        assert mock_ytdlp.resolve_stream.await_count == 0
        assert calls["legacy"] == 1


# ======================================================================
# Concurrency (§۴)
# ======================================================================


class TestConcurrencySoak:
    @pytest.mark.asyncio
    async def test_ten_concurrent_same_video_single_resolve(self):
        streamer, scenario, _, upstream, _ = build_stack()
        gate = asyncio.Event()
        inner = streamer.resolver.primary  # ScenarioResolver

        async def gated_resolve_stream(video_id, purpose="playback", quality=None):
            await gate.wait()
            return await inner.resolve_stream(video_id, purpose, quality)

        # primary واقعی را با نسخه gated می‌پوشانیم
        class Gated:
            resolve_stream = staticmethod(gated_resolve_stream)

        streamer.resolver.primary = Gated()

        async def one():
            return await streamer.stream_response(youtube_track("vidS1"), env=FLAG_ON)

        tasks = [asyncio.create_task(one()) for _ in range(10)]
        await asyncio.sleep(0.05)  # فرصت ورود همه به single-flight
        gate.set()
        results = await asyncio.gather(*tasks)

        assert all(r.status_code == 200 for r in results)
        # resolve دقیقاً یک بار (single-flight روی bridge/Health)؛ اما بایت‌ها
        # per-consumer است — هر پلیر stream خودش را می‌گیرد (رفتار درست)
        assert scenario.calls == {ytid("vidS1"): 1}
        assert len(upstream.request_urls) == 10
        assert streamer._inflight == {}

    @pytest.mark.asyncio
    async def test_concurrent_different_videos_independent(self):
        streamer, scenario, _, upstream, _ = build_stack()

        vids = [f"vidX{i}" for i in range(10)]
        results = await asyncio.gather(
            *[streamer.stream_response(youtube_track(v), env=FLAG_ON) for v in vids]
        )
        assert all(r.status_code == 200 for r in results)
        assert len(upstream.request_urls) == 10
        assert all(count == 1 for count in scenario.calls.values())  # بدون duplicate


# ======================================================================
# Client Health end-to-end (فاز ۷ — reuse، بدون سیستم جدید)
# ======================================================================


class TestClientHealthSoak:
    @pytest.mark.asyncio
    async def test_full_health_lifecycle_through_playback(self):
        from tests.test_client_health import FakeClock

        clock = FakeClock()
        monitor = ClientHealthMonitor(clock=clock)
        streamer, scenario, mock_ytdlp, upstream, _ = build_stack(monitor)
        # primary با شکست client-failure شکست می‌خورد تا چرخه health دیده شود
        # (BridgeUnavailableError عمداً در health شمرده نمی‌شود — فاز ۷)
        scenario.kind = "clientfail"

        for _ in range(2):
            r = await streamer.stream_response(youtube_track("vidH"), env=FLAG_ON)
            assert r.status_code == 200
        assert monitor.state_of(ytid("vidH")) == "UNHEALTHY"
        assert scenario.calls[ytid("vidH")] == 2

        # تلاش سوم: primary skip می‌شود و فقط yt-dlp صدا زده می‌شود
        r = await streamer.stream_response(youtube_track("vidH"), env=FLAG_ON)
        assert r.status_code == 200
        assert scenario.calls[ytid("vidH")] == 2  # بدون افزایش

        # موفقیت yt-dlp نباید health InnerTubeX را reset کرده باشد
        snap = monitor.snapshot()
        assert snap["clients"][ytid("vidH")]["unknown"]["failure_count"] == 2

        # cooldown تمام → تلاش مجدد primary
        clock.advance(301)
        r = await streamer.stream_response(youtube_track("vidH"), env=FLAG_ON)
        assert r.status_code == 200
        assert scenario.calls[ytid("vidH")] == 3

        # موفقیت primary → HEALTHY و پاک‌شدن entry؛ state بدون secret
        # (شکست تازه در تلاش قبلی cooldown را تمدید کرده — باید تمام شود)
        clock.advance(301)
        scenario.kind = "success"
        r = await streamer.stream_response(youtube_track("vidH"), env=FLAG_ON)
        assert r.status_code == 200
        assert monitor.state_of(ytid("vidH")) == "HEALTHY"
        snap = monitor.snapshot()
        assert ytid("vidH") not in snap["clients"]
        raw = json.dumps(snap).lower()
        assert "googlevideo" not in raw and "sig=" not in raw


# ======================================================================
# Soak — ۵۰ attempt ترکیبی (§۳)
# ======================================================================


class TestSoakFiftyAttempts:
    @pytest.mark.asyncio
    async def test_soak_mixed_50_attempts(self, monkeypatch, caplog):
        monitor = ClientHealthMonitor()
        streamer, scenario, mock_ytdlp, upstream, _ = build_stack(monitor)
        latencies: dict[str, list[float]] = {
            "cache_hit": [], "hls_to_legacy": [], "itx_fallback": [],
            "recovery": [], "legacy_500": [],
        }

        # --- ۱۰×A/B: cache hit در سطح هندلر (نباید هیچ resolve ای ببینند) ---
        monkeypatch.setenv(STREAM_V2_FLAG, "1")
        monkeypatch.setattr(main, "is_stream_v2_enabled", lambda *a, **k: True)
        patch_legacy(monkeypatch, ready_file=object())
        monkeypatch.setattr(main, "get_live_playback", lambda: streamer)
        baseline_resolves = scenario.total

        for i in range(10):
            t0 = time.perf_counter()
            result = await handler_call(youtube_track(f"vidCH{i}"))
            latencies["cache_hit"].append(time.perf_counter() - t0)
            assert result == ("LEGACY_SENTINEL", ytid(f"vidCH{i}"))
        assert scenario.total == baseline_resolves  # cache hit صفر resolve

        # --- ۴۰ attempt در سطح streamer ---
        for i in range(10):
            # C: HLS → proxy manifest (فاز ۱۴؛ rollback فقط برای unsupported)
            scenario.kind = "hls"
            t0 = time.perf_counter()
            r = await streamer.stream_response(youtube_track(f"soak_hls_{i}"), env=FLAG_ON)
            latencies["hls_to_legacy"].append(time.perf_counter() - t0)
            assert r is not None and r.media_type == "application/vnd.apple.mpegurl"
            assert b"googlevideo" not in r.body

            # D: InnerTubeX failure → دقیقاً یک fallback
            scenario.kind = "itxfail"
            t0 = time.perf_counter()
            r = await streamer.stream_response(youtube_track(f"soak_fb_{i}"), env=FLAG_ON)
            latencies["itx_fallback"].append(time.perf_counter() - t0)
            assert r.status_code == 200
            assert scenario.calls[ytid(f"soak_fb_{i}")] == 1

            # E: runtime 403 → recovery → دقیقاً ۲ resolve و استریم تازه
            scenario.kind = "recovery"
            t0 = time.perf_counter()
            r = await streamer.stream_response(youtube_track(f"soak_rec_{i}"), env=FLAG_ON)
            latencies["recovery"].append(time.perf_counter() - t0)
            assert r.status_code == 200
            assert scenario.calls[ytid(f"soak_rec_{i}")] == 2  # بدون duplicate recovery

            # F: 500 → بدون recovery → خطای classified
            scenario.kind = "fail500"
            t0 = time.perf_counter()
            with pytest.raises(NetworkError):
                await streamer.stream_response(youtube_track(f"soak_l5_{i}"), env=FLAG_ON)
            latencies["legacy_500"].append(time.perf_counter() - t0)
            assert scenario.calls[ytid(f"soak_l5_{i}")] == 1

        # --- ادعاهای نهایی soak ---
        assert scenario.total == 50  # ۱۰×(hls:1 + fallback:1 + recovery:2 + 500:1) — بدون duplicate
        assert mock_ytdlp.resolve_stream.await_count == 10  # فقط برای itxfail ها
        expected_proxy = 10 + 10 + 20 + 10  # hls:1 manifest x10, fallback:1 x10, recovery:2 x10, 500:1 x10
        assert len(upstream.request_urls) == expected_proxy

        # recovery پروکسی هرگز OLD را دوباره نزده است
        assert not any("OLD" in u and u in upstream.request_urls[1:] and
                       upstream.request_urls[upstream.request_urls.index(u) - 1] == u
                       for u in upstream.request_urls)
        duplicate_back_to_back = any(
            upstream.request_urls[k] == upstream.request_urls[k - 1]
            for k in range(1, len(upstream.request_urls))
        )
        assert not duplicate_back_to_back  # هیچ URL منقضی‌ای بلافاصله retry نشده

        # health state محدود و بدون secret
        snap = monitor.snapshot()
        assert snap["entry_count"] <= 50
        raw_snap = json.dumps(snap).lower()
        for forbidden in ("googlevideo", "https://", "sig=", "cookie", "authorization", "visitor", "session"):
            assert forbidden not in raw_snap

        # shadow metrics توسط playback واقعی تغییر نمی‌کند (بدون double counting)
        DEFAULT_SHADOW_METRICS.reset()
        before = DEFAULT_SHADOW_METRICS.snapshot()
        scenario.kind = "success"
        r = await streamer.stream_response(youtube_track("soak_metric_probe"), env=FLAG_ON)
        assert r is not None and r.status_code == 200
        assert DEFAULT_SHADOW_METRICS.snapshot() == before

        # task leak: همه task ها تمام شده و inflight خالی است
        pending = [t for t in asyncio.all_tasks() if not t.done()]
        assert len(pending) <= 1
        assert streamer._inflight == {}

        # امنیت کل soak در لاگ‌ها
        combined = " ".join(r.getMessage() for r in caplog.records).lower()
        for forbidden in ("googlevideo", "sig=", "signature=", "cookie", "authorization", "po_token", "visitor"):
            assert forbidden not in combined

        # latency: همه مسیرها in-process و زیر سقف منطقی
        for path, values in latencies.items():
            assert values and max(values) < 5.0, f"{path}: {max(values)}"

    @pytest.mark.asyncio
    async def test_soak_recovery_never_loops_on_persistent_rejection(self):
        """۵ attempt پشت‌سرهم با rejection پایدار → همیشه دقیقاً ۲ resolve و توقف."""
        streamer, scenario, _, upstream, _ = build_stack()
        scenario.kind = "recovery"
        # حتی استریم تازه رد می‌شود — transport 403 از ابتدا (با شمارش درخواست‌ها)
        seen_urls: list[str] = []

        def always403_handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            return httpx.Response(403, content=b"")

        streamer = LivePlaybackStreamer(
            resolver=streamer.resolver,
            http_transport=httpx.MockTransport(always403_handler),
        )

        for i in range(5):
            from app.stream.playback import StreamRecoverySafe
            with pytest.raises(StreamRecoverySafe):
                await streamer.stream_response(youtube_track(f"vidL{i}"), env=FLAG_ON)
            assert scenario.calls[ytid(f"vidL{i}")] == 2  # هرگز بیش از ۲
        assert len(seen_urls) == 10


# ======================================================================
# Backward Compatibility (قرارداد فعلی حفظ می‌شود)
# ======================================================================


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_legacy_file_response_contract_intact(
        self, monkeypatch, tmp_path, fresh_db, track
    ):
        """Web/Android قرارداد فعلی (FileResponse با Range/CORS) را می‌بینند."""
        cache_file = tmp_path / "str_abc.m4a"
        cache_file.write_bytes(b"\x00" * 128)
        monkeypatch.setattr(stream_cache.db, "find_any_ready", lambda *a, **k: None)
        monkeypatch.setattr(stream_cache, "_find_cached_audio", lambda key: cache_file)

        resp = await stream_cache.get_stream_response(track, range_header=None, quality=None)
        assert type(resp).__name__ == "FileResponse"
        assert resp.media_type == "audio/mp4"
        assert resp.headers.get("accept-ranges") == "bytes"
        assert resp.headers.get("access-control-allow-origin") == "*"
