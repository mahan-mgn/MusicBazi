"""
کشِ کاتالوگ — همان چیزی که موقع قطعیِ بین‌الملل جای اپل/دیزر/اسپاتیفای را می‌گیرد.

بدون این، در حالتِ اینترانت `/api/search` فقط یک ۵۰۲ است و صفحه‌ی آلبوم و
هنرمند ۴۰۴. با آن، هرچه یک‌بار از جلوی چشمِ کاربر رد شده قابلِ جستجو و مرور
می‌ماند — و چون فایل‌های صوتی از قبل روی دیسکِ خودِ سرورند، «مرور کردن» یعنی
واقعاً پخش کردن، نه تماشای یک فهرستِ مرده.

سه لایه، از دقیق به عام:

1. `catalog_search` — عینِ همان جستجو، اگر قبلاً زده شده باشد.
2. `catalog_entity` — ردیف‌های تکی. جستجویی که هرگز زده نشده هم جواب می‌گیرد،
   چون هر ترکی که در نتیجه‌ی *هر* جستجو یا صفحه‌ی آلبومی دیده شده اینجا هست.
3. کتابخانه — ترک‌هایی که فایلشان روی دیسک است. ممکن است از مسیرِ لینکِ مستقیم
   آمده باشند و هیچ‌وقت در هیچ جستجویی نبوده باشند.

کش هیچ‌وقت منقضی نمی‌شود و این عمدی است: تاریخِ انقضا وقتی معنی دارد که بشود
داده‌ی تازه گرفت. اینجا انتخاب بینِ «داده‌ی سه‌ماهه» و «هیچ» است.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from . import db
from .catalog import interleave
from .models import Album, AlbumDetail, Artist, ArtistDetail, Playlist, SearchResults, Track

log = logging.getLogger(__name__)

# سقفِ هر بخش در نتیجه‌ی جستجوی آفلاین. همان حس‌وحالِ SEARCH_LIMIT را می‌دهد
# بدون اینکه یک عبارتِ عمومی («love») کلِ کشِ چندهزارتایی را برگرداند.
OFFLINE_LIMIT = 30


def _norm(query: str) -> str:
    return " ".join(query.strip().lower().split())


# ---------- نوشتن ----------


def _track_row(t: Track) -> tuple[str, str, str, str, str]:
    text = f"{t.title} {t.artist} {t.album or ''}".lower()
    return (t.id, "track", t.source, text, t.model_dump_json())


def _album_row(a: Album) -> tuple[str, str, str, str, str]:
    return (a.id, "album", a.source, f"{a.title} {a.artist}".lower(), a.model_dump_json())


def _artist_row(a: Artist) -> tuple[str, str, str, str, str]:
    return (a.id, "artist", a.source, f"{a.name} {a.subtitle}".lower(), a.model_dump_json())


def _playlist_row(p: Playlist) -> tuple[str, str, str, str, str]:
    return (p.id, "playlist", p.source, f"{p.title} {p.owner}".lower(), p.model_dump_json())


def _entities(payload: Any) -> list[tuple[str, str, str, str, str]]:
    """هر ردیفِ قابلِ جستجویی که در این پاسخ هست."""
    rows: list[tuple[str, str, str, str, str]] = []
    if isinstance(payload, SearchResults):
        rows += [_track_row(t) for t in payload.tracks]
        rows += [_album_row(a) for a in payload.albums]
        rows += [_artist_row(a) for a in payload.artists]
        rows += [_playlist_row(p) for p in payload.playlists]
    elif isinstance(payload, ArtistDetail):
        rows.append(_artist_row(payload))
        rows += [_track_row(t) for t in payload.topTracks + payload.radio]
        rows += [_track_row(t) for t in payload.likedTracks + payload.repostedTracks]
        rows += [_album_row(a) for a in payload.albums]
        rows += [_artist_row(a) for a in payload.related]
        rows += [_playlist_row(p) for p in payload.playlists]
    elif isinstance(payload, AlbumDetail):
        # خودِ AlbumDetail زیرکلاسِ Album است، پس ردیفِ آلبومش هم ثبت می‌شود و
        # دفعه‌ی بعد در بخشِ «آلبوم‌ها»ی جستجوی آفلاین پیدا می‌شود
        rows.append(_album_row(payload))
        rows += [_track_row(t) for t in payload.tracks]
    return rows


def remember_search(query: str, results: SearchResults) -> None:
    """
    پاسخِ یک جستجوی موفق. باید *قبل* از محلی‌سازیِ کاور صدا زده شود تا آدرسِ
    اصلیِ CDN در کش بماند — آدرسِ `/api/art/...` وابسته به همین دیتابیس است و
    ذخیره‌ی آن به‌جای آدرسِ اصلی، یک ارجاعِ دایره‌ای می‌ساخت.
    """
    key = _norm(query)
    if not key:
        return
    now = time.time()
    try:
        db.put_search(key, results.model_dump_json(), now)
        db.put_entities(_entities(results), now)
    except Exception:
        log.warning("ذخیره‌ی کشِ جستجو نشد", exc_info=True)


def remember_ref(ref: str, kind: str, payload: AlbumDetail | ArtistDetail) -> None:
    """
    صفحه‌ی آلبوم یا هنرمند.

    زیرِ دو کلید می‌نشیند: همان `ref`ی که کاربر داده (که ممکن است لینکِ کامل
    باشد) و شناسه‌ی داخلیِ خودِ نتیجه. بدونِ دومی، آلبومی که یک‌بار با لینکِ
    اسپاتیفای باز شده بود، موقعِ کلیک از داخلِ نتیجه‌ی جستجو — که شناسه می‌فرستد
    نه لینک — دوباره پیدا نمی‌شد.
    """
    now = time.time()
    body = payload.model_dump_json()
    try:
        for key in {ref.strip(), payload.id}:
            if key:
                db.put_ref(key, kind, body, now)
        db.put_entities(_entities(payload), now)
    except Exception:
        log.warning("ذخیره‌ی کشِ %s نشد", kind, exc_info=True)


# ---------- خواندن ----------


def _parse(rows: list, model: type) -> list:
    out = []
    for row in rows:
        try:
            out.append(model.model_validate_json(row["payload"]))
        except Exception:
            continue  # ردیفِ خراب یا مدلی که از آن‌موقع عوض شده — رد شود
    return out


def _library_tracks(query: str, limit: int) -> list[Track]:
    """
    ترک‌هایی که فایلشان روی دیسک است.

    آخر از همه می‌آیند ولی مهم‌ترین‌اند: تنها ردیف‌هایی از نتیجه‌ی آفلاین‌اند که
    دکمه‌ی پخششان قطعاً کار می‌کند.
    """
    try:
        rows, _, _ = db.library(query, limit, 0)
    except Exception:
        return []
    out: list[Track] = []
    for row in rows:
        try:
            out.append(Track.model_validate_json(row["track_json"]))
        except Exception:
            continue
    return out


def search(query: str) -> SearchResults:
    """
    جستجو در چیزهایی که قبلاً دیده شده‌اند.

    اول عینِ همان عبارت امتحان می‌شود: اگر کاربر دیروز همین را جستجو کرده،
    نتیجه‌ی امروزش باید دقیقاً همان چیدمان و همان ترتیب باشد، نه یک بازسازیِ
    تقریبی که «آن آهنگی که بالا بود» را جای دیگری می‌گذارد.
    """
    key = _norm(query)

    if row := db.get_search(key):
        try:
            return SearchResults.model_validate_json(row["payload"])
        except Exception:
            log.debug("کشِ جستجوی «%s» قابل خواندن نبود", key)

    result = SearchResults(query=query)
    result.tracks = _parse(db.search_entities("track", key, OFFLINE_LIMIT), Track)
    result.albums = _parse(db.search_entities("album", key, OFFLINE_LIMIT), Album)
    result.artists = _parse(db.search_entities("artist", key, OFFLINE_LIMIT), Artist)
    result.playlists = _parse(db.search_entities("playlist", key, OFFLINE_LIMIT), Playlist)

    seen = {t.id for t in result.tracks}
    for track in _library_tracks(key, OFFLINE_LIMIT):
        if track.id not in seen:
            seen.add(track.id)
            result.tracks.append(track)

    # همان چیدمانِ نوبتیِ حالتِ آنلاین — بدونش، ترتیبِ `seen_at` باعث می‌شد کلِ
    # صفحه‌ی اول از یک منبع باشد فقط چون آخرین جستجو آنجا بوده
    result.tracks = interleave(result.tracks)
    result.albums = interleave(result.albums)
    result.artists = interleave(result.artists)
    result.playlists = interleave(result.playlists)
    return result


def album(ref: str) -> AlbumDetail | None:
    row = db.get_ref(ref.strip(), "album")
    if row is None:
        return None
    try:
        return AlbumDetail.model_validate_json(row["payload"])
    except Exception:
        return None


def artist(ref: str) -> ArtistDetail | None:
    row = db.get_ref(ref.strip(), "artist")
    if row is None:
        return None
    try:
        return ArtistDetail.model_validate_json(row["payload"])
    except Exception:
        return None


def stats() -> dict:
    entities, searches = db.catalog_stats()
    return {"entities": entities, "searches": searches}
