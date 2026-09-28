"""تشخیص لینک و نگاشت متادیتا — جایی که یک regex اشتباه، کل ورودی را می‌بلعد."""

from __future__ import annotations

import asyncio

import pytest

from app import catalog
from app.catalog import ID, _dedupe_artists, _dedupe_tracks, interleave
from app.models import Album, AlbumDetail, Artist, ArtistDetail, SearchResults, Track
from app.providers import deezer, itunes, soundcloud, spotify, ytdlp


def _track(title: str, artist: str, source: str = "apple") -> Track:
    return Track(
        id=f"{source}:{title}", title=title, artist=artist, durationMs=1, source=source, sourceUrl="x"
    )


def _artist(name: str, source: str = "apple", artwork: str | None = None, subtitle: str = "هنرمند") -> Artist:
    return Artist(
        id=f"{source}:artist:{name}", name=name, artworkUrl=artwork,
        source=source, sourceUrl=f"https://{source}.example/{name}", subtitle=subtitle,
    )


def _album(title: str, artist: str, source: str = "soundcloud") -> Album:
    return Album(
        id=f"{source}:{title}", title=title, artist=artist, year=2025,
        trackCount=12, source=source, sourceUrl="x",
    )


class TestUrlParsing:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://open.spotify.com/album/1A2B3c", ("album", "1A2B3c")),
            ("https://open.spotify.com/playlist/37i9dQ", ("playlist", "37i9dQ")),
            ("https://open.spotify.com/track/abc123?si=xyz", ("track", "abc123")),
            # لینکی که اپ موبایل می‌سازد، بخش زبان دارد
            ("https://open.spotify.com/intl-fa/album/xyz", ("album", "xyz")),
        ],
    )
    def test_spotify(self, url, expected):
        assert spotify.parse_url(url) == expected

    def test_spotify_rejects_other_hosts(self):
        assert spotify.parse_url("https://example.com/album/1") is None

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.deezer.com/album/12345", ("album", "12345")),
            ("https://www.deezer.com/fa/playlist/999", ("playlist", "999")),
            ("https://www.deezer.com/en/artist/42", ("artist", "42")),
        ],
    )
    def test_deezer(self, url, expected):
        assert deezer.parse_url(url) == expected

    def test_apple(self):
        assert itunes.parse_url(
            "https://music.apple.com/us/album/mard-e-tanha/1801042661?i=1801042670"
        ) == ("album", "1801042661")
        assert itunes.parse_url("https://music.apple.com/us/artist/farhad/500") == (
            "artist",
            "500",
        )


class TestInternalIds:
    @pytest.mark.parametrize(
        "ident",
        ["itunes:album:1", "deezer:playlist:2", "sp:track:abc", "yt:track:dQw4", "sc:track:x"],
    )
    def test_accepted(self, ident):
        assert ID.match(ident)

    @pytest.mark.parametrize("ident", ["spotify:album:1", "itunes:banana:1", "just-a-string"])
    def test_rejected(self, ident):
        assert ID.match(ident) is None


class TestArtwork:
    def test_size_is_rewritten(self):
        url = "https://is1.mzstatic.com/image/thumb/x/100x100bb.jpg"
        assert itunes.artwork(url, 600).endswith("600x600bb.jpg")

    def test_none_stays_none(self):
        assert itunes.artwork(None) is None


class TestDedupe:
    def test_the_same_track_survives_on_every_platform(self):
        """
        هم‌نام بودن با اپل نباید نسخه‌ی بقیه را حذف کند. وقتی می‌کرد، از ساندکلاد
        فقط ریمیکس‌ها می‌ماندند و خودِ ترکِ اصلی — که با اپل هم‌نام است — می‌افتاد.
        """
        rows = [
            _track("EDGEBAR", "Dorcci"),
            _track("edgebar", "DORCCI", "deezer"),
            _track("EDGEBAR", "Dorcci", "spotify"),
            _track("EDGEBAR", "Dorcci", "soundcloud"),
        ]
        assert [t.source for t in _dedupe_tracks(rows)] == [
            "apple", "deezer", "spotify", "soundcloud",
        ]

    def test_duplicates_inside_one_source_still_collapse(self):
        """اپل همان ترک را هم از سینگل هم از آلبوم می‌دهد — آن یکی واقعاً تکراری است."""
        rows = [_track("Barf", "Farhad"), _track("barf", "FARHAD")]
        assert len(_dedupe_tracks(rows)) == 1

    def test_the_same_artist_survives_on_every_platform(self):
        """
        قبلاً نسخه‌ی عکس‌دار برنده می‌شد و از چهار پلتفرم یک کارت می‌ماند —
        جستجوی «Dorcci» فقط دیزر را می‌آورد و صفحه‌ی سه پلتفرم دیگرِ همان هنرمند
        هیچ راهی نداشت.
        """
        rows = [
            _artist("Dorcci", "apple"),
            _artist("dorcci", "deezer", artwork="http://img"),
            _artist("DORCCI", "spotify"),
            _artist("Dorcci", "soundcloud"),
        ]

        assert [a.source for a in _dedupe_artists(rows)] == [
            "apple", "deezer", "spotify", "soundcloud",
        ]

    def test_duplicates_inside_one_source_prefer_the_one_with_a_photo(self):
        """یک نام گاهی چند ردیف در همان کاتالوگ دارد؛ آن یکی واقعاً تکراری است."""
        rows = [
            _artist("Farhad Mehrad", "deezer"),
            _artist("farhad mehrad", "deezer", artwork="http://img"),
        ]

        merged = _dedupe_artists(rows)

        assert len(merged) == 1
        assert merged[0].artworkUrl == "http://img"

    def test_artists_with_different_names_both_survive(self):
        def make(i, name):
            return Artist(
                id=f"a{i}", name=name, artworkUrl=None, source="apple",
                sourceUrl="x", subtitle="",
            )

        assert len(_dedupe_artists([make(1, "A"), make(2, "B")])) == 2


