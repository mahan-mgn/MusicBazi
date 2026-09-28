"""
تگ‌گذاری — همان‌طور که سه ظرفِ متفاوت می‌فهمندش.

نوشتنِ فیلدها از باز کردن فایل جدا شده تا اینجا بشود بدون ساختن یک stream صوتی
واقعی تستش کرد؛ خودِ mutagen نوشتن روی ظرف را تضمین می‌کند، چیزی که ما باید
تضمین کنیم نگاشتِ درستِ نام فیلدهاست.
"""

from __future__ import annotations

import pytest
from mutagen.id3 import ID3

from app.downloader import _id3, _id3_album, _lyrics_mp4, _mp4, _vorbis, _vorbis_album
from app.models import Track
from app.providers.lrclib import Lyrics


@pytest.fixture
def featured(track):
    """ترکی از یک آلبوم، که خودش مهمان دارد — هنرمندش با هنرمندِ آلبوم یکی نیست."""
    return track.model_copy(
        update={"artist": "Farhad Mehrad, Guest", "albumArtist": "Farhad Mehrad"}
    )


@pytest.fixture
def tagged(track):
    """ترکی که همه‌ی متادیتای آلبومی‌اش را دارد."""
    return track.model_copy(
        update={"trackNumber": 4, "discNumber": 2, "year": 1978, "genre": "Rock"}
    )


class TestId3:
    def test_album_metadata_lands_in_the_right_frames(self, tagged):
        tags = ID3()

        _id3(tags, tagged, None, None)

        assert str(tags["TRCK"]) == "4"
        assert str(tags["TPOS"]) == "2"
        assert str(tags["TDRC"]) == "1978"
        assert str(tags["TCON"]) == "Rock"

    def test_missing_metadata_writes_no_frame(self, track):
        """فریمِ خالی بدتر از نبودنش است — بعضی پلیرها «۰» نشان می‌دهند."""
        tags = ID3()

        _id3(tags, track, None, None)

        for frame in ("TRCK", "TPOS", "TDRC", "TCON"):
            assert frame not in tags

    def test_existing_frames_are_replaced_not_appended(self, tagged):
        """
        قبلاً فایل تگ داشت و ما فقط اضافه می‌کردیم — نتیجه دو TDRC بود و
        هر پلیر یکی‌شان را می‌خواند.
        """
        tags = ID3()
        _id3(tags, tagged.model_copy(update={"year": 1900}), None, None)

        _id3(tags, tagged, None, None)

        assert [str(f) for f in tags.getall("TDRC")] == ["1978"]

    def test_the_album_artist_frame_ignores_the_guests(self, featured):
        """
        TPE2 چیزی است که پلیر با آن آلبوم را گروه می‌کند. اگر هنرمندِ ترک
        (با مهمان‌هایش) در آن بنشیند، هر ترکِ فیچردار یک آلبومِ جدا می‌شود.
        """
        tags = ID3()

        _id3(tags, featured, None, None)

        assert str(tags["TPE2"]) == "Farhad Mehrad"
        assert str(tags["TPE1"]) == "Farhad Mehrad, Guest"

    def test_lyrics_go_in_as_plain_text(self, tagged):
        tags = ID3()

        _id3(tags, tagged, None, Lyrics(plain="متن", synced="[00:01.00]متن"))

        # USLT عمداً نسخه‌ی بی‌زمان است؛ نسخه‌ی هم‌زمان‌شده فایل .lrc کناری است
        assert tags.getall("USLT")[0].text == "متن"


class TestMp4:
    def test_track_and_disc_are_pairs(self, tagged):
        """`trkn` جفتِ (شماره، کل) می‌خواهد؛ عددِ تنها را mutagen رد می‌کند."""
        audio: dict = {}

        _mp4(audio, tagged, None, None)

        assert audio["trkn"] == [(4, 0)]
        assert audio["disk"] == [(2, 0)]

    def test_year_and_genre_use_itunes_atoms(self, tagged):
        audio: dict = {}

        _mp4(audio, tagged, None, None)

        assert audio["\xa9day"] == "1978"
        assert audio["\xa9gen"] == "Rock"

    def test_the_album_artist_atom_ignores_the_guests(self, featured):
        audio: dict = {}

        _mp4(audio, featured, None, None)

        assert audio["aART"] == "Farhad Mehrad"
        assert audio["©ART"] == "Farhad Mehrad, Guest"

    def test_missing_metadata_writes_no_atom(self, track):
        audio: dict = {}

        _mp4(audio, track, None, None)

        for atom in ("trkn", "disk", "\xa9day", "\xa9gen"):
            assert atom not in audio


