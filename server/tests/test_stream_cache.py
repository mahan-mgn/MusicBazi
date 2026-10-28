from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import db, main, stream_cache
from app.lyrics.models import Lyrics
from app.models import Track
from app.resolver import Candidate


@pytest.fixture
def clean_stream_cache(tmp_path, monkeypatch, fresh_db):
    cache_dir = tmp_path / "cache" / "stream"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(stream_cache, "STREAM_CACHE_DIR", cache_dir)
    # نمایه‌ی کش ماژول‌سطح است و تا ۳ ثانیه معتبر می‌ماند؛ اگر پاک نشود، مسیرِ
    # فایلِ تستِ قبلی (که با tmp_path خودش رفته) به تست بعدی نشت می‌کند و
    # extension/media-type اشتباه برمی‌گردد.
    stream_cache._cache_index.clear()
    return cache_dir


def test_serves_from_library_if_already_downloaded(clean_stream_cache, tmp_path, track, fresh_db):
    """اگر کاربر قبلاً ترک را دانلود کرده باشد، مستقیماً از فایل کتابخانه استفاده می‌شود."""
    lib_file = tmp_path / "song.mp3"
    lib_file.write_bytes(b"\x00" * 100)
    fresh_db.insert_job("job-123", track, "320", "ready", time.time())
    fresh_db.update_job("job-123", status="ready", path=str(lib_file), bytes=100)

    result_path = asyncio.run(stream_cache.get_or_fetch(track))

    assert result_path == lib_file
    # نباید هیچ فایلی در پوشه کش استریم ساخته شده باشد
    assert list(clean_stream_cache.glob("*")) == []


def test_serves_from_stream_cache_if_present(clean_stream_cache, track):
    """اگر فایل قبلاً در کش استریم باشد، دوباره دانلود نمی‌شود."""
    cache_key = stream_cache.cache_key_for(track.id)
    cached_file = clean_stream_cache / f"{cache_key}.m4a"
    cached_file.write_bytes(b"\x00" * 2048)

    with patch("app.stream_cache.resolver.resolve") as mock_resolve:
        result_path = asyncio.run(stream_cache.get_or_fetch(track))
        mock_resolve.assert_not_called()

    assert result_path == cached_file


def test_downloads_to_stream_cache_without_library_record(clean_stream_cache, track, fresh_db):
    """استریم آنلاین نباید ردیفی در جدول jobs کتابخانه بسازد."""
    cache_key = stream_cache.cache_key_for(track.id)

    candidates = [
        Candidate(
            url="https://www.youtube.com/watch?v=mock123",
            title="Mock Title",
            uploader="Mock Artist",
            duration_ms=185000,
            score=95.0,
            source="youtube",
        )
    ]

    def mock_extract(url, download=True):
        out_file = clean_stream_cache / f"{cache_key}.m4a"
        out_file.write_bytes(b"\x00" * 4096)
        return {"id": "mock123"}

    mock_ydl = MagicMock()
    mock_ydl.extract_info.side_effect = mock_extract
    mock_ydl_ctx = MagicMock()
    mock_ydl_ctx.__enter__.return_value = mock_ydl

    with (
        patch("app.stream_cache.resolver.resolve", return_value=candidates),
        patch("app.stream_cache.YoutubeDL", return_value=mock_ydl_ctx),
    ):
        result_path = asyncio.run(stream_cache.get_or_fetch(track))

    assert result_path.exists()
    assert result_path.stem == cache_key

    # بررسی عدم ثبت در دیتابیس کتابخانه
    rows, count, _ = fresh_db.library()
    assert count == 0
    assert rows == []


def test_stream_audio_endpoint_returns_file(clean_stream_cache, track):
    """اندپوینت /api/stream باید FileResponse با هدر و mime درست برگرداند."""
    cache_key = stream_cache.cache_key_for(track.id)
    cached_file = clean_stream_cache / f"{cache_key}.mp3"
    cached_file.write_bytes(b"\x00" * 2048)

    response = asyncio.run(
        main.stream_audio(
            track_id=track.id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_ms=track.durationMs,
        )
    )

    assert response.media_type == "audio/mpeg"
    assert Path(response.path) == cached_file
    assert response.headers.get("accept-ranges") == "bytes"


