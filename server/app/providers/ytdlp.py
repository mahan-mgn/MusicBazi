"""
استخراج متادیتا با yt-dlp — برای یوتیوب و ساندکلاد که API عمومی راحتی ندارند.
همه‌ی توابع بلاک‌کننده‌اند و باید در thread اجرا شوند.
"""

from __future__ import annotations

import re
from typing import Any

from yt_dlp import YoutubeDL

from .. import ydl
from ..config import PROXY, YOUTUBE_ENABLED
from ..models import Album, AlbumDetail, Artist, ArtistDetail, Playlist, SearchResults, Source, Track
from . import soundcloud

YOUTUBE_URL = re.compile(r"(youtube\.com|youtu\.be)", re.I)
SOUNDCLOUD_URL = re.compile(r"soundcloud\.com", re.I)
SPOTIFY_URL = re.compile(r"open\.spotify\.com/(album|playlist|track)/([A-Za-z0-9]+)", re.I)
INSTAGRAM_URL = re.compile(r"(instagram\.com|instagr\.am)/(?:reel|p|tv)/", re.I)
TIKTOK_URL = re.compile(r"(tiktok\.com/|vm\.tiktok\.com/)", re.I)

# صفحه‌ی یک کانال، با هر چهار شکلی که یوتیوب برای آدرسش دارد. تبِ انتهایی
# (`/videos`، `/playlists`، …) عمداً بیرون گروه می‌ماند: لینکی که کاربر
# می‌فرستد ممکن است روی هر تبی باشد و ما خودمان تبِ لازم را می‌چسبانیم.
CHANNEL_URL = re.compile(
    r"youtube\.com/(?:@[\w.\-]+|channel/[\w\-]+|c/[\w.\-]+|user/[\w.\-]+)", re.I
)

# لینکِ پروفایلِ ساندکلاد: دقیقاً یک بخش بعد از دامنه. ترک (`/user/track`) و
# ست (`/user/sets/x`) بخشِ بیشتری دارند و نباید اینجا بیفتند.
SOUNDCLOUD_PROFILE_URL = re.compile(
    r"^https?://(?:www\.|m\.)?soundcloud\.com/[\w.\-]+/?(?:[?#].*)?$", re.I
)

def _flat_opts() -> dict:
    return ydl.opts(skip_download=True, extract_flat="in_playlist", noplaylist=False)


def _source_of(url: str) -> Source:
    if SOUNDCLOUD_URL.search(url):
        return "soundcloud"
    if "music.youtube.com" in url.lower():
        return "youtube_music"
    return "youtube"


def _best_thumb(info: dict[str, Any]) -> str | None:
    """
    بزرگ‌ترین تصویر از میان چیزهایی که yt-dlp داده.

    نه `thumbnail` قابل اعتماد است (yt-dlp گاهی نسخه‌ی کوچک را آنجا می‌گذارد) و
    نه آخرین عضو لیست — ترتیب `thumbnails` تضمین‌شده نیست. پس صریح روی پهنا
    مقایسه می‌کنیم و اگر هیچ‌کدام پهنا نداشتند، به همان دوتای قبلی برمی‌گردیم.
    """
    thumbs = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    if sized := [t for t in thumbs if t.get("width")]:
        return max(sized, key=lambda t: t["width"])["url"]
    return info.get("thumbnail") or (thumbs[-1]["url"] if thumbs else None)


def _title_from_url(url: str) -> str:
    """آخرین بخشِ لینک به‌جای عنوان — وقتی هیچ متادیتایی گیر نیامده."""
    slug = url.split("?")[0].rstrip("/").rpartition("/")[2]
    return slug.replace("-", " ").replace("_", " ").strip()


def _track_year(entry: dict[str, Any]) -> int | None:
    """سالِ انتشار ترک — صفر یعنی نمی‌دانیم و نباید روی Track بنشیند."""
    year = _year(entry.get("release_year") or entry.get("release_date") or entry.get("upload_date"))
    return year or None


