"""آینه‌ی محلیِ کاور — همان چیزی که موقعِ قطعیِ بین‌الملل کتابخانه را بی‌کاور نمی‌گذارد."""

from __future__ import annotations

import pytest

from app import artcache, db
from app.models import AlbumDetail, SearchResults, Track, UserPlaylist

APPLE_500 = "https://is1-ssl.mzstatic.com/image/thumb/x/500x500bb.jpg"
APPLE_100 = "https://is1-ssl.mzstatic.com/image/thumb/x/100x100bb.jpg"


@pytest.fixture
def mirror(fresh_db, tmp_path, monkeypatch):
    """آینه‌ی روشن، روی دیتابیس و دیسکِ موقتِ خودِ تست."""
    monkeypatch.setattr(artcache, "ART_MIRROR_ENABLED", True)
    monkeypatch.setattr(artcache, "CACHE_DIR", tmp_path / "artwork")
    return fresh_db


def test_same_cover_in_two_sizes_collapses_to_one_key(mirror):
    """
    نتیجه‌ی جستجو کاور را ۱۰۰ پیکسل می‌دهد و صفحه‌ی آلبوم ۵۰۰ — یکی‌اند.

    بدون نرمال‌سازی، همان جلد دو ردیف و دو دانلودِ جدا می‌گرفت و کاربر یک
    تصویر را دو بار روی شبکه می‌آورد.
    """
    mapping = artcache.remember([APPLE_100, APPLE_500])
    assert mapping[APPLE_100] == mapping[APPLE_500]


def test_local_url_round_trips_back_to_the_cdn(mirror):
    """
    فرانت همان آدرسی که گرفته را موقعِ دانلود پس می‌فرستد.

    اگر `original` آن را به آدرسِ واقعی برنگرداند، تگ‌گذار سعی می‌کند
    `/api/art/...` را با httpx بگیرد و هر فایلِ دانلودشده بی‌کاور می‌ماند.
    """
    local = artcache.remember([APPLE_500])[APPLE_500]
    assert artcache.LOCAL.match(local)
    assert artcache.original(local) == artcache.canonical(APPLE_500)


def test_unknown_local_url_is_not_mistaken_for_a_cdn_url(mirror):
    """شناسه‌ای که در دیتابیس نیست باید None بدهد، نه خودش را."""
    assert artcache.original("/api/art/" + "0" * 20) is None
    # آدرسی که اصلاً محلی نیست باید دست‌نخورده رد شود
    assert artcache.original(APPLE_500) == APPLE_500


def test_localize_rewrites_every_nested_cover(mirror):
    """
    یک پاسخ چند سطح تودرتو دارد و همه‌شان باید محلی شوند.

    ترکِ داخلِ آلبومِ داخلِ نتیجه‌ی جستجو دقیقاً همان‌جایی است که یک پیاده‌سازیِ
    سطحی جا می‌اندازد — و همان‌جا هم بیشترین کاور دیده می‌شود.
    """
    track = Track(
        id="itunes:track:9",
        title="t",
        artist="a",
        durationMs=1000,
        source="apple",
        sourceUrl="https://example.com/t",
        artworkUrl=APPLE_500,
    )
    results = SearchResults(query="q", tracks=[track])
    artcache.localize(results)
    assert artcache.LOCAL.match(results.tracks[0].artworkUrl)


def test_localize_handles_the_playlist_cover_list(mirror):
    """`artworkUrls` جمع است و مسیرِ جدایی دارد — کاشیِ پلی‌لیست از آن ساخته می‌شود."""
    playlist = UserPlaylist(
        id="p1", name="n", kind="manual", createdAt=0.0, artworkUrls=[APPLE_500, APPLE_100]
    )
    artcache.localize(playlist)
    assert all(artcache.LOCAL.match(u) for u in playlist.artworkUrls)


def test_localize_leaves_a_response_without_covers_alone(mirror):
    detail = AlbumDetail(
        id="deezer:album:1",
        title="x",
        artist="y",
        year=2000,
        trackCount=0,
        source="deezer",
        sourceUrl="https://example.com/a",
        durationMs=0,
        tracks=[],
    )
    assert artcache.localize(detail).artworkUrl is None


def test_disabled_mirror_keeps_the_original_url(mirror, monkeypatch):
    """خاموش‌کردنِ آینه باید دقیقاً رفتارِ قبلیِ برنامه را برگرداند."""
    monkeypatch.setattr(artcache, "ART_MIRROR_ENABLED", False)
    track = Track(
        id="itunes:track:9",
        title="t",
        artist="a",
        durationMs=1,
        source="apple",
        sourceUrl="https://example.com/t",
        artworkUrl=APPLE_500,
    )
    artcache.localize(track)
    assert track.artworkUrl == APPLE_500


def test_remember_bytes_makes_a_downloaded_cover_available_offline(mirror):
    """
    کاوری که همین الان برای امبد کردن گرفته شده، مجانی در آینه هم می‌نشیند.

    این تنها مسیری است که *بدون* بازدیدِ مرورگر هم کش را پر می‌کند — یعنی ترکی
    که دانلود شده و پنج دقیقه بعد اینترنت قطع شده، باز هم کاور دارد.
    """
    artcache.remember_bytes(APPLE_500, b"\xff\xd8\xff-fake-jpeg", "image/jpeg")
    sha = artcache.LOCAL.match(artcache.remember([APPLE_500])[APPLE_500]).group(1)
    assert artcache.stored(sha) is not None