def test_stream_lyrics_endpoint(clean_stream_cache, track):
    """اندپوینت /api/stream/lyrics متن ترانه را بازمی‌گرداند."""
    cache_key = stream_cache.cache_key_for(track.id)
    lrc_file = stream_cache.lyrics_path(track.id)
    lrc_file.write_text("[00:10.00] Line 1\n[00:20.00] Line 2", encoding="utf-8")

    response = asyncio.run(
        main.stream_lyrics(
            track_id=track.id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_ms=track.durationMs,
        )
    )

    assert response.media_type == "text/plain; charset=utf-8"
    assert "[00:10.00] Line 1" in response.body.decode("utf-8")


def test_concurrent_lyrics_requests_are_merged(clean_stream_cache, track, monkeypatch):
    """
    دو تب که هم‌زمان یک ترک را باز کنند نباید دو دورِ کاملِ درخواست به
    LRCLIB/Genius بفرستند — یک تسک باید برای هر دو جواب بدهد.
    """
    from app.lyrics import manager as lyrics_manager

    calls = []

    def slow_fetch(_track, _uid="local"):
        calls.append(1)
        time.sleep(0.05)
        return Lyrics(plain="text", synced="[00:01.00]x")

    monkeypatch.setattr(lyrics_manager, "fetch", slow_fetch)

    async def both():
        return await asyncio.gather(
            stream_cache.get_or_fetch_lyrics(track),
            stream_cache.get_or_fetch_lyrics(track),
        )

    first, second = asyncio.run(both())

    assert calls == [1]
    assert first == second == "[00:01.00]x"


def test_a_negative_result_is_merged_too(clean_stream_cache, track, monkeypatch):
    """
    وقتی Providerها متنی ندارند، درخواست‌های هم‌زمان هم باید یک‌بار بیشتر
    نروند — همان ادغامی که برای نتیجه‌ی موفق کار می‌کند.
    """
    from app.lyrics import manager as lyrics_manager

    calls = []

    def miss(_track, _uid="local"):
        calls.append(1)
        time.sleep(0.05)
        return None

    monkeypatch.setattr(lyrics_manager, "fetch", miss)

    async def both():
        return await asyncio.gather(
            stream_cache.get_or_fetch_lyrics(track),
            stream_cache.get_or_fetch_lyrics(track),
        )

    first, second = asyncio.run(both())

    assert calls == [1]
    assert first is None and second is None


def test_a_failed_lyrics_fetch_does_not_wedge_the_cache(clean_stream_cache, track, monkeypatch):
    """
    شکست نباید قفل دائمی بسازد: درخواست بعدی باید دوباره سراغ Provider برود
    و وقتی موفق شد، نتیجه کش شود.
    """
    from app.lyrics import manager as lyrics_manager

    calls = []

    def flaky(_track, _uid="local"):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("network down")
        return Lyrics(plain="text", synced="[00:01.00]recovered")

    monkeypatch.setattr(lyrics_manager, "fetch", flaky)

    assert asyncio.run(stream_cache.get_or_fetch_lyrics(track)) is None
    assert asyncio.run(stream_cache.get_or_fetch_lyrics(track)) == "[00:01.00]recovered"
    assert len(calls) == 2
    # بار سوم از کش دیسک می‌آید، بدون تماس دوباره
    assert asyncio.run(stream_cache.get_or_fetch_lyrics(track)) == "[00:01.00]recovered"
    assert len(calls) == 2


def test_lyrics_are_not_rewritten_when_already_cached(clean_stream_cache, track, monkeypatch):
    """وجود فایل `.lrc` یعنی هیچ درخواستی زده نمی‌شود."""
    from app.lyrics import manager as lyrics_manager

    cache_key = stream_cache.cache_key_for(track.id)
    stream_cache.lyrics_path(track.id).write_text("[00:01.00]cached", encoding="utf-8")

    def unexpected(_track, _uid="local"):
        raise AssertionError("should not fetch")

    monkeypatch.setattr(lyrics_manager, "fetch", unexpected)

    assert asyncio.run(stream_cache.get_or_fetch_lyrics(track)) == "[00:01.00]cached"