def _entry_to_track(entry: dict[str, Any], source: Source, album: str | None) -> Track:
    # extract_flat عنوان را خام می‌دهد؛ «Artist - Title» را جدا می‌کنیم
    raw = entry.get("title") or ""
    uploader = entry.get("uploader") or entry.get("channel") or entry.get("artist") or ""
    artist = entry.get("artist") or ""
    title = entry.get("track") or raw

    track_num = None
    if m := re.match(r"^(\d{1,3})\s*[-–—.]\s*(.+)$", raw):
        track_num = int(m.group(1))
        clean_raw = m.group(2).strip()
    else:
        clean_raw = raw

    if not artist:
        if " - " in clean_raw:
            artist, title = (p.strip() for p in clean_raw.split(" - ", 1))
        else:
            artist = re.sub(r"\s*-\s*Topic$", "", uploader).strip()
            if not entry.get("track"):
                title = clean_raw

    art = _best_thumb(entry)

    vid = entry.get("id") or ""
    source_url = entry.get("webpage_url") or entry.get("url") or ""
    if source == "youtube" and vid and not source_url.startswith("http"):
        source_url = f"https://www.youtube.com/watch?v={vid}"
    elif source == "youtube_music" and vid and not source_url.startswith("http"):
        source_url = f"https://music.youtube.com/watch?v={vid}"

    uploader_id = entry.get("uploader_id") or entry.get("user_id")
    if source == "soundcloud" and uploader_id:
        artist_id = f"sc:artist:{uploader_id}"
    elif source == "youtube_music" and entry.get("channel_id"):
        artist_id = f"ytm:artist:{entry.get('channel_id')}"
    elif source == "youtube" and entry.get("channel_id"):
        artist_id = f"yt:artist:{entry.get('channel_id')}"
    else:
        artist_id = None

    set_id = entry.get("set_id")
    album_id = f"sc:playlist:{set_id}" if (source == "soundcloud" and set_id) else None
    id_prefix = "sc" if source == "soundcloud" else "ytm" if source == "youtube_music" else "yt"

    views_num = entry.get("view_count")
    views_str = f"{views_num:,} بازدید" if views_num else None

    return Track(
        id=f"{id_prefix}:track:{vid}",
        title=title or raw or _title_from_url(source_url),
        artist=soundcloud.clean_artist(artist or uploader or "ناشناس"),
        album=album or entry.get("album"),
        albumId=album_id,
        durationMs=int(float(entry.get("duration") or 0) * 1000),
        artworkUrl=art,
        source=source,
        sourceUrl=source_url,
        previewUrl=None,
        year=_track_year(entry),
        artistId=artist_id,
        trackNumber=track_num or entry.get("track_number"),
        views=views_str,
    )


def soundcloud_search(query: str) -> list[Track]:
    """
    جستجوی ساندکلاد. خودِ خواندن در `providers.soundcloud` است و اینجا فقط به
    Track تبدیل می‌شود — چون همان entry شکلی است که `_entry_to_track` می‌فهمد و
    «هنرمند - عنوان» را جدا می‌کند. عنوان ساندکلاد تقریباً همیشه همین شکل است.
    """
    return [_entry_to_track(e, "soundcloud", None) for e in soundcloud.search_tracks(query)]


def youtube_enabled() -> bool:
    """آیا کاتالوگ یوتیوب در جستجو فعال است؟"""
    return YOUTUBE_ENABLED


