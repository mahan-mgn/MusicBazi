"""
تست‌های Phase 10 — Shadow Mode Validation و Rollout Observability.

پوشش:
1. Counters: total/success/failure، innertubex_success، ytdlp_fallback
2. Metadata match/mismatch + mismatch_by_field (codec/bitrate/duration/stream_type)
3. failure_by_code aggregation بدون ورود پیام استثنا
4. Latency با monotonic clock ثبت و aggregate می‌شود
5. Snapshot: consistent، امن، بدون secret
6. Reset: کامل و بدون corruption، حتی هم‌زمان با observation
7. Thread/Async safety: بدون lost update
8. Feature Flag: OFF → هیچ Shadow work/metrics؛ ON → فعال؛ default OFF
9. Isolation: Production result mutate نمی‌شود
10. Performance sanity: overhead منطقی، سقف task فاز ۹، بدون exception unhandled
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest

from app.stream import (
    AllResolversFailedError,
    NoStreamError,
    ResolvedStream,
    STREAM_V2_FLAG,
    ShadowComparison,
    ShadowMetrics,
    ShadowStreamResolver,
    YouTubeStreamResolver,
    is_stream_v2_enabled,
)
from app.stream.shadow import (
    DEFAULT_SHADOW_METRICS,
    MAX_INFLIGHT_SHADOW_TASKS,
    compare_streams,
)
from app.stream.shadow_metrics import MAX_DISTINCT_FAILURE_CODES  # noqa: F401

FLAG_ENV_ON = {STREAM_V2_FLAG: "1"}
FLAG_ENV_OFF = {STREAM_V2_FLAG: "0"}


def make_stream(video_id: str = "vid_m", **overrides) -> ResolvedStream:
    defaults = dict(
        source="youtube",
        url="https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=PROD_SIG",
        mime_type="audio/webm",
        codec="opus",
        bitrate=160000,
        sample_rate=48000,
        channels=2,
        duration=215.0,
        content_length=3500000,
        expires_at=int(time.time()) + 3600,
        resolver_metadata={"client_name": "WEB_REMIX", "resolver": "innertubex"},
    )
    defaults.update(overrides)
    return ResolvedStream(video_id=video_id, **defaults)


def comparison_of(production, shadow, **kwargs) -> ShadowComparison:
    return compare_streams("vid_m", production, shadow, **kwargs)


@pytest.fixture
def metrics() -> ShadowMetrics:
    return ShadowMetrics()


@pytest.fixture
def shadow_mock() -> AsyncMock:
    return AsyncMock(spec=YouTubeStreamResolver)


# ======================================================================
# Metrics Counters
# ======================================================================


class TestMetricsCounters:
    def test_success_counter(self, metrics: ShadowMetrics):
        metrics.record_observation(
            comparison_of(make_stream(), make_stream(url="https://s.example/2")), 12.0
        )
        snap = metrics.snapshot()
        assert snap["total"] == 1
        assert snap["success"] == 1
        assert snap["failure"] == 0
        assert snap["innertubex_success"] == 1
        assert snap["ytdlp_fallback"] == 0

    def test_failure_counter_with_code(self, metrics: ShadowMetrics):
        metrics.record_observation(
            comparison_of(None, None, shadow_error_code="BRIDGE_UNAVAILABLE"), 5.0
        )
        snap = metrics.snapshot()
        assert snap["total"] == 1
        assert snap["success"] == 0
        assert snap["failure"] == 1
        assert snap["failure_by_code"] == {"BRIDGE_UNAVAILABLE": 1}

    def test_innertubex_vs_ytdlp_fallback(self, metrics: ShadowMetrics):
        itx = make_stream()  # resolver=innertubex بدون fallback_from
        fallback = make_stream(
            resolver_metadata={"resolver": "yt-dlp", "fallback_from": "innertubex"}
        )
        metrics.record_observation(comparison_of(make_stream(), itx), 10.0)
        metrics.record_observation(comparison_of(make_stream(), itx), 10.0)
        metrics.record_observation(comparison_of(make_stream(), fallback), 20.0)
        snap = metrics.snapshot()
        assert snap["innertubex_success"] == 2
        assert snap["ytdlp_fallback"] == 1
        assert snap["total"] == 3

    def test_metadata_match_and_mismatch(self, metrics: ShadowMetrics):
        metrics.record_observation(comparison_of(make_stream(), make_stream()), 5.0)
        metrics.record_observation(
            comparison_of(make_stream(), make_stream(codec="mp4a.40.2")), 5.0
        )
        snap = metrics.snapshot()
        assert snap["metadata_match"] == 1
        assert snap["metadata_mismatch"] == 1
        assert snap["mismatch_by_field"] == {"codec": 1}

    def test_mismatch_not_counted_when_outcomes_differ(self, metrics: ShadowMetrics):
        # Production شکست + Shadow موفق → metadata_match/mismatch شمرده نمی‌شود
        metrics.record_observation(
            comparison_of(None, make_stream(), production_error="ALL_RESOLVERS_FAILED"), 5.0
        )
        snap = metrics.snapshot()
        assert snap["metadata_match"] == 0
        assert snap["metadata_mismatch"] == 0


# ======================================================================
# Mismatch Analysis
# ======================================================================


class TestMismatchAnalysis:
    @pytest.mark.parametrize(
        "override,field_name",
        [
            ({"codec": "mp4a.40.2"}, "codec"),
            ({"bitrate": 128000}, "bitrate"),
            ({"duration": 180.0}, "duration"),
            ({"stream_type": "HLS"}, "stream_type"),
        ],
    )
    def test_single_field_mismatch(self, metrics: ShadowMetrics, override, field_name):
        metrics.record_observation(comparison_of(make_stream(), make_stream(**override)), 1.0)
        assert metrics.snapshot()["mismatch_by_field"] == {field_name: 1}

    def test_multiple_mismatch_fields(self, metrics: ShadowMetrics):
        shadow = make_stream(codec="mp4a.40.2", bitrate=128000, sample_rate=44100)
        metrics.record_observation(comparison_of(make_stream(), shadow), 1.0)
        snap = metrics.snapshot()
        assert snap["metadata_mismatch"] == 1
        assert snap["mismatch_by_field"] == {"bitrate": 1, "codec": 1, "sample_rate": 1}

    def test_mismatch_by_field_is_bounded(self):
        m = ShadowMetrics(max_mismatch_fields=2)
        for i, codec in enumerate(["c1", "c2", "c3", "c4"]):
            m.record_observation(
                comparison_of(make_stream(), make_stream(codec=codec)), 1.0
            )
        snap = m.snapshot()
        # دو فیلد متمایز اول نگه داشته می‌شوند؛ بقیه در bucket سرریز جمع می‌شوند
        assert snap["mismatch_by_field"] == {"codec": 4}
        # سقف متمایزها با فیلدهای متفاوت تست می‌شود
        m2 = ShadowMetrics(max_mismatch_fields=2)
        for override in ({"codec": "x"}, {"bitrate": 1}, {"sample_rate": 1}, {"channels": 5}):
            m2.record_observation(
                comparison_of(make_stream(), make_stream(**override)), 1.0
            )
        snap2 = m2.snapshot()
        assert snap2["mismatch_by_field"] == {"bitrate": 1, "codec": 1, "other": 2}


# ======================================================================
# Failure Analysis & Security
# ======================================================================


class TestFailureAnalysis:
    def test_failure_codes_aggregate(self, metrics: ShadowMetrics):
        for code in ["TIMEOUT", "TIMEOUT", "NO_STREAM", "CLIENT_REJECTED"]:
            metrics.record_observation(
                comparison_of(None, None, shadow_error_code=code), 5.0
            )
        snap = metrics.snapshot()
        assert snap["failure_by_code"] == {
            "CLIENT_REJECTED": 1,
            "NO_STREAM": 1,
            "TIMEOUT": 2,
        }

    def test_failure_codes_bounded(self):
        m = ShadowMetrics(max_failure_codes=3)
        for i in range(6):
            m.record_observation(
                comparison_of(None, None, shadow_error_code=f"CODE_{i}"), 1.0
            )
        snap = m.snapshot()
        # سه کد متمایز اول نگه داشته می‌شوند؛ بقیه در bucket سرریز جمع می‌شوند
        assert snap["failure_by_code"] == {
            "CODE_0": 1,
            "CODE_1": 1,
            "CODE_2": 1,
            "other": 3,
        }

    @pytest.mark.asyncio
    async def test_exception_message_never_enters_metrics(
        self, shadow_mock: AsyncMock, metrics: ShadowMetrics
    ):
        secret = "failed fetching https://rr1---sn.googlevideo.com/videoplayback?sig=SECRET&cookie=SID"
        shadow_mock.resolve.side_effect = RuntimeError(secret)
        service = ShadowStreamResolver(shadow_resolver=shadow_mock, metrics=metrics)

        comparison = await service.observe("vid_secret", env=FLAG_ENV_ON)

        raw = json.dumps(metrics.snapshot(), default=str).lower()
        for forbidden in ("googlevideo", "https://", "sig=", "secret", "cookie", "videoplayback"):
            assert forbidden not in raw
        # فقط کلاس خطا ثبت شده
        assert comparison.shadow_error_code == "RuntimeError"
        assert metrics.snapshot()["failure_by_code"] == {"RUNTIMEERROR": 1}


# ======================================================================
# Latency
# ======================================================================


class TestLatency:
    def test_latency_recorded_and_aggregated(self, metrics: ShadowMetrics):
        metrics.record_observation(comparison_of(make_stream(), make_stream()), 10.0)
        metrics.record_observation(comparison_of(make_stream(), make_stream()), 30.0)
        snap = metrics.snapshot()
        assert snap["latency_count"] == 2
        assert snap["latency_total_ms"] == 40.0
        assert snap["latency_avg_ms"] == 20.0
        assert snap["latency_max_ms"] == 30.0

    def test_negative_latency_is_clamped(self, metrics: ShadowMetrics):
        metrics.record_observation(comparison_of(make_stream(), make_stream()), -5.0)
        assert metrics.snapshot()["latency_total_ms"] == 0.0

    @pytest.mark.asyncio
    async def test_observe_measures_real_latency(
        self, shadow_mock: AsyncMock, metrics: ShadowMetrics
    ):
        async def slow(*args, **kwargs):
            await asyncio.sleep(0.03)
            return make_stream()

        shadow_mock.resolve.side_effect = slow
        service = ShadowStreamResolver(shadow_resolver=shadow_mock, metrics=metrics)
        await service.observe("vid_lat", production_stream=make_stream(), env=FLAG_ENV_ON)

        snap = metrics.snapshot()
        assert snap["latency_count"] == 1
        assert snap["latency_avg_ms"] >= 25.0  # monotonic clock واقعی


# ======================================================================
# Snapshot
# ======================================================================


class TestSnapshot:
    def test_snapshot_structure_and_consistency(self, metrics: ShadowMetrics):
        metrics.record_observation(comparison_of(make_stream(), make_stream()), 5.0)
        snap = metrics.snapshot()
        expected_keys = {
            "total", "success", "failure", "innertubex_success", "ytdlp_fallback",
            "metadata_match", "metadata_mismatch", "latency_total_ms", "latency_count",
            "latency_avg_ms", "latency_max_ms", "failure_by_code", "mismatch_by_field",
        }
        assert set(snap.keys()) == expected_keys
        assert snap["total"] == snap["success"] + snap["failure"]
        # snapshot دو بار پشت‌سرهم یکسان است (consistent read)
        assert metrics.snapshot() == snap

    def test_snapshot_contains_no_secrets(self, metrics: ShadowMetrics):
        metrics.record_observation(
            comparison_of(
                make_stream(url="https://rr1.googlevideo.com/x?sig=TOPSECRET"),
                make_stream(url="https://rr2.googlevideo.com/y?sig=SHADOWSECRET"),
            ),
            5.0,
        )
        metrics.record_observation(
            comparison_of(None, None, shadow_error_code="PO_TOKEN_ERROR"), 5.0
        )
        raw = json.dumps(metrics.snapshot(), default=str).lower()
        for forbidden in ("googlevideo", "https://", "sig=", "topsecret", "shadowsecret",
                          "cookie", "authorization", "visitor", "session", "vid_m"):
            assert forbidden not in raw

    @pytest.mark.asyncio
    async def test_snapshot_during_concurrent_observations_does_not_crash(
        self, metrics: ShadowMetrics
    ):
        stop = asyncio.Event()

        async def observer_loop():
            n = 0
            while not stop.is_set():
                metrics.record_observation(comparison_of(make_stream(), make_stream()), 1.0)
                n += 1
                await asyncio.sleep(0)
            return n

        async def snapshot_loop():
            snaps = 0
            while not stop.is_set():
                snap = metrics.snapshot()
                # snapshot همیشه consistent است: total == success + failure
                assert snap["total"] == snap["success"] + snap["failure"]
                snaps += 1
                await asyncio.sleep(0)
            return snaps

        async def runner():
            t1 = asyncio.create_task(observer_loop())
            t2 = asyncio.create_task(snapshot_loop())
            await asyncio.sleep(0.1)
            stop.set()
            return await asyncio.gather(t1, t2)

        observed, snapshots = await runner()
        assert observed > 0 and snapshots > 0


# ======================================================================
# Reset
# ======================================================================


class TestReset:
    def test_reset_clears_all_counters(self, metrics: ShadowMetrics):
        metrics.record_observation(comparison_of(make_stream(), make_stream()), 5.0)
        metrics.record_observation(
            comparison_of(None, None, shadow_error_code="TIMEOUT"), 5.0
        )
        metrics.reset()
        snap = metrics.snapshot()
        assert snap["total"] == 0
        assert snap["success"] == 0
        assert snap["failure"] == 0
        assert snap["failure_by_code"] == {}
        assert snap["latency_count"] == 0

    def test_reset_then_record_no_corruption(self, metrics: ShadowMetrics):
        metrics.record_observation(comparison_of(make_stream(), make_stream()), 5.0)
        metrics.reset()
        metrics.record_observation(comparison_of(make_stream(), make_stream()), 7.0)
        snap = metrics.snapshot()
        assert snap["total"] == 1
        assert snap["latency_total_ms"] == 7.0

    def test_reset_during_concurrent_observations_no_crash(self, metrics: ShadowMetrics):
        def worker(_):
            for _ in range(200):
                metrics.record_observation(comparison_of(make_stream(), make_stream()), 1.0)

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(worker, i) for i in range(6)]
            # reset هم‌زمان با observation ها
            pool.submit(metrics.reset)
            pool.submit(metrics.snapshot)
            [f.result() for f in futures]

        snap = metrics.snapshot()
        assert snap["total"] == snap["success"] + snap["failure"]


# ======================================================================
# Feature Flag Interaction
# ======================================================================


class TestFeatureFlagInteraction:
    def test_default_flag_is_still_off(self):
        import os

        env_without_flag = {k: v for k, v in os.environ.items() if k != STREAM_V2_FLAG}
        assert is_stream_v2_enabled(env_without_flag) is False

    def test_flag_off_records_no_metrics(self, shadow_mock: AsyncMock, metrics: ShadowMetrics):
        service = ShadowStreamResolver(shadow_resolver=shadow_mock, metrics=metrics)
        asyncio.run(service.observe("vid_off", production_stream=make_stream(), env=None))
        shadow_mock.resolve.assert_not_called()
        assert metrics.snapshot()["total"] == 0

    @pytest.mark.asyncio
    async def test_flag_on_records_metrics(self, shadow_mock: AsyncMock, metrics: ShadowMetrics):
        shadow_mock.resolve.return_value = make_stream()
        service = ShadowStreamResolver(shadow_resolver=shadow_mock, metrics=metrics)
        await service.observe("vid_on", production_stream=make_stream(), env=FLAG_ENV_ON)
        assert metrics.snapshot()["total"] == 1


# ======================================================================
# Isolation
# ======================================================================


class TestIsolation:
    @pytest.mark.asyncio
    async def test_metrics_do_not_mutate_production_result(
        self, shadow_mock: AsyncMock, metrics: ShadowMetrics
    ):
        import copy

        shadow_mock.resolve.return_value = make_stream(url="https://s.example/shadow")
        service = ShadowStreamResolver(shadow_resolver=shadow_mock, metrics=metrics)

        production = make_stream()
        snapshot_before = copy.deepcopy(production.model_dump())
        await service.observe("vid_iso", production_stream=production, env=FLAG_ENV_ON)

        assert production.model_dump() == snapshot_before

    @pytest.mark.asyncio
    async def test_shadow_failure_leaves_production_unaffected(
        self, shadow_mock: AsyncMock, metrics: ShadowMetrics
    ):
        shadow_mock.resolve.side_effect = NoStreamError("no stream")
        service = ShadowStreamResolver(shadow_resolver=shadow_mock, metrics=metrics)

        production = make_stream()
        comparison = await service.observe(
            "vid_iso2", production_stream=production, env=FLAG_ENV_ON
        )
        assert comparison.production_outcome == "success"
        assert comparison.shadow_outcome == "failure"
        assert metrics.snapshot()["failure"] == 1


# ======================================================================
# Performance Sanity
# ======================================================================


class TestPerformanceSanity:
    def test_metrics_overhead_is_reasonable(self, metrics: ShadowMetrics):
        start = time.monotonic()
        for _ in range(1000):
            metrics.record_observation(comparison_of(make_stream(), make_stream()), 1.0)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0  # ۱۰۰۰ observation در چند ثانیه — overhead ناچیز
        assert metrics.snapshot()["total"] == 1000

    @pytest.mark.asyncio
    async def test_task_limit_and_no_unhandled_exceptions(
        self, shadow_mock: AsyncMock, metrics: ShadowMetrics
    ):
        gate = asyncio.Event()

        async def hanging(*args, **kwargs):
            await gate.wait()
            raise NoStreamError("no stream")

        shadow_mock.resolve.side_effect = hanging
        service = ShadowStreamResolver(shadow_resolver=shadow_mock, metrics=metrics)

        tasks = [service.spawn_observation(f"vid_p{i}", env=FLAG_ENV_ON) for i in range(MAX_INFLIGHT_SHADOW_TASKS + 3)]
        spawned = [t for t in tasks if t is not None]
        assert len(spawned) == MAX_INFLIGHT_SHADOW_TASKS  # سقف فاز ۹ برقرار است

        gate.set()
        results = await asyncio.gather(*spawned)
        # همه exception ها توسط observe drain شده‌اند → هیچ unhandled نیست
        assert all(t.exception() is None for t in spawned)
        assert all(r.shadow_outcome == "failure" for r in results)
        assert metrics.snapshot()["failure"] == MAX_INFLIGHT_SHADOW_TASKS

    @pytest.mark.asyncio
    async def test_default_singleton_metrics_wired(self, shadow_mock: AsyncMock):
        """ShadowStreamResolver بدون تزریق به نمونه مشترک وصل است."""
        DEFAULT_SHADOW_METRICS.reset()
        shadow_mock.resolve.return_value = make_stream()
        service = ShadowStreamResolver(shadow_resolver=shadow_mock)
        await service.observe("vid_singleton", env=FLAG_ENV_ON)
        assert DEFAULT_SHADOW_METRICS.snapshot()["total"] == 1
