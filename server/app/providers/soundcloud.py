"""
متادیتای ترک‌های ساندکلاد از api-v2 — عمومی، فقط client_id می‌خواهد.

چرا کنار yt-dlp یکی دیگر: استخراج تختِ (`extract_flat`) یک «ست» ساندکلاد فقط
شناسه و لینک ترک‌ها را برمی‌گرداند و عنوان/مدت/کاور را نه — همان چیزی که آلبوم
را با یک مشت ترکِ بی‌نام و «ناشناس» نشان می‌داد. استخراج کامل این‌ها را دارد،
ولی به ازای هر ترک چند درخواستِ فرمت می‌زند و یک ترکِ DRMدار کل آلبوم را
می‌ترکاند. این اندپوینت هر پنجاه ترک را در یک درخواست و بدون لمس فرمت‌ها می‌دهد.
"""

from __future__ import annotations

import logging
import re
import threading
from urllib.parse import parse_qsl, urlsplit
from collections.abc import Callable
from typing import Any

import httpx

from ..config import HTTP_TIMEOUT, SEARCH_LIMIT, SOUNDCLOUD_CLIENT_ID, SOUNDCLOUD_ENABLED, YTDLP_PROXY
from ..models import Album, Artist, Playlist

log = logging.getLogger(__name__)

API = "https://api-v2.soundcloud.com"

# api-v2 لیست شناسه‌های بلندتر از این را با ۴۰۰ رد می‌کند
BATCH = 50

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_SCRIPT_SRC = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']')
_CLIENT_ID = re.compile(r'client_id\s*:\s*["\']([0-9a-zA-Z]{32})["\']')
# اندازه در نام فایلِ کاور است؛ large یعنی ۱۰۰ پیکسل و برای گرید کم است
_ARTWORK_SIZE = re.compile(r"-[0-9a-z]+\.(jpg|png)$", re.I)

# شناسه‌های عمومی شناخته‌شده برای مواقعی که اسکرپ مستقیم شکست می‌خورد
_FALLBACK_CLIENT_IDS = [
    "Pb72ranhoyt6gw7hM7TkzUItXlMWSNSo",
    "d2a233b8a1351119aa6734c2ab5215ff",
    "2t9loNfhTwNDjflNYC5FI6TAtupIVYBa",
]

# client_id عمر دارد و عوض می‌شود. تا وقتی کار می‌کند نگهش می‌داریم تا هر آلبوم
# دو درخواستِ اضافه برای پیدا کردنش نزند.
_cached_id: str | None = None
_id_lock = threading.Lock()


def enabled() -> bool:
    """آیا کاتالوگ ساندکلاد فعال است؟"""
    return SOUNDCLOUD_ENABLED


def _http() -> httpx.Client:
    # همان پروکسی‌ای که yt-dlp با آن ساندکلاد را می‌خواند — اگر خودِ ساندکلاد
    # مستقیم در دسترس نباشد، این درخواست‌ها هم نیستند
    return httpx.Client(
        timeout=HTTP_TIMEOUT,
        proxy=YTDLP_PROXY,
        headers={"User-Agent": UA},
        follow_redirects=True,
    )


def _scrape_client_id(http: httpx.Client) -> str | None:
    """
    client_id را از جاوااسکریپتِ خودِ سایت درمی‌آورد — همان کاری که yt-dlp می‌کند.

    تنها نکته‌ی مهم این است که این تابع فقط *یک بار* در لحظه باید اجرا شود:
    درخواست‌های موازیِ جستجو (ترک/آلبوم/پلی‌لیست/کاربر در `_soundcloud_search`)
    هم‌زمان این را صدا می‌زدند و هر کدام دوباره از صفحه‌ی ساندکلاد درمی‌آوردند.
    با قفل، دومین/سومین درخواست از همان کشِ تازه استفاده می‌کنند.
    """
    global _cached_id
    with _id_lock:
        if _cached_id:
            return _cached_id
        fresh = _scrape_client_id_unlocked(http)
        if fresh:
            _cached_id = fresh
        return fresh


