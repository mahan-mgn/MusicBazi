"""
چیدمان آرشیو.

این لایه ورودی‌اش از کاتالوگ‌های بیرونی می‌آید — عنوانی که `/` یا `..` دارد
نباید بتواند از الگو بیرون بزند.
"""

from __future__ import annotations

import pytest

from app import paths


@pytest.fixture
def full(track):
    return track.model_copy(
        update={"trackNumber": 4, "discNumber": 1, "year": 1978, "genre": "Rock"}
    )


class TestRender:
    def test_default_layout_is_artist_album_track(self, full):
        assert paths.render(full, ".mp3") == "Farhad Mehrad/Mard-E Tanha/04 - Mard-e Tanha.mp3"

    def test_the_folder_follows_the_album_artist_not_the_guests(self, full):
        """
        وگرنه هر ترکِ فیچردارِ یک آلبوم پوشه‌ی خودش را می‌گرفت و آلبوم در
        کتابخانه به چند تکه می‌شکست.
        """
        featured = full.model_copy(
            update={"artist": "Farhad Mehrad, Guest", "albumArtist": "Farhad Mehrad"}
        )

        assert paths.render(featured, ".mp3").startswith("Farhad Mehrad/Mard-E Tanha/")

    def test_track_number_is_zero_padded(self, full):
        """مرتب‌سازی الفبایی باید همان ترتیب آلبوم را بدهد، وگرنه ۱۰ قبل از ۲ می‌آید."""
        assert "/04 - " in paths.render(full, ".mp3")
        assert "/12 - " in paths.render(full.model_copy(update={"trackNumber": 12}), ".mp3")

    def test_a_missing_value_removes_its_own_segment(self, full):
        """ترکِ بی‌آلبوم نباید در پوشه‌ای بی‌نام گم شود."""
        without = full.model_copy(update={"album": None})

        assert paths.render(without, ".flac") == "Farhad Mehrad/04 - Mard-e Tanha.flac"

    def test_a_missing_value_does_not_leave_its_separator(self, full):
        """`{track} - {title}` برای ترک بی‌شماره «- عنوان» می‌شد."""
        without = full.model_copy(update={"trackNumber": None})

        assert paths.render(without, ".mp3").endswith("/Mard-e Tanha.mp3")

    def test_a_title_cannot_escape_the_template(self, full):
        evil = full.model_copy(update={"title": "../../etc/passwd", "artist": "a/b"})

        rendered = paths.render(evil, ".mp3")

        # دقیقاً سه بخش — همان‌قدر که خودِ الگو دارد، نه یکی بیشتر
        assert len(rendered.split("/")) == 3
        assert ".." not in rendered.split("/")

    def test_custom_template_is_honored(self, full):
        rendered = paths.render(full, ".mp3", "{year} - {album}/{track}. {title}")

        assert rendered == "1978 - Mard-E Tanha/04. Mard-e Tanha.mp3"

    def test_an_unknown_placeholder_falls_back_to_a_flat_name(self, full):
        """الگوی غلط نباید دانلود را بسوزاند — نام تخت همیشه بهتر از هیچ است."""
        assert paths.render(full, ".mp3", "{nope}") == "Farhad Mehrad - Mard-e Tanha.mp3"


class TestM3u:
    def test_order_is_preserved(self, full):
        second = full.model_copy(update={"title": "Jomeh", "trackNumber": 5})
        entries = [(full, "a.mp3"), (second, "b.mp3")]

        lines = paths.m3u(entries).splitlines()

        assert lines[0] == "#EXTM3U"
        assert lines[2] == "a.mp3"
        assert lines[4] == "b.mp3"

    def test_duration_is_in_seconds(self, full):
        assert "#EXTINF:185," in paths.m3u([(full, "a.mp3")])

    def test_unknown_duration_is_minus_one(self, full):
        """`-1` قرارداد خودِ M3U برای «نمی‌دانم» است؛ صفر یعنی ترکِ صفرثانیه‌ای."""
        assert "#EXTINF:-1," in paths.m3u([(full.model_copy(update={"durationMs": 0}), "a.mp3")])


