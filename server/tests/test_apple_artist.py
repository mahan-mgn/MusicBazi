"""
عکس پروفایلِ هنرمند در اپل‌موزیک.

iTunes Search API این عکس را ندارد، پس از `og:image` صفحه‌ی وبِ هنرمند
برمی‌داریم. آن صفحه ۴۰۰ کیلوبایت است و در هر جستجو هشت‌تایش گرفته می‌شود —
پس آنچه اینجا تست می‌شود بیشتر از پارس کردن است: زود بستنِ وصل، کش، و اینکه
افتادنِ این مسیر نباید نتیجه‌ی جستجو را با خودش پایین بکشد.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.providers import itunes

ARTIST_ID = "1641976333"
CDN = "https://is1-ssl.mzstatic.com/image/thumb/Features221/v4/e0/05/dc/e005dc/mzl.aqdcmfwv.jpg"
SQUARE = f"{CDN}/{itunes.DISPLAY}x{itunes.DISPLAY}cc.jpg"

# لوگوی خودِ اپل‌موزیک — چیزی که هنرمندِ بی‌عکس می‌گیرد
LOGO = "https://music.apple.com/assets/meta/apple-music.png"


def _page(og: str | None) -> str:
    tag = f'<meta property="og:image" content="{og}">' if og else ""
    return f"<html><head><title>x</title>{tag}</head>"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _serving(html: str, status: int = 200, calls: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(status, html=html)

    return handler


@pytest.fixture(autouse=True)
def _clean_cache():
    """کش ماژول‌سطحی است؛ بدون این، ترتیبِ تست‌ها روی نتیجه اثر می‌گذاشت."""
    itunes._image_cache.clear()
    yield
    itunes._image_cache.clear()


def _images(handler, ids: list[str]) -> dict[str, str | None]:
    async def run():
        async with _client(handler) as client:
            return await itunes.artist_images(client, ids)

    return asyncio.run(run())


class TestParsing:
    def test_the_wide_link_preview_becomes_a_square_avatar(self):
        """
        `og:image` برشِ ۱۲۰۰×۶۳۰ی پیش‌نمایشِ لینک است. کارتِ هنرمند گرد است و آن
        نسبت را کشیده نشان می‌داد؛ `cc` همان تصویر را مربع می‌برد.
        """
        page = _page(f"{CDN}/1200x630cw.png")

        assert _images(_serving(page), [ARTIST_ID]) == {ARTIST_ID: SQUARE}

    def test_the_generic_apple_music_logo_is_not_a_profile_picture(self):
        """
        هنرمندی که عکس ندارد لوگوی اپل‌موزیک را می‌گیرد. آن لوگو روی هر کارت
        یکی است و از حرفِ اولِ نام هم کم‌تر می‌گوید — پس کارت به همان حالتِ
        قبلی برمی‌گردد.
        """
        assert _images(_serving(_page(LOGO)), [ARTIST_ID]) == {ARTIST_ID: None}

    def test_attribute_order_is_not_assumed(self):
        html = f'<html><head><meta content="{CDN}/1200x630cw.png" property="og:image"></head>'

        assert _images(_serving(html), [ARTIST_ID]) == {ARTIST_ID: SQUARE}

    def test_a_page_without_the_tag_leaves_the_card_as_it_was(self):
        assert _images(_serving(_page(None)), [ARTIST_ID]) == {ARTIST_ID: None}

    def test_a_missing_artist_page_is_not_an_error(self):
        assert _images(_serving(_page(None), status=404), [ARTIST_ID]) == {ARTIST_ID: None}

    def test_the_connection_closes_as_soon_as_the_tag_is_found(self):
        """
        صفحه‌ی واقعی ۴۰۰ کیلوبایت است و `og:image` در چند کیلوبایتِ اول می‌آید.
        بدون بستنِ زودهنگام، هر جستجو هشت صفحه‌ی کامل را می‌کشید.
        """
        head = _page(f"{CDN}/1200x630cw.png").encode()
        pulled = 0

        async def body():
            nonlocal pulled
            pulled += 1
            yield head
            for _ in range(50):
                pulled += 1
                yield b"x" * 8192

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body(), headers={"content-type": "text/html"})

        assert _images(handler, [ARTIST_ID]) == {ARTIST_ID: SQUARE}
        assert pulled == 1

    def test_a_page_that_never_has_the_tag_stops_at_the_cap(self):
        """اگر تگ اصلاً نیاید، سقف جلوی خواندنِ کلِ صفحه را می‌گیرد."""
        chunk = 8192
        pulled = 0

        async def body():
            nonlocal pulled
            for _ in range(200):
                pulled += 1
                yield b"x" * chunk

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body(), headers={"content-type": "text/html"})

        assert _images(handler, [ARTIST_ID]) == {ARTIST_ID: None}
        assert pulled <= itunes._HEAD_LIMIT // chunk + 1


class TestCaching:
    def test_the_same_artist_is_fetched_once(self):
        calls: list[str] = []
        handler = _serving(_page(f"{CDN}/1200x630cw.png"), calls=calls)

        _images(handler, [ARTIST_ID])
        again = _images(handler, [ARTIST_ID, ARTIST_ID])

        assert again == {ARTIST_ID: SQUARE}
        assert len(calls) == 1

    def test_having_no_picture_is_remembered_too(self):
        """وگرنه جستجوی دوباره‌ی همان نام، همان هشت صفحه را دوباره می‌گرفت."""
        calls: list[str] = []
        handler = _serving(_page(LOGO), calls=calls)

        _images(handler, [ARTIST_ID])
        _images(handler, [ARTIST_ID])

        assert len(calls) == 1

    def test_a_network_failure_is_retried_next_time(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if len(calls) == 1:
                raise httpx.ConnectError("down")
            return httpx.Response(200, html=_page(f"{CDN}/1200x630cw.png"))

        assert _images(handler, [ARTIST_ID]) == {ARTIST_ID: None}
        assert _images(handler, [ARTIST_ID]) == {ARTIST_ID: SQUARE}


class TestSearchAndArtistPage:
    """عکس باید به همان هنرمندی بچسبد که شناسه‌اش را داده — نه به ردیفِ بغلی."""

    @staticmethod
    def _handler(rows: dict[str, list[dict]], pages: dict[str, str]):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "itunes.apple.com" in url:
                entity = request.url.params.get("entity", "")
                return httpx.Response(200, json={"results": rows.get(entity, [])})
            artist_id = url.rstrip("/").rsplit("/", 1)[-1]
            return httpx.Response(200, html=pages.get(artist_id, _page(None)))

        return handler

    def test_search_matches_each_picture_to_its_own_artist(self):
        rows = {
            "musicArtist": [
                {"artistId": 1, "artistName": "یکی", "primaryGenreName": "Pop"},
                {"artistId": 2, "artistName": "دیگری", "primaryGenreName": "Rap"},
            ]
        }
        pages = {"1": _page(f"{CDN}/1200x630cw.png"), "2": _page(LOGO)}

        async def run():
            async with _client(self._handler(rows, pages)) as client:
                return await itunes.search(client, "x")

        results = asyncio.run(run())

        assert [(a.name, a.artworkUrl) for a in results.artists] == [
            ("یکی", SQUARE),
            ("دیگری", None),
        ]

    def test_the_artist_page_prefers_the_real_picture_over_an_album_cover(self):
        cover = "https://is1-ssl.mzstatic.com/image/thumb/Music/x/100x100bb.jpg"
        rows = {
            "album": [
                {"wrapperType": "artist", "artistId": 1, "artistName": "یکی"},
                {
                    "wrapperType": "collection", "collectionId": 9, "collectionName": "A",
                    "artistName": "یکی", "artworkUrl100": cover, "releaseDate": "2025-01-01T00:00:00Z",
                },
            ],
            "song": [],
        }

        async def run(page: str):
            itunes._image_cache.clear()
            async with _client(self._handler(rows, {"1": page})) as client:
                return await itunes.artist(client, "1")

        with_picture = asyncio.run(run(_page(f"{CDN}/1200x630cw.png")))
        without = asyncio.run(run(_page(LOGO)))

        assert with_picture.artworkUrl == SQUARE
        # بی‌عکس، همان رفتارِ قبلی: کاورِ تازه‌ترین آلبوم
        assert without.artworkUrl.endswith("/500x500bb.jpg")

    def test_artist_without_albums_falls_back_to_songs_lookup(self):
        rows = {
            "album": [],
            "song": [
                {"wrapperType": "artist", "artistId": 5, "artistName": "هنرمند تک‌آهنگی"},
                {
                    "wrapperType": "track", "kind": "song", "trackId": 501,
                    "trackName": "Single Song", "artistName": "هنرمند تک‌آهنگی",
                },
            ],
        }

        async def run():
            itunes._image_cache.clear()
            async with _client(self._handler(rows, {"5": _page(None)})) as client:
                return await itunes.artist(client, "5")

        detail = asyncio.run(run())
        assert detail is not None
        assert detail.name == "هنرمند تک‌آهنگی"
        assert len(detail.topTracks) == 1
        assert detail.topTracks[0].title == "Single Song"

    def test_parse_url_supports_various_apple_music_artist_urls(self):
        urls = [
            ("https://music.apple.com/us/artist/taylor-swift/159260351", "159260351"),
            ("https://music.apple.com/artist/taylor-swift/159260351", "159260351"),
            ("https://music.apple.com/us/artist/159260351", "159260351"),
            ("https://music.apple.com/artist/159260351", "159260351"),
            ("https://music.apple.com/us/artist/taylor-swift/159260351?uo=4", "159260351"),
        ]
        for url, expected_id in urls:
            parsed = itunes.parse_url(url)
            assert parsed == ("artist", expected_id), f"Failed to parse {url}"