def _scrape_client_id_unlocked(http: httpx.Client) -> str | None:
    """بدون قفل — فقط از داخل `_scrape_client_id` صدا زده می‌شود."""
    try:
        page = http.get("https://soundcloud.com/")
        page.raise_for_status()
        # آخرین اسکریپت‌ها همان‌هایی‌اند که client_id در آن‌هاست
        for src in reversed(_SCRIPT_SRC.findall(page.text)):
            try:
                script = http.get(src)
                script.raise_for_status()
            except httpx.HTTPError:
                continue
            if m := _CLIENT_ID.search(script.text):
                return m.group(1)
    except Exception as exc:
        log.debug("Scraping soundcloud client_id failed: %s", exc)

    # اگر اسکرپ مستقیم نشد، از yt-dlp کمک می‌گیریم
    try:
        import yt_dlp

        y = yt_dlp.YoutubeDL({"quiet": True})
        ie = yt_dlp.extractor.soundcloud.SoundcloudIE(y)
        ie._update_client_id()
        if cid := getattr(ie, "_CLIENT_ID", None):
            return cid
    except Exception:
        pass

    return None


def _fetch(http: httpx.Client, ids: list[str], client_id: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), BATCH):
        res = http.get(
            f"{API}/tracks",
            params={"ids": ",".join(ids[i : i + BATCH]), "client_id": client_id},
        )
        res.raise_for_status()
        for row in res.json() or []:
            if row.get("id"):
                rows[str(row["id"])] = row
    return rows


def _with_client_id(
    call: Callable[[httpx.Client, str], Any], hint: str | None = None
) -> Any:
    """
    `call` را با یک client_id معتبر اجرا می‌کند و اگر سوخته بود یکی تازه می‌گیرد.

    ترتیبِ امتحان: کشِ درونِ ماژول، hint (client_idی که yt-dlp خودش به دست آورده)،
    بعد اسکرپِ تازه از سایت. اگر هیچ‌کدام جواب نداد، شناسه‌ی پیکربندی یا یدکی‌ها.
    هر ۴۰۱/۴۰۳ یعنی آن شناسه مُرده و باید رد شود، نه اینکه کلِ جستجو بمیرد.
    """
    global _cached_id

    known = list(dict.fromkeys(c for c in (_cached_id, hint) if c))
    tried: set[str] = set()

    with _http() as http:
        def attempt(client_id: str) -> Any:
            global _cached_id
            out = call(http, client_id)
            with _id_lock:
                _cached_id = client_id
            return out

        for client_id in [*known, None]:
            if client_id is None:
                # هیچ‌کدام از کشده‌ها کار نکرد؛ یکی تازه از سایت درمی‌آوریم
                client_id = _scrape_client_id(http)
                if not client_id or client_id in tried:
                    break
            tried.add(client_id)
            try:
                return attempt(client_id)
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (401, 403):
                    raise

        # اسکرپ هم جواب نداد — شناسه‌های پیکربندی و یدکی می‌مانند
        for fallback_id in (SOUNDCLOUD_CLIENT_ID, *_FALLBACK_CLIENT_IDS):
            if not fallback_id or fallback_id in tried:
                continue
            tried.add(fallback_id)
            try:
                return attempt(fallback_id)
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (401, 403):
                    raise

    raise httpx.HTTPError("client_id معتبری برای ساندکلاد پیدا نشد")


def tracks(ids: list[str], hint: str | None = None) -> dict[str, dict[str, Any]]:
    """ترک‌ها را با شناسه می‌گیرد؛ کلیدِ خروجی همان شناسه است."""
    return _with_client_id(lambda http, cid: _fetch(http, ids, cid), hint)


def _upsize(url: str | None) -> str | None:
    if not url:
        return None
    return _ARTWORK_SIZE.sub(r"-t500x500.\1", url)


def _artwork(row: dict[str, Any]) -> str | None:
    return _upsize(row.get("artwork_url") or (row.get("user") or {}).get("avatar_url"))