class TestArtistPages:
    """
    هر کارتِ هنرمند به صفحه‌ی همان پلتفرم می‌رود، پس `resolve_artist` باید هر
    چهار شناسه را بشناسد. کارتی که صفحه‌اش باز نشود فقط یک ۴۰۴ است.
    """

    @pytest.fixture
    def resolvers(self, monkeypatch):
        seen: list[str] = []

        def detail(name: str) -> ArtistDetail:
            return ArtistDetail(
                id=f"x:artist:{name}", name=name, source="apple",
                sourceUrl="x", subtitle="", topTracks=[], albums=[],
            )

        async def apple(client, ident):
            seen.append(f"apple:{ident}")
            return detail("apple")

        async def deez(client, ident):
            seen.append(f"deezer:{ident}")
            return detail("deezer")

        async def spot(client, ident):
            seen.append(f"spotify:{ident}")
            return detail("spotify")

        def cloud(ident):
            seen.append(f"soundcloud:{ident}")
            return detail("soundcloud")

        monkeypatch.setattr(itunes, "artist", apple)
        monkeypatch.setattr(deezer, "artist", deez)
        monkeypatch.setattr(spotify, "artist", spot)
        monkeypatch.setattr(spotify, "enabled", lambda: True)
        monkeypatch.setattr(ytdlp, "soundcloud_artist", cloud)
        return seen

    @pytest.mark.parametrize(
        "ref,expected",
        [
            ("itunes:artist:301788063", "apple:301788063"),
            ("deezer:artist:154508252", "deezer:154508252"),
            ("sp:artist:6jj9lOTeZC28LkPoXK9hiT", "spotify:6jj9lOTeZC28LkPoXK9hiT"),
            ("sc:artist:99", "soundcloud:99"),
        ],
    )
    def test_every_platform_resolves(self, resolvers, ref, expected):
        detail = asyncio.run(catalog.resolve_artist(None, ref))

        assert resolvers == [expected]
        assert detail is not None

    def test_spotify_without_a_key_yields_nothing_rather_than_a_broken_call(
        self, resolvers, monkeypatch
    ):
        monkeypatch.setattr(spotify, "enabled", lambda: False)

        assert asyncio.run(catalog.resolve_artist(None, "sp:artist:abc")) is None
        assert resolvers == []

    def test_an_album_id_is_not_an_artist(self, resolvers):
        assert asyncio.run(catalog.resolve_artist(None, "sp:album:abc")) is None
        assert resolvers == []


class TestArtistTrackBackfill:
    """
    صفحه‌ی هنرمند باید همان چیزی را نشان بدهد که خودِ پلتفرم نشان می‌دهد. دو
    پلتفرم لیستِ محبوب‌ها را نمی‌دهند (`/top` دیزر از این IP همیشه خالی است و
    `top-tracks` اسپاتیفای روی کلیدهای حالت توسعه ۴۰۳ می‌دهد) و صفحه‌شان فقط گرید
    آلبوم می‌شد. آلبوم‌ها که هستند — ترک‌ها از داخلِ خودشان می‌آیند.
    """

    @staticmethod
    def _album(title: str, tracks: int, source: str = "deezer") -> Album:
        return Album(
            id=f"{source}:album:{title}", title=title, artist="Dorcci", year=2025,
            trackCount=tracks, source=source, sourceUrl=f"https://{source}.example/{title}",
        )

    @staticmethod
    def _detail(albums: list[Album], tracks: list[Track] | None = None) -> ArtistDetail:
        return ArtistDetail(
            id="deezer:artist:1", name="Dorcci", source="deezer", sourceUrl="x",
            subtitle="", topTracks=tracks or [], albums=albums,
        )

    @pytest.fixture
    def refs(self, monkeypatch):
        """`resolve_ref` را می‌گیرد: هر آلبوم به‌اندازه‌ی trackCount ترک دارد."""
        asked: list[str] = []

        async def fake(client, ref):
            asked.append(ref)
            title = ref.rsplit("/", 1)[1]
            # سینگل‌ها یک‌ترکه‌اند و بقیه آلبومِ کاملِ دوازده‌ترکه
            count = {"EDGEBAR": 1, "BROKEN": 1, "GONAH": 2}.get(title, 12)
            return AlbumDetail(
                id=f"deezer:album:{title}", title=title, artist="Dorcci", year=2025,
                trackCount=count, source="deezer", sourceUrl=ref, durationMs=0,
                tracks=[_track(f"{title} {i}", "Dorcci", "deezer") for i in range(count)],
            )

        monkeypatch.setattr(catalog, "resolve_ref", fake)
        return asked

    def test_an_empty_track_list_is_filled_from_the_newest_releases(self, refs):
        detail = self._detail([self._album("YOUNG MORVARID", 12)])

        out = asyncio.run(catalog._fill_tracks(None, detail))

        assert [t.title for t in out.topTracks][:2] == ["YOUNG MORVARID 0", "YOUNG MORVARID 1"]
        assert len(out.topTracks) == 12

    def test_a_real_album_is_preferred_over_the_newest_singles(self, refs):
        """
        یک آلبومِ دوازده‌ترکه در یک درخواست همان لیستی را می‌دهد که سه سینگل
        نمی‌دهند — ولی ترتیبِ تازه‌به‌قدیمِ درونِ هر دسته باید بماند.
        """
        detail = self._detail(
            [
                self._album("EDGEBAR", 1),
                self._album("BROKEN", 1),
                self._album("YOUNG MORVARID", 12),
                self._album("GONAH", 1),
            ]
        )

        asyncio.run(catalog._fill_tracks(None, detail))

        assert [r.rsplit("/", 1)[1] for r in refs] == ["YOUNG MORVARID", "EDGEBAR", "BROKEN"]

    def test_an_unknown_track_count_is_not_treated_as_a_single(self, refs):
        """
        دیزر در `/artist/{id}/albums` تعداد ترک نمی‌دهد و آلبومِ واقعی با صفر
        می‌آید. اگر صفر «کم‌ترک» حساب می‌شد، آلبوم ته صف می‌رفت و صفحه فقط سه ترکِ
        سینگل داشت — همان چیزی که در داده‌ی واقعی دیدیم.
        """
        detail = self._detail(
            [
                self._album("EDGEBAR", 1),
                self._album("BROKEN", 1),
                self._album("YOUNG MORVARID", 0),
            ]
        )

        out = asyncio.run(catalog._fill_tracks(None, detail))

        assert refs[0].endswith("YOUNG MORVARID")
        assert len(out.topTracks) == catalog.FALLBACK_TRACKS

    def test_the_list_is_capped(self, refs):
        detail = self._detail([self._album(t, 12) for t in ("A", "B", "C", "D")])

        out = asyncio.run(catalog._fill_tracks(None, detail))

        assert len(out.topTracks) == catalog.FALLBACK_TRACKS
        # چهارمی اصلاً خواسته نمی‌شود
        assert len(refs) == catalog.FALLBACK_ALBUMS

    def test_a_platform_that_gives_its_own_tracks_is_left_alone(self, refs):
        """اپل و ساندکلاد لیست خودشان را دارند؛ نباید یک درخواست اضافه بزنیم."""
        mine = [_track(f"Song {i}", "Dorcci") for i in range(25)]
        detail = self._detail([self._album("YOUNG MORVARID", 12)], tracks=mine)

        out = asyncio.run(catalog._fill_tracks(None, detail))

        assert out.topTracks == mine
        assert refs == []

    def test_soundcloud_is_not_refilled_from_albums(self, refs):
        """محبوب‌های ساندکلاد ترتیب پخش دارند؛ پر کردن از آلبوم آن را خراب می‌کند."""
        mine = [_track("Quiet Hit", "Dorcci", "soundcloud")]
        detail = ArtistDetail(
            id="sc:artist:1",
            name="Dorcci",
            source="soundcloud",
            sourceUrl="x",
            subtitle="",
            topTracks=mine,
            albums=[self._album("YOUNG MORVARID", 12, "soundcloud")],
        )

        out = asyncio.run(catalog._fill_tracks(None, detail))

        assert out.topTracks == mine
        assert refs == []

    def test_a_partial_list_is_topped_up_without_losing_it(self, refs):
        """
        دیزر برای هنرمندی با هفت آلبوم فقط یک ترک برگرداند. آن یک ترک محبوبِ
        واقعی است و باید اول بماند، ولی نباید جلوی پر شدنِ بقیه را بگیرد.
        """
        mine = [_track("Real Top Track", "Dorcci", "deezer")]
        detail = self._detail([self._album("YOUNG MORVARID", 0)], tracks=mine)

        out = asyncio.run(catalog._fill_tracks(None, detail))

        assert out.topTracks[0].title == "Real Top Track"
        assert len(out.topTracks) == catalog.FALLBACK_TRACKS

    def test_a_track_the_platform_already_gave_is_not_repeated(self, refs):
        """همان ترک در لیستِ محبوب‌ها و در آلبوم هر دو هست."""
        detail = self._detail([self._album("YOUNG MORVARID", 0)])
        mine = _track("YOUNG MORVARID 0", "Dorcci", "deezer")
        detail.topTracks = [mine]

        out = asyncio.run(catalog._fill_tracks(None, detail))

        assert [t.id for t in out.topTracks].count(mine.id) == 1

    def test_an_artist_without_albums_stays_empty(self, refs):
        out = asyncio.run(catalog._fill_tracks(None, self._detail([])))

        assert out.topTracks == [] and refs == []

    def test_a_dead_album_does_not_break_the_page(self, monkeypatch):
        async def boom(client, ref):
            raise RuntimeError("502")

        monkeypatch.setattr(catalog, "resolve_ref", boom)

        out = asyncio.run(catalog._fill_tracks(None, self._detail([self._album("X", 12)])))

        assert out.topTracks == []


