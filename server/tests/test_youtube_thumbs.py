"""
کاورِ پلی‌لیستِ یوتیوب: انتخابِ نسخه‌ی امضاشده و فالبکِ ترکِ اول.

یوتیوب کاورِ پلی‌لیست را برخلاف کاورِ ویدیو فقط با امضای `sqp` سرو می‌کند.
yt-dlp نسخه‌ی بی‌امضا را هم در `thumbnails` می‌گذارد و آن نسخه بزرگ‌تر هم
هست، پس «بزرگ‌ترین پهنا» دقیقاً کاوری را برمی‌داشت که همیشه ۴۰۴ می‌داد —
سینگلِ «LOL» با مربعِ حرف‌اول باز می‌شد درحالی‌که کاورِ ترکش سالم بود.
"""

from __future__ import annotations

from app.providers import ytdlp

# شکلِ واقعیِ پاسخِ yt-dlp برای یک پلی‌لیست ریلیزِ OLAK: دو پله‌ی امضاشده و
# یک `maxresdefault` بی‌امضا که بزرگ‌ترین پهنای لیست را دارد و مرده است.
PLAYLIST_THUMBS = [
    {
        "url": "https://i9.ytimg.com/s_p/OLAK5uy_abc/mqdefault.jpg?sqp=SIG&rs=AOn1",
        "width": 180,
        "height": 180,
    },
    {
        "url": "https://i9.ytimg.com/s_p/OLAK5uy_abc/sddefault.jpg?sqp=SIG&rs=AOn2",
        "width": 640,
        "height": 640,
    },
    {
        "url": "https://i9.ytimg.com/s_p/OLAK5uy_abc/maxresdefault.jpg",
        "width": 1200,
        "height": 1200,
    },
]

TRACK_THUMBS = [
    {
        "url": "https://i.ytimg.com/vi/x33V9EP7hSw/hqdefault.jpg?sqp=SIG&rs=AOn3",
        "width": 336,
        "height": 188,
    },
]


class TestUnsignedPlaylistThumb:
    def test_playlist_thumb_without_signature_is_flagged(self):
        assert ytdlp._unsigned_playlist_thumb(
            "https://i9.ytimg.com/s_p/OLAK5uy_abc/maxresdefault.jpg"
        )

    def test_signed_playlist_thumb_is_fine(self):
        assert not ytdlp._unsigned_playlist_thumb(
            "https://i9.ytimg.com/s_p/OLAK5uy_abc/mqdefault.jpg?sqp=SIG&rs=AOn1"
        )

    def test_user_playlist_thumbs_are_covered_too(self):
        """پلی‌لیستِ کاربر زیر `pl_c` می‌آید، نه `s_p` — هر دو امضا می‌خواهند."""
        assert ytdlp._unsigned_playlist_thumb(
            "https://i.ytimg.com/pl_c/PLabc/studio_square_thumbnail.jpg"
        )

    def test_video_thumbnail_is_never_flagged(self):
        """کاورِ ویدیو بی‌امضا هم کار می‌کند — نباید دست بخورد."""
        assert not ytdlp._unsigned_playlist_thumb(
            "https://i.ytimg.com/vi/x33V9EP7hSw/maxresdefault.jpg"
        )


class TestBestThumb:
    def test_signed_playlist_version_wins_over_larger_unsigned_one(self):
        picked = ytdlp._best_thumb({"thumbnails": PLAYLIST_THUMBS})

        assert "sddefault" in picked
        assert "sqp=" in picked

    def test_largest_width_still_wins_when_nothing_is_unsigned(self):
        thumbs = [t for t in PLAYLIST_THUMBS if "sqp=" in t["url"]]

        assert "sddefault" in ytdlp._best_thumb({"thumbnails": thumbs})

    def test_video_thumbnails_keep_picking_the_largest(self):
        """رگرسیونِ رفتارِ قبلی: برای ویدیو همچنان بزرگ‌ترین پهنا."""
        info = {
            "thumbnails": [
                {"url": "https://i.ytimg.com/vi/abc/hqdefault.jpg", "width": 480},
                {"url": "https://i.ytimg.com/vi/abc/maxresdefault.jpg", "width": 1280},
            ]
        }

        assert ytdlp._best_thumb(info).endswith("maxresdefault.jpg")

    def test_falls_back_to_thumbnail_key_when_no_widths(self):
        info = {"thumbnail": "https://example.com/only.jpg", "thumbnails": [{"url": "x"}]}

        assert ytdlp._best_thumb(info) == "https://example.com/only.jpg"


class TestExtractArtworkFallback:
    def test_unsigned_playlist_art_falls_back_to_first_track(self, monkeypatch):
        """
        وقتی کاورِ پلی‌لیست بی‌امضاست، همان ترکِ اول استفاده می‌شود — همان
        جلدِ آلبوم است و امضا نمی‌خواهد.
        """
        track = {
            "id": "x33V9EP7hSw",
            "title": "LOL",
            "thumbnails": TRACK_THUMBS,
        }
        info = {
            "id": "OLAK5uy_abc",
            "title": "LOL",
            "webpage_url": "https://www.youtube.com/playlist?list=OLAK5uy_abc",
            "thumbnails": [t for t in PLAYLIST_THUMBS if "sqp=" not in t["url"]],
            "entries": [track],
        }
        monkeypatch.setattr(ytdlp, "YoutubeDL", _fake_ydl(info))

        detail = ytdlp.extract("https://www.youtube.com/playlist?list=OLAK5uy_abc")

        assert detail is not None
        assert "i.ytimg.com/vi/x33V9EP7hSw" in detail.artworkUrl
        assert not ytdlp._unsigned_playlist_thumb(detail.artworkUrl)

    def test_signed_playlist_art_is_left_alone(self, monkeypatch):
        """کاورِ سالمِ پلی‌لیست نباید به کاورِ ترک تنزل کند."""
        info = {
            "id": "OLAK5uy_abc",
            "title": "LOL",
            "webpage_url": "https://www.youtube.com/playlist?list=OLAK5uy_abc",
            "thumbnails": PLAYLIST_THUMBS,
            "entries": [{"id": "x33V9EP7hSw", "title": "LOL", "thumbnails": TRACK_THUMBS}],
        }
        monkeypatch.setattr(ytdlp, "YoutubeDL", _fake_ydl(info))

        detail = ytdlp.extract("https://www.youtube.com/playlist?list=OLAK5uy_abc")

        assert detail is not None
        assert "sddefault" in detail.artworkUrl


def _fake_ydl(info: dict):
    """جایگزینِ `YoutubeDL` که بدون شبکه همان `info` را پس می‌دهد."""

    class _Fake:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def extract_info(self, _url, download=False):
            return info

        def cache(self):  # pragma: no cover — مسیرِ ساندکلاد لازمش دارد
            return None

    return _Fake
