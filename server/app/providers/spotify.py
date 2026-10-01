"""
اسپاتیفای از طریق Web API — فقط برای متادیتا.

اسپاتیفای فایل صوتی نمی‌دهد (و DRM دارد)، ولی لیست ترک‌های یک آلبوم یا پلی‌لیست
را دقیق می‌دهد. همان چیزی که برای پیدا کردن صوت از منابع باز لازم داریم.

بدون کلید هم پروژه کار می‌کند: `catalog` به مسیر قدیمی (عنوان از oEmbed و جستجو
در اپل/دیزر) برمی‌گردد — ولی آن مسیر فقط آلبوم را حدس می‌زند و پلی‌لیست را اصلاً
نمی‌تواند.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from html import unescape
from typing import Any

import httpx

from ..config import (
    SPOTIFY_API,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_TOKEN_URL,
)
from ..models import Album, AlbumDetail, Artist, ArtistDetail, Playlist, SearchResults, Track

URL = re.compile(r"open\.spotify\.com/(?:intl-[a-z]{2}/)?(album|playlist|track|artist)/([A-Za-z0-9]+)", re.I)

# صفحه‌ی کاربر. جدا از بقیه چون شناسه‌اش شکل دیگری دارد: نامِ کاربریِ قدیمی
# می‌تواند نقطه و خط‌تیره و کاراکترِ URL-encoded داشته باشد، برخلاف شناسه‌ی
# base62 ی آلبوم و ترک.
USER_URL = re.compile(r"open\.spotify\.com/(?:intl-[a-z]{2}/)?user/([A-Za-z0-9._%~-]+)", re.I)

# صفحه‌بندی: اسپاتیفای برای آلبوم حداکثر ۵۰ می‌دهد. پلی‌لیست دیگر از این راه
# صفحه نمی‌خورد — ترک‌هایش از صفحه‌ی امبد می‌آیند، یک‌جا
ALBUM_PAGE = 50
MAX_TRACKS = 1000

# `market` روی صفحه‌ی هنرمند اجباری نیست ولی بودنش دو کار می‌کند: ترک‌های محبوب
# را مرتب برمی‌گرداند، و دیسکوگرافی را از نسخه‌های تکراریِ هر کشور پاک می‌کند.
# «US» چون کاتالوگ کامل‌ترین جای همین است، نه اینکه کاربر آمریکایی باشد.
MARKET = "US"

# دیسکوگرافی صفحه‌بندی‌اش با بقیه فرق دارد: اپلیکیشنِ حالت توسعه (که کلید
# بی‌درخواستِ دسترسی همان است) روی این اندپوینت limit بزرگ‌تر از ده را با
# «Invalid limit» رد می‌کند و پیش‌فرضش هم پنج است. با پنجاه، دیسکوگرافیِ هر
# هنرمند خالی می‌آمد.
ARTIST_ALBUM_PAGE = 10
ARTIST_ALBUMS = MAX_TRACKS

# زیرنویسِ هنرمندی که چیزی درباره‌اش نمی‌دانیم — روی صفحه‌ی هنرمند با تعداد
# آلبوم عوض می‌شود
UNKNOWN_ARTIST = "هنرمند"

_token: str | None = None
_token_expires = 0.0
_token_lock = asyncio.Lock()


def enabled() -> bool:
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)


def parse_url(url: str) -> tuple[str, str] | None:
    if m := URL.search(url):
        return m.group(1).lower(), m.group(2)
    if m := USER_URL.search(url):
        return "user", m.group(1)
    return None


async def _access_token(client: httpx.AsyncClient) -> str:
    """
    Client Credentials — بدون کاربر، فقط برای داده‌ی عمومی.
    توکن یک ساعت اعتبار دارد؛ زودتر از موعد تازه‌اش می‌کنیم تا وسط یک پلی‌لیست
    بزرگ منقضی نشود.
    """
    global _token, _token_expires

    async with _token_lock:
        if _token and time.time() < _token_expires:
            return _token

        secret = base64.b64encode(
            f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
        ).decode()
        res = await client.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={
                "authorization": f"Basic {secret}",
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        res.raise_for_status()
        body = res.json()
        _token = body["access_token"]
        _token_expires = time.time() + int(body.get("expires_in", 3600)) - 60
        return _token


async def _get(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    token = await _access_token(client)
    res = await client.get(
        f"{SPOTIFY_API}{path}",
        params=params,
        headers={"authorization": f"Bearer {token}"},
    )
    res.raise_for_status()
    return res.json()


def _art(images: list[dict] | None) -> str | None:
    if not images:
        return None
    # اسپاتیفای از بزرگ به کوچک می‌دهد و بزرگ‌ترینش ۶۴۰ است — نه آن‌قدر بزرگ که
    # ارزش داشته باشد نسخه‌ی متوسط (۳۰۰) را انتخاب کنیم و کاور تار تحویل بدهیم.
    # برخلاف بقیه اینجا آدرس اندازه ندارد، پس همین است که هست؛ موقع امبد هم
    # چیز بهتری در کار نیست.
    largest = max(images, key=lambda i: i.get("width") or 0)
    return largest.get("url")


def _artists(row: dict[str, Any]) -> str:
    names = [a.get("name", "") for a in (row.get("artists") or []) if a.get("name")]
    return ", ".join(names)


def _first_artist_id(row: dict[str, Any]) -> str | None:
    """شناسه‌ی نخستین آرتیستِ ردیف — ناوبری فرانت به صفحه‌ی آرتیست."""
    for a in row.get("artists") or []:
        if a.get("id"):
            return f"sp:artist:{a['id']}"
    return None


def _track(row: dict[str, Any], album_row: dict[str, Any] | None = None) -> Track | None:
    if not row or not row.get("id"):
        return None
    alb = row.get("album") or album_row or {}
    return Track(
        id=f"sp:track:{row['id']}",
        title=row.get("name") or "",
        artist=_artists(row) or _artists(alb),
        album=alb.get("name"),
        albumId=f"sp:album:{alb['id']}" if alb.get("id") else None,
        durationMs=int(row.get("duration_ms") or 0),
        artworkUrl=_art(alb.get("images")),
        source="spotify",
        sourceUrl=(row.get("external_urls") or {}).get("spotify")
        or f"https://open.spotify.com/track/{row['id']}",
        previewUrl=row.get("preview_url"),
        explicit=bool(row.get("explicit")),
        trackNumber=row.get("track_number"),
        discNumber=row.get("disc_number"),
        artistId=_first_artist_id(row),
        year=_year(alb.get("release_date")),
        # اسپاتیفای ژانر را روی ترک و آلبوم نمی‌دهد، فقط روی هنرمند —
        # و آن هم یک درخواست جدا می‌خواهد که ارزشش را ندارد
        genre=None,
    )


def _year(release_date: str | None) -> int | None:
    """`release_date` می‌تواند `2025`، `2025-03` یا `2025-03-14` باشد."""
    head = (release_date or "")[:4]
    return int(head) if head.isdigit() else None


def _release_type(row: dict[str, Any]) -> str | None:
    """
    دسته‌ی انتشار از `album_type` اسپاتیفای.

    EP جداگانه نیست: اسپاتیفای آن را `single` می‌گذارد. اگر تعداد ترک بین ۲ و ۶
    باشد EP است — همان حدودی که خودِ اپ هم برای کارت «EP» به کار می‌برد.
    """
    kind = (row.get("album_type") or "").lower()
    tracks = int(row.get("total_tracks") or 0)
    if kind == "compilation":
        return "compilation"
    if kind == "album":
        return "album"
    if kind == "single":
        if 2 <= tracks <= 6:
            return "ep"
        return "single"
    return None


def _album_head(row: dict[str, Any]) -> Album:
    return Album(
        id=f"sp:album:{row['id']}",
        title=row.get("name") or "",
        artist=_artists(row),
        year=_year(row.get("release_date")) or 0,
        artworkUrl=_art(row.get("images")),
        trackCount=int(row.get("total_tracks") or 0),
        source="spotify",
        sourceUrl=(row.get("external_urls") or {}).get("spotify")
        or f"https://open.spotify.com/album/{row['id']}",
        artistId=_first_artist_id(row),
        releaseType=_release_type(row),
        releaseDate=row.get("release_date"),
    )


def _playlist_head(row: dict[str, Any]) -> Playlist:
    owner = row.get("owner") or {}
    return Playlist(
        id=f"sp:playlist:{row['id']}",
        title=row.get("name") or "",
        owner=owner.get("display_name") or "Spotify",
        # برخلاف آلبوم (`total_tracks`)، اینجا تعداد ترک زیرِ «items» است نه «tracks»
        trackCount=int((row.get("items") or {}).get("total") or 0),
        artworkUrl=_art(row.get("images")),
        source="spotify",
        sourceUrl=(row.get("external_urls") or {}).get("spotify")
        or f"https://open.spotify.com/playlist/{row['id']}",
    )


async def search_playlists(client: httpx.AsyncClient, query: str, limit: int = 10) -> list[Playlist]:
    """
    جدا از `search` عمومی نگه داشته می‌شود (که فقط `type=album,track,artist`
    می‌زند و همه‌جای اپ استفاده می‌شود) — فقط چت‌بات وایب صدایش می‌زند، و اگر
    اندپوینتِ پلی‌لیستِ اسپاتیفای برای این کلید محدود بود (محتمل برای اپ‌های
    تازه، مثل همان محدودیتِ artist top-tracks)، نباید جستجوی عمومی را با خودش
    پایین بکشد.
    """
    if not enabled():
        return []
    body = await _get(client, "/search", q=query, type="playlist", limit=limit)
    items = (body.get("playlists") or {}).get("items") or []
    return [_playlist_head(r) for r in items if r and r.get("id")]


def _artist_head(row: dict[str, Any]) -> Artist:
    """
    پروفایل هنرمند. اسپاتیفای اینجا واقعاً عکسِ خودِ هنرمند می‌دهد (نه کاور
    آلبوم) — چیزی که اپل در جستجو ندارد.

    ژانر و تعداد دنبال‌کننده روی کلیدهای حالت توسعه در پاسخ نیستند، پس زیرنویس
    اغلب همان «هنرمند» می‌ماند.
    """
    genres = [g for g in (row.get("genres") or []) if g]
    followers = int(((row.get("followers") or {}).get("total")) or 0)
    if genres:
        subtitle = "، ".join(genres[:2])
    elif followers:
        subtitle = f"{followers:,} دنبال‌کننده"
    else:
        subtitle = UNKNOWN_ARTIST
    return Artist(
        id=f"sp:artist:{row['id']}",
        name=row.get("name") or "",
        artworkUrl=_art(row.get("images")),
        source="spotify",
        sourceUrl=(row.get("external_urls") or {}).get("spotify")
        or f"https://open.spotify.com/artist/{row['id']}",
        subtitle=subtitle,
    )


async def _all_pages(
    client: httpx.AsyncClient, path: str, page: int, cap: int = MAX_TRACKS, **params: Any
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while offset < cap:
        body = await _get(client, path, limit=page, offset=offset, **params)
        batch = body.get("items") or []
        items += batch
        if len(batch) < page or not body.get("next"):
            break
        offset += page
    return items


async def album(client: httpx.AsyncClient, album_id: str) -> AlbumDetail | None:
    head = await _get(client, f"/albums/{album_id}")
    if not head.get("id"):
        return None

    # صفحه‌ی اول ترک‌ها داخل خود پاسخ آلبوم است؛ فقط اگر بیشتر بود صفحه می‌زنیم
    rows = (head.get("tracks") or {}).get("items") or []
    if (head.get("tracks") or {}).get("next"):
        rows = await _all_pages(client, f"/albums/{album_id}/tracks", ALBUM_PAGE)

    tracks = [t for r in rows if (t := _track(r, head))]
    base = _album_head(head)
    # آواتارِ آرتیست: «Get Artist» یک درخواست بیشتر است و عکسِ واقعیِ پروفایل
    # را می‌دهد — چیزی که ردیفِ آلبوم ندارد
    base.artistArtworkUrl = await _artist_avatar(client, base.artistId)
    if base.artistArtworkUrl:
        for t in tracks:
            if not t.artistArtworkUrl:
                t.artistArtworkUrl = base.artistArtworkUrl
    return AlbumDetail(
        **base.model_dump(),
        durationMs=sum(t.durationMs for t in tracks),
        tracks=tracks,
    )


async def _artist_avatar(client: httpx.AsyncClient, artist_id: str | None) -> str | None:
    """عکسِ پروفایلِ آرتیست با «Get Artist» — شکستش فقط None می‌شود، نه خطا."""
    if not artist_id:
        return None
    try:
        head = await _get(client, f"/artists/{artist_id.rsplit(':', 1)[-1]}")
        return _art(head.get("images"))
    except Exception:
        return None


_EMBED_DATA = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


async def _embed_entity(client: httpx.AsyncClient, kind: str, spotify_id: str) -> dict[str, Any] | None:
    """
    صفحه‌ی امبدِ عمومی (همان که در iframe جاسازی می‌شود)، نه Web API.

    از نوامبر ۲۰۲۴ اسپاتیفای «Get Playlist Items» را روی توکنِ Client
    Credentials (بدون کاربر) با ۴۰۳ می‌بندد — نه فقط پلی‌لیست‌های ادیتوریال،
    هر پلی‌لیستِ عمومی. سرِ پلی‌لیست (`/playlists/{id}`) هنوز باز است ولی بی‌فایده
    است چون خودِ ترک‌ها را نمی‌شود گرفت. صفحه‌ی امبد نه کلید می‌خواهد نه این
    محدودیت را دارد و کل ترک‌لیست را در یک JSON کنار HTML می‌دهد.
    """
    res = await client.get(f"https://open.spotify.com/embed/{kind}/{spotify_id}")
    res.raise_for_status()
    if not (m := _EMBED_DATA.search(res.text)):
        return None
    data = json.loads(m.group(1))
    state = ((data.get("props") or {}).get("pageProps") or {}).get("state") or {}
    return (state.get("data") or {}).get("entity")


def _embed_art(cover: dict[str, Any] | None) -> str | None:
    sources = (cover or {}).get("sources") or []
    if not sources:
        return None
    sized = [s for s in sources if s.get("width")]
    return (max(sized, key=lambda s: s["width"]) if sized else sources[0]).get("url")


def _embed_track(row: dict[str, Any]) -> Track | None:
    uri = row.get("uri") or ""
    # آیتم‌های غیرترک (پادکست و…) هم همین شکل ردیف را دارند، فقط uri فرق دارد
    if not uri.startswith("spotify:track:"):
        return None
    track_id = uri.rsplit(":", 1)[-1]
    if not track_id:
        return None
    return Track(
        id=f"sp:track:{track_id}",
        title=row.get("title") or "",
        artist=row.get("subtitle") or "",
        durationMs=int(row.get("duration") or 0),
        source="spotify",
        sourceUrl=f"https://open.spotify.com/track/{track_id}",
        # پیش‌نمایشِ سی‌ثانیه‌ای هم همان زمان از Web API حذف شد؛ امبد هنوز دارد
        previewUrl=(row.get("audioPreview") or {}).get("url"),
        explicit=bool(row.get("isExplicit")),
    )


# همزمانیِ لوکاپِ کاورِ تک‌تک ترک‌ها — نه صفر (کاورِ درست بهتر از کاورِ پلی‌لیست
# برای همه است) نه زیاد (به ریت‌لیمیتِ اسپاتیفای می‌خوریم)
ART_CONCURRENCY = 12


_art_cache: dict[str, str | None] = {}


async def _track_arts(client: httpx.AsyncClient, tracks: list[Track]) -> dict[str, str | None]:
    """
    کاورِ آلبومِ هر ترکِ پلی‌لیست.

    ترک‌لیستِ صفحه‌ی امبد کاور ندارد. «Get Several Tracks» ی Web API هم مثل
    ترک‌های پلی‌لیست روی این کلید ۴۰۳ می‌گیرد، پس تک‌تک با «Get Track» می‌رویم.

    اپ‌های تأییدنشده سهمیه‌ی روزانه‌ی کمی روی «Get Track» دارند (صد ترک در هر
    بار دیدنِ یک پلی‌لیست، زود می‌سوزاندش). وقتی به آن سهمیه خورد، به جستجو
    (که سهمیه‌ی جداگانه دارد و معمولاً هنوز باز است) با عنوان/هنرمند برمی‌گردیم.

    با کش، دیدنِ دوباره‌ی همان پلی‌لیست یا ترکِ مشترکِ بینِ دو پلی‌لیست دیگر
    درخواستی نمی‌زند. فقط موفقیت کش می‌شود — شکست کش نمی‌شود تا بار بعد که
    سهمیه‌ی «Get Track» برگشت (دقیق‌تر از جستجوست)، دوباره امتحان شود.
    """
    sem = asyncio.Semaphore(ART_CONCURRENCY)

    def raw_id(t: Track) -> str:
        return t.id.rsplit(":", 1)[-1]

    missing = [t for t in tracks if raw_id(t) not in _art_cache]

    async def one(t: Track) -> None:
        tid = raw_id(t)
        async with sem:
            art: str | None = None
            try:
                row = await _get(client, f"/tracks/{tid}")
                art = _art((row.get("album") or {}).get("images"))
            except httpx.HTTPError:
                pass

            if not art:
                try:
                    body = await _get(
                        client, "/search", q=f'track:"{t.title}" artist:"{t.artist}"',
                        type="track", limit=1,
                    )
                    items = (body.get("tracks") or {}).get("items") or []
                    if items:
                        art = _art((items[0].get("album") or {}).get("images"))
                except httpx.HTTPError:
                    pass

            if art:
                _art_cache[tid] = art

    await asyncio.gather(*(one(t) for t in missing))
    return {raw_id(t): _art_cache.get(raw_id(t)) for t in tracks}


async def playlist(client: httpx.AsyncClient, playlist_id: str) -> AlbumDetail | None:
    entity = await _embed_entity(client, "playlist", playlist_id)
    if not entity or not entity.get("id"):
        return None

    tracks = [t for r in (entity.get("trackList") or []) if (t := _embed_track(r))]
    cover = _embed_art(entity.get("coverArt"))

    # کاورِ واقعیِ هر ترک؛ اگر لوکاپش شکست خورد یا خودِ ترک محلی/بی‌کاور بود،
    # کاورِ پلی‌لیست جای خالی‌اش را می‌گیرد تا کارت بی‌عکس نماند
    arts = await _track_arts(client, tracks)
    for t in tracks:
        t.artworkUrl = arts.get(t.id.rsplit(":", 1)[-1]) or cover

    return AlbumDetail(
        id=f"sp:playlist:{entity['id']}",
        title=entity.get("name") or "",
        artist=entity.get("subtitle") or "Spotify",
        year=0,
        artworkUrl=cover,
        trackCount=len(tracks),
        source="spotify",
        sourceUrl=f"https://open.spotify.com/playlist/{entity['id']}",
        durationMs=sum(t.durationMs for t in tracks),
        tracks=tracks,
    )


async def track(client: httpx.AsyncClient, track_id: str) -> AlbumDetail | None:
    """تک‌آهنگ هم در قالب AlbumDetail برمی‌گردد تا فرانت مسیر جدا لازم نداشته باشد."""
    row = await _get(client, f"/tracks/{track_id}")
    single = _track(row)
    if single is None:
        return None
    alb = row.get("album") or {}
    return AlbumDetail(
        id=f"sp:track:{row['id']}",
        title=single.title,
        artist=single.artist,
        year=_year(alb.get("release_date")) or 0,
        artworkUrl=single.artworkUrl,
        trackCount=1,
        source="spotify",
        sourceUrl=single.sourceUrl,
        durationMs=single.durationMs,
        tracks=[single],
    )


async def artist(client: httpx.AsyncClient, artist_id: str) -> ArtistDetail | None:
    """
    صفحه‌ی هنرمند: ترک‌های محبوب به‌علاوه‌ی دیسکوگرافی.

    ترک‌های محبوب روی کلیدهای حالت توسعه ۴۰۳ می‌گیرند (اسپاتیفای این اندپوینت را
    برای اپ‌های جدید بست). صفحه بدون آن هم کار می‌کند — دیسکوگرافی سرِ جایش است و
    دانلود از صفحه‌ی آلبوم انجام می‌شود — پس خطایش خورده می‌شود و صدا نمی‌کند.
    """
    head, top, albums = await asyncio.gather(
        _get(client, f"/artists/{artist_id}"),
        _get(client, f"/artists/{artist_id}/top-tracks", market=MARKET),
        _all_pages(
            client,
            f"/artists/{artist_id}/albums",
            ARTIST_ALBUM_PAGE,
            ARTIST_ALBUMS,
            include_groups="album,single",
            market=MARKET,
        ),
        # سرِ صفحه بدون ترک و آلبوم هم به کار می‌آید؛ عکسِ خودِ هنرمند فقط همان‌جاست
        return_exceptions=True,
    )
    if not isinstance(head, dict) or not head.get("id"):
        return None

    tracks = (
        [t for r in (top.get("tracks") or []) if (t := _track(r))]
        if isinstance(top, dict)
        else []
    )

    discography: list[Album] = []
    if isinstance(albums, list):
        # اسپاتیفای آلبوم‌ها را گروه‌به‌گروه می‌دهد (اول album ها بعد single ها) و
        # صفحه‌ی خودش تازه‌به‌قدیم نشان می‌دهد. با تاریخِ کامل مرتب می‌کنیم نه سال،
        # چون هنرمندی که در یک سال ده سینگل داده وگرنه ترتیبِ دلبخواه می‌گیرد.
        rows = sorted(albums, key=lambda r: r.get("release_date") or "", reverse=True)

        # حتی با `market` هم یک آلبوم چند بار می‌آید (نسخه‌ی معمولی، دیلاکس،
        # ری‌ایشو). با شناسه یکتا نمی‌شود چون شناسه‌شان واقعاً فرق دارد.
        seen: set[tuple[str, int]] = set()
        for row in rows:
            if not row.get("id"):
                continue
            album_row = _album_head(row)
            key = (album_row.title.strip().lower(), album_row.year)
            if key in seen:
                continue
            seen.add(key)
            discography.append(album_row)

    base = _artist_head(head)
    if base.artworkUrl:
        for t in tracks:
            if not t.artistArtworkUrl:
                t.artistArtworkUrl = base.artworkUrl
    if base.subtitle == UNKNOWN_ARTIST and discography:
        # کلیدِ حالت توسعه ژانر و دنبال‌کننده را هم نمی‌دهد، پس زیرنویس «هنرمند»
        # خالی می‌ماند. تعداد آلبوم را همین‌جا داریم و مثل دیزر گویاتر است.
        base.subtitle = f"{len(discography)} آلبوم"
    return ArtistDetail(**base.model_dump(), topTracks=tracks, albums=discography)


# ---------- صفحه‌ی کاربر ----------
#
# کاربرِ عادی (نه هنرمند) هم صفحه دارد و رویش پلی‌لیست‌های عمومی‌اش نشسته —
# لینکی که در تلگرام دست‌به‌دست می‌شود اغلب همین است.
#
# از Web API نمی‌آید: هم «Get User's Profile» هم «Get User's Playlists» روی
# توکنِ client-credentials ۴۰۳ می‌دهند (اپِ حالت توسعه فقط داده‌ی کاربرهای
# allowlist خودش را می‌بیند)، و کلیدِ تأییدشده هم اینجا فرقی نمی‌کند چون
# پروژه باید بدون کلید هم این صفحه را باز کند.
#
# صفحه‌ی عمومیِ پروفایل برای خزنده‌ها سمت سرور رندر می‌شود و همان فهرستِ
# «Public Playlists» را در HTML دارد. یک شرط دارد: با User-Agent ی که شبیه
# مرورگرِ دسکتاپ باشد، اسپاتیفای به‌جای آن نسخه‌ی خالیِ وب‌پلیر را می‌دهد و
# هیچ لینکِ پلی‌لیستی در HTML نیست. UA ی خودِ اپ («MusicBazi/…») و حتی نداشتنِ
# UA هر دو نسخه‌ی رندرشده را می‌گیرند — پس اینجا عمداً هیچ UA ی مرورگرمانندی
# ست نمی‌شود.
_META_TAG = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r'([a-zA-Z:_-]+)="([^"]*)"')
_PROFILE_PLAYLIST = re.compile(r'<a\b[^>]*href="/playlist/([A-Za-z0-9]+)"[^>]*>(.*?)</a>', re.S | re.I)
_SPAN = re.compile(r"<span[^>]*>(.*?)</span>", re.S | re.I)
_IMG_SRC = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"', re.I)
_TAGS = re.compile(r"<[^>]+>")

# زیرنویسِ کاربری که هیچ پلی‌لیستِ عمومی‌ای ندارد
UNKNOWN_USER = "کاربر"


def _meta(html: str, key: str) -> str | None:
    """محتوای یک متاتگ، بی‌توجه به ترتیبِ صفت‌ها و `property` یا `name` بودنش."""
    for tag in _META_TAG.finditer(html):
        attrs = dict(_ATTR.findall(tag.group(0)))
        if key in (attrs.get("property"), attrs.get("name")):
            return unescape(attrs.get("content") or "").strip() or None
    return None


def _text(html: str) -> str:
    return unescape(_TAGS.sub("", html)).strip()


def _profile_playlists(html: str, owner: str) -> list[Playlist]:
    """
    پلی‌لیست‌های عمومیِ صفحه‌ی پروفایل، به همان ترتیبی که خودِ اسپاتیفای چیده.

    هر کارت یک `<a href="/playlist/…">` است با کاور و دو `<span`: عنوان و
    تعداد لایک. تعدادِ ترک در این صفحه اصلاً نیست، پس `trackCount` صفر می‌ماند
    و فرانت جای عددِ دروغ چیزی نشان نمی‌دهد.
    """
    found: list[Playlist] = []
    seen: set[str] = set()
    for playlist_id, inner in _PROFILE_PLAYLIST.findall(html):
        if playlist_id in seen:
            continue
        seen.add(playlist_id)
        spans = _SPAN.findall(inner)
        title = _text(spans[0]) if spans else ""
        cover = _IMG_SRC.search(inner)
        found.append(
            Playlist(
                id=f"sp:playlist:{playlist_id}",
                title=title or playlist_id,
                owner=owner,
                trackCount=0,
                artworkUrl=unescape(cover.group(1)) if cover else None,
                source="spotify",
                sourceUrl=f"https://open.spotify.com/playlist/{playlist_id}",
            )
        )
    return found


async def user(client: httpx.AsyncClient, user_id: str) -> ArtistDetail | None:
    """
    صفحه‌ی یک کاربر: نام و آواتار و پلی‌لیست‌های عمومی‌اش.

    همان `ArtistDetail` برمی‌گردد که صفحه‌ی هنرمند — با `kind="user"` و بدون
    دیسکوگرافی — تا فرانت مسیر و صفحه‌ی جدا لازم نداشته باشد. برخلاف بقیه‌ی
    این ماژول کلید نمی‌خواهد.
    """
    res = await client.get(f"https://open.spotify.com/user/{user_id}")
    if res.status_code == 404:
        return None  # چنین کاربری نیست
    res.raise_for_status()
    html = res.text

    # صفحه‌ی کاربرِ ناموجود گاهی به‌جای ۴۰۴، پوسته‌ی خالیِ وب‌پلیر است؛ آن پوسته
    # `og:type` ی profile ندارد و بدون این شرط، یک صفحه‌ی بی‌نام و بی‌محتوا
    # به‌عنوان «کاربر» باز می‌شد
    if _meta(html, "og:type") != "profile":
        return None
    name = _meta(html, "og:title") or user_id

    playlists = _profile_playlists(html, name)
    return ArtistDetail(
        id=f"sp:user:{user_id}",
        name=name,
        artworkUrl=_meta(html, "og:image"),
        source="spotify",
        sourceUrl=_meta(html, "og:url") or f"https://open.spotify.com/user/{user_id}",
        subtitle=f"{len(playlists)} پلی‌لیست" if playlists else UNKNOWN_USER,
        kind="user",
        playlists=playlists,
    )


async def search(client: httpx.AsyncClient, query: str, limit: int = 10) -> SearchResults:
    """
    جستجوی اسپاتیفای فقط وقتی صدا زده می‌شود که کلید ست باشد.

    هنرمند هم می‌خواهیم تا بخش «هنرمندان» کارتِ اسپاتیفای هم داشته باشد. یک
    درخواست بیشتر نمی‌شود؛ `type` چندتایی در همان یک فراخوانی جواب می‌دهد.
    """
    body = await _get(client, "/search", q=query, type="album,track,artist", limit=limit)
    tracks = [t for r in ((body.get("tracks") or {}).get("items") or []) if (t := _track(r))]
    albums = [
        _album_head(r) for r in ((body.get("albums") or {}).get("items") or []) if r.get("id")
    ]
    artists = [
        _artist_head(r) for r in ((body.get("artists") or {}).get("items") or []) if r.get("id")
    ]
    return SearchResults(query=query, tracks=tracks, albums=albums, artists=artists)