class TestEnhancedLrcIsOffByDefault:
    """
    فاز ۲B.8 — پیش‌فرضِ پروژه «فقط LRC خطی» است، مثل قبل از ۲B.5.

    تگِ کنترلِ کلمهٔ `<mm:ss.xx>` یک افزودنی است و روی خروجیِ *همهٔ*
    مصرف‌کننده‌ها اثر می‌گذارد (کشِ استریم، پاسخِ endpoint، فایل `.lrc`
    دانلود). پس باید صریحاً روشن شود، نه پیش‌فرض.

    `MUSICBAZI_LYRICS_ENHANCED_LRC=1` رفتارِ ۲B.5 را برمی‌گرداند.
    """

    def _word_timed(self):
        from app.lyrics.models import LyricLine, LyricWord

        return Lyrics(
            lines=(
                LyricLine(
                    start_ms=1000,
                    text="hello world",
                    words=(
                        LyricWord(start_ms=1000, text="hello "),
                        LyricWord(start_ms=1500, text="world"),
                    ),
                ),
            ),
            sync_type="word",
        )

    def _run(self, clean_stream_cache, track, monkeypatch, found):
        from app.lyrics import manager as lyrics_manager

        monkeypatch.setattr(lyrics_manager, "fetch", lambda _t, _uid="local": found)
        return asyncio.run(stream_cache.get_or_fetch_lyrics(track))

    def test_the_default_never_writes_a_word_tag(self, clean_stream_cache, track, monkeypatch):
        monkeypatch.delenv("MUSICBAZI_LYRICS_ENHANCED_LRC", raising=False)

        content = self._run(clean_stream_cache, track, monkeypatch, self._word_timed())

        assert content is not None
        assert "<00:01.00>" not in content, "تگِ کلمه در حالتِ پیش‌فرض نباید باشد"
        assert content == "[00:01.00]hello world"

    def test_the_default_still_keeps_the_line_timestamps(self, clean_stream_cache, track, monkeypatch):
        """حذفِ تگِ کلمه نباید زمان‌بندیِ خط را هم از بین ببرد."""
        monkeypatch.delenv("MUSICBAZI_LYRICS_ENHANCED_LRC", raising=False)

        content = self._run(clean_stream_cache, track, monkeypatch, self._word_timed())

        assert content.startswith("[00:01.00]")

    def test_the_flag_on_restores_the_word_tags(self, clean_stream_cache, track, monkeypatch):
        monkeypatch.setenv("MUSICBAZI_LYRICS_ENHANCED_LRC", "1")

        content = self._run(clean_stream_cache, track, monkeypatch, self._word_timed())

        assert "<00:01.00>" in content
        assert "hello " in content

    def test_a_line_only_result_is_identical_in_both_modes(self, clean_stream_cache, track, monkeypatch):
        """وقتی داده‌ی کلمه‌ای نیست، فلگ هیچ تفاوتی نمی‌سازد."""
        from app.lyrics import manager as lyrics_manager

        found = Lyrics(plain="t", synced="[00:01.00]plain", sync_type="line")
        monkeypatch.setattr(lyrics_manager, "fetch", lambda _t, _uid="local": found)

        monkeypatch.delenv("MUSICBAZI_LYRICS_ENHANCED_LRC", raising=False)
        off = asyncio.run(stream_cache.get_or_fetch_lyrics(track))

        stream_cache.lyrics_path(track.id).unlink()
        monkeypatch.setenv("MUSICBAZI_LYRICS_ENHANCED_LRC", "1")
        on = asyncio.run(stream_cache.get_or_fetch_lyrics(track))

        assert off == on == "[00:01.00]plain"

    def test_a_written_synced_field_is_never_rewritten(self, clean_stream_cache, track, monkeypatch):
        """
        Providerی که خودش `synced` دارد (lrclib، lrc.red، unison) دست‌نخورده
        می‌ماند — فلگ فقط وقتی دخالت می‌کند که تنها `lines` وجود دارد.
        """
        from app.lyrics import manager as lyrics_manager

        found = Lyrics(plain="t", synced="[00:01.00]raw from provider")
        monkeypatch.setattr(lyrics_manager, "fetch", lambda _t, _uid="local": found)
        monkeypatch.delenv("MUSICBAZI_LYRICS_ENHANCED_LRC", raising=False)

        assert asyncio.run(stream_cache.get_or_fetch_lyrics(track)) == "[00:01.00]raw from provider"

    def test_the_old_frontend_parser_still_finds_the_lines_when_on(
        self, clean_stream_cache, track, monkeypatch
    ):
        """حالتِ روشن هم باید برای پارسرِ خطی معتبر بماند (رگرسیونِ کلاینتِ قدیمی)."""
        from app.lyrics.parsers import parse_lrc

        monkeypatch.setenv("MUSICBAZI_LYRICS_ENHANCED_LRC", "1")
        content = self._run(clean_stream_cache, track, monkeypatch, self._word_timed())

        assert parse_lrc(content) is not None
        assert parse_lrc(content).lines[0].start_ms == 1000

    def test_the_flag_is_read_at_call_time_not_at_import(self, clean_stream_cache, track, monkeypatch):
        """
        فلگ باید هر بار خوانده شود، نه در زمانِ import قفل شود — وگرنه تست و
        اجرای واقعی نمی‌توانند بدونِ راه‌اندازی مجدد عوضش کنند.
        """
        from app.lyrics import manager as lyrics_manager

        monkeypatch.setattr(lyrics_manager, "fetch", lambda _t, _uid="local": self._word_timed())

        monkeypatch.delenv("MUSICBAZI_LYRICS_ENHANCED_LRC", raising=False)
        first = asyncio.run(stream_cache.get_or_fetch_lyrics(track))
        stream_cache.lyrics_path(track.id).unlink()

        monkeypatch.setenv("MUSICBAZI_LYRICS_ENHANCED_LRC", "1")
        second = asyncio.run(stream_cache.get_or_fetch_lyrics(track))

        assert "<" not in first
        assert "<" in second


