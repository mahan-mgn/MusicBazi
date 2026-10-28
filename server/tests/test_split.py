"""
تکه‌کردنِ میکس — پارسِ نامِ چپترها و فیلترِ چپترهای بی‌معنی.

مهم‌ترین قسمتش همین پارس است: خروجی مستقیم به تگِ فایل می‌رود، پس «۰۱. فرهاد -
مرد تنها» باید هنرمند و عنوان بدهد نه یک عنوانِ درهم.
"""

from __future__ import annotations

from pathlib import Path

from app import split


def test_splits_artist_and_title():
    assert split.clean_title("Farhad - Mard-e Tanha") == ("Farhad", "Mard-e Tanha")


def test_strips_leading_track_number():
    assert split.clean_title("01. Farhad - Mard-e Tanha") == ("Farhad", "Mard-e Tanha")
    assert split.clean_title("[03] Farhad – Mard-e Tanha") == ("Farhad", "Mard-e Tanha")


def test_strips_timestamps_uploaders_leave_in_the_name():
    assert split.clean_title("0:00 Farhad - Mard-e Tanha") == ("Farhad", "Mard-e Tanha")


def test_strips_promo_suffix():
    artist, title = split.clean_title("Farhad - Mard-e Tanha (Official Audio)")
    assert (artist, title) == ("Farhad", "Mard-e Tanha")


def test_persian_dash_and_names():
    assert split.clean_title("۰۱ - فرهاد مهراد - مرد تنها")[1] == "مرد تنها"


def test_without_a_separator_the_artist_stays_unknown():
    """
    حدسِ اشتباهِ هنرمند بدتر از نداشتنِ آن است — صدازننده هنرمندِ خودِ ویدیو
    را جایش می‌گذارد.
    """
    assert split.clean_title("Mard-e Tanha") == (None, "Mard-e Tanha")


def test_empty_name_falls_back_to_the_raw_value():
    assert split.clean_title("---") == (None, "---")


def _info(chapters):
    return {"duration": 3600, "chapters": chapters}


def test_short_chapters_are_dropped():
    """اینترو و تیتراژ چپتر دارند ولی آهنگ نیستند."""
    found = split._chapters_from(
        _info(
            [
                {"title": "Intro", "start_time": 0, "end_time": 12},
                {"title": "A - B", "start_time": 12, "end_time": 300},
            ]
        )
    )
    assert [c.song_title for c in found] == ["B"]


def test_last_chapter_without_end_uses_total_duration():
    found = split._chapters_from(
        _info([{"title": "A - B", "start_time": 3000, "end_time": 0}])
    )
    assert found[0].end_ms == 3_600_000


def test_chapter_count_is_capped():
    raw = [
        {"title": f"A{i} - B{i}", "start_time": i * 60, "end_time": i * 60 + 60}
        for i in range(200)
    ]
    assert len(split._chapters_from(_info(raw))) == split.MAX_CHAPTERS


def test_child_track_carries_order_and_album():
    source = split.SplitSource(
        url="https://youtu.be/x",
        title="Best of Farhad",
        uploader="Some Channel",
        duration_ms=3_600_000,
        artwork_url=None,
        chapters=[],
    )
    chapter = split.Chapter(
        index=2, title="03. A - B", start_ms=600_000, end_ms=780_000, artist="A", song_title="B"
    )
    track = split._child_track(source, chapter, "320")

    assert track.title == "B"
    assert track.artist == "A"
    assert track.album == "Best of Farhad"
    assert track.trackNumber == 3
    assert track.durationMs == 180_000


def test_child_track_falls_back_to_the_uploader():
    source = split.SplitSource(
        url="https://youtu.be/x",
        title="Mix",
        uploader="Some Channel",
        duration_ms=1000,
        artwork_url=None,
        chapters=[],
    )
    chapter = split.Chapter(
        index=0, title="B", start_ms=0, end_ms=1000, artist=None, song_title="B"
    )
    assert split._child_track(source, chapter, "320").artist == "Some Channel"


def test_same_mix_in_two_qualities_is_not_the_same_track():
    """
    بازاستفاده روی (track_id, quality) کار می‌کند؛ اگر شناسه کیفیت را در خود
    نداشت، تکه‌کردنِ دوباره با flac همان فایلِ ۳۲۰ را برمی‌گرداند.
    """
    source = split.SplitSource(
        url="https://youtu.be/x", title="Mix", uploader="C", duration_ms=1, artwork_url=None, chapters=[]
    )
    chapter = split.Chapter(0, "B", 0, 1000, None, "B")
    assert split._child_track(source, chapter, "320").id != split._child_track(
        source, chapter, "flac"
    ).id


class TestFinalizeContract:
    """
    `downloader.finalize` هم مسیرِ .lrc می‌دهد هم حکمِ کاور. هر دو صداکننده باید
    از همان شکل بخوانند — وگرنه `split` که مستقیم نتیجه را در دیتابیس می‌نوشت،
    به‌جای مسیرِ فایل، بازنماییِ رشته‌ایِ خودِ آبجکت را ذخیره می‌کرد و ردیفِ
    تکه‌ها به یک `.lrc` ناموجود اشاره می‌ماند.
    """

    def test_the_lyrics_path_is_a_path_not_the_result_object(self, tmp_path, monkeypatch):
        from app import downloader
        from app.providers.lrclib import Lyrics

        monkeypatch.setattr(downloader, "fetch_lyrics", lambda t, uid="local": Lyrics(plain="x", synced=None))
        monkeypatch.setattr(downloader, "_fetch_artwork", lambda url: None)
        monkeypatch.setitem(downloader._TAGGERS, ".mp3", lambda *a: None)
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"")

        final = downloader.finalize(audio, _child_source_track())

        assert isinstance(final.lyrics_path, Path)
        assert isinstance(final.cover, bool)


def _child_source_track():
    from app.models import Track

    return Track(
        id="yt:track:1",
        title="Chapter",
        artist="Someone",
        durationMs=1000,
        source="youtube",
        sourceUrl="https://youtube.com/watch?v=1",
        artworkUrl="https://i.ytimg.com/vi/1/hqdefault.jpg",
    )
