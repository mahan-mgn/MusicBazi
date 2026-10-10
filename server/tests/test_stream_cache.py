from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import db, main, stream_cache
from app.models import Track
from app.resolver import Candidate


@pytest.fixture
def clean_stream_cache(tmp_path, monkeypatch, fresh_db):
    cache_dir = tmp_path / "cache" / "stream"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(stream_cache, "STREAM_CACHE_DIR", cache_dir)
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
    lrc_file = clean_stream_cache / f"{cache_key}.lrc"
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