class TestSpotifyMapping:
    def test_track_row_becomes_track(self):
        row = {
            "id": "abc",
            "name": "Barf",
            "duration_ms": 240_000,
            "explicit": True,
            "artists": [{"name": "Farhad"}, {"name": "Guest"}],
            "album": {"id": "alb", "name": "Barf", "images": [{"url": "http://i"}]},
            "external_urls": {"spotify": "http://open"},
        }
        t = spotify._track(row)
        assert t.id == "sp:track:abc"
        assert t.artist == "Farhad, Guest"
        assert t.albumId == "sp:album:alb"
        assert t.source == "spotify"
        assert t.explicit is True

    def test_missing_id_yields_none(self):
        assert spotify._track({}) is None

    def test_artist_row_becomes_a_profile_link(self):
        row = {
            "id": "art1",
            "name": "Dorcci",
            "genres": ["persian trap", "persian pop", "rap"],
            "followers": {"total": 120_500},
            "images": [{"url": "http://small", "width": 160}, {"url": "http://big", "width": 640}],
            "external_urls": {"spotify": "http://open/artist"},
        }

        a = spotify._artist_head(row)

        assert a.id == "sp:artist:art1"
        assert a.source == "spotify"
        assert a.sourceUrl == "http://open/artist"
        # بزرگ‌ترین عکس، چون کارت روی نمایشگر رتینا می‌نشیند
        assert a.artworkUrl == "http://big"
        # فقط دو ژانر اول؛ بقیه در یک خط جا نمی‌شوند
        assert a.subtitle == "persian trap، persian pop"

    def test_an_artist_without_genres_shows_followers(self):
        row = {"id": "art2", "name": "Dorcci", "followers": {"total": 4200}}

        assert spotify._artist_head(row).subtitle == "4,200 دنبال‌کننده"

    def test_an_unknown_artist_still_gets_a_subtitle(self):
        assert spotify._artist_head({"id": "art3", "name": "X"}).subtitle == "هنرمند"


class TestDeezerAlbumRows:
    def test_a_single_is_known_to_have_one_track(self):
        """
        `/artist/{id}/albums` تعداد ترک نمی‌دهد ولی `record_type` می‌دهد — و همین
        است که آلبومِ واقعی را در صفحه‌ی هنرمند جلوی سینگل می‌اندازد.
        """
        single = deezer._album({"id": 1, "title": "EDGEBAR", "record_type": "single"})
        album = deezer._album({"id": 2, "title": "YOUNG MORVARID", "record_type": "album"})

        assert single.trackCount == 1
        # آلبوم را نمی‌دانیم چند ترک است؛ صفر یعنی نامعلوم، نه خالی
        assert album.trackCount == 0
        assert single.releaseType == "single"
        assert album.releaseType == "album"

    def test_a_real_count_still_wins(self):
        """`/search/album` خودش nb_tracks می‌دهد و حدس نباید جایش را بگیرد."""
        row = {"id": 3, "title": "GONAH", "record_type": "single", "nb_tracks": 4}

        assert deezer._album(row).trackCount == 4