def _is_channel_artist_match(cname: str, track_artist: str, query: str, is_verified: bool = False) -> bool:
    """
    بررسی تطابق نام کانال با هنرمند یا کوئری کاربر.
    کانال‌های متفرقه، گردآورنده، رقص یا متن آهنگ (مثل 7clouds یا yazou2011) نباید به عنوان هنرمند ثبت شوند.
    """
    if not cname:
        return False
    cn = re.sub(r"(\s*-\s*Topic|\s*VEVO)$", "", cname, flags=re.IGNORECASE).strip().lower()
    art = track_artist.strip().lower()
    q = query.strip().lower()

    c_clean = re.sub(r"[\s_.-]+", "", cn)
    art_clean = re.sub(r"[\s_.-]+", "", art)
    q_clean = re.sub(r"[\s_.-]+", "", q)

    is_official_channel = is_verified or cname.endswith(("- Topic", "VEVO"))

    # ۱. آیا نام کانال با عبارت جستجو هم‌پوشانی دارد؟
    if c_clean and q_clean and (c_clean == q_clean or c_clean in q_clean or q_clean in c_clean):
        return True

    # ۲. آیا کانال رسمی/تأییدشده است و نامش با هنرمند اثر تطابق دارد؟
    if is_official_channel and c_clean and art_clean and (c_clean == art_clean or c_clean in art_clean or art_clean in c_clean):
        return True

    return False


def youtube_search(query: str, limit: int = 15) -> SearchResults:
    """
    جستجوی یوتیوب با yt-dlp.
    هر ورودی به Track با منبع 'youtube' نگاشت می‌شود و کانال‌های رسمی و منطبق
    نیز به‌عنوان Artist استخراج می‌شوند (تفکیک کانال ناشر از هنرمند).
    """
    q = query.strip()
    if not q:
        return SearchResults(query=query)

    opts = ydl.opts(
        skip_download=True,
        extract_flat="in_playlist",
        ignoreerrors=True,
        socket_timeout=10,
    )
    with YoutubeDL(opts) as y:
        info = y.extract_info(f"ytsearch{limit}:{q}", download=False)

    entries = (info or {}).get("entries") or []
    tracks: list[Track] = []
    artists: list[Artist] = []
    seen_channels: set[str] = set()

    for e in entries:
        if not e:
            continue

        is_tab = e.get("ie_key") == "YoutubeTab"
        if is_tab:
            cid = e.get("id") or e.get("channel_id")
            cname = e.get("title") or e.get("channel") or e.get("uploader")
            avatar = _best_thumb(e)
            if cid and cname and cid not in seen_channels:
                seen_channels.add(cid)
                artists.append(
                    Artist(
                        id=f"yt:artist:{cid}",
                        name=cname,
                        artworkUrl=avatar,
                        source="youtube",
                        sourceUrl=e.get("url") or f"https://www.youtube.com/channel/{cid}",
                        subtitle="یوتیوب",
                        kind="artist",
                        verified=bool(e.get("channel_is_verified")),
                    )
                )
            continue

        try:
            track = _entry_to_track(e, "youtube", None)
            tracks.append(track)
        except Exception:
            continue

        cid = e.get("channel_id")
        cname = e.get("channel") or e.get("uploader")
        is_verified = bool(e.get("channel_is_verified"))
        if cid and cname and cid not in seen_channels:
            if _is_channel_artist_match(cname, track.artist, q, is_verified):
                seen_channels.add(cid)
                artists.append(
                    Artist(
                        id=f"yt:artist:{cid}",
                        name=cname,
                        artworkUrl=_best_thumb(e),
                        source="youtube",
                        sourceUrl=e.get("channel_url") or f"https://www.youtube.com/channel/{cid}",
                        subtitle="یوتیوب",
                        kind="artist",
                        verified=is_verified,
                    )
                )

    return SearchResults(query=query, tracks=tracks, artists=artists)


