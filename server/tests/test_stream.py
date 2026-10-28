"""
پخش در مرورگر — همان فایلِ دانلود، ولی با قرارداد متفاوت.

دو چیز اینجا واقعاً مهم است و هر دو بی‌سروصدا خراب می‌شوند: mime درست (وگرنه
`<audio>` اصلاً رمزگشایی را شروع نمی‌کند) و نبودِ content-disposition (وگرنه
مرورگر وسط پخش، دانلود را شروع می‌کند).
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import HTTPException

from app import jobs, main


@pytest.fixture
def stream_db(tmp_path, monkeypatch, fresh_db):
    monkeypatch.setattr(jobs, "DOWNLOAD_DIR", tmp_path)
    jobs.manager._jobs.clear()
    return fresh_db


def _ready(db, track, job_id, path):
    path.write_bytes(b"\x00" * 64)
    db.insert_job(job_id, track, "320", "ready", time.time())
    db.update_job(job_id, status="ready", path=str(path), bytes=64)


@pytest.mark.parametrize(
    ("name", "mime"),
    [
        ("a.mp3", "audio/mpeg"),
        ("a.m4a", "audio/mp4"),
        ("a.opus", "audio/ogg"),
        ("a.flac", "audio/flac"),
    ],
)
def test_mime_follows_the_real_extension(stream_db, tmp_path, track, name, mime):
    _ready(stream_db, track, "j1", tmp_path / name)

    response = asyncio.run(main.stream_file("j1"))

    assert response.media_type == mime


def test_stream_is_not_an_attachment(stream_db, tmp_path, track):
    """با content-disposition، دانلودمنیجر مرورگر وسط پخش می‌پرد."""
    _ready(stream_db, track, "j1", tmp_path / "a.mp3")

    response = asyncio.run(main.stream_file("j1"))

    assert "content-disposition" not in response.headers
    # جابه‌جایی روی نوار پخش بدون این هدر، کل فایل را دوباره دانلود می‌کند
    assert response.headers.get("accept-ranges") == "bytes"


def test_download_stays_an_attachment(stream_db, tmp_path, track):
    """اندپوینت ذخیره نباید قربانی تغییرِ اندپوینت پخش شود."""
    _ready(stream_db, track, "j1", tmp_path / "a.mp3")

    response = asyncio.run(main.download_file("j1"))

    assert "attachment" in response.headers.get("content-disposition", "")


def test_missing_file_is_404(stream_db, tmp_path, track):
    stream_db.insert_job("ghost", track, "320", "ready", time.time())
    stream_db.update_job(
        "ghost", status="ready", path=str(tmp_path / "vanished.mp3"), bytes=1
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.stream_file("ghost"))

    assert exc.value.status_code == 404


def test_find_any_ready_by_meta_matches_different_track_id(stream_db, tmp_path, track):
    """اگر ترکی با شناسه‌ی آلبوم دانلود شده باشد، درخواست با شناسه‌ی سینگل باید همان فایل را پیدا کند."""
    album_track = track.model_copy(update={"id": "sp:track:album-id", "title": "Aminak Hit", "artist": "Aminak"})
    _ready(stream_db, album_track, "job-album", tmp_path / "hit.mp3")

    # جستجو با شناسه‌ی متفاوتِ سینگل
    found = stream_db.find_any_ready("sp:track:single-id")
    assert found is None

    # ولی جستجو با متادیتا باید فایل دانلودشده را بیابد
    found_meta = stream_db.find_any_ready_by_meta("Aminak Hit - Single", "Aminak")
    assert found_meta is not None
    assert found_meta["id"] == "job-album"


class TestThumbEndpoint:
    """
    `/thumb` برای باتِ تلگرام است: بات به‌جای گرفتنِ دوباره‌ی کاور از CDN — که
    گاهی تایم‌اوت می‌داد و ردیفِ آهنگ را در لیست بی‌تصویر می‌گذاشت — همین را
    از سرور می‌خواهد، و سرور از داخلِ خودِ فایل درش می‌آورد.
    """

    def test_a_missing_job_is_not_found(self, stream_db):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(main.download_thumb("nope"))

        assert raised.value.status_code == 404

    def test_a_file_with_no_cover_anywhere_is_not_found(
        self, stream_db, tmp_path, track, monkeypatch
    ):
        """۴۰۴ یعنی «کاوری نیست»؛ بات همان‌جا بی‌کاور می‌فرستد، نه اینکه بیفتد."""
        monkeypatch.setattr(main.downloader, "thumbnail", lambda path, url=None: None)
        _ready(stream_db, track, "j-thumb-none", tmp_path / "a.mp3")

        with pytest.raises(HTTPException) as raised:
            asyncio.run(main.download_thumb("j-thumb-none"))

        assert raised.value.status_code == 404

    def test_the_cover_comes_back_as_jpeg(self, stream_db, tmp_path, track, monkeypatch):
        monkeypatch.setattr(main.downloader, "thumbnail", lambda path, url=None: b"\xff\xd8jpeg")
        _ready(stream_db, track, "j-thumb-ok", tmp_path / "a.mp3")

        response = asyncio.run(main.download_thumb("j-thumb-ok"))

        assert response.media_type == "image/jpeg"
        assert response.body == b"\xff\xd8jpeg"

    def test_the_catalog_url_is_offered_as_the_fallback(
        self, stream_db, tmp_path, track, monkeypatch
    ):
        """
        فایلِ بی‌کاور هنوز می‌تواند کاور داشته باشد — از همان کاتالوگی که ترک
        از آن آمده. بدونِ پاس دادنِ آدرس، آن مسیر هیچ‌وقت امتحان نمی‌شد.
        """
        seen: dict = {}

        def spy(path, url=None):
            seen["url"] = url
            return b"\xff\xd8"

        monkeypatch.setattr(main.downloader, "thumbnail", spy)
        _ready(stream_db, track, "j-thumb-url", tmp_path / "a.mp3")

        asyncio.run(main.download_thumb("j-thumb-url"))

        assert seen["url"] == track.artworkUrl