class TestSpotifyArtistPage:
    """صفحه‌ی هنرمندِ اسپاتیفای — سه اندپوینت که با هم یک صفحه می‌سازند."""

    HEAD = {
        "id": "art1",
        "name": "Dorcci",
        "genres": ["persian trap"],
        "images": [{"url": "http://face", "width": 640}],
        "external_urls": {"spotify": "http://open/artist"},
    }

    @staticmethod
    def _album_row(album_id: str, name: str, date: str) -> dict:
        return {
            "id": album_id,
            "name": name,
            "release_date": date,
            "total_tracks": 10,
            "artists": [{"name": "Dorcci"}],
            "images": [{"url": "http://cover", "width": 640}],
        }

    def _stub(self, monkeypatch, calls: list[tuple[str, dict]] | None = None, **overrides):
        bodies = {
            "/artists/art1": self.HEAD,
            "/artists/art1/top-tracks": {
                "tracks": [
                    {
                        "id": "t1", "name": "EDGEBAR", "duration_ms": 1,
                        "artists": [{"name": "Dorcci"}], "album": {"id": "a1", "name": "X"},
                    }
                ]
            },
            "/artists/art1/albums": {
                "items": [
                    self._album_row("a1", "YOUNG MORVARID", "2023-05-01"),
                    self._album_row("a2", "GONAH", "2025-01-01"),
                ]
            },
            **overrides,
        }

        async def fake_get(client, path, **params):
            if calls is not None:
                calls.append((path, params))
            body = bodies.get(path)
            if isinstance(body, BaseException):
                raise body
            return body or {}

        monkeypatch.setattr(spotify, "_get", fake_get)

    def test_the_page_has_a_head_top_tracks_and_a_discography(self, monkeypatch):
        self._stub(monkeypatch)

        detail = asyncio.run(spotify.artist(None, "art1"))

        assert detail.id == "sp:artist:art1"
        assert detail.artworkUrl == "http://face"
        assert [t.title for t in detail.topTracks] == ["EDGEBAR"]
        # تازه‌ترین اول — مثل اپل و دیزر
        assert [a.title for a in detail.albums] == ["GONAH", "YOUNG MORVARID"]

    def test_reissues_of_one_album_collapse(self, monkeypatch):
        """
        اسپاتیفای یک آلبوم را چند بار می‌دهد (نسخه‌ی کشورها، ری‌ایشو) و شناسه‌شان
        هم فرق دارد، پس یکتاسازی با id کاری نمی‌کرد.
        """
        self._stub(
            monkeypatch,
            **{
                "/artists/art1/albums": {
                    "items": [
                        self._album_row("a1", "GONAH", "2025-01-01"),
                        self._album_row("a2", "gonah", "2025-03-02"),
                        self._album_row("a3", "GONAH", "2019-01-01"),
                    ]
                }
            },
        )

        albums = asyncio.run(spotify.artist(None, "art1")).albums

        # هم‌نامِ هم‌سال یکی است و تازه‌ترینشان می‌ماند؛ نسخه‌ی ۲۰۱۹ واقعاً
        # انتشار دیگری است و سرِ جایش می‌ماند
        assert [(a.title, a.year) for a in albums] == [("gonah", 2025), ("GONAH", 2019)]

    def test_a_dead_side_call_still_opens_the_page(self, monkeypatch):
        """عکس و نامِ هنرمند فقط در سرِ صفحه‌اند — آن یکی نباید گروگانِ بقیه باشد."""
        self._stub(
            monkeypatch,
            **{
                "/artists/art1/top-tracks": RuntimeError("429"),
                "/artists/art1/albums": RuntimeError("429"),
            },
        )

        detail = asyncio.run(spotify.artist(None, "art1"))

        assert detail.name == "Dorcci"
        assert detail.topTracks == [] and detail.albums == []

    def test_a_missing_artist_is_none(self, monkeypatch):
        self._stub(monkeypatch, **{"/artists/art1": {}})

        assert asyncio.run(spotify.artist(None, "art1")) is None

    def test_the_discography_is_newest_first_by_full_date(self, monkeypatch):
        """
        اسپاتیفای آلبوم‌ها را گروه‌به‌گروه می‌دهد (اول album ها، بعد single ها) و
        مرتب‌سازیِ سالانه، ده سینگلِ یک سال را با ترتیب دلبخواه رها می‌کرد.
        صفحه‌ی خودِ اسپاتیفای تازه‌ترین را اول می‌گذارد.
        """
        self._stub(
            monkeypatch,
            **{
                "/artists/art1/albums": {
                    "items": [
                        self._album_row("a1", "YOUNG MORVARID", "2025-02-21"),
                        self._album_row("a2", "EDGEBAR", "2026-08-05"),
                        self._album_row("a3", "BROKEN", "2026-07-18"),
                        self._album_row("a4", "LAST CHANCE", "2025-12-26"),
                    ]
                }
            },
        )

        albums = asyncio.run(spotify.artist(None, "art1")).albums

        assert [a.title for a in albums] == [
            "EDGEBAR", "BROKEN", "LAST CHANCE", "YOUNG MORVARID",
        ]

    def test_the_discography_is_asked_for_in_small_pages(self, monkeypatch):
        """
        کلیدِ حالت توسعه — همان چیزی که بدون درخواستِ دسترسی گیر می‌آید — روی این
        اندپوینت limit بزرگ‌تر از ده را با «Invalid limit» رد می‌کند. با ۵۰،
        دیسکوگرافیِ هر هنرمند بی‌صدا خالی می‌آمد.
        """
        calls: list[tuple[str, dict]] = []
        self._stub(monkeypatch, calls=calls)

        asyncio.run(spotify.artist(None, "art1"))

        limits = [p["limit"] for path, p in calls if path.endswith("/albums") and "limit" in p]
        assert limits and max(limits) <= 10

    def test_a_long_discography_is_paged_through(self, monkeypatch):
        """صفحه‌ی ده‌تایی یعنی هنرمندِ چهل‌آلبومی چند درخواست لازم دارد."""
        pages = [
            {
                "items": [self._album_row(f"a{i}", f"Album {i}", f"20{i:02d}-01-01") for i in range(n, n + 10)],
                "next": "http://more" if n < 20 else None,
            }
            for n in (0, 10, 20)
        ]
        sent: list[int] = []

        async def fake_get(client, path, **params):
            if path == "/artists/art1":
                return self.HEAD
            if path.endswith("/albums"):
                sent.append(params["offset"])
                return pages[params["offset"] // 10]
            return {}

        monkeypatch.setattr(spotify, "_get", fake_get)

        albums = asyncio.run(spotify.artist(None, "art1")).albums

        assert sent == [0, 10, 20]
        assert len(albums) == 30


class TestInterleave:
    """
    بخش «همه» فقط پنج تای اول را نشان می‌دهد. با چهار منبعِ پشت‌سرهم، منبع آخر
    هیچ‌وقت به آن پنج تا نمی‌رسید — همین‌جا قفل می‌شود.
    """

    def test_sources_take_turns(self):
        rows = [
            _track("a1", "x"), _track("a2", "x"),
            _track("s1", "x", "spotify"), _track("s2", "x", "spotify"),
            _track("c1", "x", "soundcloud"),
        ]
        assert [t.source for t in interleave(rows)] == [
            "apple", "spotify", "soundcloud", "apple", "spotify",
        ]

    def test_every_source_reaches_the_first_page(self):
        """منبعی که ده‌تا نتیجه داده نباید منبعی که یکی داده را از صفحه بیرون کند."""
        rows = [_track(f"s{i}", "x", "spotify") for i in range(10)]
        rows.append(_track("c1", "x", "soundcloud"))
        assert "soundcloud" in [t.source for t in interleave(rows)[:5]]

    def test_order_inside_a_source_survives(self):
        """هر کاتالوگ خودش بر اساس ربط مرتب کرده — آن ترتیب نباید به هم بخورد."""
        rows = [_track(f"a{i}", "x") for i in range(3)]
        rows += [_track(f"s{i}", "x", "spotify") for i in range(3)]
        out = interleave(rows)
        assert [t.title for t in out if t.source == "apple"] == ["a0", "a1", "a2"]
        assert [t.title for t in out if t.source == "spotify"] == ["s0", "s1", "s2"]

    def test_albumsinterleave_too(self):
        rows = [_album("A", "x", "spotify"), _album("B", "x", "spotify"), _album("C", "x", "deezer")]
        assert [a.source for a in interleave(rows)] == ["spotify", "deezer", "spotify"]

    def test_empty_stays_empty(self):
        assert interleave([]) == []


class TestSearchFanout:
    """
    اپل و دیزر همیشه؛ اسپاتیفای فقط با کلید و ساندکلاد فقط وقتی در AUDIO_SOURCES
    باشد. هر کدام که بیفتد نباید بقیه را با خودش پایین بکشد.
    """

    @pytest.fixture
    def providers(self, monkeypatch):
        called: list[str] = []

        def stub(name: str, results: SearchResults):
            async def fake(client, query, *args, **kwargs):
                called.append(name)
                return results

            return fake

        monkeypatch.setattr(
            itunes,
            "search",
            stub(
                "apple",
                SearchResults(
                    query="q",
                    tracks=[_track("Barf", "F")],
                    artists=[_artist("Dorcci", "apple", subtitle="Pop")],
                ),
            ),
        )
        monkeypatch.setattr(
            deezer,
            "search",
            stub(
                "deezer",
                SearchResults(
                    query="q",
                    albums=[_album("EDGEBAR", "Dorcci", "deezer")],
                    artists=[
                        _artist("DORCCI", "deezer", artwork="http://img"),
                        _artist("Dorcci Fan Club", "deezer"),
                    ],
                ),
            ),
        )
        monkeypatch.setattr(
            spotify,
            "search",
            stub(
                "spotify",
                SearchResults(
                    query="q",
                    tracks=[_track("Gol", "F", "spotify")],
                    artists=[_artist("dorcci", "spotify")],
                ),
            ),
        )

        def sc_tracks(query):
            called.append("soundcloud")
            return [_track("Sar", "F", "soundcloud")]

        def sc_albums(query):
            called.append("soundcloud-albums")
            return [_album("YOUNG MORVARID", "Dorcci")]

        def sc_users(query):
            called.append("soundcloud-users")
            return [_artist("Dorcci", "soundcloud", subtitle="۱۲ آهنگ")]

        monkeypatch.setattr(ytdlp, "soundcloud_search", sc_tracks)
        monkeypatch.setattr(soundcloud, "search_albums", sc_albums)
        monkeypatch.setattr(soundcloud, "search_users", sc_users)
        # پیش‌فرضِ آزمون: هر دوی اختیاری‌ها روشن
        monkeypatch.setattr(spotify, "enabled", lambda: True)
        monkeypatch.setattr(catalog, "AUDIO_SOURCES", ("youtube", "soundcloud"))
        return called

    def test_every_provider_contributes(self, providers):
        out = asyncio.run(catalog.search(None, "q"))
        assert sorted(providers) == [
            "apple", "deezer", "soundcloud", "soundcloud-albums", "soundcloud-users", "spotify",
        ]
        assert [t.source for t in out.tracks] == ["apple", "spotify", "soundcloud"]

    def test_the_artists_section_has_a_card_per_platform(self, providers):
        """
        همان هنرمند از چهار کاتالوگ، چهار کارت — تا صفحه‌ی هر پلتفرم در دسترس
        باشد. با یکتاسازیِ بین‌منبعی، «Dorcci» فقط دیزر را نشان می‌داد.
        """
        artists = asyncio.run(catalog.search(None, "q")).artists

        assert {a.source for a in artists} == {"apple", "deezer", "spotify", "soundcloud"}
        assert sorted(a.source for a in artists if a.name.lower() == "dorcci") == [
            "apple", "deezer", "soundcloud", "spotify",
        ]

    def test_the_cards_take_turns_between_platforms(self, providers):
        """گرید فقط پنج کارتِ اول را نشان می‌دهد؛ هیچ پلتفرمی نباید از آن بیرون بماند."""
        artists = asyncio.run(catalog.search(None, "q")).artists

        assert len({a.source for a in artists[:4]}) == 4

    def test_a_dead_artist_endpoint_does_not_sink_the_search(self, providers, monkeypatch):
        """کارتِ هنرمند تزئینی است؛ افتادنش نباید ترک و آلبوم را با خودش ببرد."""

        def boom(query):
            raise RuntimeError("client_id سوخته")

        monkeypatch.setattr(soundcloud, "search_users", boom)
        out = asyncio.run(catalog.search(None, "q"))

        assert [t.source for t in out.tracks] == ["apple", "spotify", "soundcloud"]
        assert "soundcloud" not in {a.source for a in out.artists}

    def test_albums_come_from_every_source_that_has_one(self, providers):
        """
        دیزر تا حالا هیچ آلبومی نمی‌داد چون `/search/album` اصلاً زده نمی‌شد و
        بخش آلبوم‌ها فقط اپل و اسپاتیفای داشت.
        """
        albums = asyncio.run(catalog.search(None, "q")).albums
        assert sorted(a.source for a in albums) == ["deezer", "soundcloud"]
        assert {a.title for a in albums} == {"EDGEBAR", "YOUNG MORVARID"}

    def test_spotify_is_skipped_without_a_key(self, providers, monkeypatch):
        monkeypatch.setattr(spotify, "enabled", lambda: False)
        out = asyncio.run(catalog.search(None, "q"))
        assert "spotify" not in providers
        assert [t.source for t in out.tracks] == ["apple", "soundcloud"]

    def test_soundcloud_is_skipped_when_not_an_audio_source(self, providers, monkeypatch):
        monkeypatch.setattr(catalog, "AUDIO_SOURCES", ("youtube",))
        out = asyncio.run(catalog.search(None, "q"))
        assert not [p for p in providers if p.startswith("soundcloud")]
        assert [t.source for t in out.tracks] == ["apple", "spotify"]

    @pytest.mark.parametrize("broken", ["spotify", "soundcloud"])
    def test_one_failure_does_not_sink_the_others(self, providers, monkeypatch, broken):
        if broken == "spotify":

            async def boom(client, query, *args, **kwargs):
                raise RuntimeError("401")

            monkeypatch.setattr(spotify, "search", boom)
        else:

            def boom(query):
                raise RuntimeError("client_id سوخته")

            monkeypatch.setattr(ytdlp, "soundcloud_search", boom)

        survivors = [t.source for t in asyncio.run(catalog.search(None, "q")).tracks]
        assert "apple" in survivors and broken not in survivors

    def test_a_dead_track_endpoint_still_yields_albums(self, providers, monkeypatch):
        """دو اندپوینتِ ساندکلاد مستقل‌اند — افتادن یکی نباید دیگری را ببلعد."""

        def boom(query):
            raise RuntimeError("client_id سوخته")

        monkeypatch.setattr(ytdlp, "soundcloud_search", boom)
        out = asyncio.run(catalog.search(None, "q"))
        assert "soundcloud" in [a.source for a in out.albums]


class TestPlaylistSearch:
    """جستجوی پلی‌لیستِ اختصاصی برای چت‌بات وایب (vibe.py) — جدا از `search` عمومیِ هر پلتفرم."""

    def test_deezer_maps_playlist_rows(self, monkeypatch):
        async def fake_get(client, path, **params):
            assert path == "/search/playlist"
            assert params["q"] == "sad songs"
            return {
                "data": [
                    {
                        "id": 1,
                        "title": "Sad Songs",
                        "nb_tracks": 50,
                        "link": "https://www.deezer.com/playlist/1",
                        "user": {"name": "Deezer"},
                    }
                ]
            }

        monkeypatch.setattr(deezer, "_get", fake_get)

        found = asyncio.run(deezer.search_playlists(None, "sad songs"))

        assert len(found) == 1
        assert found[0].id == "deezer:playlist:1"
        assert found[0].source == "deezer"
        assert found[0].trackCount == 50

    def test_spotify_returns_nothing_without_a_key(self, monkeypatch):
        """اندپوینتِ پلی‌لیستِ اسپاتیفای بدون کلید اصلاً زده نمی‌شود، نه اینکه بخورد و بترکد."""
        monkeypatch.setattr(spotify, "enabled", lambda: False)
        monkeypatch.setattr(
            spotify,
            "_get",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not connect")),
        )

        assert asyncio.run(spotify.search_playlists(None, "sad songs")) == []

    def test_spotify_maps_playlist_rows(self, monkeypatch):
        monkeypatch.setattr(spotify, "enabled", lambda: True)

        async def fake_get(client, path, **params):
            assert params["type"] == "playlist"
            return {
                "playlists": {
                    "items": [
                        {
                            "id": "abc",
                            "name": "Sad Hour",
                            "owner": {"display_name": "Spotify"},
                            # اسپاتیفای اینجا تعداد ترک را زیرِ «items» می‌دهد، نه «tracks»
                            "items": {"total": 40},
                            "images": [{"url": "http://x", "width": 300}],
                            "external_urls": {"spotify": "https://open.spotify.com/playlist/abc"},
                        }
                    ]
                }
            }

        monkeypatch.setattr(spotify, "_get", fake_get)

        found = asyncio.run(spotify.search_playlists(None, "sad songs"))

        assert len(found) == 1
        assert found[0].id == "sp:playlist:abc"
        assert found[0].owner == "Spotify"
        assert found[0].trackCount == 40


class TestAlbumArtistStamp:
    """
    هنرمندِ آلبوم روی ترک‌ها.

    هیچ سرویسی این را روی خودِ ترک نمی‌دهد. اگر پخش نشود، فایلِ خروجی TPE2 را
    از هنرمندِ ترک می‌گیرد و آلبومی که چند ترکش مهمان دارد، در پلیر به چند
    آلبومِ هم‌نام تکه‌تکه می‌شود — دقیقاً همان چیزی که کاربر در ویندوز مدیا
    پلیر می‌دید.
    """

    def _tracks(self, album: str | None, *artists: str) -> list[Track]:
        return [
            Track(
                id=f"sp:track:{i}", title=f"T{i}", artist=a, album=album,
                durationMs=1, source="spotify", sourceUrl="x",
            )
            for i, a in enumerate(artists)
        ]

    def _detail(self, title: str, artist: str, tracks: list[Track]) -> AlbumDetail:
        return AlbumDetail(
            id="sp:album:1", title=title, artist=artist, year=2025,
            trackCount=len(tracks), source="spotify", sourceUrl="x",
            durationMs=sum(t.durationMs for t in tracks), tracks=tracks,
        )

    def test_featured_tracks_keep_the_album_artist(self):
        tracks = self._tracks("GRAY WEEK", "NoTsH", "NoTsH, Rowly", "NoTsH, Aminak")

        detail = self._detail("GRAY WEEK", "NoTsH", tracks)

        assert [t.albumArtist for t in detail.tracks] == ["NoTsH"] * 3
        # هنرمندِ خودِ ترک دست‌نخورده می‌ماند؛ مهمان‌ها در TPE1 می‌مانند
        assert detail.tracks[1].artist == "NoTsH, Rowly"

    def test_a_playlist_does_not_stamp_its_owner_on_the_tracks(self):
        """پلی‌لیست هم AlbumDetail است، ولی «هنرمند»ش سازنده‌ی پلی‌لیست است."""
        tracks = self._tracks("Rust In Peace", "Megadeth") + self._tracks("Bark", "Sote")

        detail = self._detail("Sad Hour", "Spotify", tracks)

        assert [t.albumArtist for t in detail.tracks] == [None, None]

    def test_an_album_without_track_numbers_is_numbered_by_position(self):
        """
        ساندکلاد و یوتیوب شماره‌ی ترک نمی‌دهند. ترتیبِ فهرست همان ترتیبِ
        پلتفرم است، پس جایگاه می‌شود شماره — وگرنه فایل بی‌TRCK می‌ماند و هر
        پلیری آلبوم را به میلِ خودش می‌چیند.
        """
        tracks = self._tracks("GRAY WEEK", "NoTsH", "NoTsH, Rowly", "NoTsH, Aminak")

        detail = self._detail("GRAY WEEK", "NoTsH", tracks)

        assert [t.trackNumber for t in detail.tracks] == [1, 2, 3]

    def test_real_track_numbers_are_never_replaced(self):
        """کاتالوگی که شماره داده، حرفِ آخر را می‌زند — حتی اگر ترتیبش این نباشد."""
        tracks = self._tracks("X", "A", "B")
        tracks[0].trackNumber = 7
        tracks[1].trackNumber = 2

        detail = self._detail("X", "A", tracks)

        assert [t.trackNumber for t in detail.tracks] == [7, 2]

    def test_a_partly_numbered_album_is_left_alone(self):
        """شماره‌گذاریِ جای خالی با جایگاه، ترتیبِ واقعی را به‌هم می‌ریخت."""
        tracks = self._tracks("X", "A", "B")
        tracks[1].trackNumber = 5

        detail = self._detail("X", "A", tracks)

        assert [t.trackNumber for t in detail.tracks] == [None, 5]

    def test_a_single_track_detail_gets_no_position(self):
        """تک‌آهنگ می‌تواند ترکِ پنجمِ آلبومش باشد؛ «۱» زدن رویش دروغ است."""
        detail = self._detail("Solo", "Sote", self._tracks("Solo", "Sote"))

        assert detail.tracks[0].trackNumber is None

    def test_the_album_id_lands_on_the_tracks(self):
        detail = self._detail("X", "A", self._tracks("X", "A", "B"))

        assert [t.albumId for t in detail.tracks] == ["sp:album:1"] * 2

    def test_a_playlist_id_is_not_an_album_id(self):
        """
        ست ساندکلاد و پلی‌لیست هم AlbumDetail برمی‌گردند. شناسه‌شان به‌عنوان
        albumId، گروه‌بندیِ کتابخانه را روی چیزی می‌بست که آلبوم نیست.
        """
        tracks = self._tracks("Sad Hour", "A", "B")

        detail = AlbumDetail(
            id="sp:playlist:9", title="Sad Hour", artist="Spotify", year=2025,
            trackCount=2, source="spotify", sourceUrl="x",
            durationMs=2, tracks=tracks,
        )

        assert [t.albumId for t in detail.tracks] == [None, None]

    def test_a_track_without_an_album_is_left_alone(self):
        detail = self._detail("Solo", "Sote", self._tracks(None, "Sote"))

        assert detail.tracks[0].albumArtist is None

    def test_an_explicit_album_artist_wins(self):
        """اگر روزی سرویسی خودش داد، حدسِ ما نباید رویش بنویسد."""
        tracks = self._tracks("Compilation", "A")
        tracks[0].albumArtist = "Various Artists"

        detail = self._detail("Compilation", "A", tracks)

        assert detail.tracks[0].albumArtist == "Various Artists"

    def test_album_artwork_stamps_on_all_tracks(self):
        """کاور آلبوم باید روی همه‌ی ترک‌ها بنشیند، حتی ترکی که قبلاً کاور سینگل داشته."""
        tracks = self._tracks("FUCK MUSIC", "Mvshreghi", "Mvshreghi")
        tracks[0].artworkUrl = "https://cdn.example.com/single-cover.jpg"
        tracks[1].artworkUrl = None

        detail = AlbumDetail(
            id="sc:playlist:2304743880", title="FUCK MUSIC", artist="Mvshreghi", year=2026,
            trackCount=2, source="soundcloud", sourceUrl="x",
            artworkUrl="https://cdn.example.com/album-cover.jpg",
            releaseType="album",
            durationMs=2, tracks=tracks,
        )

        assert detail.tracks[0].artworkUrl == "https://cdn.example.com/album-cover.jpg"
        assert detail.tracks[1].artworkUrl == "https://cdn.example.com/album-cover.jpg"

    def test_playlist_does_not_stamp_artwork(self):
        """پلی‌لیست نباید کاورِ خودش را روی ترک‌ها بنشاند."""
        tracks = self._tracks("Party", "A", "B")
        tracks[0].artworkUrl = "https://cdn.example.com/track-a.jpg"

        detail = AlbumDetail(
            id="sc:playlist:99", title="Party", artist="User", year=2025,
            trackCount=2, source="soundcloud", sourceUrl="x",
            artworkUrl="https://cdn.example.com/playlist-cover.jpg",
            durationMs=2, tracks=tracks,
        )

        assert detail.tracks[0].artworkUrl == "https://cdn.example.com/track-a.jpg"


class TestReleaseYearParsing:
    """
    سالِ انتشار در ردیفِ *آلبوم* فیلدِ اجباری است، و قبلاً با `int(...)`ِ مستقیم
    خوانده می‌شد. هر پلتفرمی که تاریخِ بدشکل بدهد (یا اصلاً ندهد) یک ValueError
    وسطِ ساختنِ پاسخ می‌انداخت و چون این توابع در حلقه‌ی نتایج صدا زده می‌شوند،
    یک ردیفِ خراب کلِ جستجو را ۵۰۲ می‌کرد — نه فقط همان یک آلبوم را.
    """

    def test_itunes_album_survives_a_malformed_date(self):
        row = {
            "collectionId": 1, "collectionName": "A", "artistName": "B",
            "releaseDate": "N/A", "trackCount": 1,
        }
        assert itunes._album(row).year == 0

    def test_deezer_album_survives_a_malformed_date(self):
        row = {"id": 1, "title": "A", "artist": {"name": "B"}, "release_date": "N/A", "nb_tracks": 1}
        assert deezer._album(row).year == 0

    def test_spotify_album_survives_a_malformed_date(self):
        row = {
            "id": "x", "name": "A", "artists": [{"name": "B"}],
            "release_date": "N/A", "total_tracks": 1, "images": [], "external_urls": {},
        }
        assert spotify._album_head(row).year == 0

    def test_soundcloud_album_survives_a_malformed_date(self):
        row = {
            "id": 1, "title": "A", "user": {"username": "B"},
            "release_date": "garbage", "track_count": 1, "permalink_url": "u",
        }
        assert soundcloud._album(row).year == 0

    def test_real_dates_still_parse(self):
        assert itunes._album(
            {"collectionId": 1, "collectionName": "A", "artistName": "B",
             "releaseDate": "2013-05-17T07:00:00Z", "trackCount": 1}
        ).year == 2013
        assert deezer._album(
            {"id": 1, "title": "A", "artist": {"name": "B"}, "release_date": "2013-05-17", "nb_tracks": 1}
        ).year == 2013
        # ساندکلاد وقتی release_date ندارد، از created_at می‌خواند
        assert soundcloud._album(
            {"id": 1, "title": "A", "user": {"username": "B"},
             "created_at": "2019/05/07 12:00:00 +0000", "track_count": 1, "permalink_url": "u"}
        ).year == 2019

    def test_ytdlp_reads_either_release_year_or_upload_date(self):
        # `release_year` عدد است و `upload_date` رشته‌ی «YYYYMMDD»
        assert ytdlp._year(2019) == 2019
        assert ytdlp._year("20190507") == 2019
        assert ytdlp._year(None) == 0
        assert ytdlp._year("bogus") == 0

    def test_soundcloud_track_carries_release_year(self):
        entry = soundcloud.as_entry(
            {
                "title": "WIND",
                "permalink_url": "https://soundcloud.com/x/wind",
                "created_at": "2026/03/01 12:00:00 +0000",
                "duration": 180000,
            }
        )
        assert entry["release_date"].startswith("2026")
        track = ytdlp._entry_to_track(entry, "soundcloud", None)
        assert track.year == 2026
        assert ytdlp._track_year({}) is None


class TestReleaseType:
    def test_spotify_ep_is_a_short_single(self):
        ep = spotify._album_head({"id": "1", "name": "EP", "album_type": "single", "total_tracks": 4})
        single = spotify._album_head({"id": "2", "name": "A", "album_type": "single", "total_tracks": 1})
        album = spotify._album_head({"id": "3", "name": "LP", "album_type": "album", "total_tracks": 12})

        assert ep.releaseType == "ep"
        assert single.releaseType == "single"
        assert album.releaseType == "album"

    def test_apple_compilation_is_not_own_release(self):
        own = {"collectionId": 1, "collectionName": "Mine", "artistId": 9, "trackCount": 10}
        compilation = {
            "collectionId": 2,
            "collectionName": "Hits",
            "collectionType": "Compilation",
            "artistId": 9,
            "trackCount": 20,
        }
        guest = {
            "collectionId": 3,
            "collectionName": "Various",
            "collectionArtistId": 99,
            "artistId": 9,
            "trackCount": 15,
        }

        assert itunes._own_release(own, 9) is True
        assert itunes._own_release(compilation, 9) is False
        assert itunes._own_release(guest, 9) is False
        assert itunes._release_type(compilation) == "compilation"
        assert itunes._release_type(own) == "album"

    def test_soundcloud_one_track_set_is_a_single(self):
        row = {
            "id": 1,
            "title": "A",
            "user": {"username": "B", "id": 7},
            "track_count": 1,
            "permalink_url": "u",
        }
        album = soundcloud._album(row)
        assert album.releaseType == "single"
        assert album.artistId == "sc:artist:7"

    def test_soundcloud_verified_flag_is_mapped(self):
        row = {
            "id": 1,
            "username": "accia",
            "permalink_url": "https://soundcloud.com/accia",
            "verified": True,
            "track_count": 4,
        }
        assert soundcloud._user(row).verified is True
        row["verified"] = False
        assert soundcloud._user(row).verified is False