def as_entry(row: dict[str, Any]) -> dict[str, Any]:
    """ردیفِ api-v2 را به شکل یک entry ی yt-dlp درمی‌آورد."""
    user = row.get("user") or {}
    publisher = row.get("publisher_metadata") or {}
    track_set = row.get("set") or {}
    row_album = row.get("album")
    album_title = (
        publisher.get("album_title")
        or (row_album.get("title") if isinstance(row_album, dict) else row_album)
        or (track_set.get("title") if isinstance(track_set, dict) else None)
    )
    duration = row.get("duration") or row.get("full_duration") or 0
    set_id = track_set.get("id") or (row_album.get("id") if isinstance(row_album, dict) else None)
    return {
        "title": row.get("title") or "",
        # فقط ترکِ رسماً منتشرشده ناشر دارد؛ بقیه با جدا کردن «هنرمند - عنوان»
        # از خودِ تیتر حدس زده می‌شوند
        "artist": publisher.get("artist") or "",
        "uploader": user.get("username") or "",
        "uploader_id": str(user.get("id")) if user.get("id") else "",
        "user_id": str(user.get("id")) if user.get("id") else "",
        "album": album_title,
        "set_id": str(set_id) if set_id else "",
        "duration": duration / 1000,
        "thumbnail": _artwork(row),
        "webpage_url": row.get("permalink_url") or "",
        "release_date": row.get("release_date") or row.get("created_at") or "",
        # صفحه‌ی هنرمند محبوب‌ها را با همین می‌چیند؛ جستجو نادیده‌اش می‌گیرد
        "playback_count": int(row.get("playback_count") or 0),
    }


def _api(path: str, **params: Any) -> Any:
    """یک GET روی api-v2 با client_id معتبر — و اگر سوخته بود، با یکی تازه."""

    def call(http: httpx.Client, client_id: str) -> Any:
        # next_href را خودِ API برمی‌گرداند؛ حفظ query آن برای صفحه‌بندی لازم است.
        url = path if path.startswith(f"{API}/") else f"{API}{path}"
        res = http.get(url, params={**params, "client_id": client_id})
        res.raise_for_status()
        return res.json()

    return _with_client_id(call)


def _collection(path: str, **params: Any) -> list[dict[str, Any]]:
    """
    اندپوینت‌های لیستی جواب را در `collection` می‌پیچند، ولی نه همه — بعضی‌شان
    (مثل ترک‌های یک کاربر) آرایه‌ی خالی می‌دهند.
    """
    requested = max(0, int(params.get("limit", BATCH)))
    if not requested:
        return []
    page_size = min(BATCH, requested)
    page_params = {**params, "limit": page_size}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    while len(rows) < requested:
        body = _api(path, **page_params)
        if isinstance(body, list):
            page = body
            next_href = None
        else:
            body = body or {}
            page = body.get("collection") or []
            next_href = body.get("next_href")
        fresh = []
        for row in page:
            key = str(row.get("id") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            fresh.append(row)
        rows.extend(fresh)
        if not next_href or not fresh:
            break
        parsed = urlsplit(next_href)
        if parsed.netloc and parsed.netloc != urlsplit(API).netloc:
            break
        path = parsed.path
        page_params = dict(parse_qsl(parsed.query))
        page_params.pop("client_id", None)
        page_params["limit"] = min(BATCH, requested - len(rows))
    return rows[:requested]


def _search(path: str, query: str, limit: int) -> list[dict[str, Any]]:
    return _collection(path, q=query, limit=limit)


def search_tracks(query: str, limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
    """
    جستجوی ترک — خروجی entryهای yt-dlp شکل است، نه Track.

    عمداً از `scsearch` ی خودِ yt-dlp استفاده نمی‌کنیم: آن به ازای هر نتیجه یک
    استخراج جدا می‌زند، در حالی که این اندپوینت کل صفحه را با متادیتای کامل در
    یک درخواست می‌دهد.
    """
    return _entries(_search("/search/tracks", query, limit))


def _entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**as_entry(row), "id": str(row["id"])}
        for row in rows
        # بی‌لینک یعنی غیرقابل دانلود، و BLOCK یعنی از این IP پخش نمی‌شود —
        # همان IP ای که خودِ دانلود هم از آن می‌رود، پس نتیجه‌ی مرده است
        if row.get("id") and row.get("permalink_url") and row.get("policy") != "BLOCK"
    ]