def soundcloud_artist(user_id: str) -> ArtistDetail | None:
    """
    صفحه‌ی هنرمندِ ساندکلاد: ترک‌های خودش، آلبوم‌هایش، و آن‌چه لایک/ریپست کرده.

    مثل `soundcloud_search` اینجاست نه در `providers.soundcloud`، چون تبدیلِ
    entry به Track همین‌جا زندگی می‌کند و جای دوباره‌نویسی‌اش نیست.
    """
    head = soundcloud.user(user_id)
    if head is None:
        return None

    # هیچ‌کدام حیاتی نیست: صفحه‌ی یک کاربرِ بی‌آلبوم هم باید باز شود
    try:
        uploads = soundcloud.user_tracks(user_id)
    except Exception:
        uploads = []
    try:
        entries = soundcloud.user_top_tracks(user_id)
        if not entries and uploads:
            raise RuntimeError("SoundCloud returned no Top Tracks")
    except Exception:
        entries = sorted(
            uploads,
            key=lambda e: int(e.get("playback_count") or 0),
            reverse=True,
        )
    try:
        albums = soundcloud.user_discography(user_id, uploads, head)
    except Exception:
        albums = []
    try:
        playlists = soundcloud.user_playlists(user_id)
    except Exception:
        playlists = []
    try:
        liked = soundcloud.user_likes(user_id)
    except Exception:
        liked = []
    try:
        reposted = soundcloud.user_reposts(user_id)
    except Exception:
        reposted = []

    def _owned(e: dict[str, Any]) -> Track:
        track = _entry_to_track(e, "soundcloud", None)
        track.artistId = head.id
        return track

    # تبِ Tracks ساندکلاد تازه‌به‌قدیم است؛ محبوب‌ترین‌های صفحه‌ی هنرمند
    # همان‌ها را با تعداد پخش می‌چیند — مثل خودِ پلتفرم.
    entries.sort(key=lambda e: int(e.get("playback_count") or 0), reverse=True)

    return ArtistDetail(
        **head.model_dump(),
        topTracks=[_owned(e) for e in entries],
        albums=albums,
        playlists=playlists,
        likedTracks=[_entry_to_track(e, "soundcloud", None) for e in liked],
        repostedTracks=[_entry_to_track(e, "soundcloud", None) for e in reposted],
    )


def soundcloud_user(url: str) -> ArtistDetail | None:
    """
    همان صفحه، ولی از روی لینکِ پروفایل.

    لینکِ ساندکلاد شناسه‌ی عددی ندارد و بقیه‌ی اندپوینت‌ها بدون آن کار
    نمی‌کنند، پس اول `/resolve`. اگر لینک پروفایل نبود (ترک، ست) None
    برمی‌گردد و صدازننده سراغ مسیرِ آلبوم می‌رود.
    """
    user_id = soundcloud.resolve_user_id(url)
    return soundcloud_artist(user_id) if user_id else None


# صفحه‌ی کانال: چند ویدیوی تازه، انتشارهای رسمی، و همه‌ی پلی‌لیست‌ها.
CHANNEL_TRACKS = 50
CHANNEL_RELEASES = 60
CHANNEL_PLAYLISTS = 40


def _channel_tab(url: str, limit: int) -> dict[str, Any] | None:
    """
    یک تبِ کانال، تخت. کانالی که آن تب را ندارد خطا می‌دهد (نه لیست خالی) و
    این‌جا None می‌شود: کانالی که فقط پلی‌لیست دارد تبِ Videos ندارد و
    برعکس — هیچ‌کدام نباید صفحه را زمین بزند.
    """
    try:
        with YoutubeDL(_flat_opts() | {"playlistend": limit}) as y:
            return y.extract_info(url, download=False)
    except Exception:
        return None


def _channel_head(url: str) -> dict[str, Any] | None:
    """فچِ سبکِ کانال فقط برای آواتار — بدون تب و بدون لیست."""
    try:
        with YoutubeDL(_flat_opts()) as y:
            return y.extract_info(url, download=False)
    except Exception:
        return None


def _channel_avatar(info: dict[str, Any]) -> str | None:
    """
    عکسِ خودِ کانال، نه بنرش.

    yt-dlp هر دو را در یک لیست می‌ریزد و بنر همیشه پهن‌تر است، پس
    `_best_thumb` — که بزرگ‌ترین را برمی‌دارد — همیشه بنر را می‌داد: یک نوارِ
    ۲۵۶۰×۴۲۴ که در قابِ گردِ صفحه‌ی هنرمند تکه‌ای از وسطش دیده می‌شد.
    """
    thumbs = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    avatar = next((t for t in thumbs if t.get("id") == "avatar_uncropped"), None)
    if avatar:
        return avatar["url"]
    # آواتارِ کانال مربع است و بنر نه — همین تفکیک وقتی می‌ماند که آن شناسه نباشد
    square = [t for t in thumbs if t.get("width") and t.get("width") == t.get("height")]
    return max(square, key=lambda t: t["width"])["url"] if square else None


