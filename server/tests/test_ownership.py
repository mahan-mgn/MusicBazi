"""
جداسازیِ داده‌ی هر حساب — مرحله‌ی دومِ حساب‌های کاربری.

قاعده‌ای که همه‌ی این تست‌ها از آن محافظت می‌کنند: **یک فایل روی دیسک، یک
ردیف `jobs`، ولی کتابخانه/لایک/پخش/پلی‌لیست مالِ خودِ کاربر.** دو نفر که یک
ترک را دانلود می‌کنند فایل را share می‌کنند؛ کسی که ترک را برمی‌دارد فقط
مالکیتِ خودش را از دست می‌دهد و فایل تا آخرین مالک می‌ماند.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app import db, jobs, main
from app.models import PlayEvent, PlaylistCreate


@pytest.fixture
def library(tmp_path, monkeypatch, fresh_db):
    monkeypatch.setattr(jobs, "DOWNLOAD_DIR", tmp_path)
    jobs.manager._jobs.clear()
    return fresh_db


def _second_user(user_id: str = "u2") -> str:
    db.create_user(user_id, "local", username=user_id)
    return user_id


def _ready(db, track, job_id, tmp_path, *, title: str | None = None, user_id: str = "local"):
    audio = tmp_path / f"{job_id}.mp3"
    audio.write_bytes(b"x" * 10)
    stored = track.model_copy(update={"id": f"{track.id}:{job_id}", "title": title or track.title})
    db.insert_job(job_id, stored, "320", "ready", time.time(), user_id=user_id)
    db.update_job(job_id, status="ready", path=str(audio), bytes=10)
    return job_id


# ---------- کتابخانه ----------


def test_a_job_added_by_one_user_is_invisible_to_another(library, track, tmp_path):
    _ready(library, track, "j1", tmp_path)
    other = _second_user()

    mine, total, _ = library.library()
    theirs, their_total, their_bytes = library.library(user_id=other)

    assert total == 1 and [r["id"] for r in mine] == ["j1"]
    assert their_total == 0 and theirs == [] and their_bytes == 0


def test_library_totals_are_per_user(library, track, tmp_path):
    other = _second_user()
    _ready(library, track, "j1", tmp_path)
    _ready(library, track, "j2", tmp_path, title="Other", user_id=other)

    _, guest_total, guest_bytes = library.library()
    _, other_total, other_bytes = library.library(user_id=other)

    assert guest_total == 1 and other_total == 1
    # حجم هم اسکوپ می‌شود، وگرنه هدرِ کتابخانه حجمِ حسابِ دیگری را هم می‌شمرد
    assert guest_bytes == other_bytes == 10


def test_search_only_sees_your_own_library(library, track, tmp_path):
    _ready(library, track, "j1", tmp_path, title="Jomeh")
    other = _second_user()

    assert library.library("jomeh")[1] == 1
    assert library.library("jomeh", user_id=other)[1] == 0


# ---------- مالکیت ----------


def test_sharing_one_file_keeps_two_separate_libraries(library, track, tmp_path):
    """همان فایل، دو کتابخانه — دقیقاً تصمیمی که جدولِ جدا برایش ساخته شد."""
    job_id = _ready(library, track, "j1", tmp_path)
    other = _second_user()

    library.own(job_id, other)

    assert library.owner_count(job_id) == 2
    assert library.owns_job("local", job_id) and library.owns_job(other, job_id)
    # یک ردیفِ جاب، دو مالک — فایل دوباره دانلود نمی‌شود
    assert len(library._query("SELECT id FROM jobs")) == 1


def test_owning_twice_does_not_reset_added_at_or_favorite(library, track, tmp_path):
    job_id = _ready(library, track, "j1", tmp_path)
    library.set_favorite(job_id, True)
    before = library._query(
        "SELECT favorite, added_at FROM job_owners WHERE job_id = ?", (job_id,)
    )[0]

    library.own(job_id, "local", added_at=time.time() + 999)

    after = library._query(
        "SELECT favorite, added_at FROM job_owners WHERE job_id = ?", (job_id,)
    )[0]
    assert after["favorite"] == before["favorite"] == 1
    assert after["added_at"] == before["added_at"]


def test_disown_leaves_the_file_for_the_other_owner(library, track, tmp_path):
    job_id = _ready(library, track, "j1", tmp_path)
    other = _second_user()
    library.own(job_id, other)

    assert library.disown(job_id, "local") is True

    assert library.owner_count(job_id) == 1
    assert library.get_job(job_id) is not None
    assert library.owns_job(other, job_id)
    assert library.owns_job("local", job_id) is False


# ---------- علاقه‌مندی ----------


def test_favorites_are_per_user(library, track, tmp_path):
    job_id = _ready(library, track, "j1", tmp_path)
    other = _second_user()
    library.own(job_id, other)

    library.set_favorite(job_id, True)

    assert [r["id"] for r in library.favorite_jobs()] == [job_id]
    assert library.favorite_jobs(user_id=other) == []


def test_favoriting_someone_elses_track_does_nothing(library, track, tmp_path):
    job_id = _ready(library, track, "j1", tmp_path)
    other = _second_user()

    assert library.set_favorite(job_id, True, other) is False
    assert library.favorite_jobs() == []


# ---------- پخش و آمار ----------


def _play(job_id: str, user_id: str, seconds: int = 10):
    return asyncio.run(main.record_play(PlayEvent(jobId=job_id, seconds=seconds), user_id))


def test_plays_are_recorded_for_the_listener_only(library, track, tmp_path):
    job_id = _ready(library, track, "j1", tmp_path)
    other = _second_user()
    library.own(job_id, other)

    _play(job_id, "local")

    assert len(library.recent_plays(10)) == 1
    assert library.recent_plays(10, other) == []
    assert library.play_totals(0)[0] == 1
    assert library.play_totals(0, other)[0] == 0


def test_playing_a_track_you_do_not_own_is_rejected(library, track, tmp_path):
    """وگرنه هر کسی با حدسِ شناسه می‌توانست آمارِ حسابِ دیگری را آلوده کند."""
    job_id = _ready(library, track, "j1", tmp_path)
    other = _second_user()

    with pytest.raises(Exception):
        _play(job_id, other)

    assert library.recent_plays(10, other) == []


def test_top_charts_do_not_leak_between_accounts(library, track, tmp_path):
    other = _second_user()
    _ready(library, track, "j1", tmp_path, title="Mine")
    _ready(library, track, "j2", tmp_path, title="Theirs", user_id=other)

    _play("j1", "local")
    _play("j2", other)

    assert [r["title"] for r in library.top_tracks(0, 10)] == ["Mine"]
    assert [r["title"] for r in library.top_tracks(0, 10, other)] == ["Theirs"]


# ---------- میکس و مالکیتِ ردیف‌ها ----------


def test_daily_mix_only_contains_your_own_tracks(library, track, tmp_path):
    other = _second_user()
    _ready(library, track, "j1", tmp_path, title="Mine")
    _ready(library, track, "j2", tmp_path, title="Theirs", user_id=other)

    mine = library.daily_mix(None, set(), 10)
    theirs = library.daily_mix(None, set(), 10, other)

    assert [r["id"] for r in mine] == ["j1"]
    assert [r["id"] for r in theirs] == ["j2"]


def test_owned_refs_are_per_user(library, track, tmp_path):
    _ready(library, track, "j1", tmp_path)
    other = _second_user()

    assert list(library.owned_refs([f"{track.id}:j1"])) == [f"{track.id}:j1"]
    assert library.owned_refs([f"{track.id}:j1"], other) == {}


# ---------- پلی‌لیست ----------


def _playlist(user_id: str, name: str = "My mix") -> str:
    created = asyncio.run(
        main.create_playlist(PlaylistCreate(name=name, kind="manual"), user_id)
    )
    return created.id


def test_a_playlist_belongs_to_its_creator(library):
    mine = _playlist("local", "Mine")
    theirs = _playlist(_second_user(), "Theirs")

    assert [p.id for p in asyncio.run(main.list_playlists())] == [mine]
    assert [p.id for p in asyncio.run(main.list_playlists("u2"))] == [theirs]


def test_opening_someone_elses_playlist_is_a_404(library):
    theirs = _playlist(_second_user())

    with pytest.raises(Exception):
        asyncio.run(main.get_playlist(theirs))

    assert asyncio.run(main.get_playlist(theirs, "u2")).id == theirs


def test_deleting_someone_elses_playlist_is_refused(library):
    theirs = _playlist(_second_user())

    with pytest.raises(Exception):
        asyncio.run(main.remove_playlist(theirs))

    assert asyncio.run(main.get_playlist(theirs, "u2")).id == theirs


def test_adding_a_track_you_do_not_own_is_refused(library, track, tmp_path):
    job_id = _ready(library, track, "j1", tmp_path)
    other = _second_user()
    theirs = _playlist(other)

    from app.models import PlaylistItemsRequest

    with pytest.raises(Exception):
        asyncio.run(main.add_playlist_items(theirs, PlaylistItemsRequest(jobIds=[job_id]), other))

    assert asyncio.run(main.get_playlist(theirs, other)).trackCount == 0


def test_smart_playlist_reads_the_owners_library(library, track, tmp_path):
    """قانون روی کتابخانه‌ی خودِ کاربر اجرا می‌شود، نه روی فایل‌های همه."""
    other = _second_user()
    _ready(library, track, "j1", tmp_path, title="Jomeh")
    _ready(library, track, "j2", tmp_path, title="Gol", user_id=other)

    from app.models import PlaylistRule

    mine = asyncio.run(
        main.create_playlist(
            PlaylistCreate(name="Mine", kind="smart", rule=PlaylistRule(query="jomeh")), "local"
        )
    )
    theirs = asyncio.run(
        main.create_playlist(
            PlaylistCreate(name="Theirs", kind="smart", rule=PlaylistRule(query="jomeh")), other
        )
    )

    assert asyncio.run(main.get_playlist(mine.id)).trackCount == 1
    assert asyncio.run(main.get_playlist(theirs.id, other)).trackCount == 0


# ---------- مهاجرت ----------


def test_existing_rows_are_given_to_the_guest(library, track, tmp_path):
    """
    داده‌ی نسخه‌ی تک‌کاربره باید بدونِ کم‌شدن به مهمان برسد.

    شبیه‌سازیِ نصبِ قدیمی: ردیفِ جاب بدونِ مالک نوشته می‌شود، بعد مهاجرت
    دوباره اجرا می‌شود — همان کاری که `connect()` روی دیتابیسِ موجود می‌کند.
    """
    _ready(library, track, "j1", tmp_path)
    library._exec("DELETE FROM job_owners")

    library._migrate(library.connect())

    assert library.owns_job("local", "j1")
    assert library.library()[1] == 1
