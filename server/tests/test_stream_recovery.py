"""
تست‌های Phase 8 — بازیابی استریم منقضی و رزولوشن مجدد (StreamRecovery).

پوشش:
1. استریم سالم → هیچ re-resolution انجام نمی‌شود
2. استریم pre-expired → دقیقاً یک resolve → استریم تازه
3. Near expiry با skew فعلی (۳۰ ثانیه): <= now+30 ناامن، > now+30 امن
4. Runtime 403 → یک re-resolution
5. Runtime 410 → یک re-resolution
6. Non-expiration 500 → نباید به EXPIRED_STREAM رده‌بندی شود
7. شکست re-resolution → علت اصلی + علت recovery حفظ می‌شود
8. حلقه بی‌نهایت ممنوع: re-resolve == 1
9. استریم تازهِ منقضی → بودجه تمام → خطای نهایی
10. همان URL → در صورت معتبر بودن، موفق
11. Metadata: استریم تازه authoritative است
12. همزمانی: چند caller همزمان → فقط یک resolve (single-flight)
13. امنیت: هیچ signed URL/token/cookie در لاگ‌ها نشت نمی‌کند
"""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock

import pytest

from app.stream import (
    AllResolversFailedError,
    ExpiredStreamError,
    InnerTubeXResolver,
    MAX_RERESOLVE_ATTEMPTS,
    NetworkError,
    NoStreamError,
    ResolvedStream,
    StreamRecovery,
    StreamRecoveryError,
    YouTubeStreamResolver,
    YtDlpResolver,
    classify_runtime_failure,
)


def make_stream(
    video_id: str = "vid_rec",
    *,
    expires_in: int = 21600,
    url: str = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=OLD_SIG",
    client_name: str = "WEB_REMIX",
    codec: str = "opus",
    bitrate: int = 160000,
    mime_type: str = "audio/webm",
    extra_meta: dict | None = None,
) -> ResolvedStream:
    meta = {"client_name": client_name, "resolver": "innertubex"}
    if extra_meta:
        meta.update(extra_meta)
    return ResolvedStream(
        source="youtube",
        video_id=video_id,
        url=url,
        mime_type=mime_type,
        codec=codec,
        bitrate=bitrate,
        expires_at=int(time.time()) + expires_in,
        resolver_metadata=meta,
    )


@pytest.fixture
def mock_resolver() -> AsyncMock:
    return AsyncMock(spec=YouTubeStreamResolver)