def _channel_banner(info: dict[str, Any]) -> str | None:
    """بنر عریض و پانورامای بالای کانال یوتیوب."""
    thumbs = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    banner = next((t for t in thumbs if "banner" in str(t.get("id") or "").lower()), None)
    if banner:
        return banner["url"]
    wide = [t for t in thumbs if t.get("width") and t.get("height") and t["width"] >= t["height"] * 1.8]
    if wide:
        return max(wide, key=lambda t: t["width"])["url"]
    return None


def _channel_playlist(entry: dict[str, Any], owner: str) -> Playlist | None:
    if not entry.get("id"):
        return None
    return Playlist(
        id=f"yt:playlist:{entry['id']}",
        title=entry.get("title") or "",
        owner=owner,
        # تبِ پلی‌لیست‌ها تعداد را نمی‌دهد؛ فرانت جای عددِ صفر چیزی نشان نمی‌دهد
        trackCount=int(entry.get("playlist_count") or 0),
        artworkUrl=_best_thumb(entry),
        source="youtube",
        sourceUrl=entry.get("url") or f"https://www.youtube.com/playlist?list={entry['id']}",
    )


def youtube_channel(url: str) -> ArtistDetail | None:
    """
    صفحه‌ی یک کانال: ویدیوهای تازه، آلبوم‌ها/انتشارهای رسمی (تب Releases)، و پلی‌لیست‌ها.
    """
    if not (m := CHANNEL_URL.search(url)):
        return None
    root = f"https://www.{m.group(0)}"

    videos = _channel_tab(f"{root}/videos", CHANNEL_TRACKS)
    releases = _channel_tab(f"{root}/releases", CHANNEL_RELEASES)
    lists = _channel_tab(f"{root}/playlists", CHANNEL_PLAYLISTS)
    head = videos or releases or lists
    if not head:
        return None

    name = head.get("channel") or head.get("uploader") or _title_from_url(root)
    channel_id = head.get("channel_id") or ""
    tracks = [
        _entry_to_track(e, "youtube", None) for e in (videos or {}).get("entries") or [] if e
    ]
    playlists = [
        p for e in (lists or {}).get("entries") or [] if e and (p := _channel_playlist(e, name))
    ]
    albums = [
        Album(
            id=f"yt:playlist:{e['id']}",
            title=e.get("title") or "بدون عنوان",
            artist=name,
            year=0,
            trackCount=int(e.get("playlist_count") or 0),
            artworkUrl=_best_thumb(e),
            source="youtube",
            sourceUrl=e.get("url") or f"https://www.youtube.com/playlist?list={e['id']}",
            artistId=f"yt:artist:{channel_id}" if channel_id else None,
            releaseType="album",
        )
        for e in (releases or {}).get("entries") or []
        if e and e.get("id")
    ]

    followers = int(head.get("channel_follower_count") or 0)
    avatar = _channel_avatar(head)
    banner = _channel_banner(head)

    # استخراج هندل
    handle: str | None = None
    if m_handle := re.search(r"(@[\w.\-]+)", url):
        handle = m_handle.group(1)
    elif uploader_id := head.get("uploader_id"):
        handle = f"@{uploader_id.lstrip('@')}"

    # تکمیل آرت‌ورک و متادیتای آلبوم‌های یوتیوب از روی کاتالوگ متناظر YouTube Music
    singles: list[Album] = []
    if channel_id and albums:
        try:
            from . import youtube_music
            ytm_art = youtube_music.get_artist(channel_id)
            if ytm_art and ytm_art.albums:
                art_map = {a.title.strip().lower(): a for a in ytm_art.albums}
                for a in albums:
                    match = art_map.get(a.title.strip().lower())
                    if match and match.artworkUrl:
                        a.artworkUrl = match.artworkUrl
                        if match.year:
                            a.year = match.year
                        if match.releaseType:
                            a.releaseType = match.releaseType
                        if match.trackCount and match.trackCount > a.trackCount:
                            a.trackCount = match.trackCount
                singles = [a for a in albums if a.releaseType == "single"]
        except Exception:
            pass

        track_art_map = {t.title.strip().lower(): t.artworkUrl for t in tracks if t.artworkUrl}
        for a in albums:
            if not a.artworkUrl:
                a_clean = a.title.strip().lower()
                for t_title, art_url in track_art_map.items():
                    if a_clean in t_title or t_title in a_clean:
                        a.artworkUrl = art_url
                        break
            if not a.artworkUrl and avatar:
                a.artworkUrl = avatar

    if not singles:
        singles = [a for a in albums if a.trackCount == 1 or a.releaseType == "single"]

    subs_text = f"{followers:,} دنبال‌کننده" if followers else None
    is_artist = bool(tracks or albums or "topic" in name.lower())

    return ArtistDetail(
        id=f"yt:{'artist' if is_artist else 'user'}:{channel_id}",
        name=name,
        artworkUrl=avatar,
        source="youtube",
        sourceUrl=head.get("channel_url") or root,
        subtitle=subs_text or "یوتیوب",
        kind="artist" if is_artist else "user",
        topTracks=tracks,
        videos=tracks,
        albums=albums,
        singles=singles,
        playlists=playlists,
        description=head.get("description"),
        handle=handle,
        bannerUrl=banner,
        subscriberCount=subs_text,
        videoCount=len(tracks),
    )


