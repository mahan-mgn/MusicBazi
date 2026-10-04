"""
تست‌های کشِ قدیمیِ بات (`store`) — که حالا فقط خواندنِ ردیف‌ها برای مهاجرت و
خالی‌کردنشان بعد از موفقیت را نگه داشته است. SQLite واقعی روی فایلِ موقت،
بدون شبکه و بدون mock.
"""

from __future__ import annotations

import time

import pytest

from app.bot import store


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """هر تست دیتابیسِ خودش را دارد — ردیفِ تستِ قبلی نباید دیده شود."""
    monkeypatch.setattr(store, "BOT_DB_PATH", tmp_path / "bot.db")
    yield
    store.close()


def _seed(chat_id: int, artist_id: str, name: str) -> None:
    """درجِ مستقیم — خودِ `add` عمداً حذف شده تا مسیرِ نوشتن یکی بماند (سرور)."""
    conn = store._db()
    conn.execute(
        """INSERT INTO follows
           (chat_id, artist_id, artist_name, artist_source_url, source,
            artwork_url, last_release_id, last_release_title, created_at)
           VALUES (?, ?, ?, ?, 'spotify', NULL, 'a1', 'Album One', ?)""",
        (chat_id, artist_id, name, "https://open.spotify.com/artist/x", time.time()),
    )
    conn.commit()


class TestAllFollows:
    def test_returns_follows_across_every_chat(self):
        _seed(1, "sp:artist:1", "Farhad")
        _seed(2, "sp:artist:2", "Dariush")
        names = {f.artist_name for f in store.all_follows()}
        assert names == {"Farhad", "Dariush"}

    def test_empty_when_no_legacy_rows(self):
        assert store.all_follows() == []

    def test_row_maps_to_legacy_fields(self):
        _seed(7, "sp:artist:1", "Farhad")
        [f] = store.all_follows()
        assert f.chat_id == 7
        assert f.artist_id == "sp:artist:1"
        assert f.last_release_id == "a1"
        assert f.last_release_title == "Album One"


class TestClearAll:
    def test_empties_the_legacy_table(self):
        _seed(1, "sp:artist:1", "Farhad")
        store.clear_all()
        assert store.all_follows() == []

    def test_clearing_twice_is_fine(self):
        store.clear_all()
        store.clear_all()


class TestTelegramFilesCache:
    def test_save_and_get_cached_file(self):
        store.save_telegram_file(
            "track-1:320",
            file_id="CQACAgQAAxkBAAE...",
            file_unique_id="unique-123",
            title="Song",
            artist="Singer",
            duration_sec=210,
            quality="mp3 320",
            artwork_url="https://example.com/cover.jpg",
        )
        cached = store.get_telegram_file("track-1:320")
        assert cached is not None
        assert cached["file_id"] == "CQACAgQAAxkBAAE..."
        assert cached["title"] == "Song"
        assert cached["duration_sec"] == 210
        assert cached["quality"] == "mp3 320"
        assert cached["artwork_url"] == "https://example.com/cover.jpg"

    def test_get_missing_key_returns_none(self):
        assert store.get_telegram_file("nonexistent") is None

    def test_delete_cached_file(self):
        store.save_telegram_file("track-1:320", file_id="file-1")
        assert store.get_telegram_file("track-1:320") is not None
        store.delete_telegram_file("track-1:320")
        assert store.get_telegram_file("track-1:320") is None

    def test_delete_telegram_files_for_track(self):
        store.save_telegram_file("track-1", file_id="f1")
        store.save_telegram_file("track-1:320", file_id="f2")
        store.save_telegram_file("track-1:default", file_id="f3")
        store.save_telegram_file("https://soundcloud.com/sc-1:320", file_id="f4")
        store.save_telegram_file("track-2:320", file_id="f5")

        store.delete_telegram_files_for_track("track-1", "https://soundcloud.com/sc-1")

        assert store.get_telegram_file("track-1") is None
        assert store.get_telegram_file("track-1:320") is None
        assert store.get_telegram_file("track-1:default") is None
        assert store.get_telegram_file("https://soundcloud.com/sc-1:320") is None
        assert store.get_telegram_file("track-2:320") is not None

    def test_empty_or_invalid_inputs_handled_safely(self):
        store.save_telegram_file("", "")
        assert store.get_telegram_file("") is None
        store.delete_telegram_file("")


class TestLyricsCache:
    def test_save_and_get_lyrics(self):
        store.save_lyrics("hash123", "Line 1\nLine 2", title="Song", artist="Singer")
        cached = store.get_lyrics("hash123")
        assert cached is not None
        assert cached["lyrics"] == "Line 1\nLine 2"
        assert cached["title"] == "Song"
        assert cached["artist"] == "Singer"

    def test_get_missing_lyrics_returns_none(self):
        assert store.get_lyrics("nonexistent") is None

    def test_empty_lyrics_not_saved(self):
        store.save_lyrics("empty", "")
        assert store.get_lyrics("empty") is None


class TestChatQuality:
    def test_save_and_get_chat_quality(self):
        store.save_chat_quality(12345, "flac")
        assert store.get_chat_quality(12345) == "flac"

    def test_update_chat_quality(self):
        store.save_chat_quality(12345, "128")
        assert store.get_chat_quality(12345) == "128"
        store.save_chat_quality(12345, "320")
        assert store.get_chat_quality(12345) == "320"

    def test_missing_chat_quality_returns_none(self):
        assert store.get_chat_quality(999999) is None

    def test_invalid_chat_id_handled_safely(self):
        store.save_chat_quality(None, "320")
        assert store.get_chat_quality(None) is None
        assert store.get_chat_quality("not-an-int") is None


class TestRefCache:
    def test_save_and_get_ref(self):
        store.save_ref("h_123456", "https://example.com/very/long/album/ref/123456789")
        assert store.get_ref("h_123456") == "https://example.com/very/long/album/ref/123456789"

    def test_safe_callback_ref_short_returns_verbatim(self):
        ref = "simple_artist_id"
        safe = store.safe_callback_ref(ref)
        assert safe == ref
        assert store.resolve_callback_ref(safe) == ref

    def test_safe_callback_ref_long_returns_short_hash(self):
        long_url = "https://music.youtube.com/playlist?list=OLAK5uy_k1234567890123456789012345678901234567890"
        safe = store.safe_callback_ref(long_url)
        assert safe.startswith("h_")
        assert len(safe.encode("utf-8")) <= 20
        recovered = store.resolve_callback_ref(safe)
        assert recovered == long_url

    def test_safe_callback_ref_with_colon_returns_hash(self):
        ref_with_colon = "spotify:artist:123"
        safe = store.safe_callback_ref(ref_with_colon)
        assert safe.startswith("h_")
        assert store.resolve_callback_ref(safe) == ref_with_colon

    def test_resolve_callback_ref_non_hash_returns_as_is(self):
        assert store.resolve_callback_ref("normal_ref") == "normal_ref"
        assert store.resolve_callback_ref("") == ""


class TestStoreConcurrency:
    def test_concurrent_reads_and_writes(self):
        from concurrent.futures import ThreadPoolExecutor

        def worker(i: int):
            store.save_telegram_file(f"track-{i}", file_id=f"fid-{i}")
            store.save_chat_quality(i, "320")
            store.save_ref(f"h_{i}", f"ref_{i}")
            assert store.get_telegram_file(f"track-{i}") is not None
            assert store.get_chat_quality(i) == "320"
            assert store.get_ref(f"h_{i}") == f"ref_{i}"

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(worker, range(40)))

