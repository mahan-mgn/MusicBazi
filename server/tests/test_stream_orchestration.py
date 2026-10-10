"""
تست‌های واحد برای ارکستراسیون YouTubeStreamResolver و سیاست فال‌بک (Phase 6).
سنجش:
1. موفقیت رزولور اصلی (InnerTubeX) بدون صدا زدن yt-dlp.
2. شکست رزولور اصلی و فال‌بک موفق به yt-dlp برای تمام رده‌های خطا.
3. شکست هر دو رزولور و اعتبارسنجی AllResolversFailedError با حفظ هر دو علت ریشه‌ای.
4. ممانعت از ایجاد لوپ تلاش مجدد (دقیقاً ۱ بار کال برای هر رزولور).
5. اعتبارسنجی انقضای لحظه‌ای استریم (Resolution-time expiration).
6. آزمون امنیت و عدم نشت مقادیر حساس در لاگ‌ها، خطاها و متادیتا.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock
import pytest

from app.stream import (
    AllResolversFailedError,
    BridgeTimeoutError,
    BridgeUnavailableError,
    CipherError,
    ClientRejectedError,
    ExpiredStreamError,
    InnerTubeXResolver,
    InvalidResponseError,
    NetworkError,
    NoStreamError,
    POTokenError,
    ResolvedStream,
    UnsupportedFormatError,
    YouTubeStreamResolver,
    YtDlpResolver,
)


@pytest.fixture
def sample_innertubex_stream():
    return ResolvedStream(
        source="youtube",
        video_id="vid_sample",
        url="https://rr1---sn-abc.googlevideo.com/videoplayback?id=vid_sample&sig=SECRET_SIG",
        mime_type="audio/webm",
        codec="opus",
        bitrate=160000,
        sample_rate=48000,
        channels=2,
        content_length=3500000,
        expires_at=int(time.time()) + 21600,
        duration=215.0,
        headers={"User-Agent": "Mozilla/5.0"},
        requires_range=False,
        resolver_metadata={"client_name": "WEB_REMIX", "itag": "251"},
        is_lossless=False,
        stream_type="PROGRESSIVE",
    )


@pytest.fixture
def sample_ytdlp_stream():
    return ResolvedStream(
        source="youtube",
        video_id="vid_sample",
        url="https://rr2---sn-xyz.googlevideo.com/videoplayback?id=vid_sample&sig=YTDLP_SIG",
        mime_type="audio/mp4",
        codec="mp4a.40.2",
        bitrate=128000,
        sample_rate=44100,
        channels=2,
        content_length=3100000,
        expires_at=int(time.time()) + 21600,
        duration=215.0,
        headers={"User-Agent": "Mozilla/5.0"},
        requires_range=False,
        resolver_metadata={"resolver": "yt-dlp", "format_id": "140"},
        is_lossless=False,
        stream_type="PROGRESSIVE",
    )


class TestYouTubeStreamResolverOrchestration:
    @pytest.mark.asyncio
    async def test_primary_success_does_not_call_fallback(self, sample_innertubex_stream):
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.return_value = sample_innertubex_stream

        mock_ytdlp = AsyncMock(spec=YtDlpResolver)

        resolver = YouTubeStreamResolver(primary_resolver=mock_itx, fallback_resolver=mock_ytdlp)
        result = await resolver.resolve("vid_sample", purpose="playback")

        assert result == sample_innertubex_stream
        assert mock_itx.resolve_stream.call_count == 1
        mock_ytdlp.resolve_stream.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "primary_error_cls,error_code",
        [
            (BridgeUnavailableError, "BRIDGE_UNAVAILABLE"),
            (BridgeTimeoutError, "TIMEOUT"),
            (NoStreamError, "NO_STREAM"),
            (ClientRejectedError, "CLIENT_REJECTED"),
            (CipherError, "CIPHER_ERROR"),
            (POTokenError, "PO_TOKEN_ERROR"),
            (InvalidResponseError, "INVALID_RESPONSE"),
            (UnsupportedFormatError, "UNSUPPORTED_FORMAT"),
            (NetworkError, "NETWORK_ERROR"),
            (ExpiredStreamError, "EXPIRED_STREAM"),
        ],
    )
    async def test_primary_failure_triggers_fallback_success(
        self, primary_error_cls, error_code, sample_ytdlp_stream
    ):
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = primary_error_cls(f"InnerTubeX {error_code}", video_id="vid_sample")

        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream

        resolver = YouTubeStreamResolver(primary_resolver=mock_itx, fallback_resolver=mock_ytdlp)
        result = await resolver.resolve("vid_sample", purpose="download", quality="m4a")

        assert result.video_id == "vid_sample"
        assert result.codec == "mp4a.40.2"
        # بررسی ثبت متادیتای تشخیصی غیرحساس فال‌بک
        assert result.resolver_metadata["resolver"] == "yt-dlp"
        assert result.resolver_metadata["fallback_from"] == "innertubex"
        assert result.resolver_metadata["primary_failure"] == error_code

        # بررسی تعداد فراخوانی دقیقاً ۱ بار (بدون لوپ)
        assert mock_itx.resolve_stream.call_count == 1
        assert mock_ytdlp.resolve_stream.call_count == 1
        mock_ytdlp.resolve_stream.assert_awaited_once_with(
            video_id="vid_sample",
            purpose="download",
            quality="m4a",
        )

    @pytest.mark.asyncio
    async def test_both_resolvers_fail_raises_all_resolvers_failed_preserving_root_causes(self):
        primary_err = ClientRejectedError("Bot-check active", video_id="vid_both_fail", code="CLIENT_REJECTED")
        fallback_err = NetworkError("Connection refused by proxy", video_id="vid_both_fail")

        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = primary_err

        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.side_effect = fallback_err

        resolver = YouTubeStreamResolver(primary_resolver=mock_itx, fallback_resolver=mock_ytdlp)

        with pytest.raises(AllResolversFailedError) as exc_info:
            await resolver.resolve("vid_both_fail")

        err = exc_info.value
        assert err.video_id == "vid_both_fail"
        assert err.code == "ALL_RESOLVERS_FAILED"
        assert err.primary_code == "CLIENT_REJECTED"
        assert err.fallback_code == "NETWORK_ERROR"
        assert err.primary_error == primary_err
        assert err.fallback_error == fallback_err

        # اطمینان از سقف دقیق ۱ بار تلاش برای هر رزولور
        assert mock_itx.resolve_stream.call_count == 1
        assert mock_ytdlp.resolve_stream.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_video_id_raises_value_error_without_calling_resolvers(self):
        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_ytdlp = AsyncMock(spec=YtDlpResolver)

        resolver = YouTubeStreamResolver(primary_resolver=mock_itx, fallback_resolver=mock_ytdlp)

        with pytest.raises(ValueError):
            await resolver.resolve("   ")

        mock_itx.resolve_stream.assert_not_called()
        mock_ytdlp.resolve_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolution_time_expired_stream_from_primary_triggers_fallback(
        self, sample_innertubex_stream, sample_ytdlp_stream
    ):
        # استریمی که تاریخ انقضای آن در گذشته است
        expired_stream = sample_innertubex_stream.model_copy(update={"expires_at": int(time.time()) - 100})

        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.return_value = expired_stream

        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream

        resolver = YouTubeStreamResolver(primary_resolver=mock_itx, fallback_resolver=mock_ytdlp)
        result = await resolver.resolve("vid_sample")

        assert result.resolver_metadata["resolver"] == "yt-dlp"
        assert result.resolver_metadata["primary_failure"] == "EXPIRED_STREAM"
        assert mock_itx.resolve_stream.call_count == 1
        assert mock_ytdlp.resolve_stream.call_count == 1

    @pytest.mark.asyncio
    async def test_security_invariants_no_sensitive_data_in_error_or_metadata(self, sample_ytdlp_stream):
        # تست اطمینان از عدم نشت سکرت‌ها و توکن‌ها در خطا و متادیتا
        primary_err = POTokenError("Failed token generation with secret_po_token_123", video_id="vid_sec")

        mock_itx = AsyncMock(spec=InnerTubeXResolver)
        mock_itx.resolve_stream.side_effect = primary_err

        mock_ytdlp = AsyncMock(spec=YtDlpResolver)
        mock_ytdlp.resolve_stream.return_value = sample_ytdlp_stream

        resolver = YouTubeStreamResolver(primary_resolver=mock_itx, fallback_resolver=mock_ytdlp)
        result = await resolver.resolve("vid_sec")

        meta = result.resolver_metadata
        assert "secret_po_token_123" not in str(meta)
        assert "Cookie" not in str(meta)
        assert "Authorization" not in str(meta)
        assert meta["primary_failure"] == "PO_TOKEN_ERROR"
