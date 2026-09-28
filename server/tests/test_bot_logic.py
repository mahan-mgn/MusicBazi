"""
منطق خالصِ بات تلگرام — بدون شبکه، بدون mock برای httpx/telegram.
"""

from __future__ import annotations

import pytest

from app.bot.logic import (
    AUTO_QUALITY,
    TELEGRAM_FILE_LIMIT,
    audio_filename,
    clean_filename_part,
    clean_lrc_lyrics,
    extract_album_features,
    format_album_button,
    format_album_caption,
    format_album_duration,
    format_artist_button,
    format_artist_search_button,
    format_playlist_button,
    format_track_button,
    looks_like_profile_url,
    looks_like_social_media_video,
    looks_like_url,
    looks_like_youtube_video,
    new_releases,
    paginate_slice,
    progress_bar,
    quality_label,
    source_badge,
    too_large_for_telegram,
    track_lyrics_hash,
)
from app.models import Album, AlbumDetail, Track


def _album(id: str, title: str = "T") -> Album:
    return Album(
        id=id, title=title, artist="A", year=2026, trackCount=1,
        source="spotify", sourceUrl="https://x",
    )


class TestLooksLikeUrl:
    def test_recognizes_http_and_https(self):
        assert looks_like_url("https://open.spotify.com/track/x")
        assert looks_like_url("http://example.com")

    def test_rejects_plain_search_text(self):
        assert not looks_like_url("مرد تنها فرهاد مهراد")

    def test_ignores_surrounding_whitespace(self):
        assert looks_like_url("  https://deezer.com/track/1  ")