class TestArtistCatalogArchive:
    def test_single_release_detection(self, track):
        # ترک بدون آلبوم
        assert paths.is_single_release(track.model_copy(update={"album": None})) is True

        # ترک با آلبوم برابر با عنوان
        single_track = track.model_copy(update={"title": "Gorg", "album": "Gorg", "trackNumber": 1})
        assert paths.is_single_release(single_track) is True

        # ترک با پسوند Single در نام آلبوم
        single_with_suffix = track.model_copy(update={"title": "Gorg", "album": "Gorg - Single", "trackNumber": 1})
        assert paths.is_single_release(single_with_suffix) is True

        # ترک هم‌نام با آلبوم اما شماره ترک بیش از ۱ (عضو آلبوم)
        title_track_in_album = track.model_copy(update={"title": "Barzakh", "album": "Barzakh", "trackNumber": 3})
        assert paths.is_single_release(title_track_in_album) is False

        # ترک هم‌نام با آلبوم که در بسته چندین ترک از آن آلبوم وجود دارد
        album_counts = {"barzakh": 12, "gorg": 1}
        title_track_first = track.model_copy(update={"title": "Barzakh", "album": "Barzakh", "trackNumber": 1})
        assert paths.is_single_release(title_track_first, album_counts) is False

        # تک‌آهنگ مستقل در همان بسته
        standalone_single = track.model_copy(update={"title": "Gorg", "album": "Gorg", "trackNumber": 1})
        assert paths.is_single_release(standalone_single, album_counts) is True

    def test_render_archive_path_places_singles_in_artist_root(self, track):
        """تک‌آهنگ‌های کاتالوگ مستقیماً زیر پوشه هنرمند قرار می‌گیرند، بدون پوشه اضافه."""
        single = track.model_copy(update={"title": "Nawazesh", "album": "Nawazesh", "trackNumber": 1, "artist": "Amir Tataloo"})
        rendered = paths.render_archive_path(single, ".mp3", is_album=False, primary_artist="Amir Tataloo")
        assert rendered == "Amir Tataloo/Nawazesh.mp3"

    def test_render_archive_path_places_album_tracks_in_album_subfolder(self, track):
        """تمام ترک‌های آلبوم همراه با شماره در پوشه همان آلبوم قرار می‌گیرند."""
        t1 = track.model_copy(update={"title": "Bebor", "album": "Ebrahim", "trackNumber": 1, "artist": "Mohsen Chavoshi"})
        t2 = track.model_copy(update={"title": "Jahan", "album": "Ebrahim", "trackNumber": 2, "artist": "Mohsen Chavoshi"})

        assert paths.render_archive_path(t1, ".mp3", is_album=True, primary_artist="Mohsen Chavoshi") == "Mohsen Chavoshi/Ebrahim/01 - Bebor.mp3"
        assert paths.render_archive_path(t2, ".mp3", is_album=True, primary_artist="Mohsen Chavoshi") == "Mohsen Chavoshi/Ebrahim/02 - Jahan.mp3"

    def test_render_archive_path_keeps_guest_tracks_in_main_artist_album(self, track):
        """ترک‌هایی که خواننده مهمان دارند به پوشه هنرمند دیگر پرتاب نمی‌شوند و در آلبوم اصلی می‌مانند."""
        guest_track = track.model_copy(
            update={
                "title": "Kojayi",
                "album": "Shahrzad",
                "trackNumber": 5,
                "artist": "Mohsen Chavoshi, Sina Sarlak",
                "albumArtist": "Mohsen Chavoshi",
            }
        )
        rendered = paths.render_archive_path(guest_track, ".mp3", is_album=True, primary_artist="Mohsen Chavoshi")
        assert rendered == "Mohsen Chavoshi/Shahrzad/05 - Kojayi.mp3"

