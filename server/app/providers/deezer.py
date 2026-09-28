"""Deezer API — عمومی و بدون کلید. تنها منبع ما برای پلی‌لیست."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from ..config import DEEZER_API, SEARCH_LIMIT
from ..models import Album, AlbumDetail, Artist, ArtistDetail, Playlist, SearchResults, Track

ALBUM_URL = re.compile(r"deezer\.com/(?:[a-z]{2}/)?album/(\d+)", re.I)
PLAYLIST_URL = re.compile(r"deezer\.com/(?:[a-z]{2}/)?playlist/(\d+)", re.I)
TRACK_URL = re.compile(r"deezer\.com/(?:[a-z]{2}/)?track/(\d+)", re.I)
ARTIST_URL = re.compile(r"deezer\.com/(?:[a-z]{2}/)?artist/(\d+)", re.I)
# صفحه‌ی کاربر — دیزر «profile» صدایش می‌کند، نه «user»
PROFILE_URL = re.compile(r"deezer\.com/(?:[a-z]{2}/)?profile/(\d+)", re.I)


def _track(row: dict[str, Any], album_row: dict[str, Any] | None = None) -> Track:
    alb = row.get("album") or album_row or {}
    artist = row.get("artist") or {}
    return Track(
        id=f"deezer:track:{row['id']}",
        title=row.get("title_short") or row.get("title") or "",
        artist=artist.get("name") or "",
        album=alb.get("title"),
        albumId=f"deezer:album:{alb['id']}" if alb.get("id") else None,
        durationMs=int(row.get("duration") or 0) * 1000,
        artworkUrl=_cover(alb, "cover"),
        source="deezer",
        sourceUrl=row.get("link") or f"https://www.deezer.com/track/{row['id']}",
        previewUrl=row.get("preview"),
        explicit=bool(row.get("explicit_lyrics")),
        trackNumber=row.get("track_position"),
        discNumber=row.get("disk_number"),
        artistId=f"deezer:artist:{artist['id']}" if artist.get("id") else None,
        artistArtworkUrl=_cover(artist, "picture"),
        # نتیجه‌ی جستجو فقط یک آلبومِ خلاصه همراه دارد؛ سال و ژانر تنها وقتی
        # می‌آیند که از صفحه‌ی آلبوم آمده باشیم
        year=_year(alb.get("release_date")),
        genre=_genre(alb),
    )


def _cover(row: dict[str, Any], field: str) -> str | None:
    """
    بزرگ‌ترین کاوری که به درد نمایش می‌خورد.

    دیزر چهار پله می‌دهد: small=۵۶، medium=۲۵۰، big=۵۰۰، xl=۱۰۰۰. تا حالا
    medium برمی‌داشتیم که روی نمایشگر رتینا تار است. xl را عمداً برنمی‌داریم —
    برای کارت ۲۰۰ پیکسلی چیزی اضافه نمی‌کند و بیست‌تا از آن، نتیجه‌ی جستجو را
    سنگین می‌کند. موقع دانلود، `artwork.candidates` خودش تا xl بالا می‌رود.
    """
    return row.get(f"{field}_big") or row.get(f"{field}_medium") or row.get(field)


def _year(release_date: str | None) -> int | None:
    head = (release_date or "")[:4]
    return int(head) if head.isdigit() else None


def _genre(album_row: dict[str, Any]) -> str | None:
    rows = (album_row.get("genres") or {}).get("data") or []
    return next((g["name"] for g in rows if g.get("name")), None)


def _implied_tracks(row: dict[str, Any]) -> int:
    """
    `/artist/{id}/albums` بر خلاف `/search/album` تعداد ترک نمی‌دهد، ولی
    `record_type` می‌دهد: سینگل یک ترک است و درباره‌ی آلبوم و ای‌پی چیزی
    نمی‌دانیم (صفر یعنی نامعلوم).

    همین تفاوتِ کوچک جای دیگری کار می‌کند: موقع پر کردنِ بخش آهنگ‌های صفحه‌ی
    هنرمند، آلبومِ واقعی باید جلوی سینگل بیفتد وگرنه لیست سه‌تایی می‌شود.
    """
    return 1 if row.get("record_type") == "single" else 0


def _release_type(row: dict[str, Any]) -> str | None:
    """
    دسته‌ی انتشار از `record_type` دیزر.

    `/artist/{id}/albums` تعداد ترک نمی‌دهد؛ بدون این فیلد فرانت آلبومِ واقعی را
    از فیلتر «آلبوم‌ها» بیرون می‌انداخت چون trackCount صفر بود.
    """
    kind = (row.get("record_type") or "").lower()
    if kind in ("album", "single", "ep", "compilation"):
        return kind
    return None


def _album(row: dict[str, Any]) -> Album:
    artist = row.get("artist") or {}
    return Album(
        id=f"deezer:album:{row['id']}",
        title=row.get("title") or "",
        artist=artist.get("name") or "",
        year=_year(row.get("release_date")) or 0,
        artworkUrl=_cover(row, "cover"),
        trackCount=int(row.get("nb_tracks") or _implied_tracks(row)),
        source="deezer",
        sourceUrl=row.get("link") or f"https://www.deezer.com/album/{row['id']}",
        # جستجوی دیزر آرتیست‌آیدی و عکسِ آرتیست را همراهِ آلبوم می‌دهد — رایگان
        artistId=f"deezer:artist:{artist['id']}" if artist.get("id") else None,
        artistArtworkUrl=_cover(artist, "picture"),
        releaseType=_release_type(row),
        releaseDate=row.get("release_date"),
    )


def _playlist(row: dict[str, Any]) -> Playlist:
    creator = row.get("user") or row.get("creator") or {}
    return Playlist(
        id=f"deezer:playlist:{row['id']}",
        title=row.get("title") or "",
        owner=creator.get("name") or "ناشناس",
        trackCount=int(row.get("nb_tracks") or 0),
        artworkUrl=_cover(row, "picture"),
        source="deezer",
        sourceUrl=row.get("link") or f"https://www.deezer.com/playlist/{row['id']}",
    )


def _artist(row: dict[str, Any]) -> Artist:
    albums = row.get("nb_album")
    fans = row.get("nb_fan")
    if albums:
        subtitle = f"{albums} آلبوم"
    elif fans:
        subtitle = f"{fans:,} دنبال‌کننده"
    else:
        subtitle = "هنرمند"
    return Artist(
        id=f"deezer:artist:{row['id']}",
        name=row.get("name") or "",
        artworkUrl=_cover(row, "picture"),
        source="deezer",
        sourceUrl=row.get("link") or f"https://www.deezer.com/artist/{row['id']}",
        subtitle=subtitle,
    )


async def _get(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    res = await client.get(f"{DEEZER_API}{path}", params=params)
    res.raise_for_status()
    body = res.json()
    if isinstance(body, dict) and "error" in body and body["error"]:
        raise httpx.HTTPError(str(body["error"]))
    return body


async def search(client: httpx.AsyncClient, query: str) -> SearchResults:
    # هر چهار تا مستقل‌اند — سریالی زدنشان زمان جستجو را چهار برابر می‌کند.
    # هنرمند را از دیزر هم می‌گیریم چون برخلاف iTunes عکس دارد.
    tracks, albums, playlists, artists = await asyncio.gather(
        _get(client, "/search/track", q=query, limit=SEARCH_LIMIT),
        _get(client, "/search/album", q=query, limit=SEARCH_LIMIT),
        _get(client, "/search/playlist", q=query, limit=SEARCH_LIMIT),
        _get(client, "/search/artist", q=query, limit=8),
    )
    return SearchResults(
        query=query,
        tracks=[_track(r) for r in tracks.get("data", []) if r.get("id")],
        albums=[_album(r) for r in albums.get("data", []) if r.get("id")],
        playlists=[_playlist(r) for r in playlists.get("data", []) if r.get("id")],
        artists=[_artist(r) for r in artists.get("data", []) if r.get("id")],
    )


async def search_playlists(client: httpx.AsyncClient, query: str, limit: int = SEARCH_LIMIT) -> list[Playlist]:
    """
    جدا از `search` عمومی — چت‌بات وایب (vibe.py) فقط پلی‌لیست می‌خواهد، نه
    ترک/آلبوم/هنرمندِ همان جستجو که آن تابع همیشه هر چهار تا را می‌زند.
    """
    body = await _get(client, "/search/playlist", q=query, limit=limit)
    return [_playlist(r) for r in body.get("data", []) if r.get("id")]


async def album(client: httpx.AsyncClient, album_id: str) -> AlbumDetail | None:
    row = await _get(client, f"/album/{album_id}")
    if not row.get("id"):
        return None
    tracks = [_track(t, row) for t in (row.get("tracks") or {}).get("data", [])]
    base = _album(row)
    # پاسخِ `/album/{id}` آرتیست را خلاصه می‌دهد (بدون عکس)؛ `/artist/{id}`
    # عکسِ پروفایل را می‌دهد. شکستش فقط None می‌شود.
    artist_row = row.get("artist") or {}
    if artist_row.get("id"):
        try:
            base.artistArtworkUrl = _cover(await _get(client, f"/artist/{artist_row['id']}"), "picture")
        except Exception:
            pass
    if base.artistArtworkUrl:
        for t in tracks:
            if not t.artistArtworkUrl:
                t.artistArtworkUrl = base.artistArtworkUrl
    return AlbumDetail(
        **base.model_dump(),
        durationMs=sum(t.durationMs for t in tracks),
        tracks=tracks,
    )


async def playlist(client: httpx.AsyncClient, playlist_id: str) -> AlbumDetail | None:
    """پلی‌لیست را هم به شکل AlbumDetail برمی‌گردانیم تا فرانت یک صفحه بیشتر لازم نداشته باشد."""
    row = await _get(client, f"/playlist/{playlist_id}")
    if not row.get("id"):
        return None
    tracks = [_track(t) for t in (row.get("tracks") or {}).get("data", []) if t.get("id")]
    creator = row.get("creator") or {}
    return AlbumDetail(
        id=f"deezer:playlist:{row['id']}",
        title=row.get("title") or "",
        artist=creator.get("name") or "پلی‌لیست",
        year=0,
        artworkUrl=_cover(row, "picture"),
        trackCount=len(tracks),
        source="deezer",
        sourceUrl=row.get("link") or f"https://www.deezer.com/playlist/{row['id']}",
        durationMs=sum(t.durationMs for t in tracks),
        tracks=tracks,
    )


async def artist(client: httpx.AsyncClient, artist_id: str) -> ArtistDetail | None:
    head, top, albums, related, radio, playlists = await asyncio.gather(
        _get(client, f"/artist/{artist_id}"),
        _get(client, f"/artist/{artist_id}/top", limit=25),
        _get(client, f"/artist/{artist_id}/albums", limit=100),
        _get(client, f"/artist/{artist_id}/related", limit=10),
        _get(client, f"/artist/{artist_id}/radio", limit=25),
        _get(client, f"/artist/{artist_id}/playlists", limit=25),
        return_exceptions=True,
    )
    if not isinstance(head, dict) or not head.get("id"):
        return None

    # تاریخِ کامل، نه سال: صفحه‌ی خودِ دیزر تازه‌ترین انتشار را اول می‌گذارد و با
    # مرتب‌سازیِ سالانه، شش سینگلِ یک سال ترتیبِ دلبخواه می‌گرفتند
    rows = (
        sorted(albums.get("data", []), key=lambda r: r.get("release_date") or "", reverse=True)
        if isinstance(albums, dict)
        else []
    )
    discography = [_album({**r, "artist": head}) for r in rows if r.get("id")]

    tracks = (
        [_track(r) for r in top.get("data", []) if r.get("id")]
        if isinstance(top, dict)
        else []
    )

    # هر سه اختیاری‌اند — شکستن یکی نباید بقیه‌ی صفحه‌ی هنرمند را خراب کند
    related_artists = (
        [_artist(r) for r in related.get("data", []) if r.get("id")]
        if isinstance(related, dict)
        else []
    )
    radio_tracks = (
        [_track(r) for r in radio.get("data", []) if r.get("id")]
        if isinstance(radio, dict)
        else []
    )
    artist_playlists = (
        [_playlist(r) for r in playlists.get("data", []) if r.get("id")]
        if isinstance(playlists, dict)
        else []
    )

    base = _artist(head)
    return ArtistDetail(
        **base.model_dump(),
        topTracks=tracks,
        albums=discography,
        related=related_artists,
        radio=radio_tracks,
        playlists=artist_playlists,
    )


# پلی‌لیست‌های یک کاربر. بیشتر از این هم صفحه می‌خواهد هم چیزی به صفحه‌ی
# پروفایل اضافه نمی‌کند.
USER_PLAYLISTS = 50

# زیرنویسِ کاربری که هیچ پلی‌لیستِ عمومی‌ای ندارد
UNKNOWN_USER = "کاربر"


async def user(client: httpx.AsyncClient, user_id: str) -> ArtistDetail | None:
    """
    صفحه‌ی یک کاربر (نه هنرمند): پلی‌لیست‌های عمومی‌اش.

    همان `ArtistDetail` ی صفحه‌ی هنرمند برمی‌گردد با `kind="user"` — بدون
    دیسکوگرافی، چون کاربر انتشاری ندارد. `/user/{id}/playlists` فقط
    پلی‌لیست‌های عمومی را می‌دهد، ولی «آهنگ‌های محبوب» (`is_loved_track`) هم
    میانشان است: آن یکی صفحه‌ی قابل‌بازکردن ندارد و کارتش به بن‌بست می‌رسید.
    """
    head, playlists = await asyncio.gather(
        _get(client, f"/user/{user_id}"),
        _get(client, f"/user/{user_id}/playlists", limit=USER_PLAYLISTS),
        return_exceptions=True,
    )
    if not isinstance(head, dict) or not head.get("id"):
        return None

    rows = [
        _playlist({**r, "user": r.get("creator") or head})
        for r in (playlists.get("data", []) if isinstance(playlists, dict) else [])
        if r.get("id") and r.get("public") and not r.get("is_loved_track")
    ]
    return ArtistDetail(
        id=f"deezer:user:{head['id']}",
        name=head.get("name") or "",
        artworkUrl=_cover(head, "picture"),
        source="deezer",
        sourceUrl=head.get("link") or f"https://www.deezer.com/profile/{head['id']}",
        subtitle=f"{len(rows)} پلی‌لیست" if rows else UNKNOWN_USER,
        kind="user",
        playlists=rows,
    )


def parse_url(url: str) -> tuple[str, str] | None:
    if m := ALBUM_URL.search(url):
        return "album", m.group(1)
    if m := PLAYLIST_URL.search(url):
        return "playlist", m.group(1)
    if m := TRACK_URL.search(url):
        return "track", m.group(1)
    if m := ARTIST_URL.search(url):
        return "artist", m.group(1)
    if m := PROFILE_URL.search(url):
        return "user", m.group(1)
    return None