def test_stream_prefetch_endpoint(clean_stream_cache, track):
    """اندپوینت /api/stream/prefetch تا آماده‌شدن فایل صبر می‌کند."""
    from unittest.mock import AsyncMock
    from app.models import TrackRef

    req = TrackRef(
        trackId=track.id,
        sourceUrl=track.sourceUrl,
        title=track.title,
        artist=track.artist,
        album=track.album,
        durationMs=track.durationMs,
    )

    with patch("app.stream_cache.get_or_fetch", new_callable=AsyncMock) as mock_fetch:
        res = asyncio.run(main.stream_prefetch(req))
        assert res == {"ok": True}
        mock_fetch.assert_awaited_once()


def test_stream_prefetch_v2_warms_cache():
    """اگر V2 روشن و ترک یوتیوب باشد، کشِ URL گرم می‌شود بدون دانلودِ فایل سنگین روی دیسک."""
    from unittest.mock import AsyncMock
    from app.models import TrackRef

    req = TrackRef(
        trackId="yt_track_1",
        source="youtube",
        sourceUrl="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Test Title",
        artist="Test Artist",
    )

    with patch("app.main.is_stream_v2_enabled", return_value=True), \
         patch("app.main.get_live_playback") as mock_glp, \
         patch("app.stream_cache.get_or_fetch", new_callable=AsyncMock) as mock_fetch:
        mock_glp.return_value.warm = AsyncMock(return_value=True)
        res = asyncio.run(main.stream_prefetch(req))
        assert res == {"ok": True, "warm": "resolved"}
        mock_glp.return_value.warm.assert_awaited_once()
        mock_fetch.assert_not_called()


def test_stream_prefetch_endpoint_reports_download_failure(track):
    """شکست آماده‌سازی باید پاسخ ناموفق بدهد تا زمان‌بندی کل صف ادامه یابد."""
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    from app.models import TrackRef

    req = TrackRef(
        trackId=track.id,
        sourceUrl=track.sourceUrl,
        title=track.title,
        artist=track.artist,
        quality="320",
    )
    with patch("app.stream_cache.get_or_fetch", new_callable=AsyncMock, side_effect=RuntimeError):
        try:
            asyncio.run(main.stream_prefetch(req))
        except HTTPException as exc:
            assert exc.status_code == 502
        else:
            raise AssertionError("prefetch failure should return HTTP 502")