def _year(value: Any) -> int:
    """
    سالِ انتشار، یا صفر وقتی تاریخ بدشکل/غایب است.

    `int(...)`ِ مستقیم روی رشته‌ای که عدد نیست ValueError می‌داد و چون این
    تابع وسطِ ساختنِ نتیجه‌ی جستجو صدا زده می‌شود، یک ردیفِ خراب کلِ پاسخ را
    ۵۰۲ می‌کرد — نه فقط همان یک آلبوم را.
    """
    head = str(value or "")[:4]
    return int(head) if head.isdigit() else 0


def _user_artist_id(row: dict[str, Any]) -> str | None:
    uid = (row.get("user") or {}).get("id")
    return f"sc:artist:{uid}" if uid else None


def _release_type(track_count: int, declared: Any = None) -> str:
    """
    دسته‌ی انتشار برای فیلتر دیسکوگرافی.

    `set_type` نوع رسمیِ ساندکلاد است و باید بر حدسِ تعداد ترک مقدم باشد؛ برای
    داده‌های قدیمی یا پاسخ‌هایی که این فیلد را ندارند، تعداد ترک fallback است.
    """
    if declared in {"album", "single", "ep", "compilation"}:
        return declared
    if track_count <= 1:
        return "single"
    if track_count <= 6:
        return "ep"
    return "album"


def _album(row: dict[str, Any]) -> Album:
    tracks = int(row.get("track_count") or 0)
    return Album(
        # ساندکلاد آلبوم و پلی‌لیست را با یک نوع نگه می‌دارد و `extract` هم
        # همین شناسه را می‌سازد؛ دو جور نامیدنش صفحه‌ی آلبوم را می‌شکست
        id=f"sc:playlist:{row['id']}",
        title=row.get("title") or "",
        artist=(row.get("user") or {}).get("username") or "ناشناس",
        year=_year(row.get("release_date") or row.get("created_at")),
        artworkUrl=_artwork(row),
        trackCount=tracks,
        source="soundcloud",
        sourceUrl=row["permalink_url"],
        artistId=_user_artist_id(row),
        releaseType=_release_type(tracks, row.get("set_type")),
        releaseDate=((row.get("release_date") or row.get("created_at") or "")[:10]) or None,
    )


def _albums(rows: list[dict[str, Any]]) -> list[Album]:
    return [
        _album(row)
        for row in rows
        # آلبومِ بی‌ترک هم در نتایج می‌آید (ست ساخته شده و پر نشده) — کارتی که
        # باز کردنش به صفحه‌ی خالی می‌رسد
        if row.get("id") and row.get("permalink_url") and row.get("track_count")
    ]


def search_albums(query: str, limit: int = SEARCH_LIMIT) -> list[Album]:
    """
    آلبوم‌های ساندکلاد.

    اندپوینتش از `playlists` جداست و همین جدایی نکته‌ی اصلی است: ساندکلاد «ست»
    را هم برای آلبوم رسمی به کار می‌برد هم برای میکسِ دست‌ساز کاربر، و فقط این
    مسیر آن‌هایی را می‌دهد که خودِ هنرمند به‌عنوان آلبوم منتشر کرده.
    """
    return _albums(_search("/search/albums", query, limit))


def _playlist(row: dict[str, Any]) -> Playlist:
    return Playlist(
        id=f"sc:playlist:{row['id']}",
        title=row.get("title") or "",
        owner=(row.get("user") or {}).get("username") or "ناشناس",
        trackCount=int(row.get("track_count") or 0),
        artworkUrl=_artwork(row),
        source="soundcloud",
        sourceUrl=row.get("permalink_url") or "",
    )


