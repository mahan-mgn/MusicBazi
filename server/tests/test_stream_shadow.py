"""
تست‌های Phase 9 — Feature Flag (MUSICBAZI_STREAM_V2) و Shadow Mode.

پوشش:
1. Feature Flag: پیش‌فرض OFF، روشن/خاموش صریح، مقدار invalid → امن (OFF)
2. Flag خاموش → Production path بدون هیچ تغییری (Shadow اصلاً اجرا نمی‌شود)
3. Shadow موفق / شکست‌خورده / ایزوله‌شدن exception آن
4. Production موفق + Shadow شکست → Production همچنان موفق
5. Production شکست + Shadow موفق → نتیجه Shadow هرگز جایگزین نمی‌شود
6. Shadow نتیجه Production را mutate نمی‌کند
7. Comparison: فیلدهای متفاوت (codec/bitrate/duration/stream_type) بدون URL
8. Async Task با drain-callback (هیچ exception unhandled نمی‌ماند) + سقف inflight
9. امنیت: هیچ signed URL/cookie/token در comparison و لاگ‌ها
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from unittest.mock import AsyncMock

import pytest

from app.stream import (
    AllResolversFailedError,
    ExpiredStreamError,
    NetworkError,
    NoStreamError,
    ResolvedStream,
    SHADOW_COMPARE_FIELDS,
    STREAM_V2_FLAG,
    ShadowComparison,
    ShadowStreamResolver,
    YouTubeStreamResolver,
    is_stream_v2_enabled,
)
from app.stream.shadow import MAX_INFLIGHT_SHADOW_TASKS, compare_streams

FLAG_ENV_ON = {STREAM_V2_FLAG: "1"}
FLAG_ENV_OFF = {STREAM_V2_FLAG: "0"}


def make_stream(video_id: str = "vid_shadow", **overrides) -> ResolvedStream:
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


@pytest.fixture
def shadow_resolver_mock() -> AsyncMock:
    return AsyncMock(spec=YouTubeStreamResolver)


# ======================================================================
# Feature Flag
# ======================================================================


class TestFeatureFlag:
    @pytest.mark.parametrize("missing_env", [None, {}])
    def test_default_is_off(self, missing_env):
        assert is_stream_v2_enabled(missing_env) is False

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", "on", " on "])
    def test_explicit_enable(self, raw):
        assert is_stream_v2_enabled({STREAM_V2_FLAG: raw}) is True

    @pytest.mark.parametrize("raw", ["0", "false", "FALSE", "No", "off", ""])
    def test_explicit_disable(self, raw):
        assert is_stream_v2_enabled({STREAM_V2_FLAG: raw}) is False

    @pytest.mark.parametrize("raw", ["banana", "2", "enable!", "tru", "٠١"])
    def test_invalid_value_is_safely_off(self, raw, caplog):
        with caplog.at_level(logging.WARNING, logger="app.stream.feature_flags"):
            assert is_stream_v2_enabled({STREAM_V2_FLAG: raw}) is False

    def test_flag_reads_process_environment(self, monkeypatch):
        monkeypatch.setenv(STREAM_V2_FLAG, "1")
        assert is_stream_v2_enabled() is True
        monkeypatch.setenv(STREAM_V2_FLAG, "0")
        assert is_stream_v2_enabled() is False
        monkeypatch.delenv(STREAM_V2_FLAG)
        assert is_stream_v2_enabled() is False

    def test_flag_off_keeps_production_path_untouched(self, shadow_resolver_mock: AsyncMock):
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        # observe با flag خاموش: هیچ resolve ای اجرا نمی‌شود
        result = asyncio.run(
            service.observe("vid_x", production_stream=make_stream(), env=None)
        )
        assert result is None
        shadow_resolver_mock.resolve.assert_not_called()

        # spawn هم هیچ Task ای نمی‌سازد
        assert service.spawn_observation("vid_x", env=None) is None
        shadow_resolver_mock.resolve.assert_not_called()


# ======================================================================
# Shadow Mode
# ======================================================================


class TestShadowMode:
    @pytest.mark.asyncio
    async def test_shadow_success_returns_comparison(self, shadow_resolver_mock: AsyncMock):
        shadow_stream = make_stream(url="https://shadow.example/videoplayback?id=x&sig=SHADOW_SIG")
        shadow_resolver_mock.resolve.return_value = shadow_stream
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        production = make_stream()
        comparison = await service.observe(
            "vid_s", production_stream=production, env=FLAG_ENV_ON
        )

        assert isinstance(comparison, ShadowComparison)
        assert comparison.production_outcome == "success"
        assert comparison.shadow_outcome == "success"
        assert comparison.shadow_path == "innertubex"
        assert comparison.matches is True
        assert comparison.differences == {}
        assert isinstance(comparison.to_dict(), dict)

    @pytest.mark.asyncio
    async def test_shadow_failure_is_isolated(self, shadow_resolver_mock: AsyncMock):
        shadow_resolver_mock.resolve.side_effect = AllResolversFailedError(
            video_id="vid_f",
            primary_error=NoStreamError("no stream", video_id="vid_f"),
            fallback_error=NetworkError("net", video_id="vid_f"),
        )
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        # observe نباید raise کند — خطای Shadow فقط Diagnostic است
        comparison = await service.observe("vid_f", env=FLAG_ENV_ON)

        assert comparison.shadow_outcome == "failure"
        assert comparison.shadow_error_code == "ALL_RESOLVERS_FAILED"
        assert comparison.production_outcome == "failure"  # production هم موجود نبود

    @pytest.mark.asyncio
    async def test_unexpected_shadow_exception_is_isolated(self, shadow_resolver_mock: AsyncMock):
        shadow_resolver_mock.resolve.side_effect = RuntimeError("boom")
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        comparison = await service.observe("vid_u", env=FLAG_ENV_ON)
        assert comparison.shadow_outcome == "failure"
        assert comparison.shadow_error_code == "RuntimeError"

    @pytest.mark.asyncio
    async def test_production_success_survives_shadow_failure(
        self, shadow_resolver_mock: AsyncMock
    ):
        """Production موفق + Shadow شکست → Production همچنان موفق است."""
        shadow_resolver_mock.resolve.side_effect = RuntimeError("shadow down")
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        production = make_stream()
        comparison = await service.observe(
            "vid_pf", production_stream=production, env=FLAG_ENV_ON
        )

        assert comparison.production_outcome == "success"
        assert comparison.shadow_outcome == "failure"
        # خروجی تابع فقط یک Diagnostic است؛ هیچ stream ای به‌عنوان نتیجه برگردانده نشده
        assert not isinstance(comparison, ResolvedStream)

    @pytest.mark.asyncio
    async def test_shadow_result_never_replaces_production(
        self, shadow_resolver_mock: AsyncMock
    ):
        """Production شکست + Shadow موفق → رفتار Production بدون تغییر می‌ماند."""
        shadow_stream = make_stream(url="https://shadow.example/videoplayback?id=x&sig=SHADOW_SIG")
        shadow_resolver_mock.resolve.return_value = shadow_stream
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        comparison = await service.observe(
            "vid_ps",
            production_stream=None,
            production_error_code="ALL_RESOLVERS_FAILED",
            env=FLAG_ENV_ON,
        )

        assert comparison.production_outcome == "failure"
        assert comparison.shadow_outcome == "success"
        assert comparison.matches is False
        # نتیجه Shadow به‌هیچ‌شکلی به‌عنوان stream بازگردانده نشده است
        assert not isinstance(comparison, ResolvedStream)

    @pytest.mark.asyncio
    async def test_shadow_does_not_mutate_production_stream(
        self, shadow_resolver_mock: AsyncMock
    ):
        shadow_stream = make_stream(url="https://shadow.example/videoplayback?id=x&sig=SHADOW_SIG")
        shadow_resolver_mock.resolve.return_value = shadow_stream
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        production = make_stream()
        snapshot = copy.deepcopy(production.model_dump())
        await service.observe("vid_m", production_stream=production, env=FLAG_ENV_ON)

        assert production.model_dump() == snapshot

    @pytest.mark.asyncio
    async def test_shadow_receives_only_video_id_semantics(
        self, shadow_resolver_mock: AsyncMock
    ):
        """Shadow با همان purpose/quality و video_id رزولوشن می‌گیرد (نه URL قدیمی)."""
        shadow_resolver_mock.resolve.return_value = make_stream()
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        await service.observe(
            "vid_args", production_stream=make_stream(), env=FLAG_ENV_ON
        )
        _, kwargs = shadow_resolver_mock.resolve.call_args
        assert kwargs == {"video_id": "vid_args", "purpose": "playback", "quality": None}

    @pytest.mark.asyncio
    async def test_empty_video_id_is_caller_bug_not_shadow_failure(
        self, shadow_resolver_mock: AsyncMock
    ):
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)
        with pytest.raises(ValueError):
            await service.observe("  ", env=FLAG_ENV_ON)
        shadow_resolver_mock.resolve.assert_not_called()


# ======================================================================
# Comparison Model
# ======================================================================


class TestComparisonModel:
    def test_compare_fields_exclude_sensitive_entries(self):
        forbidden = {"url", "headers", "expires_at"}
        assert not (set(SHADOW_COMPARE_FIELDS) & forbidden)

    def test_identical_metadata_matches(self):
        comparison = compare_streams("vid_c", make_stream(), make_stream(url="https://shadow.example/videoplayback?id=x&sig=S2"))
        assert comparison.matches is True
        assert comparison.differences == {}

    def test_codec_difference_detected(self):
        comparison = compare_streams("vid_c", make_stream(), make_stream(codec="mp4a.40.2"))
        assert comparison.matches is False
        assert "codec" in comparison.differences

    def test_bitrate_difference_detected(self):
        comparison = compare_streams("vid_c", make_stream(), make_stream(bitrate=128000))
        assert "bitrate" in comparison.differences

    def test_duration_difference_detected(self):
        comparison = compare_streams("vid_c", make_stream(), make_stream(duration=180.0))
        assert "duration" in comparison.differences

    def test_stream_type_difference_detected(self):
        comparison = compare_streams("vid_c", make_stream(), make_stream(stream_type="HLS"))
        assert "stream_type" in comparison.differences

    def test_comparison_object_has_no_signed_url(self):
        prod = make_stream(url="https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=SECRET_PROD")
        shadow = make_stream(url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=y&sig=SECRET_SHADOW")
        comparison = compare_streams("vid_sec", prod, shadow)

        raw = json.dumps(comparison.to_dict(), default=str)
        for forbidden in ("googlevideo", "https://", "sig=", "SECRET_PROD", "SECRET_SHADOW"):
            assert forbidden not in raw

    def test_fallback_path_detected(self):
        shadow = make_stream(
            url="https://shadow.example/videoplayback?id=x&sig=S",
            resolver_metadata={"resolver": "yt-dlp", "fallback_from": "innertubex"},
        )
        comparison = compare_streams("vid_fb", None, shadow)
        assert comparison.shadow_path == "yt-dlp-fallback"

    def test_production_failure_with_shadow_success_not_match(self):
        comparison = compare_streams(
            "vid_mixed", None, make_stream(), production_error="ALL_RESOLVERS_FAILED"
        )
        assert comparison.production_outcome == "failure"
        assert comparison.shadow_outcome == "success"
        assert comparison.matches is False
        assert comparison.production_error_code == "ALL_RESOLVERS_FAILED"


# ======================================================================
# Async Task Isolation
# ======================================================================


class TestSpawnedTaskSafety:
    @pytest.mark.asyncio
    async def test_spawned_task_exceptions_are_drained(self, shadow_resolver_mock: AsyncMock):
        shadow_resolver_mock.resolve.side_effect = RuntimeError("exploded")
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        task = service.spawn_observation("vid_t", env=FLAG_ENV_ON)
        assert task is not None
        await asyncio.sleep(0.02)
        await task

        # exception توسط observe swallow شده → task نتیجه عادی دارد
        assert task.exception() is None
        assert task.result().shadow_outcome == "failure"

    @pytest.mark.asyncio
    async def test_spawned_task_cancellation_is_safe(self, shadow_resolver_mock: AsyncMock):
        gate = asyncio.Event()

        async def hanging(*args, **kwargs):
            await gate.wait()
            return make_stream()

        shadow_resolver_mock.resolve.side_effect = hanging
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        task = service.spawn_observation("vid_cancel", env=FLAG_ENV_ON)
        await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.sleep(0.05)  # فرصت اجرای drain-callback

        assert task.cancelled()
        # event loop پایدار است و هیچ exception unhandled ای گزارش نشده

    @pytest.mark.asyncio
    async def test_inflight_cap_bounded(self, shadow_resolver_mock: AsyncMock):
        gate = asyncio.Event()

        async def hanging(*args, **kwargs):
            await gate.wait()
            return make_stream()

        shadow_resolver_mock.resolve.side_effect = hanging
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        tasks = []
        for _ in range(MAX_INFLIGHT_SHADOW_TASKS + 5):
            tasks.append(service.spawn_observation("vid_cap", env=FLAG_ENV_ON))

        spawned = [t for t in tasks if t is not None]
        skipped = [t for t in tasks if t is None]
        assert len(spawned) == MAX_INFLIGHT_SHADOW_TASKS
        assert len(skipped) == 5

        gate.set()
        await asyncio.gather(*spawned, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_spawn_disabled_by_flag(self, shadow_resolver_mock: AsyncMock):
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)
        assert service.spawn_observation("vid_off", env=FLAG_ENV_OFF) is None
        shadow_resolver_mock.resolve.assert_not_called()


# ======================================================================
# Security
# ======================================================================


class TestShadowSecurity:
    @pytest.mark.asyncio
    async def test_logs_never_contain_urls_or_credentials(
        self, shadow_resolver_mock: AsyncMock, caplog
    ):
        secret_url = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=SECRET_SIG&cookie=abc"
        shadow_resolver_mock.resolve.side_effect = AllResolversFailedError(
            video_id="vid_log",
            primary_error=ExpiredStreamError("expired", video_id="vid_log"),
            fallback_error=ExpiredStreamError("expired", video_id="vid_log"),
        )
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        with caplog.at_level(logging.DEBUG):
            await service.observe(
                "vid_log",
                production_stream=make_stream(url=secret_url),
                env=FLAG_ENV_ON,
            )

        combined = " ".join(r.getMessage() for r in caplog.records).lower()
        for forbidden in ("googlevideo", "https://", "sig=", "signature=", "cookie",
                          "authorization", "po_token", "visitor", "session"):
            assert forbidden not in combined

    @pytest.mark.asyncio
    async def test_comparison_never_carries_headers_or_expiry(
        self, shadow_resolver_mock: AsyncMock
    ):
        shadow_stream = make_stream(
            url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=y&sig=SHADOW_SECRET",
            headers={"Authorization": "Bearer something", "Cookie": "SID=xyz"},
        )
        shadow_resolver_mock.resolve.return_value = shadow_stream
        service = ShadowStreamResolver(shadow_resolver=shadow_resolver_mock)

        comparison = await service.observe(
            "vid_hdr", production_stream=make_stream(), env=FLAG_ENV_ON
        )
        raw = json.dumps(comparison.to_dict(), default=str).lower()
        for forbidden in ("googlevideo", "https://", "sig=", "bearer", "sid=", "authorization"):
            assert forbidden not in raw


