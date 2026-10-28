"""
صفحه‌ی هنرمندِ YouTube Music: تکمیلِ انتشارهای جامانده و تحملِ پاسخِ خالی.

سه نقصِ جدا اینجا پوشش داده می‌شود:

۱. کاروسلِ «Singles & EPs» برای انتشارِ همین‌تازه‌منتشرشده عقب می‌ماند. تک‌آهنگ
   در جستجو و در `ytm:album:` بود ولی در صفحه‌ی هنرمند نبود، چون صفحه فقط از
   همان کاروسل ساخته می‌شد.
۲. کانالِ یوتیوب و هنرمندِ یوتیوب موزیک دو شناسه‌ی متفاوت دارند
   (`UC0DXllI…` در برابر `UCSsq6HUy…`). تکمیلِ انتشارها شناسه‌ی یوتیوب را به
   جستجو می‌داد و چون نتایج شناسه‌ی یوتیوب‌موزیک را دارند، هیچ‌وقت مطابقت
   نمی‌گرفت و بی‌اثر می‌ماند.
۳. یوتیوب موزیک برای همان آلبوم‌های تازه گاهی بدنه‌ی خالی (`noindex` بدون
   `contents`) برمی‌گرداند و `ytmusicapi` رویش می‌شکند. یک استثنا تا
   `resolve_ref` می‌رفت و کاربر ۵۰۲ می‌گرفت درحالی‌که آلبوم سالم بود.
"""

from __future__ import annotations

from app.models import Album, Track
from app.providers import youtube_music


def _track(artist_id: str | None) -> Track:
    return Track(
        id="ytm:track:x",
        title="T",
        artist="A",
        durationMs=1000,
        source="youtube_music",
        sourceUrl="https://music.youtube.com/watch?v=x",
        artistId=artist_id,
    )


def _album(title: str, year: int = 0, release_date: str | None = None) -> Album:
    return Album(
        id=f"ytm:album:{title}",
        title=title,
        artist="Tlkhoon",
        year=year,
        trackCount=1,
        source="youtube_music",
        sourceUrl=f"https://music.youtube.com/browse/{title}",
        releaseType="single",
        releaseDate=release_date,
    )


class TestReleaseOrdering:
    def test_a_freshly_added_release_sorts_to_the_front(self):
        """
        تکمیلِ انتشارها به *انتها* می‌چسباند، ولی کاروسل جدیدترین‌اول است —
        پس بدونِ مرتب‌سازی، تازه‌ترین اثرِ هنرمند ته لیست می‌افتاد و کاربر
        باید اسکرول می‌کرد تا ببیندش.
        """
        releases = [
            _album("Ajibe!", year=2026),
            _album("Mochale", year=2024),
            _album("LOL", year=2026, release_date="2026-10-17"),  # تازه اضافه‌شده
        ]

        releases.sort(key=youtube_music._release_sort_key, reverse=True)

        assert releases[0].title == "LOL"

    def test_year_alone_orders_items_that_have_no_date(self):
        releases = [
            _album("old", year=2020),
            _album("new", year=2026),
            _album("mid", year=2023),
        ]

        releases.sort(key=youtube_music._release_sort_key, reverse=True)

        assert [a.title for a in releases] == ["new", "mid", "old"]

    def test_an_item_with_a_date_outranks_its_dated_sibling_of_the_same_year(self):
        releases = [_album("plain", year=2026), _album("dated", year=2026, release_date="2026-01-05")]

        releases.sort(key=youtube_music._release_sort_key, reverse=True)

        assert releases[0].title == "dated"

    def test_a_dated_older_year_does_not_jump_above_a_newer_year(self):
        """
        رگرسیون: کلید در نسخه‌ی اول `(تاریخ، سال)` بود و انتشارِ ۲۰۲۴ با تاریخِ
        کامل بالای انتشارِ ۲۰۲۶ بی‌تاریخ می‌افتاد.
        """
        releases = [_album("newer", year=2026), _album("older", year=2024, release_date="2024-05-20")]

        releases.sort(key=youtube_music._release_sort_key, reverse=True)

        assert releases[0].title == "newer"