def _playlists(rows: list[dict[str, Any]]) -> list[Playlist]:
    return [
        _playlist(row)
        for row in rows
        if row.get("id") and row.get("permalink_url") and row.get("track_count")
    ]


def search_playlists(query: str, limit: int = SEARCH_LIMIT) -> list[Playlist]:
    """پلی‌لیست‌ها و ست‌های ساندکلاد."""
    return _playlists(_search("/search/playlists", query, limit))


# هشت‌تا، همان‌قدر که اپل و دیزر برای هنرمند برمی‌دارند. بیستِ SEARCH_LIMIT
# اینجا فقط دنبال‌کننده‌های هم‌نامِ خودِ هنرمند را به لیست می‌آورد.
USER_LIMIT = 8


def _user(row: dict[str, Any]) -> Artist:
    followers = int(row.get("followers_count") or 0)
    tracks_count = int(row.get("track_count") or 0)
    if followers:
        subtitle = f"{followers:,} دنبال‌کننده"
    elif tracks_count:
        subtitle = f"{tracks_count:,} آهنگ"
    else:
        subtitle = "ساندکلاد"
    return Artist(
        id=f"sc:artist:{row['id']}",
        name=row.get("username") or row.get("permalink") or "",
        artworkUrl=_avatar(row.get("avatar_url")),
        source="soundcloud",
        sourceUrl=row["permalink_url"],
        subtitle=subtitle,
        # ساندکلاد بین هنرمند و شنونده تفکیک ندارد، پس تنها چیزی که می‌شود به آن
        # تکیه کرد خودِ داده است: حسابی که هیچ ترکی منتشر نکرده و فقط پلی‌لیست
        # دارد، صفحه‌اش هم باید صفحه‌ی کاربر باشد نه هنرمند
        kind="artist" if tracks_count else "user",
        verified=bool(row.get("verified")),
    )


def search_users(query: str, limit: int = USER_LIMIT) -> list[Artist]:
    """
    کاربرها — همان چیزی که در ساندکلاد جای «هنرمند» را می‌گیرد.
    """
    return [
        _user(row)
        for row in _search("/search/users", query, limit)
        if row.get("id") and row.get("permalink_url") and row.get("track_count")
    ]


def user(user_id: str) -> Artist | None:
    """سرِ صفحه‌ی یک کاربر."""
    row = _api(f"/users/{user_id}")
    if not isinstance(row, dict) or not row.get("id") or not row.get("permalink_url"):
        return None
    return _user(row)


def resolve_user_id(url: str) -> str | None:
    """
    شناسه‌ی عددیِ کاربر از روی لینکِ پروفایل.

    لینکِ ساندکلاد فقط نامِ مستعار دارد (`soundcloud.com/accia`) و بقیه‌ی
    اندپوینت‌ها شناسه‌ی عددی می‌خواهند. `/resolve` هر لینکی را می‌گیرد، پس
    نوعِ خروجی چک می‌شود: لینکِ ترک یا ست هم از همین راه جواب می‌گیرد و بدون
    این شرط، صفحه‌ی هنرمند با شناسه‌ی یک ترک ساخته می‌شد.
    """
    row = _api("/resolve", url=url)
    if not isinstance(row, dict) or row.get("kind") != "user" or not row.get("id"):
        return None
    return str(row["id"])


# هر پاسخ حداکثر پنجاه ردیف می‌دهد؛ `_collection` همه‌ی `next_href`ها را تا
# سقفِ موردنیاز دنبال می‌کند.
USER_TRACKS = 5000
USER_ALBUMS = 5000


def user_tracks(user_id: str, limit: int = USER_TRACKS) -> list[dict[str, Any]]:
    """
    همه‌ی آپلودهای کاربر — entryهای yt-dlp شکل، مثل `search_tracks`.

    ترتیبش تازه‌به‌قدیم است و برای ساختن بخش Singles & EP استفاده می‌شود.
    """
    return _entries(_collection(f"/users/{user_id}/tracks", limit=limit))


