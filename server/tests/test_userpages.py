"""
صفحه‌ی کاربر — کسی که هنرمند نیست و فقط پلی‌لیستِ عمومی دارد.

لینکی که در تلگرام دست‌به‌دست می‌شود اغلب همین است و تا حالا ۴۰۴ می‌گرفت. سه
چیز اینجا قفل می‌شود: تشخیصِ خودِ لینک (که با لینکِ ترک و آلبوم قاطی نشود)،
درآوردنِ پلی‌لیست‌ها از هر پلتفرم، و اینکه صفحه‌ی نبود/خالی هیچ‌وقت به‌جای
پروفایل یک چیزِ بی‌ربط برنگرداند.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import catalog
from app.models import ArtistDetail
from app.providers import deezer, itunes, soundcloud, spotify, ytdlp

# همان شکلی که صفحه‌ی پروفایلِ اسپاتیفای سمت سرور رندر می‌کند: هر پلی‌لیست یک
# لینک با کاور، عنوان، و یک زیرنویسِ لایک — تعداد ترک اصلاً در صفحه نیست.
PROFILE_HTML = """
<html><head>
<meta property="og:type" content="profile"/>
<meta content="Mahan MgN" property="og:title"/>
<meta property="og:image" content="https://i.scdn.co/image/avatar"/>
<meta property="og:url" content="https://open.spotify.com/user/u1"/>
</head><body>
<h2>Public Playlists</h2>
<a draggable="false" class="x" href="/playlist/AAA111"><img loading="lazy" src="https://cdn/cover1.jpg" class="y"/>
  <div><span data-encore-id="text">KLBZ &amp; friends</span><span>1,024 likes</span></div></a>
<a class="x" href="/playlist/BBB222"><img src="https://cdn/cover2.jpg"/>
  <div><span>HAMECHI</span><span></span></div></a>