def _year(value: Any) -> int:
    """
    سالِ انتشار، یا صفر وقتی تاریخ بدشکل/غایب است.

    `int(...)`ِ مستقیم روی رشته‌ای که عدد نیست ValueError می‌داد و چون این
    تابع وسطِ ساختنِ نتیجه‌ی جستجو صدا زده می‌شود، یک ردیفِ خراب کلِ پاسخ را
    ۵۰۲ می‌کرد — نه فقط همان یک آلبوم را.
    """
    head = str(value or "")[:4]
    return int(head) if head.isdigit() else 0


def extract(url: str) -> AlbumDetail | None:
    """
    یک لینک یوتیوب/ساندکلاد را به AlbumDetail تبدیل می‌کند.
    ویدیو/ترک تکی هم به شکل آلبومِ تک‌آهنگه برمی‌گردد تا فرانت یک مسیر بیشتر نداشته باشد.
    """
    source = _source_of(url)
    with YoutubeDL(_flat_opts()) as y:
        info = y.extract_info(url, download=False)
        # yt-dlp خودش برای خواندن ساندکلاد یک client_id گرفته و کش کرده؛
        # همان را قرض می‌گیریم تا دوباره از سایت درش نیاوریم
        sc_client_id = y.cache.load("soundcloud", "client_id") if source == "soundcloud" else None

    if not info:
        return None

    entries = [e for e in (info.get("entries") or []) if e]
    is_playlist = bool(entries)
    title = info.get("title") or "بدون عنوان"

    if is_playlist:
        # ست ساندکلاد در حالت تخت فقط شناسه و لینک می‌دهد — بقیه را از api-v2 می‌گیریم
        if source == "soundcloud":
            entries = soundcloud.hydrate(entries, sc_client_id)
        tracks = [_entry_to_track(e, source, title) for e in entries]
    else:
        tracks = [_entry_to_track(info, source, None)]

    art = _best_thumb(info)
    if not art and tracks:
        art = tracks[0].artworkUrl

    kind = "playlist" if is_playlist else "track"
    # شناسه‌ی کانالِ آپلودکننده — کلیدِ ناوبریِ فرانت به صفحه‌ی آرتیست.
    # آواتار: یوتیوب همان entry دارد (`_channel_avatar`)؛ صفحه‌ی watch خودش
    # thumbnailsِ کانال را نمی‌دهد، پس یک فچِ سبکِ کانال می‌زنیم. ساندکلاد
    # `uploader_thumbnail` نمی‌دهد — استخراج‌گرِ yt-dlp اصلاً چنین فیلدی
    # ندارد — پس آواتارِ کاربر را از api-v2 می‌گیریم؛ همان منبعی که
    # صفحه‌ی آرتیست از آن پر می‌شود و آواتارِ پیش‌فرضش آن‌جا انداخته می‌شود.
    channel_id = info.get("channel_id") or info.get("uploader_id")
    avatar = _channel_avatar(info) if source == "youtube" else info.get("uploader_thumbnail")
    if source == "youtube" and not avatar and channel_id:
        head = _channel_head(f"https://www.youtube.com/channel/{channel_id}")
        avatar = _channel_avatar(head) if head else None
    if source == "soundcloud" and not avatar and channel_id:
        try:
            head = soundcloud.user(channel_id)
        except Exception:
            head = None
        avatar = head.artworkUrl if head else None
    raw_type = (info.get("album_type") or info.get("set_type") or "").lower()
    uploader_name = (info.get("uploader") or "").strip().casefold()
    if source == "soundcloud" and is_playlist:
        if raw_type in ("album", "ep", "single", "compilation"):
            release_type = raw_type
        else:
            # ست ساندکلاد: اگر متعلق به خود هنرمند است (نام آپلودکننده در آرتیست ترک‌ها هست
            # یا ترک‌ها آرتیست یکسان دارند) یک انتشار آلبومی/EP است نه پلی‌لیست کاربر
            matching_tracks = [
                t for t in tracks
                if uploader_name and (uploader_name in t.artist.casefold() or t.artist.casefold() in uploader_name)
            ]
            same_artist = len(set(t.artist.casefold() for t in tracks)) == 1 if tracks else False
            if (matching_tracks and len(matching_tracks) >= len(tracks) / 2) or same_artist:
                release_type = soundcloud._release_type(len(tracks))
            else:
                release_type = None
    elif raw_type in ("album", "ep", "single", "compilation"):
        release_type = raw_type
    elif is_playlist:
        release_type = None
    else:
        release_type = "single"

    id_prefix = "sc" if source == "soundcloud" else "ytm" if source == "youtube_music" else "yt"
    artist_id = (
        f"ytm:artist:{channel_id}"
        if source == "youtube_music" and channel_id
        else f"yt:artist:{channel_id}"
        if source == "youtube" and channel_id
        else f"sc:artist:{channel_id}"
        if source == "soundcloud" and channel_id
        else None
    )

    return AlbumDetail(
        id=f"{id_prefix}:{kind}:{info.get('id') or ''}",
        title=title,
        artist=soundcloud.clean_artist(info.get("uploader") or info.get("channel") or (tracks[0].artist if tracks else "")),
        year=_year(info.get("release_year") or info.get("upload_date")),
        artworkUrl=art,
        trackCount=len(tracks),
        source=source,
        sourceUrl=info.get("webpage_url") or url,
        artistId=artist_id,
        artistArtworkUrl=avatar,
        durationMs=sum(t.durationMs for t in tracks),
        tracks=tracks,
        releaseType=release_type,
    )


def spotify_title(url: str) -> str | None:
    """
    اسپاتیفای بدون کلید API قابل خواندن نیست. ولی oEmbed عمومی است و عنوان را می‌دهد،
    و با همان عنوان می‌شود در اپل/دیزر جستجو کرد.
    """
    import httpx

    try:
        res = httpx.get(
            "https://open.spotify.com/oembed",
            params={"url": url},
            timeout=8.0,
            proxy=PROXY,
        )
        res.raise_for_status()
        return res.json().get("title")
    except Exception:
        return None