def user_top_tracks(user_id: str, limit: int = USER_TRACKS) -> list[dict[str, Any]]:
    """Top Tracks واقعیِ SoundCloud را با مرتب‌سازی رسمیِ hotness می‌گیرد."""
    return _entries(
        _collection(f"/users/{user_id}/tracks", limit=limit, order="hotness")
    )


def user_albums(user_id: str, limit: int = USER_ALBUMS) -> list[Album]:
    """
    فقط آن ست‌هایی که کاربر به‌عنوان آلبوم منتشر کرده، از تازه به قدیم.

    `/playlists` هم داشتیم ولی هر میکسِ دست‌سازِ کاربر را می‌آورد و دیسکوگرافی را
    با «فولدرِ آهنگ‌های مورد علاقه» پر می‌کرد.
    """
    rows = _collection(f"/users/{user_id}/albums", limit=limit)
    # ستِ ساندکلاد گاهی تاریخ انتشار ندارد و فقط تاریخِ ساخت دارد
    rows.sort(key=lambda r: r.get("release_date") or r.get("created_at") or "", reverse=True)
    return _albums(rows)


_RELEASE_SUFFIX = re.compile(r"\s*[-–—]\s*(single|ep)\s*$", re.I)


def _release_title_and_type(value: str) -> tuple[str, str | None]:
    """پسوند نوع انتشار را از `album_title`ای که SoundCloud می‌دهد جدا می‌کند."""
    match = _RELEASE_SUFFIX.search(value)
    if not match:
        return value.strip(), None
    title = value[: match.start()].strip()
    return title or value.strip(), "ep" if match.group(1).lower() == "ep" else "single"


def _track_as_single(
    entry: dict[str, Any],
    artist: Artist,
    *,
    title: str | None = None,
    release_type: str = "single",
    track_count: int = 1,
) -> Album:
    """ترک یا انتشار تک‌آهنگی ساندکلاد در کارت Discography."""
    date = str(entry.get("release_date") or "")
    return Album(
        id=f"sc:track:{entry.get('id') or ''}",
        title=(title or entry.get("title") or "").strip(),
        artist=artist.name,
        year=_year(date),
        artworkUrl=entry.get("thumbnail"),
        trackCount=track_count,
        source="soundcloud",
        sourceUrl=entry.get("webpage_url") or "",
        artistId=artist.id,
        releaseType=release_type,
    )


def user_discography(
    user_id: str,
    track_entries: list[dict[str, Any]],
    artist: Artist,
    limit: int = USER_ALBUMS,
) -> list[Album]:
    """
    دیسکوگرافی صفحه‌ی هنرمند: ست‌ها به‌علاوه‌ی ترک‌هایی که ست نیستند.

    `/users/{id}/albums` ست‌های رسمی را می‌دهد؛ ترک‌هایشان در `/tracks` هم
    هستند و باید با نام همان ست حذف شوند. اما `album_title` برای سینگل‌ها هم
    وجود دارد (مثلاً `WIND - Single`) و نباید به‌اشتباه عضو یک آلبوم تلقی شود.
    """
    try:
        rows = _collection(f"/users/{user_id}/albums", limit=limit)
    except Exception:
        rows = []

    dated: list[tuple[str, Album]] = []
    album_titles: set[str] = set()
    for row in rows:
        if not (row.get("id") and row.get("permalink_url") and row.get("track_count")):
            continue
        album = _album(row)
        dated.append((str(row.get("release_date") or row.get("created_at") or ""), album))
        title = album.title.strip().casefold()
        if title:
            album_titles.add(title)

    ep_releases: dict[str, list[dict[str, Any]]] = {}
    for entry in track_entries:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        release_name = str(entry.get("album") or "").strip()
        normalized_release = release_name.casefold()
        # ترک‌های یک ست/آلبوم رسمی در uploads نیز هستند؛ کارت مجموعه از
        # `/albums` می‌آید و از تکرار تک‌تک ترک‌ها در دیسکوگرافی جلوگیری می‌شود.
        if normalized_release in album_titles or title.casefold() in album_titles:
            continue
        release_title, release_type = _release_title_and_type(release_name)
        if release_type == "ep":
            ep_releases.setdefault(release_title.casefold(), []).append(entry)
            continue
        dated.append((
            str(entry.get("release_date") or ""),
            _track_as_single(
                entry,
                artist,
                title=release_title if release_type == "single" else title,
                release_type="single",
            ),
        ))

    for entries in ep_releases.values():
        first = max(entries, key=lambda item: str(item.get("release_date") or ""))
        release_title, _ = _release_title_and_type(str(first.get("album") or ""))
        dated.append((
            str(first.get("release_date") or ""),
            _track_as_single(
                first,
                artist,
                title=release_title,
                release_type="ep",
                track_count=len(entries),
            ),
        ))

    dated.sort(key=lambda item: item[0], reverse=True)
    return [album for _, album in dated]


