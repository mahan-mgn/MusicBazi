"""
تست‌های واحد برای YtDlpResolver.
سنجش استخراج صوت، نگاشت فیلدها به ResolvedStream، مدیریت خطاها،
انقضای آدرس و امنیت عدم نشت سکرت‌ها.
"""

from __future__ import annotations

import time
import pytest
from yt_dlp.utils import DownloadError, UnavailableVideoError

import app.stream.ytdlp as ytdlp_module
from app.stream import (
    ClientRejectedError,
    ExpiredStreamError,
    InvalidResponseError,
    NetworkError,
    NoStreamError,
    ResolvedStream,
    StreamResolverError,
    YtDlpResolver,
)


@pytest.fixture
def fake_ytdlp_success_info():
    future_expire = int(time.time()) + 21600
    return {
        "id": "dQw4w9WgXcQ",
        "title": "Rick Astley - Never Gonna Give You Up",
        "duration": 212.0,
        "loudness": -8.5,
        "extractor": "youtube",
        "formats": [
            {
                "format_id": "18",
                "vcodec": "avc1.42001E",
                "acodec": "mp4a.40.2",
                "abr": 96.0,
                "url": "https://rr1---sn-abc.googlevideo.com/videoplayback?id=18",
                "protocol": "https",
            },
            {
                "format_id": "140",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "ext": "m4a",
                "abr": 128.0,
                "asr": 44100,
                "audio_channels": 2,
                "filesize": 3400000,
                "url": f"https://rr1---sn-abc.googlevideo.com/videoplayback?id=140&expire={future_expire}",
                "protocol": "https",
                "http_headers": {
                    "User-Agent": "Mozilla/5.0",
                    "Cookie": "PREF=f1=50000000; SID=SECRET_COOKIE",
                    "Authorization": "Bearer SECRET_BEARER_TOKEN",
                    "X-YouTube-Identity-Token": "SECRET_ID_TOKEN",
                },
            },
            {
                "format_id": "251",
                "vcodec": "none",
                "acodec": "opus",
                "ext": "webm",
                "abr": 160.0,
                "asr": 48000,
                "audio_channels": 2,
                "filesize": 4200000,
                "url": f"https://rr1---sn-abc.googlevideo.com/videoplayback?id=251&expire={future_expire}",
                "protocol": "https",
                "format_note": "medium",
                "http_headers": {
                    "User-Agent": "Mozilla/5.0",
                    "Cookie": "SID=SECRET_COOKIE",
                },
            },
        ],
    }