class TestYtmArtistId:
    def test_uses_the_artist_id_carried_by_the_tracks(self):
        """
        ترک‌ها شناسه‌ی یوتیوب‌موزیک را دارند و همان باید به جستجو برود؛ نه
        شناسه‌ی یوتیوبی که صفحه با آن صدا زده شده.
        """
        tracks = [_track("ytm:artist:UCSsq6HUy"), _track("ytm:artist:UCSsq6HUy")]

        assert youtube_music._ytm_artist_id(tracks, "UC0DXllI") == "UCSsq6HUy"

    def test_the_most_frequent_artist_wins_over_a_featured_one(self):
        """
        ترکِ فیچردار ممکن است هنرمندِ مهمان را اول بیاورد.

        نسخه‌ی اولِ این تابع «اولین شناسه‌ای که با خودمان یکی نیست» را برمی‌داشت
        و در عمل یک هنرمندِ مهمان را به جستجو می‌فرستاد؛ نتیجه‌اش این بود که
        تکمیلِ انتشارها هیچ‌وقت مطابقت نمی‌گرفت و سینگلِ تازه گم می‌ماند.
        """
        tracks = [
            _track("ytm:artist:UCguest"),  # مهمان، اول آمده
            _track("ytm:artist:UCSowner"),
            _track("ytm:artist:UCSowner"),
            _track("ytm:artist:UCSowner"),
        ]

        assert youtube_music._ytm_artist_id(tracks, "UC0DXllI") == "UCSowner"

    def test_own_id_wins_when_it_is_already_the_ytm_id(self):
        """
        در مسیرِ یوتیوب‌موزیک `clean_id` خودش شناسه‌ی درست است؛ حذفش می‌کردیم
        و به یک مهمان می‌رسیدیم.
        """
        tracks = [_track("ytm:artist:UCSowner"), _track("ytm:artist:UCSowner")]

        assert youtube_music._ytm_artist_id(tracks, "UCSowner") == "UCSowner"

    def test_falls_back_to_the_given_id_when_tracks_carry_nothing(self):
        """از روی ترک‌ها چیزی نیامد — همان شناسه‌ی صدازده‌شده بهتر از هیچ است."""
        assert youtube_music._ytm_artist_id([_track(None)], "UC0DXllI") == "UC0DXllI"
        assert youtube_music._ytm_artist_id([], "UC0DXllI") == "UC0DXllI"


class TestSupplementReleases:
    def _client(self, search_rows: list[dict]):
        class _Client:
            def search(self, _q, filter=None, limit=50):  # noqa: A002
                return search_rows

        return _Client()

    def test_release_missing_from_carousel_is_added(self):
        """
        سینگلِ «LOL»: در نتایجِ جستجو هست، در `seen_release_ids` (کاروسل) نه.
        """
        client = self._client(
            [
                {
                    "title": "LOL",
                    "videoId": "x33V9EP7hSw",
                    "album": {"id": "MPREb_BbNQdNecMVa", "name": "LOL"},
                    "artists": [{"id": "UCSsq6HUy", "name": "Tlkhoon"}],
                    "thumbnails": [{"url": "https://yt3.googleusercontent.com/x=w120", "width": 120}],
                }
            ]
        )
        seen: set[str] = set()
        singles: list = []

        youtube_music._supplement_releases(
            client, "UCSsq6HUy", "Tlkhoon", seen, singles
        )

        assert len(singles) == 1
        assert singles[0].id == "ytm:album:MPREb_BbNQdNecMVa"
        assert singles[0].title == "LOL"
        assert singles[0].source == "youtube_music"
        assert singles[0].releaseType == "single"
        # در `seen` ثبت شده تا جای دیگری دوباره اضافه‌اش نکند
        assert "MPREb_BbNQdNecMVa" in seen

    def test_duplicate_upload_with_different_id_is_skipped_by_title(self):
        """
        یوتیوب‌موزیک یک تک‌آهنگ را زیر دو `browseId` جدا دارد (`KAASH` و
        `Kaash`) با همان `videoId`. مقایسه‌ی شناسه چیزی نمی‌گیرد، پس صفحه‌ی
        هنرمند دو کارتِ هم‌نام نشان می‌داد.
        """
        client = self._client(
            [
                {
                    "title": "Kaash",
                    "videoId": "lx9r_Vvwg8Y",
                    "album": {"id": "MPREb_ubqP6mqE3FR", "name": "Kaash"},
                    "artists": [{"id": "UCSsq6HUy"}],
                }
            ]
        )
        seen: set[str] = set()
        # کاروسل نسخه‌ی «KAASH» را از قبل دارد (شناسه‌اش هم ثبت شده)
        singles = [_album("KAASH", year=2023)]
        seen.add("MPREb_ggvZ9GGPhiM")

        youtube_music._supplement_releases(client, "UCSsq6HUy", "Tlkhoon", seen, singles)

        assert len(singles) == 1
        assert singles[0].title == "KAASH"

    def test_duplicate_upload_with_a_different_year_is_still_skipped(self):
        """
        همان تک‌آهنگ گاهی دو سالِ متفاوت دارد — `Mochale` هم ۲۰۲۳ و هم ۲۰۲۴
        ثبت شده. سال نباید در کلیدِ یکتاسازی بیاید، وگرنه دوباره دو کارت
        می‌شود.
        """
        client = self._client(
            [
                {
                    "title": "Mochale",
                    "videoId": "Z9y7kpXzIbw",
                    "album": {"id": "MPREb_wz3KLsS3egl", "name": "Mochale"},
                    "artists": [{"id": "UCSsq6HUy"}],
                }
            ]
        )
        seen: set[str] = set()
        singles = [_album("Mochale", year=2023)]
        seen.add("MPREb_ZVJm0nf8dSM")

        youtube_music._supplement_releases(client, "UCSsq6HUy", "Tlkhoon", seen, singles)

        assert len(singles) == 1

    def test_release_already_in_carousel_is_not_duplicated(self):
        client = self._client(
            [
                {
                    "title": "Ajibe!",
                    "videoId": "dg4rIxLqZ4c",
                    "album": {"id": "MPREb_lENorPJTOUR", "name": "Ajibe!"},
                    "artists": [{"id": "UCSsq6HUy"}],
                }
            ]
        )
        seen = {"MPREb_lENorPJTOUR"}
        singles: list = []

        youtube_music._supplement_releases(client, "UCSsq6HUy", "Tlkhoon", seen, singles)

        assert singles == []

    def test_songs_by_other_artists_are_ignored(self):
        """جستجوی نام ممکن است ترکِ هنرمندِ دیگری را هم بیاورد."""
        client = self._client(
            [
                {
                    "title": "Something",
                    "videoId": "abc",
                    "album": {"id": "MPREb_other", "name": "Other"},
                    "artists": [{"id": "UCotherartist"}],
                }
            ]
        )
        seen: set[str] = set()
        singles: list = []

        youtube_music._supplement_releases(client, "UCSsq6HUy", "Tlkhoon", seen, singles)

        assert singles == []
        assert seen == set()

    def test_song_without_album_is_skipped(self):
        """ترکی که آلبومش را یوتیوب نداده قابلِ ساختنِ ردیفِ آلبوم نیست."""
        client = self._client(
            [
                {
                    "title": "Stray",
                    "videoId": "abc",
                    "album": None,
                    "artists": [{"id": "UCSsq6HUy"}],
                }
            ]
        )
        seen: set[str] = set()
        singles: list = []

        youtube_music._supplement_releases(client, "UCSsq6HUy", "Tlkhoon", seen, singles)

        assert singles == []

    def test_search_failure_does_not_break_the_page(self):
        class _Boom:
            def search(self, *_a, **_k):
                raise RuntimeError("network down")

        seen: set[str] = set()
        singles: list = []

        youtube_music._supplement_releases(_Boom(), "UCx", "X", seen, singles)

        assert singles == []