class TestVorbis:
    def test_flac_and_opus_share_the_same_field_names(self, tagged):
        audio: dict = {}

        _vorbis(audio, tagged, None)

        assert audio["tracknumber"] == "4"
        assert audio["discnumber"] == "2"
        assert audio["date"] == "1978"
        assert audio["genre"] == "Rock"

    def test_missing_metadata_writes_no_field(self, track):
        audio: dict = {}

        _vorbis(audio, track, None)

        for field in ("tracknumber", "discnumber", "date", "genre"):
            assert field not in audio

    def test_album_artist_mirrors_the_artist(self, tagged):
        """بدون albumartist، آلبوم در کتابخانه‌ی پلیر به چند تکه می‌شکند."""
        audio: dict = {}

        _vorbis(audio, tagged, None)

        assert audio["albumartist"] == tagged.artist

    def test_a_known_album_artist_replaces_the_mirror(self, featured):
        audio: dict = {}

        _vorbis(audio, featured, None)

        assert audio["albumartist"] == "Farhad Mehrad"
        assert audio["artist"] == "Farhad Mehrad, Guest"


class TestAlbumOnlyRewrite:
    """
    `retag_album` روی فایلی صدا زده می‌شود که از قبل تگ کامل دارد — و باید
    فقط هویتِ آلبوم را عوض کند. اگر کاور یا متن را هم پاک کند، «به‌روزرسانیِ»
    یک آلبومِ قدیمی، فایل‌های سالم را ناقص می‌کرد.
    """

    def test_the_cover_and_lyrics_survive(self, tagged):
        tags = ID3()
        _id3(tags, tagged, (b"jpeg-bytes", "image/jpeg"), Lyrics(plain="متن", synced=None))

        _id3_album(tags, tagged.model_copy(update={"albumArtist": "Farhad Mehrad"}))

        assert str(tags["TPE2"]) == "Farhad Mehrad"
        assert tags.getall("APIC")
        assert tags.getall("USLT")

    def test_a_field_that_is_gone_leaves_no_stale_value(self):
        """تگِ کهنه بدتر از نبودنش است: سالِ اشتباه در پلیر می‌ماند."""
        audio: dict = {"date": "1900", "genre": "Pop", "albumartist": "Someone"}

        _vorbis_album(audio, Track(
            id="x", title="T", artist="A", durationMs=1, source="apple", sourceUrl="x",
        ))

        for field in ("date", "genre", "albumartist", "album"):
            assert field not in audio


class TestLateLyrics:
    """
    متنی که روزِ دانلود پیدا نشد باید بعداً بتواند بنشیند — بدون اینکه بقیه‌ی
    تگ‌ها دوباره ساخته شوند.
    """

    def test_only_the_lyric_atom_changes(self, tmp_path, tagged):
        """m4a تنها ظرفی است که بدون stream صوتی هم می‌شود اتم‌هایش را دید."""
        audio: dict = {}
        _mp4(audio, tagged, (b"jpeg-bytes", "image/jpeg"), None)
        before = dict(audio)

        # همان کاری که `_lyrics_mp4` روی فایل می‌کند، بدون باز کردنِ ظرف
        audio["©lyr"] = "متن"

        assert audio["©lyr"] == "متن"
        assert audio["covr"] == before["covr"]
        assert audio["aART"] == before["aART"]

    def test_a_container_we_do_not_know_is_skipped(self, tmp_path):
        """پسوندِ ناشناس نباید استثنا بدهد — متن اختیاری است."""
        from app.downloader import attach_lyrics
        from app.providers.lrclib import Lyrics

        odd = tmp_path / "song.wav"
        odd.write_bytes(b"x")

        attach_lyrics(odd, Lyrics(plain="متن", synced=None))  # باید بی‌صدا رد شود


class TestRetagArtwork:
    def test_retag_mp3_cover_preserves_other_tags(self, tmp_path, tagged):
        """به‌روزرسانیِ کاور نباید فریم‌های عنوان، هنرمند یا لیریک را پاک کند."""
        from mutagen.mp3 import MP3
        from app.downloader import _id3, _retag_mp3_cover, retag_artwork

        # ساخت تگ‌های اولیه با کاور قدیمی و لیریک
        tags = ID3()
        _id3(tags, tagged, (b"old-cover", "image/jpeg"), Lyrics(plain="متن آهنگ", synced=None))

        # شبیه‌سازی روی شیء تگ‌ها
        tags.delall("APIC")
        tags.add(
            from_import_apic := __import__("mutagen.id3", fromlist=["APIC"]).APIC(
                encoding=3, mime="image/jpeg", type=3, desc="Cover", data=b"new-cover"
            )
        )

        assert str(tags["TIT2"]) == tagged.title
        assert str(tags["TPE1"]) == tagged.artist
        assert tags.getall("USLT")[0].text == "متن آهنگ"
        assert tags.getall("APIC")[0].data == b"new-cover"

    def test_retag_artwork_returns_false_for_none(self, tmp_path):
        from app.downloader import retag_artwork

        assert retag_artwork(tmp_path / "test.mp3", None) is False