def test_a_row_whose_file_vanished_goes_back_to_pending(mirror):
    """
    دیسک پاک شده ولی ردیف مانده.

    ۴۰۴ِ دائمی جوابِ درستی نیست: آن کاور تا ابد مرده می‌ماند. باید دوباره
    «نگرفته» شود تا دفعه‌ی بعد که اینترنت بود گرفته شود.
    """
    artcache.remember_bytes(APPLE_500, b"data", "image/jpeg")
    sha = artcache.LOCAL.match(artcache.remember([APPLE_500])[APPLE_500]).group(1)

    artcache.path_for(sha).unlink()
    assert artcache.stored(sha) is None
    assert any(row["sha"] == sha for row in mirror.artwork_pending(10))


# ---------- آدرسِ مطلقِ محلی، آن‌چه فقط اپ اندروید تولید می‌کند ----------
#
# `src/lib/server.ts` هر `/api/...` را که از سرور می‌گیرد به آدرسِ مطلق
# تبدیل می‌کند (صفحه از `https://localhost` سرو می‌شود و مسیرِ نسبی یعنی
# «خودِ اپ»). پس موقعِ دانلود، کاور به‌شکلِ
# `http://127.0.0.1:8000/api/art/{sha}` برمی‌گردد. نشناختنش یعنی هر
# فایلِ دانلودشده روی گوشی بی‌کاور بماند.

ABSOLUTE = "http://127.0.0.1:8000/api/art/"


def test_absolute_local_url_round_trips_back_to_the_cdn(mirror):
    """همان round-tripِ بالا، در شکلی که اپ نیتیو می‌فرستد."""
    local = artcache.remember([APPLE_500])[APPLE_500]
    sha = artcache.LOCAL.match(local).group(1)
    assert artcache.original(ABSOLUTE + sha) == artcache.canonical(APPLE_500)


def test_absolute_local_url_is_not_registered_as_a_source(mirror):
    """
    برگشتِ آینه به خودش ثبت نشود.

    اگر `remember` آن را یک منبعِ بیرونی حساب کند، ردیفی می‌سازیم که «آدرسِ
    CDN»ش خودِ `/api/art` است — و گرفتنش یعنی درخواست به خودمان.
    """
    local = artcache.remember([APPLE_500])[APPLE_500]
    sha = artcache.LOCAL.match(local).group(1)

    assert artcache.remember([ABSOLUTE + sha]) == {}
    assert mirror.artwork_row(sha)["url"] == artcache.canonical(APPLE_500)


def test_self_referential_row_is_dropped_not_fetched(mirror):
    """
    ردیفِ مسمومِ نسخه‌های قبل.

    `fetch` نباید سراغِ خودش برود: هر لایه یک نخ و یک اتصال می‌گیرد و تا
    پرشدنِ استخرِ نخ، کل سرور معلّق می‌ماند. ردیف هم باید پاک شود وگرنه هر
    بازدیدِ بعدی همان کار را می‌کند.
    """
    poisoned = artcache.remember([APPLE_500])[APPLE_500]
    sha = artcache.LOCAL.match(poisoned).group(1)
    mirror._exec("UPDATE artwork SET url = ? WHERE sha = ?", (poisoned, sha))

    assert artcache.fetch(sha) is None
    assert mirror.artwork_row(sha) is None


class TestSniff:
    """
    هدرِ Content-Type سروِ کاور.

    فایل‌های آینه بیِ پسوندند و `FileResponse` بیِ media_type آن‌ها را
    octet-stream می‌فروشد — مرورگر sniffing می‌کند ولی curl/دیباگر نوعِ
    غلط می‌بینند.
    """

    def test_jpeg_png_webp_are_recognized(self, tmp_path):
        for name, blob, want in [
            ("a", b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
            ("b", b"\x89PNG\r\n\x1a\n" + b"\x00" * 4, "image/png"),
            ("c", b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        ]:
            p = tmp_path / name
            p.write_bytes(blob)
            assert artcache.sniff(p) == want

    def test_unknown_bytes_and_missing_file_return_none(self, tmp_path):
        p = tmp_path / "junk"
        p.write_bytes(b"not an image at all....")
        assert artcache.sniff(p) is None
        assert artcache.sniff(tmp_path / "ghost") is None


class TestServe:
    """مسیرِ `/api/art/{sha}` باید نوعِ واقعیِ تصویر را اعلام کند."""

    JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32

    def test_stored_cover_is_served_as_image_jpeg(self, mirror, monkeypatch):
        from fastapi.testclient import TestClient

        from app import reach
        from app.main import app

        monkeypatch.setattr(reach, "REACH_PROBES", ())
        sha = artcache.LOCAL.match(artcache.remember([APPLE_500])[APPLE_500]).group(1)
        path = artcache.path_for(sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.JPEG)
        db.artwork_stored(sha, "image/jpeg", len(self.JPEG), now=1.0)

        with TestClient(app) as c:
            res = c.get(f"/api/art/{sha}")

        # پیش از sniff این octet-stream بود؛ مرورگر تحملش کرد، curl نه
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/jpeg"
        assert res.headers["cache-control"] == "public, max-age=31536000, immutable"