USER_PLAYLISTS = 50


def _playlist(row: dict[str, Any]) -> Playlist:
    return Playlist(
        # همان شناسه‌ای که `_album` می‌سازد: ساندکلاد آلبوم و پلی‌لیست را با یک
        # نوع نگه می‌دارد و صفحه‌شان هم یکی است
        id=f"sc:playlist:{row['id']}",
        title=row.get("title") or "",
        owner=(row.get("user") or {}).get("username") or "ناشناس",
        trackCount=int(row.get("track_count") or 0),
        artworkUrl=_artwork(row),
        source="soundcloud",
        sourceUrl=row["permalink_url"],
    )


def user_playlists(user_id: str, limit: int = USER_PLAYLISTS) -> list[Playlist]:
    """
    ست‌هایی که کاربر ساخته و آلبوم نیستند — همان تبِ Playlists صفحه‌اش.

    مکملِ `user_albums` است نه جایگزینش: آنجا فقط انتشارهای رسمی می‌آید و
    اینجا میکس‌های دست‌ساز، و کارتشان هم در صفحه جای جدا دارد. حسابی که هیچ
    ترکی منتشر نکرده — که در ساندکلاد کم نیست — تمامِ محتوایش همین است.
    """
    rows = _collection(f"/users/{user_id}/playlists", limit=limit)
    return [
        _playlist(row)
        for row in rows
        # ستِ خالی کارتی است که باز کردنش به صفحه‌ی خالی می‌رسد، و آلبوم از
        # `user_albums` می‌آید — دو بار نشان دادنش فقط صفحه را تکراری می‌کند
        if row.get("id") and row.get("permalink_url") and row.get("track_count")
        and not row.get("is_album")
    ]


USER_LIKES = 50
USER_REPOSTS = 50


def _item_id(row: dict[str, Any]) -> Any:
    """شناسه‌ی ترک یا پلی‌لیستِ زیرِ یک آیتمِ لایک/ریپست — برای تشخیصِ تکراری."""
    nested = row.get("track") or row.get("playlist")
    return nested.get("id") if isinstance(nested, dict) else None