def test_soundcloud_stream_download_uses_bestaudio_and_ffmpeg_postprocessor(clean_stream_cache, track):
    """ترک ساندکلاد حتی وقتی کیفیت ۳۲۰ ارسال می‌شود باید فرمت bestaudio و تبدیل FFmpeg داشته باشد."""
    from app.resolver import Candidate

    sc_track = track.model_copy(
        update={
            "source": "soundcloud",
            "sourceUrl": "https://soundcloud.com/dorccileaks/track-1",
        }
    )
    cache_key = stream_cache.cache_key_for(sc_track.id, quality="320")

    candidates = [
        Candidate(
            url="https://soundcloud.com/dorccileaks/track-1",
            title="Track 1",
            uploader="dorccileaks",
            duration_ms=180000,
            score=100.0,
            source="soundcloud",
        )
    ]

    captured_opts = {}

    def mock_extract(url, download=True):
        out_file = clean_stream_cache / f"{cache_key}.mp3"
        out_file.write_bytes(b"\x00" * 4096)
        return {"id": "mock_sc_1"}

    class MockYDL:
        def __init__(self, opts):
            captured_opts.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            return mock_extract(url, download=download)

    with (
        patch("app.stream_cache.resolver.resolve", return_value=candidates),
        patch("app.stream_cache.YoutubeDL", MockYDL),
    ):
        result_path = asyncio.run(stream_cache.get_or_fetch(sc_track, quality="320"))

    assert result_path.exists()
    assert captured_opts.get("format") == "bestaudio/best"
    assert captured_opts.get("postprocessors") == [
        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}
    ]


def test_resolver_candidate_caching(track, fresh_db):
    """کاندیداهای حل‌شده باید در حافظه و دیتابیس کش شوند تا بار دوم 0ms باشد."""
    from app import resolver

    resolver.invalidate_cache(track.id)

    dummy_candidate = Candidate(
        url="https://youtube.com/watch?v=cache_test",
        title=track.title,
        uploader=track.artist,
        duration_ms=track.durationMs,
        score=99.0,
        source="youtube",
    )

    with patch("app.resolver._search_all_sources", return_value=[dummy_candidate]) as mock_search:
        # اولین فراخوانی: جستجو انجام می‌شود و کش می‌شود
        res1 = resolver.resolve(track, use_cache=True)
        assert len(res1) == 1
        assert res1[0].url == "https://youtube.com/watch?v=cache_test"
        assert mock_search.call_count == 1

        # دومین فراخوانی: از کش خوانده می‌شود و تابع جستجو دیگر صدا زده نمی‌شود
        res2 = resolver.resolve(track, use_cache=True)
        assert len(res2) == 1
        assert res2[0].url == "https://youtube.com/watch?v=cache_test"
        assert mock_search.call_count == 1  # بدون افزایش


def test_progressive_chunk_streaming(clean_stream_cache, track):
    """استریم چانک‌ها باید بدون مسدود شدن برای دانلود کامل، تکه‌ها را فورا ارسال کند."""
    session = stream_cache.StreamBroadcaster("test_key", track)
    session.media_type = "audio/mp4"
    session.total_bytes = 1000
    session.ready_event.set()

    # چانک اول را تزریق می‌کنیم
    session.append_chunk(b"CHUNK_1")

    async def _test():
        gen = stream_cache._stream_generator(session)
        first_chunk = await gen.__anext__()
        assert first_chunk == b"CHUNK_1"

        # چانک دوم تزریق می‌شود
        session.append_chunk(b"CHUNK_2")
        second_chunk = await gen.__anext__()
        assert second_chunk == b"CHUNK_2"

        # پایان استریم
        session.finished_event.set()
        session.new_chunk_event.set()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    asyncio.run(_test())


def test_format_quality_scoring():
    """محاسبه امتیاز کیفیت باید فرمت‌های باکیفیت‌تر را برتر رتبه‌بندی کند."""
    f_flac = {"format_id": "flac", "acodec": "flac", "ext": "flac", "abr": 900, "vcodec": "none", "asr": 44100}
    f_opus_160 = {"format_id": "251", "acodec": "opus", "ext": "webm", "abr": 160, "vcodec": "none", "asr": 48000}
    f_aac_128 = {"format_id": "140", "acodec": "mp4a.40.2", "ext": "m4a", "abr": 128, "vcodec": "none", "asr": 44100}
    f_mp3_128 = {"format_id": "sc", "acodec": "mp3", "ext": "mp3", "abr": 128, "vcodec": "none", "asr": 44100}
    f_video_18 = {"format_id": "18", "acodec": "mp4a.40.2", "ext": "mp4", "abr": 96, "vcodec": "avc1", "asr": 22050}

    s_flac = stream_cache._format_quality_score(f_flac)
    s_opus = stream_cache._format_quality_score(f_opus_160)
    s_aac = stream_cache._format_quality_score(f_aac_128)
    s_mp3 = stream_cache._format_quality_score(f_mp3_128)
    s_video = stream_cache._format_quality_score(f_video_18)

    assert s_flac > s_opus > s_aac > s_mp3 > s_video


