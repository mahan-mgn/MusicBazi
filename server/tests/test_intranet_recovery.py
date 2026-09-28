"""
بیرون آمدن از حالتِ اینترانت.

این فایل از یک باگِ واقعی درآمده: پروب روی `itunes.apple.com` و
`api.deezer.com` بود — دو دامنه‌ای که از آی‌پیِ ایران تحریم و geo-block شده‌اند.
برنامه «قطع» اعلام می‌کرد در حالی که اینترنت سالم بود، و چون در آن حالت دیگر
هیچ‌وقت مسیرِ زنده را امتحان نمی‌کرد، راهی برای فهمیدنِ اشتباهش نداشت. کاربر
تا ابد در حالتِ اینترانت می‌ماند.

پس آنچه اینجا آزموده می‌شود «آیا تشخیص درست است» نیست — آن هیچ‌وقت صددرصد
نمی‌شود — بلکه این است که *تشخیصِ اشتباه دیگر نمی‌تواند حبس کند*.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import catalog, reach
from app.main import app
from app.models import SearchResults, Track

LIVE = Track(
    id="itunes:track:live",
    title="Only From The Live Catalog",
    artist="Someone",
    durationMs=1000,
    source="apple",
    sourceUrl="https://example.com/live",
)


@pytest.fixture
def client(fresh_db, monkeypatch):
    # پروبِ خالی یعنی حلقه‌ی پس‌زمینه هیچ درخواستِ واقعی نمی‌زند؛ هر تست خودش
    # وضعیت را دقیقاً همان‌طور که می‌خواهد می‌چیند
    monkeypatch.setattr(reach, "REACH_PROBES", ())
    with TestClient(app) as c:
        yield c


def _pretend_offline() -> None:
    """حالتِ اینترانت، با جوابی به‌قدرِ کافی کهنه که `verify` دوباره بپرسد."""
    reach._state.online = False
    reach._state.strikes = reach.REACH_STRIKES
    reach._state.checked_at = time.time() - 3600


def _probe_says(online: bool, monkeypatch) -> None:
    async def fake_check() -> bool:
        reach._state.online = online
        reach._state.checked_at = time.time()
        return online

    monkeypatch.setattr(reach, "check", fake_check)


def test_a_wrong_offline_verdict_is_corrected_by_the_next_search(client, monkeypatch):
    """
    مهم‌ترین تستِ این فایل.

    کش چیزی ندارد و برنامه فکر می‌کند قطع است — ولی در واقع نیست. باید همان
    درخواست از مسیرِ زنده جواب بگیرد، و برنامه از حالتِ اینترانت بیرون بیاید.
    """
    _pretend_offline()
    _probe_says(True, monkeypatch)

    async def fake_search(http, query):
        return SearchResults(query=query, tracks=[LIVE])

    monkeypatch.setattr(catalog, "search", fake_search)

    body = client.get("/api/search", params={"q": "چیزی که هرگز کش نشده"}).json()
    assert [t["title"] for t in body["tracks"]] == [LIVE.title]
    assert reach.online() is True  # خودش را تصحیح کرد


def test_a_real_blackout_still_answers_from_cache_without_a_pointless_wait(
    client, monkeypatch
):
    """
    وقتی واقعاً قطع است، دریچه‌ی فرار نباید به یک تلاشِ زنده‌ی سی‌ثانیه‌ای تبدیل
    شود. پروب می‌گوید هنوز قطع است، پس همان نتیجه‌ی خالیِ کش برمی‌گردد.
    """
    _pretend_offline()
    _probe_says(False, monkeypatch)

    async def must_not_run(http, query):
        raise AssertionError("در قطعیِ واقعی نباید سراغِ کاتالوگ برود")

    monkeypatch.setattr(catalog, "search", must_not_run)

    res = client.get("/api/search", params={"q": "هیچ‌جا نیست"})
    assert res.status_code == 200
    assert res.json()["tracks"] == []
    assert reach.online() is False


def test_a_cache_hit_does_not_pay_for_an_extra_probe(client, monkeypatch, track):
    """
    کشی که جواب دارد، جواب است.

    اگر هر جستجوی آفلاین یک پروب می‌زد، مرورِ کتابخانه در حالتِ اینترانت
    به‌ازای هر عبارت چند ثانیه کند می‌شد — بی‌آنکه چیزی عوض شود.
    """
    from app import catcache

    catcache.remember_search("farhad", SearchResults(query="farhad", tracks=[track]))
    _pretend_offline()

    async def must_not_probe() -> bool:
        raise AssertionError("کش جواب داشت؛ پروبِ اضافه لازم نبود")

    monkeypatch.setattr(reach, "check", must_not_probe)

    body = client.get("/api/search", params={"q": "farhad"}).json()
    assert [t["id"] for t in body["tracks"]] == [track.id]


def test_an_uncached_album_retries_live_before_giving_up(client, monkeypatch, album):
    """صفحه‌ی آلبوم هم همان دریچه را دارد — وگرنه ۵۰۳ِ دائمی می‌گرفت."""
    from app.models import AlbumDetail

    _pretend_offline()
    _probe_says(True, monkeypatch)

    detail = AlbumDetail(**album.model_dump(), durationMs=0, tracks=[LIVE])

    async def fake_ref(http, ref):
        return detail

    monkeypatch.setattr(catalog, "resolve_ref", fake_ref)

    res = client.get("/api/album", params={"ref": album.id})
    assert res.status_code == 200
    assert res.json()["title"] == album.title


def test_an_uncached_album_during_a_real_blackout_says_so(client, monkeypatch):
    """و وقتی واقعاً قطع است، پیامِ صریحِ اینترانت — نه ۵۰۲ِ گنگ."""
    _pretend_offline()
    _probe_says(False, monkeypatch)

    res = client.get("/api/album", params={"ref": "itunes:album:never-seen"})
    assert res.status_code == 503


def test_an_online_artist_visit_is_always_fetched_fresh(client, monkeypatch, artist):
    """
    ورودِ دوباره به صفحه‌ی هنرمند وقتی آنلاین است باید از پلتفرم بیاید، نه کش.

    قبلاً stale-while-revalidate تا یک ساعت صفحه‌ی کهنه را برمی‌گرداند و انتشارِ
    تازه تا رفرشِ دستی دیده نمی‌شد. کش فقط برای قطعیِ بین‌الملل می‌ماند.
    """
    from app import catcache
    from app.models import ArtistDetail

    stale = ArtistDetail(**artist.model_dump(), topTracks=[LIVE])
    catcache.remember_ref(artist.id, "artist", stale)

    fresh_track = Track(
        id="deezer:track:new",
        title="Brand New Release",
        artist=artist.name,
        durationMs=1000,
        source="deezer",
        sourceUrl="https://example.com/new",
    )

    async def fake_artist(http, ref):
        return ArtistDetail(**artist.model_dump(), topTracks=[fresh_track])

    monkeypatch.setattr(catalog, "resolve_artist", fake_artist)

    body = client.get("/api/artist", params={"ref": artist.id}).json()
    assert [t["title"] for t in body["topTracks"]] == ["Brand New Release"]