class TestExpirationPolicy:
    def test_not_expired_no_reresolve(self, mock_resolver: AsyncMock):
        stream = make_stream(expires_in=3600)
        recovery = StreamRecovery(resolver=mock_resolver)

        result = asyncio.run(recovery.ensure_fresh(stream))

        assert result is stream
        mock_resolver.resolve.assert_not_called()

    def test_pre_expired_exactly_one_resolve(self, mock_resolver: AsyncMock):
        expired = make_stream(expires_in=-120)
        fresh = make_stream(url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=x&sig=NEW_SIG")
        mock_resolver.resolve.return_value = fresh
        recovery = StreamRecovery(resolver=mock_resolver)

        result = asyncio.run(recovery.ensure_fresh(expired))

        assert result.url == fresh.url
        assert mock_resolver.resolve.call_count == 1
        # refresh فقط با video_id انجام شده، نه با URL قدیمی
        _, kwargs = mock_resolver.resolve.call_args
        assert kwargs["video_id"] == "vid_rec"

    def test_near_expiry_within_skew_is_unsafe(self, mock_resolver: AsyncMock):
        # ۲۰ ثانیه تا انقضا: با skew ۳۰ ثانیه‌ای ناامن است
        near = make_stream(expires_in=20)
        fresh = make_stream(url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=x&sig=NEW_SIG")
        mock_resolver.resolve.return_value = fresh
        recovery = StreamRecovery(resolver=mock_resolver)

        asyncio.run(recovery.ensure_fresh(near))
        mock_resolver.resolve.assert_called_once()

    def test_beyond_skew_is_safe(self, mock_resolver: AsyncMock):
        # ۶۰ ثانیه تا انقضا: بیشتر از skew → امن
        stream = make_stream(expires_in=60)
        recovery = StreamRecovery(resolver=mock_resolver)

        result = asyncio.run(recovery.ensure_fresh(stream))
        assert result is stream
        mock_resolver.resolve.assert_not_called()

    def test_purpose_and_quality_passthrough(self, mock_resolver: AsyncMock):
        expired = make_stream(expires_in=-10)
        fresh = make_stream()
        mock_resolver.resolve.return_value = fresh
        recovery = StreamRecovery(resolver=mock_resolver)

        asyncio.run(recovery.ensure_fresh(expired, purpose="download", quality="mp4"))

        _, kwargs = mock_resolver.resolve.call_args
        assert kwargs["purpose"] == "download"
        assert kwargs["quality"] == "mp4"


class TestRuntimeFailureClassification:
    def test_http_403_triggers_one_reresolve(self, mock_resolver: AsyncMock):
        fresh = make_stream(url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=x&sig=FRESH403")
        mock_resolver.resolve.return_value = fresh
        recovery = StreamRecovery(resolver=mock_resolver)

        result = asyncio.run(
            recovery.recover_from_runtime_failure("vid_403", http_status=403, reason="Forbidden")
        )

        assert result.url == fresh.url
        assert mock_resolver.resolve.call_count == 1

    def test_http_410_triggers_one_reresolve(self, mock_resolver: AsyncMock):
        fresh = make_stream(url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=x&sig=FRESH410")
        mock_resolver.resolve.return_value = fresh
        recovery = StreamRecovery(resolver=mock_resolver)

        result = asyncio.run(
            recovery.recover_from_runtime_failure("vid_410", http_status=410, reason="Gone")
        )

        assert result.url == fresh.url
        assert mock_resolver.resolve.call_count == 1

    def test_http_500_must_not_classify_as_expired(self, mock_resolver: AsyncMock):
        recovery = StreamRecovery(resolver=mock_resolver)

        with pytest.raises(NetworkError):
            asyncio.run(
                recovery.recover_from_runtime_failure("vid_500", http_status=500, reason="Internal")
            )

        mock_resolver.resolve.assert_not_called()

    def test_signature_rejection_reason_maps_to_expired(self, mock_resolver: AsyncMock):
        fresh = make_stream()
        mock_resolver.resolve.return_value = fresh
        recovery = StreamRecovery(resolver=mock_resolver)

        result = asyncio.run(
            recovery.recover_from_runtime_failure("vid_sig", reason="signature verification failed")
        )
        assert result.url == fresh.url

    def test_insufficient_evidence_declines_recovery(self, mock_resolver: AsyncMock):
        recovery = StreamRecovery(resolver=mock_resolver)

        with pytest.raises(Exception) as exc_info:
            asyncio.run(
                recovery.recover_from_runtime_failure("vid_geo", reason="geo restriction")
            )

        assert not isinstance(exc_info.value, ExpiredStreamError)
        assert exc_info.value.code == "RUNTIME_FAILURE"
        mock_resolver.resolve.assert_not_called()

    def test_classifier_is_directly_testable(self):
        assert isinstance(classify_runtime_failure(http_status=410), ExpiredStreamError)
        assert isinstance(classify_runtime_failure(http_status=403), ExpiredStreamError)
        assert isinstance(classify_runtime_failure(reason="url expired"), ExpiredStreamError)
        assert isinstance(classify_runtime_failure(http_status=503), NetworkError)
        assert classify_runtime_failure(http_status=500).code == "NETWORK_ERROR"
        assert classify_runtime_failure(http_status=404).code == "RUNTIME_FAILURE"


class TestRecoveryBudget:
    def test_reresolve_attempt_is_exactly_one(self, mock_resolver: AsyncMock):
        # resolver همیشه استریم منقضی برمی‌گرداند → نباید حلقه تشکیل شود
        mock_resolver.resolve.return_value = make_stream(expires_in=-60)
        recovery = StreamRecovery(resolver=mock_resolver)

        with pytest.raises(StreamRecoveryError):
            asyncio.run(recovery.ensure_fresh(make_stream(expires_in=-30)))

        assert mock_resolver.resolve.call_count == 1
        assert MAX_RERESOLVE_ATTEMPTS == 1

    def test_fresh_stream_already_expired_final_error(self, mock_resolver: AsyncMock):
        mock_resolver.resolve.return_value = make_stream(expires_in=-60)
        recovery = StreamRecovery(resolver=mock_resolver)

        with pytest.raises(StreamRecoveryError) as exc_info:
            asyncio.run(recovery.ensure_fresh(make_stream(expires_in=-30)))

        err = exc_info.value
        assert err.original_reason == "EXPIRED_STREAM"
        assert isinstance(err.recovery_error, ExpiredStreamError)
        assert mock_resolver.resolve.call_count == 1

    def test_resolver_failure_preserves_both_causes(self, mock_resolver: AsyncMock):
        original = AllResolversFailedError(
            video_id="vid_fail",
            primary_error=ExpiredStreamError("expired", video_id="vid_fail"),
            fallback_error=NetworkError("net", video_id="vid_fail"),
        )
        mock_resolver.resolve.side_effect = original
        recovery = StreamRecovery(resolver=mock_resolver)

        with pytest.raises(StreamRecoveryError) as exc_info:
            asyncio.run(recovery.ensure_fresh(make_stream(expires_in=-10)))

        err = exc_info.value
        assert err.original_reason == "EXPIRED_STREAM"
        assert err.recovery_error is original
        assert err.recovery_error.primary_code == "EXPIRED_STREAM"
        assert err.recovery_error.fallback_code == "NETWORK_ERROR"

    def test_runtime_failure_resolver_failure_preserves_cause(self, mock_resolver: AsyncMock):
        original = AllResolversFailedError(
            video_id="vid_rt",
            primary_error=NoStreamError("InnerTubeX found no stream", video_id="vid_rt"),
            fallback_error=NoStreamError("yt-dlp found no stream", video_id="vid_rt"),
        )
        mock_resolver.resolve.side_effect = original
        recovery = StreamRecovery(resolver=mock_resolver)

        with pytest.raises(StreamRecoveryError) as exc_info:
            asyncio.run(recovery.recover_from_runtime_failure("vid_rt", http_status=410))

        assert exc_info.value.original_reason == "EXPIRED_STREAM"
        assert isinstance(exc_info.value.recovery_error, AllResolversFailedError)


class TestFreshStreamSemantics:
    def test_same_url_is_accepted_when_valid(self, mock_resolver: AsyncMock):
        same_url = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=SAME_SIG"
        expired = make_stream(expires_in=-10, url=same_url)
        fresh = make_stream(expires_in=3600, url=same_url)
        mock_resolver.resolve.return_value = fresh
        recovery = StreamRecovery(resolver=mock_resolver)

        result = asyncio.run(recovery.ensure_fresh(expired))
        assert result.url == fresh.url  # معیار: معتبر بودن استریم تازه، نه تفاوت رشته URL
        assert not result.is_expired()

    def test_fresh_stream_metadata_is_authoritative(self, mock_resolver: AsyncMock):
        old = make_stream(
            expires_in=-10,
            codec="opus",
            bitrate=160000,
            extra_meta={"old_marker": "should_not_leak"},
        )
        fresh = make_stream(
            url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=x&sig=NEW_SIG",
            codec="mp4a.40.2",
            bitrate=128000,
            mime_type="audio/mp4",
            extra_meta={"format_id": "140"},
        )
        mock_resolver.resolve.return_value = fresh
        recovery = StreamRecovery(resolver=mock_resolver)

        result = asyncio.run(recovery.ensure_fresh(old))

        # فیلدهای فنی استریم تازه authoritative هستند
        assert result.codec == "mp4a.40.2"
        assert result.bitrate == 128000
        assert result.mime_type == "audio/mp4"
        # هیچ metadata قدیمی کورکورانه merge نشده
        assert "old_marker" not in result.resolver_metadata
        assert result.resolver_metadata["format_id"] == "140"
        # درج تشخیصی غیرحساس بازیابی
        assert result.resolver_metadata["recovered_from"] == "EXPIRED_STREAM"
        assert result.resolver_metadata["recovery_attempt"] == 1


class TestConcurrencySingleFlight:
    def test_concurrent_callers_share_one_resolution(self, mock_resolver: AsyncMock):
        fresh = make_stream(url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=x&sig=SHARED")
        gate = asyncio.Event()

        async def slow_resolve(*args, **kwargs):
            await gate.wait()
            return fresh

        mock_resolver.resolve.side_effect = slow_resolve
        recovery = StreamRecovery(resolver=mock_resolver)
        expired = make_stream(expires_in=-10)

        async def run_all():
            async def caller():
                return await recovery.ensure_fresh(expired)

            tasks = [asyncio.create_task(caller()) for _ in range(10)]
            await asyncio.sleep(0.05)  # فرصت ورود همه به single-flight
            gate.set()
            return await asyncio.gather(*tasks)

        results = asyncio.run(run_all())

        assert mock_resolver.resolve.call_count == 1
        assert all(r.url == fresh.url for r in results)

    def test_different_videos_resolve_independently(self, mock_resolver: AsyncMock):
        mock_resolver.resolve.side_effect = (
            lambda video_id, purpose="playback", quality=None: make_stream(video_id=video_id)
        )
        recovery = StreamRecovery(resolver=mock_resolver)
        a = make_stream("vidA", expires_in=-10)
        b = make_stream("vidB", expires_in=-10)

        async def run_all():
            return await asyncio.gather(
                recovery.ensure_fresh(a),
                recovery.ensure_fresh(b),
            )

        results = asyncio.run(run_all())
        assert mock_resolver.resolve.call_count == 2
        assert {r.video_id for r in results} == {"vidA", "vidB"}

    def test_shared_failure_propagates_to_all_waiters(self, mock_resolver: AsyncMock):
        gate = asyncio.Event()

        async def gated_failure(*args, **kwargs):
            await gate.wait()
            raise AllResolversFailedError(
                video_id="vid_shared",
                primary_error=ExpiredStreamError("expired", video_id="vid_shared"),
                fallback_error=ExpiredStreamError("expired", video_id="vid_shared"),
            )

        mock_resolver.resolve.side_effect = gated_failure
        recovery = StreamRecovery(resolver=mock_resolver)
        expired = make_stream("vid_shared", expires_in=-10)

        async def run_all():
            async def caller():
                try:
                    return ("ok", await recovery.ensure_fresh(expired))
                except StreamRecoveryError as e:
                    return ("err", e)

            tasks = [asyncio.create_task(caller()) for _ in range(5)]
            await asyncio.sleep(0.05)  # فرصت ورود همه به single-flight
            gate.set()
            return await asyncio.gather(*tasks)

        results = asyncio.run(run_all())
        assert all(status == "err" for status, _ in results)
        assert mock_resolver.resolve.call_count == 1


class TestPhase6PolicyReuse:
    @pytest.mark.asyncio
    async def test_recovery_uses_existing_fallback_and_health_policy(self):
        """re-resolution باید از همان orchestration فاز ۶/۷ عبور کند (تک فال‌بک + health)."""
        from app.stream.client_health import ClientHealthMonitor

        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = NoStreamError("InnerTubeX found no stream")
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)

        def ytdlp_factory(video_id: str) -> ResolvedStream:
            return make_stream(
                video_id,
                url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=x&sig=YTDLP_FRESH",
                mime_type="audio/mp4",
                codec="mp4a.40.2",
                bitrate=128000,
                client_name="yt-dlp",
            )

        mock_ytdlp.resolve_stream.side_effect = (
            lambda video_id, purpose="playback", quality=None: ytdlp_factory(video_id)
        )

        monitor = ClientHealthMonitor()
        orchestrator = YouTubeStreamResolver(
            primary_resolver=mock_itx, fallback_resolver=mock_ytdlp, client_health=monitor
        )
        recovery = StreamRecovery(resolver=orchestrator)

        result = await recovery.ensure_fresh(make_stream("vid_policy", expires_in=-10))

        # مسیر کامل فاز ۶: primary شکست → فال‌بک موفق (دقیقاً یک بار)
        assert mock_itx.resolve_stream.call_count == 1
        assert mock_ytdlp.resolve_stream.call_count == 1
        assert result.resolver_metadata["fallback_from"] == "innertubex"
        # فاز ۷: شکست primary در health موجود ثبت شده (یک شکست، بدون state موازی)
        assert monitor.snapshot()["clients"]["vid_policy"]["unknown"]["failure_count"] == 1


class TestSecurity:
    def test_no_signed_url_or_token_in_logs(self, mock_resolver: AsyncMock, caplog):
        secret_url = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=SECRET_SIG&ip=1.2.3.4"
        mock_resolver.resolve.side_effect = AllResolversFailedError(
            video_id="vid_sec",
            primary_error=ExpiredStreamError("expired", video_id="vid_sec"),
            fallback_error=NetworkError("net", video_id="vid_sec"),
        )
        recovery = StreamRecovery(resolver=mock_resolver)

        with caplog.at_level(logging.DEBUG, logger="app.stream.recovery"):
            with pytest.raises(StreamRecoveryError):
                asyncio.run(recovery.ensure_fresh(make_stream("vid_sec", expires_in=-10, url=secret_url)))

        combined = " ".join(r.getMessage() for r in caplog.records).lower()
        for forbidden in ("googlevideo", "sig=", "signature=", "cookie", "po_token",
                          "authorization", "visitor", "https://"):
            assert forbidden not in combined

    def test_success_logs_do_not_leak_url(self, mock_resolver: AsyncMock, caplog):
        secret_url = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=SECRET_SIG"
        mock_resolver.resolve.return_value = make_stream(expires_in=3600, url=secret_url)
        recovery = StreamRecovery(resolver=mock_resolver)

        with caplog.at_level(logging.DEBUG, logger="app.stream.recovery"):
            asyncio.run(recovery.ensure_fresh(make_stream(expires_in=-10, url=secret_url)))

        combined = " ".join(r.getMessage() for r in caplog.records).lower()
        assert "googlevideo" not in combined
        assert "sig=" not in combined

    def test_recovery_error_message_contains_no_url(self, mock_resolver: AsyncMock):
        secret_url = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=x&sig=SECRET_SIG"
        mock_resolver.resolve.return_value = make_stream(expires_in=-60, url=secret_url)
        recovery = StreamRecovery(resolver=mock_resolver)

        with pytest.raises(StreamRecoveryError) as exc_info:
            asyncio.run(recovery.ensure_fresh(make_stream(expires_in=-10, url=secret_url)))

        assert "googlevideo" not in str(exc_info.value)
        assert "SECRET_SIG" not in str(exc_info.value)