class TestYtDlpResolver:
    @pytest.mark.asyncio
    async def test_resolve_success_best_audio(self, monkeypatch, fake_ytdlp_success_info):
        resolver = YtDlpResolver()

        class MockYDL:
            def __init__(self, opts):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                return fake_ytdlp_success_info

        monkeypatch.setattr(ytdlp_module, "YoutubeDL", MockYDL)

        stream = await resolver.resolve_stream("dQw4w9WgXcQ", purpose="playback")

        assert isinstance(stream, ResolvedStream)
        assert stream.source == "youtube"
        assert stream.video_id == "dQw4w9WgXcQ"
        # فرمت itag 251 به دلیل Opus و abr 160 بالاترین رتبه را کسب می‌کند
        assert stream.codec == "opus"
        assert stream.mime_type == "audio/webm"
        assert stream.bitrate == 160000
        assert stream.sample_rate == 48000
        assert stream.channels == 2
        assert stream.content_length == 4200000
        assert stream.duration == 212.0
        assert stream.loudness_db == -8.5
        assert stream.stream_type == "PROGRESSIVE"
        assert stream.is_lossless is False
        assert stream.resolver_metadata["format_id"] == "251"
        assert stream.resolver_metadata["resolver"] == "yt-dlp"

    @pytest.mark.asyncio
    async def test_resolve_m4a_quality_selection(self, monkeypatch, fake_ytdlp_success_info):
        resolver = YtDlpResolver()

        class MockYDL:
            def __init__(self, opts):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                return fake_ytdlp_success_info

        monkeypatch.setattr(ytdlp_module, "YoutubeDL", MockYDL)

        stream = await resolver.resolve_stream("dQw4w9WgXcQ", quality="m4a")

        assert isinstance(stream, ResolvedStream)
        assert stream.codec == "mp4a.40.2"
        assert stream.mime_type == "audio/mp4"
        assert stream.bitrate == 128000
        assert stream.resolver_metadata["format_id"] == "140"

    @pytest.mark.asyncio
    async def test_security_headers_and_metadata_sanitized(self, monkeypatch, fake_ytdlp_success_info):
        resolver = YtDlpResolver()

        class MockYDL:
            def __init__(self, opts):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                return fake_ytdlp_success_info

        monkeypatch.setattr(ytdlp_module, "YoutubeDL", MockYDL)

        stream = await resolver.resolve_stream("dQw4w9WgXcQ")

        # هدرهای کوکی و احراز هویت نباید در headers استریم منتقل شوند
        assert "Cookie" not in stream.headers
        assert "cookie" not in stream.headers
        assert "Authorization" not in stream.headers
        assert "authorization" not in stream.headers
        assert "X-YouTube-Identity-Token" not in stream.headers
        assert stream.headers["User-Agent"] == "Mozilla/5.0"

        # resolver_metadata نباید حاوی توکن یا کوکی باشد
        meta_str = str(stream.resolver_metadata)
        assert "SECRET" not in meta_str
        assert "Bearer" not in meta_str
        assert "Cookie" not in meta_str

    @pytest.mark.asyncio
    async def test_empty_video_id_raises_value_error(self):
        resolver = YtDlpResolver()
        with pytest.raises(ValueError):
            await resolver.resolve_stream("   ")

    @pytest.mark.asyncio
    async def test_empty_info_raises_invalid_response_error(self, monkeypatch):
        resolver = YtDlpResolver()

        class MockYDL:
            def __init__(self, opts):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                return None

        monkeypatch.setattr(ytdlp_module, "YoutubeDL", MockYDL)

        with pytest.raises(InvalidResponseError) as exc_info:
            await resolver.resolve_stream("vid_empty")
        assert exc_info.value.video_id == "vid_empty"

    @pytest.mark.asyncio
    async def test_no_audio_formats_raises_no_stream_error(self, monkeypatch):
        resolver = YtDlpResolver()
        info_no_audio = {
            "id": "vid_no_audio",
            "formats": [
                {"format_id": "160", "vcodec": "av01.0.00M.08", "acodec": "none", "url": "https://video.only"}
            ],
        }

        class MockYDL:
            def __init__(self, opts):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                return info_no_audio

        monkeypatch.setattr(ytdlp_module, "YoutubeDL", MockYDL)

        with pytest.raises(NoStreamError) as exc_info:
            await resolver.resolve_stream("vid_no_audio")
        assert exc_info.value.code == "NO_STREAM"

    @pytest.mark.asyncio
    async def test_video_unavailable_raises_client_rejected(self, monkeypatch):
        resolver = YtDlpResolver()

        class MockYDL:
            def __init__(self, opts):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                raise UnavailableVideoError("Video unavailable")

        monkeypatch.setattr(ytdlp_module, "YoutubeDL", MockYDL)

        with pytest.raises(ClientRejectedError):
            await resolver.resolve_stream("vid_unavailable")

    @pytest.mark.asyncio
    async def test_bot_check_raises_client_rejected(self, monkeypatch):
        resolver = YtDlpResolver()

        class MockYDL:
            def __init__(self, opts):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                raise DownloadError("Sign in to confirm you're not a bot")

        monkeypatch.setattr(ytdlp_module, "YoutubeDL", MockYDL)

        with pytest.raises(ClientRejectedError):
            await resolver.resolve_stream("vid_bot_check")

    @pytest.mark.asyncio
    async def test_network_failure_raises_network_error(self, monkeypatch):
        resolver = YtDlpResolver()

        class MockYDL:
            def __init__(self, opts):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                raise DownloadError("Network error: Connection timed out")

        monkeypatch.setattr(ytdlp_module, "YoutubeDL", MockYDL)

        with pytest.raises(NetworkError) as exc_info:
            await resolver.resolve_stream("vid_net_err")
        assert exc_info.value.retryable is True
        assert exc_info.value.code == "NETWORK_ERROR"

    @pytest.mark.asyncio
    async def test_expired_stream_detection(self, monkeypatch):
        resolver = YtDlpResolver()
        past_expire = int(time.time()) - 3600
        expired_info = {
            "id": "vid_expired",
            "formats": [
                {
                    "format_id": "251",
                    "vcodec": "none",
                    "acodec": "opus",
                    "ext": "webm",
                    "abr": 160.0,
                    "url": f"https://rr1---sn-abc.googlevideo.com/videoplayback?id=251&expire={past_expire}",
                    "protocol": "https",
                }
            ],
        }

        class MockYDL:
            def __init__(self, opts):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                return expired_info

        monkeypatch.setattr(ytdlp_module, "YoutubeDL", MockYDL)

        with pytest.raises(ExpiredStreamError) as exc_info:
            await resolver.resolve_stream("vid_expired")
        assert exc_info.value.code == "EXPIRED_STREAM"
        assert exc_info.value.retryable is True