class TestAlbumRawRetry:
    def test_empty_noindex_body_is_retried_until_it_lands(self):
        """
        دو پاسخِ خالی و بعد پاسخِ سالم — نتیجه باید همان آلبوم باشد، نه None.
        """
        calls = {"n": 0}

        class _Client:
            def _send_request(self, _endpoint, _body):
                calls["n"] += 1
                if calls["n"] < 3:
                    return {"microformat": {"microformatDataRenderer": {"noindex": True}}}
                return {"contents": {"real": True}}

        raw = youtube_music._album_raw_with(_Client(), "MPREb_x", attempts=3)

        assert raw == {"contents": {"real": True}}
        assert calls["n"] == 3

    def test_exhausted_attempts_return_none_instead_of_raising(self):
        """تمام تلاش‌ها خالی — None، نه استثنا (که به ۵۰۲ تبدیل می‌شد)."""

        class _Client:
            def _send_request(self, _endpoint, _body):
                return {"microformat": {"microformatDataRenderer": {"noindex": True}}}

        raw = youtube_music._album_raw_with(_Client(), "MPREb_x", attempts=2)

        assert raw is None

    def test_raising_client_is_swallowed(self):
        class _Client:
            def _send_request(self, _endpoint, _body):
                raise KeyError("contents")

        assert youtube_music._album_raw_with(_Client(), "MPREb_x", attempts=2) is None

    def test_stale_client_is_replaced_and_the_album_is_still_found(self, monkeypatch):
        """
        نمونه‌ی بی‌کارمانده بدنه‌ی خالی می‌دهد؛ نمونه‌ی نو باید جایش را بگیرد.

        این همان حالتی است که موقعِ کارِ واقعی دیده شد: `search` سالم بود ولی
        `browse` آلبوم خالی برمی‌گشت و صفحه‌ی آلبوم ۵۰۲ می‌گرفت.
        """
        stale = _EmptyClient()
        fresh = _GoodClient()

        monkeypatch.setattr(youtube_music, "_get_client", lambda: stale)
        monkeypatch.setattr(youtube_music, "_reset_client", lambda: fresh)

        assert youtube_music._album_raw("MPREb_x") is True
        assert stale.used
        assert fresh.used

    def test_both_clients_empty_means_the_album_is_really_missing(self, monkeypatch):
        monkeypatch.setattr(youtube_music, "_get_client", _EmptyClient)
        monkeypatch.setattr(youtube_music, "_reset_client", _EmptyClient)

        assert youtube_music._album_raw("MPREb_x") is False


class _EmptyClient:
    """نمونه‌ی باطل‌شده: بدنه‌ی `noindex` بدون `contents`."""

    def __init__(self):
        self.used = False

    def _send_request(self, _endpoint, _body):
        self.used = True
        return {"microformat": {"microformatDataRenderer": {"noindex": True}}}


class _GoodClient:
    def __init__(self):
        self.used = False

    def _send_request(self, _endpoint, _body):
        self.used = True
        return {"contents": {"real": True}}