class TestLooksLikeProfileUrl:
    """
    پروفایل ترک‌لیست ندارد، پس نباید به مسیرِ «همه رو بگیر» برود — و برعکس،
    لینکِ آلبوم/ترک نباید سر از مرورگرِ پروفایل دربیاورد.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://open.spotify.com/artist/6jj9lOTeZC28LkPoXK9hiT",
            "https://open.spotify.com/user/31qajthebaf2bgwqnanhyrdpplte?si=ec90",
            "https://www.deezer.com/en/profile/2529",
            "https://music.apple.com/us/artist/farhad/500",
            "https://soundcloud.com/accia",
            "https://www.youtube.com/@NoCopyrightSounds/playlists",
        ],
    )
    def test_profiles(self, url):
        assert looks_like_profile_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://open.spotify.com/album/1A2B",
            "https://open.spotify.com/playlist/37i9dQ",
            "https://soundcloud.com/dorcci/gonah",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "مرد تنها فرهاد مهراد",
        ],
    )
    def test_everything_else(self, url):
        assert not looks_like_profile_url(url)


class TestLooksLikeYouTubeVideo:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "http://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=abc12345",
            "https://www.youtube.com/shorts/xyz9876",
        ],
    )
    def test_youtube_video_urls_match(self, url):
        assert looks_like_youtube_video(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://open.spotify.com/track/12345",
            "https://soundcloud.com/artist/track",
            "https://deezer.com/track/123",
            "فرهاد مهراد کودکانه",
        ],
    )
    def test_non_youtube_urls_do_not_match(self, url):
        assert not looks_like_youtube_video(url)


class TestLooksLikeSocialMediaVideo:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.instagram.com/reel/C-123456789/",
            "https://instagram.com/p/ABCxyz/",
            "https://instagr.am/reel/123",
            "https://www.tiktok.com/@creator/video/7123456789012345678",
            "https://vm.tiktok.com/ZM8123456/",
            "https://m.tiktok.com/v/12345.html",
        ],
    )
    def test_social_media_video_urls_match(self, url):
        assert looks_like_social_media_video(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://open.spotify.com/track/123",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://soundcloud.com/user/track",
            "متن فارسی معمولی",
        ],
    )
    def test_non_social_media_urls_do_not_match(self, url):
        assert not looks_like_social_media_video(url)


class TestPaginateSlice:
    def test_first_page_of_many(self):
        start, end, page, total = paginate_slice(20, 1, 8)
        assert (start, end, page, total) == (0, 8, 1, 3)

    def test_middle_page(self):
        start, end, page, total = paginate_slice(20, 2, 8)
        assert (start, end, page, total) == (8, 16, 2, 3)

    def test_last_page(self):
        start, end, page, total = paginate_slice(20, 3, 8)
        assert (start, end, page, total) == (16, 20, 3, 3)

    def test_out_of_bounds_page_is_clamped(self):
        start, end, page, total = paginate_slice(20, 99, 8)
        assert (start, end, page, total) == (16, 20, 3, 3)
        start, end, page, total = paginate_slice(20, -5, 8)
        assert (start, end, page, total) == (0, 8, 1, 3)

    def test_empty_collection(self):
        start, end, page, total = paginate_slice(0, 1, 8)
        assert (start, end, page, total) == (0, 0, 1, 1)

    def test_single_page(self):
        start, end, page, total = paginate_slice(5, 1, 8)
        assert (start, end, page, total) == (0, 5, 1, 1)



class TestFormatTrackButton:
    def test_joins_title_and_artist(self, track):
        assert format_track_button(track) == "Mard-e Tanha — Farhad Mehrad"

    def test_truncates_long_labels(self, track):
        long_track = track.model_copy(update={"title": "T" * 80})
        label = format_track_button(long_track)
        assert len(label) == 60
        assert label.endswith("…")


class TestTooLargeForTelegram:
    def test_under_limit_is_fine(self):
        assert not too_large_for_telegram(TELEGRAM_FILE_LIMIT - 1)

    def test_over_limit_is_rejected(self):
        assert too_large_for_telegram(TELEGRAM_FILE_LIMIT + 1)


class TestCleanFilenamePart:
    def test_replaces_illegal_characters_with_hyphens(self):
        assert clean_filename_part('AC/DC: "Live" *1992*? <test>|part\\1') == "AC-DC- -Live- -1992-- -test--part-1"

    def test_strips_surrounding_dots_and_spaces(self):
        assert clean_filename_part("  ...song title...  ") == "song title"

    def test_truncates_to_max_100_chars(self):
        assert len(clean_filename_part("A" * 150)) == 100

    def test_empty_string_falls_back_to_track(self):
        assert clean_filename_part("") == "track"
        assert clean_filename_part("   ") == "track"


class TestAudioFilename:
    def test_uses_first_word_of_format_as_extension(self, track):
        assert audio_filename(track, "mp3 320") == "Farhad Mehrad - Mard-e Tanha.mp3"

    def test_falls_back_to_mp3_when_format_is_missing(self, track):
        assert audio_filename(track, None) == "Farhad Mehrad - Mard-e Tanha.mp3"

    def test_sanitizes_artist_and_title_characters(self, track):
        t = track.model_copy(update={"artist": "AC/DC", "title": "Highway to Hell / Live"})
        assert audio_filename(t, "mp3 320") == "AC-DC - Highway to Hell - Live.mp3"


class TestProgressBar:
    def test_zero_percent_is_all_empty(self):
        assert progress_bar(0, width=10) == "░" * 10

    def test_hundred_percent_is_all_filled(self):
        assert progress_bar(100, width=10) == "▓" * 10

    def test_fifty_percent_is_half_and_half(self):
        assert progress_bar(50, width=10) == "▓" * 5 + "░" * 5

    def test_clamps_out_of_range_values(self):
        assert progress_bar(-10, width=10) == "░" * 10
        assert progress_bar(150, width=10) == "▓" * 10

    def test_rounds_to_nearest_bar(self):
        assert progress_bar(42, width=10) == "▓" * 4 + "░" * 6


class TestSourceBadge:
    def test_known_sources_get_specific_emoji(self):
        assert source_badge("apple") == "🍎"
        assert source_badge("deezer") == "🎵"
        assert source_badge("spotify") == "🟢"
        assert source_badge("youtube") == "▶️"
        assert source_badge("soundcloud") == "☁️"


class TestFormatArtistButton:
    def test_passes_short_names_through(self):
        assert format_artist_button("Farhad Mehrad") == "Farhad Mehrad"

    def test_truncates_long_names(self):
        label = format_artist_button("A" * 80)
        assert len(label) == 60
        assert label.endswith("…")


class TestFormatArtistSearchButton:
    def test_includes_subtitle(self, artist):
        assert format_artist_search_button(artist) == "Farhad Mehrad — 34 آلبوم"

    def test_truncates_long_combined_label(self, artist):
        long_artist = artist.model_copy(update={"name": "A" * 80})
        label = format_artist_search_button(long_artist)
        assert len(label) == 60
        assert label.endswith("…")


class TestFormatAlbumButton:
    def test_joins_title_and_artist(self, album):
        assert format_album_button(album) == "Mard-E Tanha — Farhad Mehrad"

    def test_truncates_long_labels(self, album):
        long_album = album.model_copy(update={"title": "T" * 80})
        label = format_album_button(long_album)
        assert len(label) == 60
        assert label.endswith("…")


class TestFormatPlaylistButton:
    def test_joins_title_and_owner(self, playlist):
        assert format_playlist_button(playlist) == "بهترین‌های فرهاد — ناشناس"

    def test_truncates_long_labels(self, playlist):
        long_playlist = playlist.model_copy(update={"title": "T" * 80})
        label = format_playlist_button(long_playlist)
        assert len(label) == 60
        assert label.endswith("…")


class TestQualityLabel:
    def test_original_gets_persian_label(self):
        assert quality_label("original") == "اورجینال"

    def test_bitrates_pass_through_unchanged(self):
        assert quality_label("320") == "320"
        assert quality_label("flac") == "flac"


class TestNewReleases:
    """لیست تازه‌به‌قدیم است: تازه‌ها همه‌ی ردیف‌های قبل از آخرین شناسه‌ی دیده‌شده."""

    def test_no_seed_means_nothing_new(self):
        # اولین پرکردنِ وضعیت نباید کلِ دیسکوگرافی را «تازه» کند
        assert new_releases(None, [_album("a1")]) == []

    def test_unchanged_list_means_nothing_new(self):
        assert new_releases("a1", [_album("a1"), _album("a0")]) == []

    def test_single_new_release_on_top(self):
        albums = [_album("a2", "جدید"), _album("a1"), _album("a0")]
        [fresh] = new_releases("a1", albums)
        assert fresh.id == "a2"

    def test_several_new_releases_keep_newest_first(self):
        # خودِ تابع ترتیبِ فهرست را نگه می‌دارد؛ صداکننده برای ترتیبِ ارسال برعکسش می‌کند
        albums = [_album("a3"), _album("a2"), _album("a1")]
        assert [a.id for a in new_releases("a1", albums)] == ["a3", "a2"]

    def test_unknown_last_id_sends_only_the_latest(self):
        # شناسه‌ی ذخیره‌شده از فهرست افتاده — کلِ تاریخچه دوباره ارسال نمی‌شود
        albums = [_album("a9"), _album("a8")]
        [fresh] = new_releases("gone", albums)
        assert fresh.id == "a9"

    def test_empty_discography(self):
        assert new_releases("a1", []) == []


class TestAutoQuality:
    def test_auto_quality_is_the_highest_usual_fit_for_telegram(self):
        assert AUTO_QUALITY == "320"


def _make_track(title: str, artist: str, duration_ms: int = 180_000) -> Track:
    return Track(
        id=f"t:{title}",
        title=title,
        artist=artist,
        durationMs=duration_ms,
        source="spotify",
        sourceUrl="https://example.com",
    )


class TestExtractAlbumFeatures:
    def test_no_features_when_all_tracks_match_main_artist(self):
        tracks = [
            _make_track("Track 1", "Eminem"),
            _make_track("Track 2", "Eminem"),
        ]
        assert extract_album_features("Eminem", tracks) == []

    def test_extracts_from_artist_field(self):
        tracks = [
            _make_track("Track 1", "Eminem"),
            _make_track("Track 2", "Eminem, 50 Cent"),
            _make_track("Track 3", "Eminem feat. Dr. Dre"),
        ]
        features = extract_album_features("Eminem", tracks)
        assert features == ["50 Cent", "Dr. Dre"]

    def test_extracts_from_title_parentheses(self):
        tracks = [
            _make_track("Love The Way You Lie (feat. Rihanna)", "Eminem"),
            _make_track("Stan [ft. Dido]", "Eminem"),
        ]
        features = extract_album_features("Eminem", tracks)
        assert features == ["Rihanna", "Dido"]

    def test_deduplicates_features_preserving_order(self):
        tracks = [
            _make_track("Track 1", "Eminem, Dr. Dre"),
            _make_track("Track 2 (feat. Dr. Dre)", "Eminem"),
            _make_track("Track 3", "Eminem & 50 Cent"),
        ]
        features = extract_album_features("Eminem", tracks)
        assert features == ["Dr. Dre", "50 Cent"]

    def test_ignores_multi_part_main_artist_names(self):
        tracks = [
            _make_track("Song 1", "Kanye West, Kid Cudi"),
            _make_track("Song 2", "Kanye West, Kid Cudi, Pusha T"),
        ]
        features = extract_album_features("Kanye West & Kid Cudi", tracks)
        assert features == ["Pusha T"]


class TestFormatAlbumDuration:
    def test_formats_over_one_hour(self):
        assert format_album_duration(3665_000) == "1 ساعت و 1 دقیقه"
        assert format_album_duration(7200_000) == "2 ساعت"

    def test_formats_under_one_hour(self):
        assert format_album_duration(2520_000) == "42 دقیقه"
        assert format_album_duration(125_000) == "2 دقیقه و 5 ثانیه"

    def test_formats_zero_or_short(self):
        assert format_album_duration(0) == "0 ثانیه"
        assert format_album_duration(45_000) == "45 ثانیه"


class TestFormatAlbumCaption:
    def test_includes_all_key_metadata(self):
        tracks = [
            _make_track("Track 1", "The Weeknd"),
            _make_track("Starboy (feat. Daft Punk)", "The Weeknd, Daft Punk", 230_000),
        ]
        album = AlbumDetail(
            id="sp:album:1",
            title="Starboy",
            artist="The Weeknd",
            year=2016,
            releaseDate="2016-11-25",
            trackCount=2,
            durationMs=410_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/album/1",
            tracks=tracks,
        )
        caption = format_album_caption(album)

        assert "Starboy" in caption
        assert "The Weeknd" in caption
        assert "Daft Punk" in caption
        assert "2016-11-25" in caption
        assert "تعداد آهنگ‌ها: 2" in caption
        assert "زمان کل: 6 دقیقه" in caption

    def test_escapes_html_properly(self):
        tracks = [_make_track("Track <1>", "Artist & Co")]
        album = AlbumDetail(
            id="sp:album:2",
            title="Rock & Roll <Vol 1>",
            artist="AC/DC & Guests",
            year=2020,
            trackCount=1,
            durationMs=180_000,
            source="spotify",
            sourceUrl="https://example.com",
            tracks=tracks,
        )
        caption = format_album_caption(album)

        assert "&amp;" in caption
        assert "&lt;Vol 1&gt;" in caption
        assert "<Vol 1>" not in caption


class TestCleanLrcLyrics:
    def test_cleans_timestamps_and_metadata(self):
        raw = """[ti:Shape of You]