def test_extract_direct_stream_info_selects_highest_quality():
    """استخراج استریم باید بالاترین کیفیت ممکن را از بین فرمت‌های استخراج‌شده انتخاب کند."""
    mock_info = {
        "id": "mock_vid",
        "formats": [
            {"format_id": "18", "url": "https://googlevideo.com/18", "protocol": "https", "acodec": "mp4a.40.2", "vcodec": "avc1", "abr": 96, "ext": "mp4", "asr": 22050},
            {"format_id": "140", "url": "https://googlevideo.com/140", "protocol": "https", "acodec": "mp4a.40.2", "vcodec": "none", "abr": 128, "ext": "m4a", "asr": 44100},
            {"format_id": "251", "url": "https://googlevideo.com/251", "protocol": "https", "acodec": "opus", "vcodec": "none", "abr": 160, "ext": "webm", "asr": 48000},
        ],
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_info
    mock_ydl_ctx = MagicMock()
    mock_ydl_ctx.__enter__.return_value = mock_ydl

    with patch("app.stream_cache.YoutubeDL", return_value=mock_ydl_ctx):
        chosen = stream_cache._extract_direct_stream_info("https://youtube.com/watch?v=mock_vid")

    assert chosen is not None
    assert chosen["format_id"] == "251"


def test_stream_worker_falls_back_when_primary_candidate_fails(clean_stream_cache, track, fresh_db):
    """اگر کاندیدای اولیه شکست خورد، باید از resolve_fallback استفاده شده و استریم پخش شود."""
    cache_key = stream_cache.cache_key_for(track.id)
    primary = Candidate(
        url="https://soundcloud.com/lithe9/lychee-martini",
        title="Lychee Martini",
        uploader="Lithe",
        duration_ms=145000,
        score=100.0,
        source="soundcloud",
    )
    fallback_cand = Candidate(
        url="https://youtube.com/watch?v=fallback123",
        title="Lychee Martini",
        uploader="Lithe",
        duration_ms=145000,
        score=95.0,
        source="youtube",
    )

    def mock_extract(url, download=True):
        if "soundcloud" in url:
            raise RuntimeError("SoundCloud Go+ DRM error")
        out_file = clean_stream_cache / f"{cache_key}.m4a"
        out_file.write_bytes(b"\x00" * 4096)
        return {"id": "fallback123"}

    mock_ydl = MagicMock()
    mock_ydl.extract_info.side_effect = mock_extract
    mock_ydl_ctx = MagicMock()
    mock_ydl_ctx.__enter__.return_value = mock_ydl

    with (
        patch("app.stream_cache.resolver.resolve", return_value=[primary]),
        patch("app.stream_cache.resolver.resolve_fallback", return_value=[fallback_cand]) as mock_fb,
        patch("app.stream_cache.YoutubeDL", return_value=mock_ydl_ctx),
    ):
        result_path = asyncio.run(stream_cache.get_or_fetch(track))

    assert mock_fb.called
    assert result_path.exists()
    assert result_path.stem == cache_key


def test_stream_cache_evicts_stale_file_when_duration_mismatches(clean_stream_cache, track, fresh_db):
    """
    اگر فایلی در کش استریم با طول نامنطبق (مثلاً ۲۲۹ ثانیه) وجود داشته باشد،
    اما متادیتای مرجع ترک ۱۹۹ ثانیه باشد، فایل نامنطبق باید از دیسک پاک شده و بازگردانده نشود.
    """
    track = track.model_copy(update={"durationMs": 199_000})
    cache_key = stream_cache.cache_key_for(track.id)
    cached_file = clean_stream_cache / f"{cache_key}.m4a"
    cached_file.write_bytes(b"\x00" * 4096)

    # کاندیدای ذخیره‌شده در دیتابیس با طول ۲۲۹ ثانیه (۳:۴۹)
    fresh_db.put_resolved_candidates(track.id, [{
        "url": "https://soundcloud.com/slowed",
        "title": track.title,
        "uploader": track.artist,
        "duration_ms": 229_000,
        "score": 70.0,
        "source": "soundcloud",
    }])

    ready_file = stream_cache._find_ready_file_sync(track)
    assert ready_file is None, "فایل با طول نامنطبق نباید به عنوان فایل آماده تایید شود"
    assert not cached_file.exists(), "فایل نامنطبق باید از روی دیسک پاک شده باشد"


def test_stream_cache_clears_stale_when_canonical_override_present(clean_stream_cache, fresh_db):
    """اگر آدرس در اورراید قطعی تعریف شده باشد، کاندیدای مغایر قبلی پاک و ابطال می‌شود."""
    from app.models import Track
    from app import resolver

    tr = Track(
        id="sp:track:32xQkDh3INkWDqFYOdpZdP",
        title="Havasam",
        artist="Tlkhoon, Matin Fattahi",
        durationMs=199_000,
        source="spotify",
        sourceUrl="https://open.spotify.com/track/32xQkDh3INkWDqFYOdpZdP",
    )
    cache_key = stream_cache.cache_key_for(tr.id)
    cached_file = clean_stream_cache / f"{cache_key}.m4a"
    cached_file.write_bytes(b"\x00" * 4096)

    # فایل کش شده قبلی با URL اشتباه
    fresh_db.put_resolved_candidates(tr.id, [{
        "url": "https://soundcloud.com/random_user/slowed_reupload",
        "title": "Havasam Slowed",
        "uploader": "random_user",
        "duration_ms": 229_000,
        "score": 60.0,
        "source": "soundcloud",
    }])

    ready = stream_cache._find_ready_file_sync(tr)
    assert ready is None
    assert not cached_file.exists()


def test_stream_cache_purges_file_when_mutagen_duration_mismatches(clean_stream_cache, track, monkeypatch):
    """اگر متادیتا با مدت زمان واقعی فایل صوتی روی دیسک تفاوت داشته باشد، فایل از دیسک پاک می‌شود."""
    track = track.model_copy(update={"durationMs": 199_000})  # 3:19
    cache_key = stream_cache.cache_key_for(track.id)
    cached_file = clean_stream_cache / f"{cache_key}.mp3"
    cached_file.write_bytes(b"\x00" * 4096)

    # شبیه‌سازی خواندن طول واقعی فایل با mutagen (فایل واقعی روی دیسک ۲۲۹ ثانیه است)
    monkeypatch.setattr(stream_cache, "file_duration_ms", lambda p: 229_000)

    ready = stream_cache._find_ready_file_sync(track)
    assert ready is None
    assert not cached_file.exists(), "فایل صوتی که طول واقعی آن ۲۲۹ ثانیه است باید از دیسک پاک شود"


def test_find_any_ready_prefers_highest_quality(tmp_path, track, fresh_db):
    """تابع find_any_ready در صورت وجود چند کیفیت مختلف، بالاترین کیفیت را انتخاب می‌کند."""
    p128 = tmp_path / "song_128.mp3"
    p320 = tmp_path / "song_320.mp3"
    pflac = tmp_path / "song_flac.flac"
    p128.write_bytes(b"\x00" * 100)
    p320.write_bytes(b"\x00" * 200)
    pflac.write_bytes(b"\x00" * 400)

    fresh_db.insert_job("job-1", track, "128", "ready", time.time() - 30)
    fresh_db.update_job("job-1", status="ready", path=str(p128), bytes=100)

    fresh_db.insert_job("job-2", track, "320", "ready", time.time() - 20)
    fresh_db.update_job("job-2", status="ready", path=str(p320), bytes=200)

    fresh_db.insert_job("job-3", track, "flac", "ready", time.time() - 10)
    fresh_db.update_job("job-3", status="ready", path=str(pflac), bytes=400)

    best_row = fresh_db.find_any_ready(track.id)
    assert best_row is not None
    assert best_row["quality"] == "flac"
    assert best_row["id"] == "job-3"


