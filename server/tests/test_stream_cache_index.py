"""
تست‌های نمایه‌ی سریع کش فایل‌های استریم (stream_cache index) — بدون جست‌وجوی تکراری دیسک.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.models import Track
from app.stream_cache import (
    _cache_index,
    _find_cached_audio,
    find_ready_file,
    note_file_written,
)


def make_test_track(track_id: str = "test1234") -> Track:
    return Track(
        id=track_id,
        title="Test Song",
        artist="Test Artist",
        durationMs=1000,
        source="spotify",
        sourceUrl="https://spotify.com/track/123",
    )


class TestStreamCacheIndex:
    def test_index_caches_lookup_within_ttl(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.stream_cache.STREAM_CACHE_DIR", tmp_path)
        _cache_index.clear()

        # یک فایل تستی در کش
        fake_audio = tmp_path / "str_abcd1234efgh5678.mp3"
        fake_audio.write_bytes(b"\x00" * 2048)

        scan_count = 0
        real_iterdir = Path.iterdir

        def mock_iterdir(self):
            nonlocal scan_count
            if self == tmp_path:
                scan_count += 1
            return real_iterdir(self)

        with patch.object(Path, "iterdir", mock_iterdir):
            # بار اول اسکن انجام می‌شود
            p1 = _find_cached_audio("str_abcd1234efgh5678")
            assert p1 == fake_audio
            assert scan_count == 1

            # بار دوم با TTL 3 ثانیه از کش نمایه برمی‌گردد بدون اسکن دیسک
            p2 = _find_cached_audio("str_abcd1234efgh5678")
            assert p2 == fake_audio
            assert scan_count == 1

            # اگر fresh=True باشد، نمایه دور زده می‌شود و مجدداً اسکن می‌شود
            p3 = _find_cached_audio("str_abcd1234efgh5678", fresh=True)
            assert p3 == fake_audio
            assert scan_count == 2

    def test_note_file_written_invalidates_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.stream_cache.STREAM_CACHE_DIR", tmp_path)
        _cache_index.clear()

        fake_audio = tmp_path / "str_key999.m4a"
        fake_audio.write_bytes(b"\x00" * 2048)

        # در نمایه می‌نشیند
        p1 = _find_cached_audio("str_key999")
        assert p1 == fake_audio
        assert "str_key999" in _cache_index

        # با اعلام نوشتن فایل، کلید باطل می‌شود
        note_file_written(fake_audio)
        assert "str_key999" not in _cache_index

    @pytest.mark.asyncio
    async def test_find_ready_file_runs_async_in_thread(self, tmp_path, monkeypatch, fresh_db):
        monkeypatch.setattr("app.stream_cache.STREAM_CACHE_DIR", tmp_path)
        track = make_test_track("async_test")

        # فراخوانی find_ready_file باید بدون خطا و به عنوان async function در ترد اجرا شود
        res = await find_ready_file(track)
        assert res is None  # چون فایلی هنوز آماده نشده