def _paged(path: str, limit: int) -> list[dict[str, Any]]:
    """
    برای اندپوینت‌هایی که `limit` را جدی نمی‌گیرند و باید دنبالِ `next_href`
    رفت — لایک‌ها و ریپست‌ها این‌جورند.

    ولی وقتی فیدِ واقعی تمام می‌شود، به‌جای خالی برگشتن، `next_href` باز هم پر
    می‌ماند و همان آیتم‌های قبلی (یا حتی از سرِ لیست) را دوباره می‌دهد — بدون
    ردیابیِ شناسه‌ها، حلقه هیچ‌وقت واقعاً تمام نمی‌شد و لیستِ لایک/ریپست پر از
    تکرار می‌شد. این‌جا به‌محض این‌که یک صفحه چیزِ تازه‌ای نداشته باشد، توقف
    می‌کنیم.
    """

    def call(http: httpx.Client, client_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[Any] = set()
        url: str | None = f"{API}{path}"
        params: dict[str, Any] = {"limit": limit, "client_id": client_id}
        while url and len(rows) < limit:
            res = http.get(url, params=params)
            res.raise_for_status()
            body = res.json() or {}
            fresh: list[dict[str, Any]] = []
            for row in body.get("collection") or []:
                key = _item_id(row)
                if key is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                fresh.append(row)
            if not fresh:
                break
            rows.extend(fresh)
            # next_href پارامترهای صفحه‌ی بعد را خودش دارد؛ فقط client_id کم دارد
            url = body.get("next_href")
            params = {"client_id": client_id}
        return rows[:limit]

    return _with_client_id(call)


def _liked_tracks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    آیتم‌های لایک/ریپست هم ترک دارند هم پلی‌لیست، هر کدام زیرِ کلید خودشان
    (`track` یا `playlist`). این‌جا فقط طرف ترک را بیرون می‌کشد — پلی‌لیستِ
    لایک/ریپست‌شده جای دیگری (کتابخانه‌ی خودِ ساندکلاد) نمایش داده می‌شود، نه اینجا.
    """
    return [row["track"] for row in rows if isinstance(row.get("track"), dict)]


def user_likes(user_id: str, limit: int = USER_LIKES) -> list[dict[str, Any]]:
    """ترک‌هایی که خودِ کاربر لایک کرده — همان تبِ Likes در صفحه‌ی ساندکلاد."""
    return _entries(_liked_tracks(_paged(f"/users/{user_id}/likes", limit)))


def user_reposts(user_id: str, limit: int = USER_REPOSTS) -> list[dict[str, Any]]:
    """
    ترک‌هایی که خودِ کاربر ریپست کرده — همان تبِ Reposts در صفحه‌ی ساندکلاد.

    برخلاف بقیه‌ی اندپوینت‌های این فایل، زیرِ `/users/{id}/reposts` نیست
    (۴۰۴ می‌دهد)؛ فیدِ ریپست از `/stream/...` می‌آید، همان مسیری که خودِ
    ساندکلاد برای این تب می‌خواند — و آن هم هر بار فقط پنج‌تا می‌دهد.
    """
    return _entries(_liked_tracks(_paged(f"/stream/users/{user_id}/reposts", limit)))


def _avatar(url: str | None) -> str | None:
    """
    آواتارِ پیش‌فرضِ ساندکلاد یک تصویر خاکستریِ یکسان برای همه است. با None
    برگرداندنش، فرانت جای آن حرفِ اولِ نام را با رنگِ پایدارِ خودش می‌گذارد که
    از یک آدمکِ تکراری در همه‌ی ردیف‌ها خواناتر است.
    """
    if not url or "default_avatar" in url:
        return None
    return _upsize(url)


def hydrate(entries: list[dict[str, Any]], hint: str | None = None) -> list[dict[str, Any]]:
    """
    entryهای ناقصِ یک ست یا صفحه‌ی کاربر را سرِ جا پر می‌کند.

    استخراج تختِ یک «ست» نه عنوان می‌دهد نه آپلودکننده، ولی استخراج تختِ صفحه‌ی
    «همه‌ی ترک‌ها»ی یک کاربر عنوان را می‌دهد و آپلودکننده را نه — چک کردن فقط
    عنوان اینجا را نادیده می‌گرفت و «Artist - Title» جدا نمی‌شد، پس هر ترکِ صفحه‌ی
    هنرمند «ناشناس» می‌ماند. شرط باید هر دو را بخواهد.

    شکست اینجا کشنده نیست: آلبوم با عنوانِ حدس‌زده از روی لینک نشان داده می‌شود،
    که از هیچ بهتر است و دانلود را هم زمین نمی‌زند.
    """
    missing = [e for e in entries if e.get("id") and not (e.get("title") and e.get("uploader"))]
    if not missing:
        return entries

    try:
        rows = tracks([str(e["id"]) for e in missing], hint)
    except Exception:
        return entries

    for entry in missing:
        if row := rows.get(str(entry["id"])):
            entry.update(as_entry(row))
    return entries
