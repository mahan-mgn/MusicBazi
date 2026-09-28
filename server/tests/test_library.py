"""
کتابخانه — همان جاب‌های موفقی که فایلشان هنوز روی دیسک است.

نکته‌ی ظریفش این است که شمارش و حجم از SQL می‌آیند ولی وجود فایل را فقط
فایل‌سیستم می‌داند؛ این دو باید یک چیز بگویند.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from app import jobs, main
from app.models import DownloadRequest


@pytest.fixture
def library_db(tmp_path, monkeypatch, fresh_db):
    monkeypatch.setattr(jobs, "DOWNLOAD_DIR", tmp_path)
    jobs.manager._jobs.clear()
    return fresh_db


def _ready(db, track, job_id, path, quality="320", size=100):
    db.insert_job(job_id, track, quality, "ready", time.time())
    db.update_job(job_id, status="ready", path=str(path), bytes=size)


def test_ready_files_are_listed(library_db, tmp_path, track):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x" * 100)
    _ready(library_db, track, "j1", audio)

    page = asyncio.run(main.library())

    assert page.total == 1
    assert page.totalBytes == 100
    assert [i.jobId for i in page.items] == ["j1"]


def test_summary_never_counts_a_row_whose_file_is_gone(library_db, tmp_path, track):
    """
    قبلاً هدر «۲ آهنگ، ۱۷ مگابایت» می‌گفت درحالی‌که لیست خالی بود: ردیف از
    خروجی حذف می‌شد ولی از جمع نه.
    """
    present = tmp_path / "here.mp3"
    present.write_bytes(b"x" * 100)
    _ready(library_db, track, "j1", present, size=100)
    _ready(library_db, track, "j2", tmp_path / "vanished.mp3", size=900)

    page = asyncio.run(main.library())

    assert [i.jobId for i in page.items] == ["j1"]
    assert page.total == 1
    assert page.totalBytes == 100


def test_a_row_without_its_file_is_swept_not_just_hidden(library_db, tmp_path, track):
    """پنهان کردنش یعنی هر بار دوباره پیدایش می‌کنیم — ردیف باید برود."""
    _ready(library_db, track, "ghost", tmp_path / "vanished.mp3")

    asyncio.run(main.library())

    assert library_db.get_job("ghost") is None


def test_search_filters_by_title(library_db, tmp_path, track):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    _ready(library_db, track, "j1", audio)

    assert asyncio.run(main.library(q=track.title)).total == 1
    assert asyncio.run(main.library(q="چیزی که وجود ندارد")).total == 0


def test_mood_is_merged_onto_the_track(library_db, tmp_path, track):
    """
    والانس/انرژی روی ستون‌های خودِ جاب‌اند نه track_json — باید موقع ساختِ
    LibraryItem سرهم شوند، وگرنه شافلِ فرانت هیچ‌وقت این دو را نمی‌بیند.
    """
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    _ready(library_db, track, "j1", audio)
    library_db.update_job("j1", valence=0.75, energy=0.2)

    page = asyncio.run(main.library())

    assert page.items[0].track.valence == 0.75
    assert page.items[0].track.energy == 0.2


def test_mood_defaults_to_none_before_analysis(library_db, tmp_path, track):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    _ready(library_db, track, "j1", audio)

    page = asyncio.run(main.library())

    assert page.items[0].track.valence is None
    assert page.items[0].track.energy is None


class TestReuseBackfill:
    """
    فایلی که از قبل گرفته شده تگش را از همان روز دارد. کسی که ترکی را از
    نتیجه‌ی جستجو گرفته و حالا کل آلبوم را می‌گیرد، باید متادیتای آلبومی‌اش
    هم به‌روز شود — وگرنه همان ترک در ZIP بی‌شماره و بی‌هنرمندِ آلبوم می‌ماند
    و آلبوم در پلیر تکه‌تکه دیده می‌شود.
    """

    def _reuse(self, track):
        async def go():
            return jobs.manager.create(track, "320")

        return asyncio.run(go())

    def test_missing_album_metadata_is_filled_in(self, library_db, tmp_path, track):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"x" * 100)
        _ready(library_db, track, "j1", audio)
        richer = track.model_copy(
            update={"albumArtist": "Farhad Mehrad", "trackNumber": 4, "year": 1978}
        )

        job, reused = self._reuse(richer)

        assert reused is True
        assert (job.track.albumArtist, job.track.trackNumber, job.track.year) == (
            "Farhad Mehrad", 4, 1978,
        )
        # در دیتابیس هم نشسته، نه فقط در کشِ حافظه — وگرنه ری‌استارت پاکش می‌کرد
        stored = json.loads(library_db.get_job("j1")["track_json"])
        assert stored["albumArtist"] == "Farhad Mehrad"

    def test_what_is_already_known_is_not_overwritten(self, library_db, tmp_path, track):
        """درخواستِ تازه فقط جای خالی را پر می‌کند، جای پر را نه."""
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"x" * 100)
        known = track.model_copy(update={"albumArtist": "Various Artists"})
        _ready(library_db, known, "j1", audio)

        job, _ = self._reuse(track.model_copy(update={"albumArtist": "Farhad Mehrad"}))

        assert job.track.albumArtist == "Various Artists"

    def test_single_reused_in_album_gets_album_artwork(self, library_db, tmp_path, track, monkeypatch):
        """ترکی که به عنوان سینگل ذخیره شده بود وقتی در قالب آلبوم خواسته می‌شود کاور آلبوم را می‌گیرد."""
        retagged = []
        monkeypatch.setattr(jobs.downloader, "retag_artwork", lambda path, url: retagged.append((path, url)))
        monkeypatch.setattr(jobs.downloader, "retag_album", lambda *_: None)

        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"x" * 100)
        single = track.model_copy(
            update={"album": track.title, "artworkUrl": "https://cdn.example.com/single.jpg"}
        )
        _ready(library_db, single, "j1", audio)

        album_track = track.model_copy(
            update={
                "album": "New Album",
                "albumId": "sc:playlist:999",
                "trackNumber": 3,
                "artworkUrl": "https://cdn.example.com/album.jpg",
            }
        )

        job, reused = self._reuse(album_track)

        assert reused is True
        assert job.track.album == "New Album"
        assert job.track.trackNumber == 3
        assert job.track.artworkUrl == "https://cdn.example.com/album.jpg"
        assert retagged == [(audio, "https://cdn.example.com/album.jpg")]
        stored = json.loads(library_db.get_job("j1")["track_json"])
        assert stored["artworkUrl"] == "https://cdn.example.com/album.jpg"
        assert stored["album"] == "New Album"


class TestReuseLyrics:
    """
    فایلی که روزِ دانلود متنی برایش پیدا نشد، در دانلودِ دوباره باید یک شانسِ
    دیگر بگیرد. بدون این، تنها راهِ باقی‌مانده پاک کردنِ دستیِ ترک بود.
    """

    @pytest.fixture
    def found(self, monkeypatch):
        """متنی که این بار پیدا می‌شود، به‌علاوه‌ی شمارشِ دفعاتِ جستجو."""
        from app.providers.lrclib import Lyrics

        calls: list[str] = []

        def fake_fetch(track):
            calls.append(track.title)
            return Lyrics(plain="متن", synced=None)

        monkeypatch.setattr(jobs.downloader, "fetch_lyrics", fake_fetch)
        monkeypatch.setattr(jobs.downloader, "attach_lyrics", lambda *_: None)
        return calls

    def _reuse(self, track):
        """بازاستفاده، به‌علاوه‌ی انتظار برای کارِ پس‌زمینه‌ای که راه انداخته."""

        async def go():
            job, reused = jobs.manager.create(track, "320")
            await asyncio.gather(*jobs.manager._background)
            return job, reused

        return asyncio.run(go())

    def test_a_file_without_lyrics_tries_again(self, library_db, tmp_path, track, found):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"x" * 100)
        _ready(library_db, track, "j1", audio)

        job, reused = self._reuse(track)

        assert reused is True
        assert found == [track.title]
        assert job.lyrics_path == audio.with_suffix(".lrc")
        assert job.lyrics_path.read_text(encoding="utf-8") == "متن"
        # ردیف هم باید بداند، وگرنه بعد از ری‌استارت دوباره بی‌متن است
        assert library_db.get_job("j1")["lyrics_path"] == str(job.lyrics_path)

    def test_a_file_that_already_has_lyrics_is_left_alone(
        self, library_db, tmp_path, track, found
    ):
        """متنِ موجود دوباره گرفته نمی‌شود — نه شبکه‌اش می‌ارزد نه بازنویسی‌اش."""
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"x" * 100)
        lrc = audio.with_suffix(".lrc")
        lrc.write_text("[00:01.00]قبلی", encoding="utf-8")
        _ready(library_db, track, "j1", audio)
        library_db.update_job("j1", lyrics_path=str(lrc))

        self._reuse(track)

        assert found == []
        assert lrc.read_text(encoding="utf-8") == "[00:01.00]قبلی"


class TestRequestMetadata:
    """
    فرانت متادیتا را همراه درخواست می‌فرستد تا سرور دوباره lookup نکند. هر
    فیلدی که اینجا جا بماند، بی‌صدا از تگِ فایل و از گروه‌بندیِ کتابخانه هم
    جا می‌ماند.
    """

    def test_album_identity_reaches_the_track(self, track):
        req = DownloadRequest(
            trackId=track.id,
            sourceUrl=track.sourceUrl,
            title=track.title,
            artist="Farhad Mehrad, Guest",
            album="Mard-E Tanha",
            albumId="itunes:album:9",
            albumArtist="Farhad Mehrad",
            durationMs=1,
            trackNumber=4,
        )

        built = asyncio.run(main._track_for(None, req))

        assert (built.albumId, built.albumArtist) == ("itunes:album:9", "Farhad Mehrad")
        assert built.artist == "Farhad Mehrad, Guest"
