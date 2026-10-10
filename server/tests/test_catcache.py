"""کشِ کاتالوگ — جستجو و مرور در حالتِ اینترانت."""

from __future__ import annotations

import pytest

from app import catcache
from app.models import AlbumDetail, ArtistDetail, SearchResults, Track


def _track(ident: str, title: str, artist: str, source: str = "apple") -> Track:
    return Track(
        id=ident,
        title=title,
        artist=artist,
        album="Mard-E Tanha",
        durationMs=180_000,
        source=source,
        sourceUrl=f"https://example.com/{ident}",
    )


@pytest.fixture
def cache(fresh_db):
    return fresh_db


def test_the_same_query_comes_back_exactly_as_it_was(cache):
    """
    اگر کاربر دیروز همین را جستجو کرده، امروز باید همان چیدمان را ببیند.

    بازسازیِ تقریبی از ردیف‌های تکی هم جواب می‌داد، ولی «آن آهنگی که بالا بود»
    جای دیگری می‌نشست — و کاربر فکر می‌کرد نتیجه عوض شده.
    """
    results = SearchResults(query="farhad", tracks=[_track("itunes:track:1", "Jomeh", "Farhad")])
    catcache.remember_search("farhad", results)

    again = catcache.search("farhad")
    assert [t.id for t in again.tracks] == ["itunes:track:1"]


def test_query_matching_ignores_case_and_extra_spaces(cache):
    catcache.remember_search(
        "Farhad Mehrad", SearchResults(query="x", tracks=[_track("itunes:track:1", "a", "b")])
    )
    assert catcache.search("  farhad   mehrad ").tracks


def test_a_query_never_typed_before_still_finds_cached_rows(cache):
    """
    مهم‌ترین کارِ این ماژول.

    بدونِ جدولِ ردیف‌های تکی، حالتِ اینترانت فقط عیناً همان عبارت‌های قبلی را
    جواب می‌داد — یعنی عملاً بی‌فایده. اینجا ترک از جستجوی «farhad» آمده و با
    عبارتِ کاملاً دیگری («jomeh») پیدا می‌شود.
    """
    catcache.remember_search(
        "farhad", SearchResults(query="farhad", tracks=[_track("itunes:track:1", "Jomeh", "Farhad")])
    )
    found = catcache.search("jomeh")
    assert [t.id for t in found.tracks] == ["itunes:track:1"]


def test_an_album_page_feeds_the_offline_search_too(cache, album):
    """
    ترک‌هایی که فقط داخلِ یک صفحه‌ی آلبوم دیده شده‌اند هم باید قابلِ جستجو باشند.

    اینها معمولاً کامل‌ترین متادیتا را دارند (شماره‌ی ترک، سال) و اگر فقط
    نتیجه‌ی جستجو کش می‌شد، همه‌شان از حافظه بیرون می‌ماندند.
    """
    detail = AlbumDetail(
        **album.model_dump(),
        durationMs=600_000,
        tracks=[_track("itunes:track:7", "Shabaneh", "Farhad")],
    )
    catcache.remember_ref(album.id, "album", detail)
    assert [t.id for t in catcache.search("shabaneh").tracks] == ["itunes:track:7"]


def test_an_album_is_findable_by_both_link_and_internal_id(cache, album):
    """
    یک‌بار با لینکِ کامل باز شده، دفعه‌ی بعد از داخلِ نتیجه‌ی جستجو با شناسه.

    بدونِ ذخیره زیرِ هر دو کلید، دومی در حالتِ اینترانت ۵۰۳ می‌گرفت — با
    اینکه همان صفحه دقیقاً در دیتابیس بود.
    """
    detail = AlbumDetail(**album.model_dump(), durationMs=0, tracks=[])
    catcache.remember_ref("https://www.deezer.com/album/1", "album", detail)

    assert catcache.album("https://www.deezer.com/album/1") is not None
    assert catcache.album(album.id) is not None


def test_an_artist_page_survives_for_offline_browsing(cache, artist):
    detail = ArtistDetail(**artist.model_dump(), topTracks=[_track("deezer:track:3", "Vahdat", "F")])
    catcache.remember_ref(artist.id, "artist", detail)

    cached = catcache.artist(artist.id)
    assert cached is not None
    assert [t.id for t in cached.topTracks] == ["deezer:track:3"]


def test_a_page_never_visited_is_simply_absent(cache):
    """کشِ خالی باید `None` بدهد تا صداکننده ۵۰۳ِ صریح برگرداند، نه صفحه‌ی خالی."""
    assert catcache.album("itunes:album:404") is None
    assert catcache.artist("itunes:artist:404") is None


def test_results_are_interleaved_across_sources(cache):
    """
    بدونِ چیدنِ نوبتی، ترتیبِ «آخرین‌بارِ دیده‌شده» کلِ صفحه‌ی اول را از یک
    پلتفرم پر می‌کرد — فقط چون آخرین جستجو آنجا بوده.
    """
    catcache.remember_search(
        "seed",
        SearchResults(
            query="seed",
            tracks=[
                _track("itunes:track:1", "gol", "a", "apple"),
                _track("itunes:track:2", "gol", "b", "apple"),
                _track("deezer:track:3", "gol", "c", "deezer"),
            ],
        ),
    )
    sources = [t.source for t in catcache.search("gol").tracks]
    # دو منبع داریم، پس دومین ردیف نباید هم‌منبعِ اولی باشد
    assert sources[0] != sources[1]


def test_empty_results_do_not_overwrite_cache(cache):
    results = SearchResults(query="q", tracks=[_track("yt:track:1", "song", "artist", "youtube")])
    catcache.remember_search("q", results)

    empty = SearchResults(query="q")
    catcache.remember_search("q", empty)

    again = catcache.search("q")
    assert len(again.tracks) == 1
    assert again.tracks[0].id == "yt:track:1"


def test_degraded_partial_search_does_not_overwrite_rich_cache(cache):
    rich = SearchResults(
        query="rock",
        tracks=[
            _track(f"itunes:track:{i}", f"song{i}", "artist", "apple") for i in range(5)
        ] + [
            _track(f"ytm:track:{i}", f"song{i}", "artist", "youtube_music") for i in range(5)
        ],
    )
    catcache.remember_search("rock", rich)

    # شبیه‌سازی قطعی یک پرووایدر در جستجوی بعدی (مثلاً فقط ۲ ترک برگشته)
    degraded = SearchResults(
        query="rock",
        tracks=[_track("itunes:track:0", "song0", "artist", "apple")],
    )
    catcache.remember_search("rock", degraded)

    again = catcache.search("rock")
    # کش غنی ۱۰ ترکه دست‌نخورده مانده است
    assert len(again.tracks) == 10



def test_a_downloaded_track_shows_up_even_if_it_was_never_searched(cache, track):
    """
    ترکی که از مسیرِ لینکِ مستقیم دانلود شده هیچ‌وقت در هیچ جستجویی نبوده.

    ولی فایلش روی دیسک است — یعنی تنها ردیفی در نتیجه‌ی آفلاین که دکمه‌ی
    پخشش قطعاً کار می‌کند. جا انداختنش بدترین حذفِ ممکن بود.
    """
    cache.insert_job("job-1", track, "320", "ready", 1.0)
    cache.update_job("job-1", path="/tmp/x.mp3", bytes=1024)

    assert [t.id for t in catcache.search("mard-e tanha").tracks] == [track.id]
