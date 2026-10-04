"""
استخراج متادیتا با yt-dlp — برای یوتیوب و ساندکلاد که API عمومی راحتی ندارند.
همه‌ی توابع بلاک‌کننده‌اند و باید در thread اجرا شوند.
"""

from __future__ import annotations

import re
from typing import Any

from yt_dlp import YoutubeDL

from .. import ydl
from ..config import PROXY
from ..models import AlbumDetail, ArtistDetail, Playlist, Source, Track
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

    uploader_id = entry.get("uploader_id") or entry.get("user_id")
    if source == "soundcloud" and uploader_id:
        artist_id = f"sc:artist:{uploader_id}"
    elif source == "youtube" and entry.get("channel_id"):
        artist_id = f"yt:artist:{entry.get('channel_id')}"
    else:
        artist_id = None

    set_id = entry.get("set_id")
    album_id = f"sc:playlist:{set_id}" if (source == "soundcloud" and set_id) else None

    return Track(
        id=f"{'sc' if source == 'soundcloud' else 'yt'}:track:{vid}",
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
    )


def soundcloud_search(query: str) -> list[Track]:
    """
    جستجوی ساندکلاد. خودِ خواندن در `providers.soundcloud` است و اینجا فقط به
    Track تبدیل می‌شود — چون همان entry شکلی است که `_entry_to_track` می‌فهمد و
    «هنرمند - عنوان» را جدا می‌کند. عنوان ساندکلاد تقریباً همیشه همین شکل است.
    """
    return [_entry_to_track(e, "soundcloud", None) for e in soundcloud.search_tracks(query)]


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


# صفحه‌ی کانال: چند ویدیوی تازه، و همه‌ی پلی‌لیست‌ها. ویدیوها سقف دارند چون
# کانالِ بزرگ چند هزارتا دارد و استخراجِ تختِ همه‌شان دقیقه‌ها طول می‌کشد.
CHANNEL_TRACKS = 30
CHANNEL_PLAYLISTS = 60


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
    صفحه‌ی یک کانال: ویدیوهای تازه‌اش به‌علاوه‌ی پلی‌لیست‌های عمومی‌اش.

    یوتیوب هم مثل ساندکلاد بین «هنرمند» و «کاربر» فرقی نمی‌گذارد؛ کانالی که
    هیچ ویدیویی ندارد و فقط پلی‌لیست جمع کرده، صفحه‌اش صفحه‌ی کاربر است.

    بدون این، لینکِ کانال به `extract` می‌رفت و همه‌ی ویدیوهایش به شکل یک
    «آلبوم» برمی‌گشت — و پلی‌لیست‌هایش، که تمامِ محتوای چنین کانالی‌اند، اصلاً
    دیده نمی‌شدند.
    """
    if not (m := CHANNEL_URL.search(url)):
        return None
    root = f"https://www.{m.group(0)}"

    videos = _channel_tab(f"{root}/videos", CHANNEL_TRACKS)
    lists = _channel_tab(f"{root}/playlists", CHANNEL_PLAYLISTS)
    head = videos or lists
    if not head:
        return None

    name = head.get("channel") or head.get("uploader") or _title_from_url(root)
    tracks = [
        _entry_to_track(e, "youtube", None) for e in (videos or {}).get("entries") or [] if e
    ]
    playlists = [
        p for e in (lists or {}).get("entries") or [] if e and (p := _channel_playlist(e, name))
    ]

    followers = int(head.get("channel_follower_count") or 0)
    return ArtistDetail(
        id=f"yt:{'artist' if tracks else 'user'}:{head.get('channel_id') or ''}",
        name=name,
        artworkUrl=_channel_avatar(head),
        source="youtube",
        sourceUrl=head.get("channel_url") or root,
        subtitle=f"{followers:,} دنبال‌کننده" if followers else "یوتیوب",
        kind="artist" if tracks else "user",
        topTracks=tracks,
        playlists=playlists,
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

    return AlbumDetail(
        id=f"{'sc' if source == 'soundcloud' else 'yt'}:{kind}:{info.get('id') or ''}",
        title=title,
        artist=soundcloud.clean_artist(info.get("uploader") or info.get("channel") or (tracks[0].artist if tracks else "")),
        year=_year(info.get("release_year") or info.get("upload_date")),
        artworkUrl=art,
        trackCount=len(tracks),
        source=source,
        sourceUrl=info.get("webpage_url") or url,
        artistId=(
            f"yt:artist:{channel_id}"
            if source == "youtube" and channel_id
            else f"sc:artist:{channel_id}"
            if source == "soundcloud" and channel_id
            else None
        ),
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
