"""
تست‌های واحد قرارداد مشترک ResolvedStream.
"""

from __future__ import annotations

import time
import pytest
from pydantic import ValidationError

from app.stream.models import ResolvedStream


class TestResolvedStreamModel:
    def test_valid_resolved_stream_creation(self):
        now = int(time.time())
        stream = ResolvedStream(
            source="youtube",
            video_id="test_vid_123",
            url="https://rr1---sn-abc.googlevideo.com/videoplayback?id=123",
            mime_type="audio/webm",
            codec="opus",
            bitrate=160000,
            sample_rate=48000,
            channels=2,
            content_length=4500000,
            expires_at=now + 21600,
            duration=225.5,
            headers={"User-Agent": "Mozilla/5.0"},
            requires_range=False,
            resolver_metadata={"client": "WEB_REMIX", "itag": 251},
            is_lossless=False,
            bit_depth=16,
            loudness_db=-8.5,
            stream_type="PROGRESSIVE",
        )

        assert stream.source == "youtube"
        assert stream.video_id == "test_vid_123"
        assert stream.bitrate == 160000
        assert stream.sample_rate == 48000
        assert stream.channels == 2
        assert stream.content_length == 4500000
        assert stream.is_lossless is False
        assert stream.stream_type == "PROGRESSIVE"
        assert stream.headers["User-Agent"] == "Mozilla/5.0"
        assert stream.resolver_metadata["itag"] == 251

    def test_minimal_valid_resolved_stream(self):
        stream = ResolvedStream(
            source="soundcloud",
            video_id="sc_999",
            url="https://api-v2.soundcloud.com/media/stream",
            mime_type="audio/mpeg",
            codec="mp3",
        )

        assert stream.source == "soundcloud"
        assert stream.video_id == "sc_999"
        assert stream.bitrate is None
        assert stream.sample_rate is None
        assert stream.channels is None
        assert stream.content_length is None
        assert stream.expires_at is None
        assert stream.duration is None
        assert stream.headers == {}
        assert stream.requires_range is False
        assert stream.resolver_metadata == {}
        assert stream.is_lossless is False
        assert stream.bit_depth is None
        assert stream.loudness_db is None
        assert stream.stream_type == "PROGRESSIVE"

    @pytest.mark.parametrize(
        "invalid_field,value",
        [
            ("url", ""),
            ("url", "   "),
            ("url", "ftp://invalid.com/audio"),
            ("source", ""),
            ("video_id", " "),
            ("mime_type", ""),
            ("codec", ""),
            ("bitrate", -100),
            ("sample_rate", -48000),
            ("content_length", -1),
            ("stream_type", "INVALID_TYPE"),
        ],
    )
    def test_invalid_fields_validation(self, invalid_field, value):
        base_kwargs = {
            "source": "youtube",
            "video_id": "v123",
            "url": "https://example.com/audio.mp4",
            "mime_type": "audio/mp4",
            "codec": "aac",
        }
        base_kwargs[invalid_field] = value

        with pytest.raises(ValidationError):
            ResolvedStream(**base_kwargs)

    def test_round_trip_serialization(self):
        original = ResolvedStream(
            source="youtube",
            video_id="v_roundtrip",
            url="https://example.com/stream.opus",
            mime_type="audio/webm",
            codec="opus",
            bitrate=128000,
            sample_rate=48000,
            channels=2,
            content_length=3100000,
            expires_at=1790000000,
            duration=190.2,
            headers={"Range": "bytes=0-"},
            requires_range=True,
            resolver_metadata={"profile_id": "WEB_REMIX"},
            is_lossless=False,
            bit_depth=None,
            loudness_db=-14.0,
            stream_type="PROGRESSIVE",
        )

        d = original.to_dict()
        assert isinstance(d, dict)
        assert d["source"] == "youtube"
        assert d["video_id"] == "v_roundtrip"
        assert d["requires_range"] is True
        assert d["loudness_db"] == -14.0

        # بازسازی
        reconstructed = ResolvedStream.from_dict(d)
        assert reconstructed == original
        assert reconstructed.to_dict() == d

    def test_hls_stream_type(self):
        stream = ResolvedStream(
            source="youtube",
            video_id="v_hls",
            url="https://manifest.googlevideo.com/api/manifest/hls_playlist/test.m3u8",
            mime_type="application/x-mpegURL",
            codec="aac",
            stream_type="HLS",
        )
        assert stream.stream_type == "HLS"

    def test_lossless_audio_attributes(self):
        stream = ResolvedStream(
            source="local",
            video_id="track_flac",
            url="http://127.0.0.1:8000/api/stream/flac",
            mime_type="audio/flac",
            codec="flac",
            bitrate=920000,
            sample_rate=96000,
            channels=2,
            is_lossless=True,
            bit_depth=24,
        )
        assert stream.is_lossless is True
        assert stream.bit_depth == 24
        assert stream.sample_rate == 96000

    def test_is_expired_detection(self):
        now = time.time()

        # استریم بدون تاریخ انقضا هرگز اکسپایر نمی‌شود
        no_expiry = ResolvedStream(
            source="youtube",
            video_id="v1",
            url="https://example.com/audio",
            mime_type="audio/mp4",
            codec="aac",
            expires_at=None,
        )
        assert no_expiry.is_expired() is False

        # استریم منقضی‌شده در گذشته
        past_stream = ResolvedStream(
            source="youtube",
            video_id="v2",
            url="https://example.com/audio",
            mime_type="audio/mp4",
            codec="aac",
            expires_at=int(now - 60),
        )
        assert past_stream.is_expired() is True

        # استریم معتبر آینده با مهلت ۲ ساعت
        future_stream = ResolvedStream(
            source="youtube",
            video_id="v3",
            url="https://example.com/audio",
            mime_type="audio/mp4",
            codec="aac",
            expires_at=int(now + 7200),
        )
        assert future_stream.is_expired() is False

        # حاشیه خطای امنیتی (Skew): استریمی که ۱۰ ثانیه دیگر منقضی می‌شود، با skew=30 منقضی حساب شود
        edge_stream = ResolvedStream(
            source="youtube",
            video_id="v4",
            url="https://example.com/audio",
            mime_type="audio/mp4",
            codec="aac",
            expires_at=int(now + 10),
        )
        assert edge_stream.is_expired(skew_seconds=30) is True
        assert edge_stream.is_expired(skew_seconds=5) is False

    def test_to_android_payload_mapping(self):
        stream = ResolvedStream(
            source="youtube",
            video_id="yt_android_test",
            url="https://rr2---sn-4g5ednks.googlevideo.com/videoplayback?id=abc",
            mime_type="audio/mp4",
            codec="mp4a.40.2",
            bitrate=128000,
            sample_rate=44100,
            channels=2,
            content_length=3500000,
            expires_at=1795000000,
            duration=218.4,
            headers={"User-Agent": "okhttp/5.0"},
            is_lossless=False,
            bit_depth=16,
            loudness_db=-7.8,
            stream_type="PROGRESSIVE",
        )

        payload = stream.to_android_payload()

        assert payload["uri"] == stream.url
        assert payload["mimeType"] == "audio/mp4"
        assert payload["codec"] == "mp4a.40.2"
        assert payload["bitrateBps"] == 128000
        assert payload["sampleRateHz"] == 44100
        assert payload["bitDepth"] == 16
        assert payload["channelCount"] == 2
        assert payload["durationMs"] == 218400
        assert payload["isLossless"] is False
        assert payload["gainDb"] == -7.8
        assert payload["sourceId"] == "yt_android_test"
        assert payload["expiresAtMs"] == 1795000000000
        assert payload["streamType"] == "PROGRESSIVE"
        assert payload["headers"] == {"User-Agent": "okhttp/5.0"}

    def test_from_ytdlp_adapter(self):
        fake_ytdlp_format = {
            "url": "https://rr4---sn.googlevideo.com/videoplayback?id=xyz&expire=1792000000&sparams=expire",
            "ext": "webm",
            "acodec": "opus",
            "abr": 160.0,
            "asr": 48000,
            "audio_channels": 2,
            "filesize": 4200000,
            "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"},
            "protocol": "https",
            "format_id": "251",
            "format_note": "medium",
        }
        fake_ytdlp_info = {
            "id": "dQw4w9WgXcQ",
            "duration": 212.0,
            "loudness": -8.1,
        }

        stream = ResolvedStream.from_ytdlp(fake_ytdlp_info, fake_ytdlp_format, source="youtube")

        assert stream.source == "youtube"
        assert stream.video_id == "dQw4w9WgXcQ"
        assert stream.url == fake_ytdlp_format["url"]
        assert stream.mime_type == "audio/webm"
        assert stream.codec == "opus"
        assert stream.bitrate == 160000
        assert stream.sample_rate == 48000
        assert stream.channels == 2
        assert stream.content_length == 4200000
        assert stream.duration == 212.0
        assert stream.expires_at == 1792000000
        assert stream.loudness_db == -8.1
        assert stream.is_lossless is False
        assert stream.stream_type == "PROGRESSIVE"
        assert stream.headers["User-Agent"] == "Mozilla/5.0 (Windows NT 10.0)"
        assert stream.resolver_metadata["format_id"] == "251"

    def test_security_redacted_repr(self):
        secret_signed_url = (
            "https://rr1---sn-abc.googlevideo.com/videoplayback"
            "?expire=1792000000&ei=SecretEi&ip=1.2.3.4&id=xyz&signature=TOP_SECRET_SIG"
        )
        stream = ResolvedStream(
            source="youtube",
            video_id="xyz",
            url=secret_signed_url,
            mime_type="audio/webm",
            codec="opus",
        )

        repr_str = repr(stream)
        str_str = str(stream)

        # آدرس نباید پارامترهای حساس امضا را در لاگ‌ها فاش کند
        assert "TOP_SECRET_SIG" not in repr_str
        assert "SecretEi" not in repr_str
        assert "[signed parameters redacted]" in repr_str
        assert "TOP_SECRET_SIG" not in str_str