[ar:Ed Sheeran]
[al:Divide]
[00:09.12]The club isn't the best place to find a lover
[00:11.45]So the bar is where I go
[00:13.90]Me and my friends at the table doing shots"""
        cleaned = clean_lrc_lyrics(raw)
        assert "[ti:" not in cleaned
        assert "[ar:" not in cleaned
        assert "[00:" not in cleaned
        assert "The club isn't the best place to find a lover" in cleaned
        assert "So the bar is where I go" in cleaned

    def test_handles_persian_lyrics(self):
        raw = """[00:10.00]کودکانه
[00:15.50]بوی عیدی، بوی توپ
[00:20.10]بوی کاغذ رنگی"""
        cleaned = clean_lrc_lyrics(raw)
        assert cleaned == "کودکانه\nبوی عیدی، بوی توپ\nبوی کاغذ رنگی"

    def test_empty_input_returns_empty_string(self):
        assert clean_lrc_lyrics("") == ""
        assert clean_lrc_lyrics("   ") == ""


class TestTrackLyricsHash:
    def test_deterministic_and_short(self):
        h1 = track_lyrics_hash("spotify:track:4cOdK2wGLETKBW3PvgPWqT")
        h2 = track_lyrics_hash("spotify:track:4cOdK2wGLETKBW3PvgPWqT")
        assert h1 == h2
        assert len(h1) == 16
        # Fits easily in 64-byte telegram callback limit with prefix
        assert len(f"lyr:{h1}") < 64

    def test_different_tracks_produce_different_hashes(self):
        h1 = track_lyrics_hash("track-1")
        h2 = track_lyrics_hash("track-2")
        assert h1 != h2