<a class="x" href="/playlist/AAA111"><img src="https://cdn/cover1.jpg"/><div><span>KLBZ</span></div></a>
</body></html>
"""

EMPTY_SHELL_HTML = """
<html><head><meta property="og:title" content="Spotify - Web Player: Music for everyone"/>
<meta property="og:type" content="website"/></head><body></body></html>
"""


class _FakeResponse:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


class _FakeClient:
    """فقط `.get` دارد — همان چیزی که `spotify.user` صدا می‌زند."""

    def __init__(self, response: _FakeResponse):
        self.response = response
        self.urls: list[str] = []

    async def get(self, url, **kwargs):
        self.urls.append(url)
        return self.response


class TestSpotifyProfileHtml:
    def test_playlists_come_out_in_page_order(self):
        rows = spotify._profile_playlists(PROFILE_HTML, "Mahan MgN")

        assert [p.id for p in rows] == ["sp:playlist:AAA111", "sp:playlist:BBB222"]
        assert rows[0].sourceUrl == "https://open.spotify.com/playlist/AAA111"
        assert rows[0].artworkUrl == "https://cdn/cover1.jpg"
        assert rows[0].owner == "Mahan MgN"

    def test_html_entities_in_the_title_are_decoded(self):
        assert spotify._profile_playlists(PROFILE_HTML, "x")[0].title == "KLBZ & friends"

    def test_the_like_count_never_becomes_the_track_count(self):
        """
        صفحه‌ی پروفایل تعداد ترک را نمی‌دهد و زیرنویسِ کارت تعدادِ لایک است.
        صفر یعنی «نمی‌دانیم» و فرانت جای عددِ دروغ چیزی نشان نمی‌دهد.
        """
        assert [p.trackCount for p in spotify._profile_playlists(PROFILE_HTML, "x")] == [0, 0]

    def test_a_page_without_playlists_is_not_an_error(self):
        assert spotify._profile_playlists(EMPTY_SHELL_HTML, "x") == []


class TestSpotifyUserPage:
    def test_a_full_profile_becomes_a_user_page(self):
        client = _FakeClient(_FakeResponse(200, PROFILE_HTML))

        detail = asyncio.run(spotify.user(client, "u1"))

        assert detail is not None
        assert detail.kind == "user"
        assert detail.id == "sp:user:u1"
        assert detail.name == "Mahan MgN"
        assert detail.artworkUrl == "https://i.scdn.co/image/avatar"
        assert [p.title for p in detail.playlists] == ["KLBZ & friends", "HAMECHI"]
        # کاربر انتشاری ندارد — این دو باید خالی بمانند وگرنه صفحه ادعای
        # دیسکوگرافی می‌کند
        assert detail.topTracks == [] and detail.albums == []

    def test_a_missing_user_is_none_not_an_exception(self):
        assert asyncio.run(spotify.user(_FakeClient(_FakeResponse(404, "")), "nope")) is None

    def test_the_empty_web_player_shell_is_not_a_user(self):
        """
        اسپاتیفای برای بعضی شناسه‌های ناموجود ۲۰۰ می‌دهد و پوسته‌ی وب‌پلیر را
        برمی‌گرداند. بدون شرطِ og:type، یک صفحه‌ی بی‌نام و بی‌محتوا به‌عنوان
        «کاربر» باز می‌شد.
        """
        client = _FakeClient(_FakeResponse(200, EMPTY_SHELL_HTML))

        assert asyncio.run(spotify.user(client, "u1")) is None

    def test_no_api_key_is_needed(self, monkeypatch):
        """
        برخلاف بقیه‌ی اسپاتیفای، این مسیر از Web API نمی‌آید (آن اندپوینت‌ها
        روی توکنِ بدون‌کاربر ۴۰۳ می‌دهند) — پس نبودِ کلید نباید صفحه را ببندد.
        """
        monkeypatch.setattr(spotify, "enabled", lambda: False)
        monkeypatch.setattr(
            spotify, "_access_token", lambda *_: pytest.fail("نباید توکن بگیرد")
        )
        client = _FakeClient(_FakeResponse(200, PROFILE_HTML))

        assert asyncio.run(spotify.user(client, "u1")) is not None


class TestDeezerUserPage:
    def _playlists(self, *rows) -> dict:
        return {"data": list(rows)}

    def _row(self, pid: int, title: str, **extra) -> dict:
        return {
            "id": pid,
            "title": title,
            "nb_tracks": 12,
            "public": True,
            "link": f"https://www.deezer.com/playlist/{pid}",
            **extra,
        }

    def _patch(self, monkeypatch, head: dict, playlists: dict):
        async def fake_get(client, path, **params):
            return head if path.endswith(str(head.get("id"))) else playlists

        monkeypatch.setattr(deezer, "_get", fake_get)

    def test_public_playlists_become_the_page(self, monkeypatch):
        head = {"id": 2529, "name": "dadbond", "picture_big": "http://img", "link": "http://dz/2529"}
        self._patch(monkeypatch, head, self._playlists(self._row(1, "SKI"), self._row(2, "MIX")))

        detail = asyncio.run(deezer.user(None, "2529"))

        assert detail is not None
        assert (detail.kind, detail.id, detail.name) == ("user", "deezer:user:2529", "dadbond")
        assert [p.title for p in detail.playlists] == ["SKI", "MIX"]
        assert detail.playlists[0].owner == "dadbond"
        assert detail.subtitle == "2 پلی‌لیست"

    def test_the_loved_tracks_pseudo_playlist_is_dropped(self, monkeypatch):
        """
        «آهنگ‌های محبوب» در همین لیست می‌آید ولی صفحه‌ی قابل‌بازکردن ندارد —
        کارتش فقط به بن‌بست می‌رسید.
        """
        head = {"id": 5, "name": "x", "link": "http://dz/5"}
        self._patch(
            monkeypatch,
            head,
            self._playlists(
                self._row(1, "Loved Tracks", is_loved_track=True),
                self._row(2, "Real one"),
                self._row(3, "Hidden", public=False),
            ),
        )

        detail = asyncio.run(deezer.user(None, "5"))

        assert [p.title for p in detail.playlists] == ["Real one"]

    def test_a_missing_user_is_none(self, monkeypatch):
        async def boom(client, path, **params):
            raise httpx.HTTPError("no data")

        monkeypatch.setattr(deezer, "_get", boom)

        assert asyncio.run(deezer.user(None, "0")) is None

    def test_a_broken_playlist_call_still_opens_the_page(self, monkeypatch):
        """سرِ صفحه هست؛ نبودِ لیست نباید کل پروفایل را ۵۰۲ کند."""

        async def fake_get(client, path, **params):
            if path.endswith("/playlists"):
                raise httpx.HTTPError("down")
            return {"id": 5, "name": "x", "link": "http://dz/5"}

        monkeypatch.setattr(deezer, "_get", fake_get)

        detail = asyncio.run(deezer.user(None, "5"))

        assert detail is not None and detail.playlists == []


class TestSoundcloudUserPlaylists:
    def _row(self, pid: int, title: str, **extra) -> dict:
        return {
            "id": pid,
            "title": title,
            "track_count": 10,
            "permalink_url": f"https://soundcloud.com/x/sets/{title}",
            "user": {"username": "accia"},
            **extra,
        }

    def test_sets_become_playlists(self, monkeypatch):
        monkeypatch.setattr(
            soundcloud, "_collection", lambda path, **kw: [self._row(1, "PorrProgg")]
        )

        rows = soundcloud.user_playlists("1")

        assert [(p.id, p.trackCount, p.owner) for p in rows] == [("sc:playlist:1", 10, "accia")]

    def test_albums_and_empty_sets_stay_out(self, monkeypatch):
        """
        آلبوم از `user_albums` می‌آید و دو بار نشان دادنش صفحه را تکراری
        می‌کند؛ ستِ خالی هم کارتی است که باز کردنش به صفحه‌ی خالی می‌رسد.
        """
        monkeypatch.setattr(
            soundcloud,
            "_collection",
            lambda path, **kw: [
                self._row(1, "Album", is_album=True),
                self._row(2, "Empty", track_count=0),
                self._row(3, "Keep"),
            ],
        )

        assert [p.title for p in soundcloud.user_playlists("1")] == ["Keep"]

    def test_a_user_with_no_tracks_is_a_user_not_an_artist(self):
        """ساندکلاد بین هنرمند و شنونده تفکیک ندارد؛ تنها سیگنال، خودِ داده است."""
        listener = soundcloud._user(
            {"id": 1, "username": "accia", "permalink_url": "http://sc/accia", "track_count": 0}
        )
        uploader = soundcloud._user(
            {"id": 2, "username": "Dorcci", "permalink_url": "http://sc/d", "track_count": 12}
        )

        assert (listener.kind, uploader.kind) == ("user", "artist")


class TestUserUrlParsing:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://open.spotify.com/user/31qajthebaf2bgwqnanhyrdpplte?si=ec90", ("user", "31qajthebaf2bgwqnanhyrdpplte")),
            ("https://open.spotify.com/intl-fa/user/mahan.mgn", ("user", "mahan.mgn")),
            ("https://www.deezer.com/en/profile/2529", ("user", "2529")),
            ("https://www.deezer.com/profile/5", ("user", "5")),
        ],
    )
    def test_profile_links_are_recognised(self, url, expected):
        parsed = spotify.parse_url(url) or deezer.parse_url(url)
        assert parsed == expected

    def test_a_playlist_link_is_still_a_playlist(self):
        assert spotify.parse_url("https://open.spotify.com/playlist/AAA") == ("playlist", "AAA")

    @pytest.mark.parametrize(
        "url,is_profile",
        [
            ("https://soundcloud.com/accia", True),
            ("https://m.soundcloud.com/accia/", True),
            ("https://soundcloud.com/accia?ref=x", True),
            # ترک و ست بخشِ بیشتری دارند و باید به مسیرِ آلبوم بروند
            ("https://soundcloud.com/dorcci/gonah", False),
            ("https://soundcloud.com/accia/sets/porrprogg", False),
        ],
    )
    def test_soundcloud_profiles_are_told_apart_from_tracks(self, url, is_profile):
        assert bool(ytdlp.SOUNDCLOUD_PROFILE_URL.match(url)) is is_profile

    @pytest.mark.parametrize(
        "url,is_channel",
        [
            ("https://www.youtube.com/@NoCopyrightSounds", True),
            ("https://www.youtube.com/@NoCopyrightSounds/playlists", True),
            ("https://www.youtube.com/channel/UC_aEa8K-EOJ3D6gOs7HcyNg", True),
            ("https://www.youtube.com/user/someone", True),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
            ("https://www.youtube.com/playlist?list=PL123", False),
        ],
    )
    def test_youtube_channels_are_told_apart_from_videos(self, url, is_channel):
        assert bool(ytdlp.CHANNEL_URL.search(url)) is is_channel


class TestUserPageRouting:
    """
    لینکِ پروفایل باید به `resolve_artist` برسد و به هر پلتفرمِ خودش برود —
    و به `resolve_ref` (که آلبوم می‌سازد) نرسد.
    """

    @pytest.fixture
    def routes(self, monkeypatch):
        seen: list[str] = []

        def detail(name: str) -> ArtistDetail:
            return ArtistDetail(
                id=f"x:user:{name}", name=name, source="apple", sourceUrl="x",
                subtitle="", kind="user",
            )

        async def spot(client, ident):
            seen.append(f"spotify:{ident}")
            return detail("spotify")

        async def deez(client, ident):
            seen.append(f"deezer:{ident}")
            return detail("deezer")

        def cloud(url):
            seen.append(f"soundcloud:{url}")
            return detail("soundcloud")

        def tube(url):
            seen.append(f"youtube:{url}")
            return detail("youtube")

        monkeypatch.setattr(spotify, "user", spot)
        monkeypatch.setattr(deezer, "user", deez)
        monkeypatch.setattr(ytdlp, "soundcloud_user", cloud)
        monkeypatch.setattr(ytdlp, "youtube_channel", tube)
        # هیچ‌کدام از این‌ها نباید صدا زده شوند
        monkeypatch.setattr(itunes, "artist", lambda *a: pytest.fail("اپل پروفایل ندارد"))
        return seen

    @pytest.mark.parametrize(
        "ref,expected",
        [
            ("https://open.spotify.com/user/u1?si=x", "spotify:u1"),
            ("sp:user:u1", "spotify:u1"),
            ("https://www.deezer.com/en/profile/2529", "deezer:2529"),
            ("deezer:user:2529", "deezer:2529"),
            ("https://soundcloud.com/accia", "soundcloud:https://soundcloud.com/accia"),
            (
                "https://www.youtube.com/@NCS/playlists",
                "youtube:https://www.youtube.com/@NCS/playlists",
            ),
        ],
    )
    def test_every_platform_routes_to_its_own_user_page(self, routes, ref, expected):
        detail = asyncio.run(catalog.resolve_artist(None, ref))

        assert routes == [expected]
        assert detail is not None and detail.kind == "user"

    def test_a_spotify_user_link_is_not_treated_as_an_album(self, monkeypatch):
        """
        بدون این، مسیرِ بی‌کلیدِ `resolve_ref` عنوانِ oEmbed را در اپل/دیزر
        می‌گشت و یک آلبومِ بی‌ربط به‌جای پروفایل برمی‌گرداند.
        """
        monkeypatch.setattr(spotify, "enabled", lambda: False)
        monkeypatch.setattr(
            catalog, "_spotify_fallback", lambda *a: pytest.fail("نباید حدس بزند")
        )

        assert asyncio.run(catalog.resolve_ref(None, "https://open.spotify.com/user/u1")) is None

    def test_a_soundcloud_track_link_never_reaches_the_profile_route(self, routes):
        assert asyncio.run(catalog.resolve_artist(None, "https://soundcloud.com/dorcci/gonah")) is None
        assert routes == []


class TestArtistRouting:
    def test_apple_and_spotify_aliases_in_id_are_recognized(self, monkeypatch):
        called = []

        def dummy_detail(source: str):
            return ArtistDetail(
                id=f"{source}:artist:1", name="Artist", source=source, sourceUrl="x",
                subtitle="", kind="artist",
            )

        async def fake_itunes_artist(client, ident):
            called.append(f"itunes:{ident}")
            return dummy_detail("apple")

        async def fake_spotify_artist(client, ident):
            called.append(f"spotify:{ident}")
            return dummy_detail("spotify")

        monkeypatch.setattr(itunes, "artist", fake_itunes_artist)
        monkeypatch.setattr(spotify, "artist", fake_spotify_artist)
        monkeypatch.setattr(spotify, "enabled", lambda: True)

        # apple:artist:123 should route to itunes
        res_apple = asyncio.run(catalog.resolve_artist(None, "apple:artist:123"))
        assert res_apple is not None
        assert called[-1] == "itunes:123"

        # spotify:artist:456 should route to spotify
        res_spotify = asyncio.run(catalog.resolve_artist(None, "spotify:artist:456"))
        assert res_spotify is not None
        assert called[-1] == "spotify:456"

    def test_spotify_artist_without_key_falls_back_from_id(self, monkeypatch):
        monkeypatch.setattr(spotify, "enabled", lambda: False)
        called = []

        async def fake_fallback(client, url):
            called.append(url)
            return ArtistDetail(
                id="sp:artist:fallback", name="Fallback Artist", source="spotify",
                sourceUrl=url, subtitle="", kind="artist",
            )

        monkeypatch.setattr(catalog, "_spotify_artist_fallback", fake_fallback)

        res = asyncio.run(catalog.resolve_artist(None, "sp:artist:abc123xyz"))
        assert res is not None
        assert called == ["https://open.spotify.com/artist/abc123xyz"]

    def test_soundcloud_tab_urls_are_cleaned_for_artist_page(self, monkeypatch):
        called = []

        def fake_sc_user(url):
            called.append(url)
            return ArtistDetail(
                id="sc:artist:1", name="Dorcci", source="soundcloud",
                sourceUrl=url, subtitle="", kind="artist",
            )

        monkeypatch.setattr(ytdlp, "soundcloud_user", fake_sc_user)

        res = asyncio.run(catalog.resolve_artist(None, "https://soundcloud.com/dorcci/tracks"))
        assert res is not None
        assert called == ["https://soundcloud.com/dorcci"]
