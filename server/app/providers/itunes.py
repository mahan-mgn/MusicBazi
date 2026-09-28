"""iTunes Search API — عمومی، بدون کلید، سخاوتمند برای موسیقی فارسی."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from ..artwork import DISPLAY, resized
from ..config import ITUNES_API, SEARCH_LIMIT
from ..models import Album, AlbumDetail, Artist, ArtistDetail, SearchResults, Track

# https://music.apple.com/us/album/mard-e-tanha/1801042661?i=1801042670
ALBUM_URL = re.compile(r"music\.apple\.com/(?:[a-z]{2}/)?album/(?:[^/\s]+/)?(\d+)", re.I)
ARTIST_URL = re.compile(r"music\.apple\.com/(?:[a-z]{2}/)?artist/(?:[^/\s]+/)?(\d+)", re.I)

# صفحه‌ی هنرمند روی وب. شناسه بس است و اپل خودش به آدرسِ نام‌دار ریدایرکت می‌کند.
ARTIST_PAGE = "https://music.apple.com/us/artist/{id}"


def artwork(url: str | None, size: int = DISPLAY) -> str | None:
    """
    کاورهای اپل با اندازه در نام فایل می‌آیند؛ به اندازه‌ی دلخواه بزرگش می‌کنیم.
    جستجو همیشه `artworkUrl100` می‌دهد که برای نمایش تار است.
    """
    return resized(url, size)


def _track(row: dict[str, Any]) -> Track:
    return Track(
        id=f"itunes:track:{row['trackId']}",
        title=row.get("trackName") or "",
        artist=row.get("artistName") or "",
        album=row.get("collectionName"),
        albumId=f"itunes:album:{row['collectionId']}" if row.get("collectionId") else None,
        durationMs=int(row.get("trackTimeMillis") or 0),
        artworkUrl=artwork(row.get("artworkUrl100")),
        source="apple",
        sourceUrl=row.get("trackViewUrl") or "",
        # ناوبری «کلیک روی نام هنرمند» در ردیف آلبوم به همین شناسه تکیه دارد —
        # deezer/spotify/yt همه می‌دهند، اپل هم که در همان ردیف هست
        artistId=f"itunes:artist:{row['artistId']}" if row.get("artistId") else None,
        previewUrl=row.get("previewUrl"),
        explicit=row.get("trackExplicitness") == "explicit",
        trackNumber=row.get("trackNumber"),
        discNumber=row.get("discNumber"),
        year=_year(row.get("releaseDate")),
        genre=row.get("primaryGenreName"),
    )


def _year(release_date: str | None) -> int | None:
    """`2025-03-14T12:00:00Z` → ۲۰۲۵. تاریخ ناقص یا غایب یعنی «نمی‌دانیم»."""
    head = (release_date or "")[:4]
    return int(head) if head.isdigit() else None


def _own_release(row: dict[str, Any], artist_id: Any) -> bool:
    """
    آیا این کالکشن مالِ خودِ هنرمند است، نه compilation که فقط توش ظاهر شده؟

    `lookup?entity=album` هر دو را می‌دهد. اگر `collectionArtistId` با شناسه‌ی
    هنرمند فرق دارد، یا نوع صریحاً Compilation است، مالِ دیگران است.
    """
    if (row.get("collectionType") or "").lower() == "compilation":
        return False
    owner = row.get("collectionArtistId")
    if owner is not None and artist_id is not None and str(owner) != str(artist_id):
        return False
    return True


def _release_type(row: dict[str, Any]) -> str | None:
    """
    دسته‌ی انتشار از کالکشنِ اپل.

    `collectionType == Compilation` صریح است. بقیه از تعداد ترک حدس زده
    می‌شود: یک ترک سینگل، دو تا شش EP، بیشتر آلبوم.
    """
    kind = (row.get("collectionType") or "").lower()
    if kind == "compilation":
        return "compilation"
    tracks = int(row.get("trackCount") or 0)
    if tracks == 1:
        return "single"
    if 2 <= tracks <= 6:
        return "ep"
    if tracks > 6:
        return "album"
    return None


def _album(row: dict[str, Any], artist: dict[str, Any] | None = None) -> Album:
    """
    ردیفِ کالکشن به آلبوم.

    `artist` برای فهرستِ دیسکوگرافی می‌آید: آن ردیف‌ها آرتیست‌آیدیِ خودشان را
    همراه ندارند و بدون این، کارتِ آلبوم در صفحه‌ی هنرمند بی‌شناسه می‌ماند و
    «آثار دیگرِ همین هنرمند» وقتی از همان‌جا باز شود پر نمی‌شود.
    """
    artist_id = artist.get("artistId") if artist else row.get("artistId")
    return Album(
        id=f"itunes:album:{row['collectionId']}",
        title=row.get("collectionName") or "",
        artist=row.get("artistName") or "",
        year=_year(row.get("releaseDate")) or 0,
        artworkUrl=artwork(row.get("artworkUrl100")),
        trackCount=int(row.get("trackCount") or 0),
        source="apple",
        sourceUrl=row.get("collectionViewUrl") or "",
        artistId=f"itunes:artist:{artist_id}" if artist_id else None,
        releaseType=_release_type(row),
        releaseDate=(row.get("releaseDate") or "")[:10] or None,
    )


def _artist(row: dict[str, Any], artwork_url: str | None = None) -> Artist:
    return Artist(
        id=f"itunes:artist:{row['artistId']}",
        name=row.get("artistName") or "",
        # iTunes Search عکس هنرمند نمی‌دهد؛ از صفحه‌ی وب می‌آید (`artist_images`)
        artworkUrl=artwork_url,
        source="apple",
        # `artistLinkUrl` روی ردیفِ `lookup` همیشه هست ولی روی بعضی پاسخ‌ها
        # (مثلاً `entity=song`) غایب است؛ بدون این فالبک، دکمه‌ی «باز کردن منبع»
        # و کپیِ لینکِ صفحه‌ی هنرمند بی‌صدا می‌افتادند
        sourceUrl=row.get("artistLinkUrl") or ARTIST_PAGE.format(id=row["artistId"]),
        subtitle=row.get("primaryGenreName") or "هنرمند",
    )


# --- عکس پروفایل هنرمند ---------------------------------------------------
#
# iTunes Search API عکسِ هنرمند ندارد — نه در `search` نه در `lookup`. بقیه‌ی
# پلتفرم‌ها دارند، پس در نتیجه‌ی جستجو کارتِ اپل تنها کارتی بود که فقط حرفِ اولِ
# نام را نشان می‌داد. تنها جایی که اپل این عکس را عمومی می‌دهد صفحه‌ی وبِ خودِ
# هنرمند است: هم در `og:image` و هم در JSONِ سمت‌سرور، هر دو یک آدرس.
#
# `amp-api` (همان چیزی که خودِ سایت صدا می‌زند) توکنِ developer می‌خواهد و توکن
# هم دیگر داخل باندلِ جاوااسکریپت نیست، پس این مسیر باز نیست.

# هر دو ترتیبِ صفت پوشش داده می‌شود؛ اپل ترتیبش را تضمین نکرده.
_OG_IMAGE = re.compile(
    r'<meta[^>]+?(?:property|name)="og:image"[^>]*?content="([^"]*)"'
    r'|<meta[^>]+?content="([^"]*)"[^>]*?(?:property|name)="og:image"',
    re.I,
)

# دُمِ آدرسِ mzstatic: اندازه به‌علاوه‌ی کدِ برش — `1200x630cw.png`
_CROP = re.compile(r"/\d+x\d+[a-z]{2}(?:-\d+)?\.(?:jpg|png|webp)$", re.I)

# صفحه‌ی هنرمند حدود ۴۰۰ کیلوبایت است ولی `og:image` در `<head>` و در چند
# کیلوبایتِ اول می‌آید. استریم می‌کنیم و به‌محضِ پیدا شدنش وصل را می‌بندیم؛
# این سقف فقط برای صفحه‌ای است که اصلاً `og:image` ندارد و وگرنه تا آخر
# می‌خواندیمش.
_HEAD_LIMIT = 64 * 1024

# هشت هنرمندِ نتیجه‌ی جستجو با هم می‌روند: پشت‌سرهم، هر جستجو چند ثانیه کندتر
# می‌شد. تایم‌اوت از تایم‌اوتِ عمومیِ کلاینت کوتاه‌تر است — عکسِ پروفایل ارزشِ
# منتظر نگه داشتنِ کلِ نتیجه‌ی جستجو را ندارد.
ARTIST_IMAGE_CONCURRENCY = 8
ARTIST_IMAGE_TIMEOUT = 6.0

# نتیجه‌ی هر شناسه تا ری‌استارتِ بعدی می‌ماند. «عکس ندارد» هم کش می‌شود:
# جستجوی دوباره‌ی همان نام نباید همان هشت صفحه را دوباره بگیرد. فقط خطای شبکه
# کش نمی‌شود تا بار بعد دوباره امتحان شود.
_image_cache: dict[str, str | None] = {}


def _square(url: str) -> str | None:
    """
    `og:image` یک برشِ عریضِ ۱۲۰۰×۶۳۰ برای پیش‌نمایشِ لینک است؛ کارتِ هنرمند
    مربع (و گرد) است. همان تصویر با کدِ برشِ `cc` مربع می‌آید — همان کدی که
    خودِ اپل‌موزیک برای آواتارهای گردش استفاده می‌کند.

    هنرمندی که عکس ندارد لوگوی خودِ اپل‌موزیک را می‌گیرد
    (`music.apple.com/assets/meta/apple-music.png`). آن لوگو روی هر کارت یکی
    است و از حرفِ اولِ نام هم بی‌فایده‌تر — پس رد می‌شود و کارت به همان حالتِ
    قبلی برمی‌گردد.
    """
    if "mzstatic.com" not in url:
        return None
    return _CROP.sub(f"/{DISPLAY}x{DISPLAY}cc.jpg", url)


async def _artist_image(client: httpx.AsyncClient, artist_id: str) -> str | None:
    buf = ""
    async with client.stream(
        "GET", ARTIST_PAGE.format(id=artist_id), timeout=ARTIST_IMAGE_TIMEOUT
    ) as res:
        if res.status_code != 200:
            return None
        async for chunk in res.aiter_text():
            buf += chunk
            if m := _OG_IMAGE.search(buf):
                return _square(m.group(1) or m.group(2))
            if len(buf) >= _HEAD_LIMIT:
                break
    return None


async def artist_images(
    client: httpx.AsyncClient, artist_ids: list[str]
) -> dict[str, str | None]:
    """عکس پروفایلِ چند هنرمند با هم. شناسه‌ای که نشد، `None` می‌گیرد."""
    sem = asyncio.Semaphore(ARTIST_IMAGE_CONCURRENCY)

    async def one(artist_id: str) -> None:
        async with sem:
            try:
                _image_cache[artist_id] = await _artist_image(client, artist_id)
            except (httpx.HTTPError, UnicodeDecodeError):
                pass  # شبکه؛ دفعه‌ی بعد دوباره

    await asyncio.gather(
        *(one(i) for i in dict.fromkeys(artist_ids) if i not in _image_cache)
    )
    return {i: _image_cache.get(i) for i in artist_ids}


async def _get(client: httpx.AsyncClient, path: str, **params: Any) -> list[dict[str, Any]]:
    res = await client.get(f"{ITUNES_API}{path}", params=params)
    res.raise_for_status()
    # iTunes گاهی content-type اشتباه برمی‌گرداند، پس دستی پارس می‌کنیم
    return res.json().get("results", [])


async def search(client: httpx.AsyncClient, query: str) -> SearchResults:
    # سه فراخوانی مستقل‌اند — پشت‌سرهم زدنشان زمان جستجو را سه برابر می‌کند
    songs, albums, artists = await asyncio.gather(
        _get(client, "/search", term=query, entity="song", limit=SEARCH_LIMIT),
        _get(client, "/search", term=query, entity="album", limit=SEARCH_LIMIT),
        _get(client, "/search", term=query, entity="musicArtist", limit=8),
    )
    # عکس‌ها نمی‌توانند در همان `gather` باشند: شناسه‌ها تازه از همین جستجو
    # درمی‌آیند. با کش، همان جستجو بار دوم درخواستی اضافه نمی‌زند.
    found = [r for r in artists if r.get("artistId")]
    images = await artist_images(client, [str(r["artistId"]) for r in found])
    return SearchResults(
        query=query,
        tracks=[_track(r) for r in songs if r.get("trackId")],
        albums=[_album(r) for r in albums if r.get("collectionId")],
        artists=[_artist(r, images.get(str(r["artistId"]))) for r in found],
        playlists=[],  # iTunes Search پلی‌لیست ندارد — از دیزر می‌آید
    )


async def album(client: httpx.AsyncClient, collection_id: str) -> AlbumDetail | None:
    rows = await _get(client, "/lookup", id=collection_id, entity="song", limit=200)
    head = next((r for r in rows if r.get("wrapperType") == "collection"), None)
    if head is None:
        return None

    # lookup از قبل به ترتیب دیسک/شماره‌ی ترک می‌آید
    tracks = [
        _track(r)
        for r in rows
        if r.get("wrapperType") == "track" and r.get("kind") == "song" and r.get("trackId")
    ]
    base = _album(head)
    # آلبوم از lookup آرتیست‌آیدی و آواتار را می‌دهد؛ iTunes خودش عکسِ
    # آرتیست نمی‌دهد ولی همین آدرسِ صفحه برای ناوبری کافی است
    base.artistId = f"itunes:artist:{head.get('artistId')}" if head.get("artistId") else None
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


async def artist(client: httpx.AsyncClient, artist_id: str) -> ArtistDetail | None:
    """صفحه‌ی هنرمند: دیسکوگرافی به‌علاوه‌ی ترک‌های شناخته‌شده‌اش."""
    albums, songs, images = await asyncio.gather(
        _get(client, "/lookup", id=artist_id, entity="album", limit=100),
        _get(client, "/lookup", id=artist_id, entity="song", limit=25),
        artist_images(client, [str(artist_id)]),
    )

    head = next((r for r in albums if r.get("wrapperType") == "artist"), None) or next(
        (r for r in songs if r.get("wrapperType") == "artist"), None
    )
    if head is None:
        return None

    # با تاریخِ کامل مرتب می‌شود نه با سال: هنرمندی که در یک سال شش سینگل داده
    # وگرنه ترتیبشان دلبخواه می‌شد، درحالی‌که صفحه‌ی خودِ اپل‌موزیک تازه‌ترین را
    # اول می‌گذارد.
    #
    # `lookup?entity=album` هر کالکشنی که هنرمند توش باشد می‌آورد — از جمله
    # compilation دیگران. آن‌ها دیسکوگرافی این هنرمند نیستند.
    own_id = head.get("artistId")
    discography = [
        _album(r, head)
        for r in sorted(albums, key=lambda r: r.get("releaseDate") or "", reverse=True)
        if r.get("collectionId") and _own_release(r, own_id)
    ]
    top = [_track(r) for r in songs if r.get("trackId")]

    base = _artist(head, images.get(str(artist_id)))
    final_art = base.artworkUrl or next((a.artworkUrl for a in discography if a.artworkUrl), None)
    if final_art:
        for t in top:
            if not t.artistArtworkUrl:
                t.artistArtworkUrl = final_art
    return ArtistDetail(
        **base.model_dump(exclude={"artworkUrl"}),
        # هنرمندی که در اپل‌موزیک عکس ندارد (یا صفحه‌اش نیامد): کاور تازه‌ترین
        # آلبوم نزدیک‌ترین چیز است
        artworkUrl=final_art,
        topTracks=top,
        albums=discography,
    )


async def _artist_avatar(client: httpx.AsyncClient, artist_ref: str | None) -> str | None:
    """
    عکسِ پروفایلِ آرتیستِ اپل‌موزیک.

    iTunes Search عکسِ هنرمند نمی‌دهد؛ `artist_images` آن را از صفحه‌ی وب
    می‌کَند و فقط شناسه‌ی عددی می‌خواهد. شکستش فقط None می‌شود — صفحه‌ی آلبوم
    نباید به‌خاطرِ یک عکس بیفتد.
    """
    if not artist_ref:
        return None
    ident = artist_ref.rsplit(":", 1)[-1]
    try:
        images = await artist_images(client, [ident])
        return images.get(ident)
    except Exception:
        return None


def parse_url(url: str) -> tuple[str, str] | None:
    """('album', id) اگر لینک اپل‌موزیک باشد."""
    if m := ALBUM_URL.search(url):
        return "album", m.group(1)
    if m := ARTIST_URL.search(url):
        return "artist", m.group(1)
    return None


__all__ = ["search", "album", "artist", "artist_images", "parse_url", "artwork"]
