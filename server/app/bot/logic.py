"""
منطق خالص و بدون شبکه — بدون httpx یا python-telegram-bot، پس بدون mock هم
تست می‌شود.
"""

from __future__ import annotations

import hashlib
import html
import re

from ..models import Album, AlbumDetail, Artist, Playlist, Source, Track

URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# لینکِ صفحه‌ی هنرمند یا کاربر — همان تفکیکی که فرانت با `isArtistUrl` می‌کند.
# این‌ها آلبوم نیستند و از مسیرِ `resolve_ref` فقط «این لینک شناخته نشد»
# می‌گرفتند، در حالی که مرورگرِ پروفایلِ خودِ بات از قبل بلد است نشانشان بدهد.
PROFILE_URL_RE = re.compile(
    r"""^https?://(?:www\.|m\.)?(?:
          music\.apple\.com/[a-z]{2}/artist/
        | (?:www\.)?deezer\.com/(?:[a-z]{2}/)?(?:artist|profile)/
        | open\.spotify\.com/(?:intl-[a-z]{2}/)?(?:artist|user)/
        # ساندکلاد و یوتیوب بخشِ ثابتی برای «هنرمند» ندارند: پروفایلِ ساندکلاد
        # دقیقاً یک بخش دارد (ترک و ست بیشتر) و کانالِ یوتیوب با @/channel/c/user
        # شروع می‌شود، نه با watch یا playlist
        | soundcloud\.com/[\w.\-]+/?(?:[?\#].*)?$
        | youtube\.com/(?:@[\w.\-]+|channel/[\w\-]+|c/[\w.\-]+|user/[\w.\-]+)(?:/[a-z]+)?/?(?:[?\#].*)?$
    )""",
    re.IGNORECASE | re.VERBOSE,
)

YOUTUBE_VIDEO_RE = re.compile(
    r"""^https?://(?:www\.|m\.)?(?:
          youtube\.com/(?:watch\?|v/|embed/|shorts/)
        | youtu\.be/
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# sendAudio بدون Local Bot API Server بیش از این را قبول نمی‌کند
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024

# طول مجاز دکمه‌ی inline در تلگرام محدود است؛ عنوان‌های بلند کوتاه می‌شوند
BUTTON_LABEL_MAX = 60

# سقفِ «همه رو بگیر» روی یک آلبوم/پلی‌لیست — صفِ طولانی‌تر فقط فلودِ تلگرام
# می‌شود؛ کاربر همچنان می‌تواند تک‌تکِ بقیه را از دکمه‌های انتخاب بگیرد
MAX_BATCH_DOWNLOAD = 30

# سقفِ مستندشده‌ی تلگرام برای thumbnail — رعایت نکردنش یعنی سرور رد می‌کند
THUMB_SIZE = 200
THUMB_MAX_BYTES = 200_000

# سقفِ طولِ کپشن در تلگرام برای عکس و فایل
MAX_CAPTION_LEN = 1024

_ARTIST_SPLIT = re.compile(r"\s*(?:[,،;؛&/×+]|\bfeat\.?|\bft\.?|\bwith\b)\s*", re.IGNORECASE)
_TITLE_FEAT = re.compile(
    r"""[\(\[]\s*(?:feat\.?|ft\.?|with)\s+([^()\[\]]+)[\)\]]""",
    re.IGNORECASE,
)
_GENERIC_ARTISTS = {"various artists", "هنرمندان مختلف", "unknown", "ناشناس"}


def extract_album_features(album_artist: str, tracks: list[Track]) -> list[str]:
    """
    استخراجِ اسامیِ آرتیست‌های مهمان (Features) از ترک‌های آلبوم بدون تکرارِ
    آرتیستِ اصلی آلبوم.
    """
    main_names = {
        name.strip().casefold()
        for name in _ARTIST_SPLIT.split(album_artist)
        if name.strip()
    }
    main_names.add(album_artist.strip().casefold())

    features: list[str] = []
    seen: set[str] = set()

    def _consider(name: str) -> None:
        cleaned = name.strip(" '\"`()[]")
        norm = cleaned.casefold()
        if not cleaned or norm in main_names or norm in _GENERIC_ARTISTS or norm in seen:
            return
        seen.add(norm)
        features.append(cleaned)

    for t in tracks:
        # ۱. بررسیِ فیلدِ artist ترک
        if t.artist:
            for part in _ARTIST_SPLIT.split(t.artist):
                _consider(part)
        # ۲. بررسیِ پرانتزهای feat/ft در عنوان ترک
        if t.title:
            for match in _TITLE_FEAT.findall(t.title):
                for part in _ARTIST_SPLIT.split(match):
                    _consider(part)

    return features


def format_album_duration(duration_ms: int) -> str:
    """فرمت‌بندی زمان کل آلبوم به زبان فارسی (مثلاً «۱ ساعت و ۱۴ دقیقه» یا «۴۲ دقیقه»)."""
    total_sec = max(0, duration_ms // 1000)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    seconds = total_sec % 60

    if hours > 0:
        if minutes > 0:
            return f"{hours} ساعت و {minutes} دقیقه"
        return f"{hours} ساعت"
    if minutes > 0:
        if seconds > 0 and minutes < 5:
            return f"{minutes} دقیقه و {seconds} ثانیه"
        return f"{minutes} دقیقه"
    return f"{seconds} ثانیه"


def format_album_caption(album: AlbumDetail, track_count: int | None = None) -> str:
    """کپشنِ کارتِ آلبوم — حداکثر ۱۰۲۴ نویسه (سقفِ تلگرام)."""
    count = track_count if track_count is not None else (len(album.tracks) or album.trackCount)
    lines: list[str] = [
        f"💿 <b>{html.escape(album.title)}</b>",
        f"👤 آرتیست اصلی: <b>{html.escape(album.artist)}</b>",
    ]

    features = extract_album_features(album.artist, album.tracks)
    if features:
        features_str = "، ".join(features)
        if len(features_str) > 300:
            features_str = features_str[:297] + "…"
        lines.append(f"👥 مهمان‌ها: {html.escape(features_str)}")

    release = album.releaseDate or (str(album.year) if album.year else None)
    if release:
        lines.append(f"📅 تاریخ انتشار: {html.escape(release)}")

    if count:
        lines.append(f"🔢 تعداد آهنگ‌ها: {count}")

    if album.durationMs:
        lines.append(f"⏱ زمان کل: {format_album_duration(album.durationMs)}")

    caption = "\n".join(lines)
    if len(caption) > MAX_CAPTION_LEN:
        while lines and len("\n".join(lines)) > MAX_CAPTION_LEN:
            lines.pop()
        caption = "\n".join(lines)
    return caption


SOURCE_EMOJI: dict[Source, str] = {
    "apple": "🍎",
    "deezer": "🎵",
    "spotify": "🟢",
    "youtube": "▶️",
    "soundcloud": "☁️",
}

SOURCE_NAME: dict[Source, str] = {
    "apple": "اپل‌موزیک",
    "deezer": "دیزر",
    "spotify": "اسپاتیفای",
    "youtube": "یوتیوب",
    "soundcloud": "ساندکلاد",
}


def source_badge(source: Source) -> str:
    return SOURCE_EMOJI.get(source, "🎧")


def progress_bar(percent: float, width: int = 10) -> str:
    """▓▓▓▓░░░░░░ — نوار پیشرفت متنی، بدون هیچ کتابخانه‌ی اضافه."""
    filled = round(width * max(0.0, min(100.0, percent)) / 100)
    return "▓" * filled + "░" * (width - filled)


# همان هفت گزینه‌ی QualityPicker.tsx — تجربه‌ی بات نباید از وب جدا بیفتد
QUALITY_ROWS: list[list[str]] = [["128", "192", "320"], ["m4a", "opus", "flac"], ["original"]]
QUALITY_LABEL: dict[str, str] = {"original": "اورجینال"}
DEFAULT_QUALITY = "320"


def quality_label(quality: str) -> str:
    return QUALITY_LABEL.get(quality, quality)


# کیفیتِ تحویلِ خودکارِ انتشارِ تازه — همان چیزی که /follow قول می‌دهد. بالاترین
# کیفیتی که معمولاً زیر سقفِ فایلِ تلگرام می‌ماند؛ بالاتر از این (flac) یا
# به‌خاطر سقفِ ۵۰ مگ می‌افتد یا لینکِ مستقیم می‌خواهد، که برای «خودکار و بی‌صبر»
# سنگین است.
AUTO_QUALITY = "320"


def looks_like_url(text: str) -> bool:
    """لینک در برابر اسم آهنگ — تصمیم می‌گیرد بات سراغ resolve برود یا search."""
    return bool(URL_RE.match(text.strip()))


def looks_like_profile_url(text: str) -> bool:
    """
    لینکِ صفحه‌ی هنرمند یا کاربر، در برابر لینکِ آلبوم/پلی‌لیست/ترک.

    پروفایل ترک‌لیست ندارد که بشود «همه رو بگیر» کرد؛ مسیرش مرورگرِ پروفایل
    است، همان‌جا که آلبوم‌ها و پلی‌لیست‌هایش دکمه می‌شوند.
    """
    return bool(PROFILE_URL_RE.match(text.strip()))


def looks_like_youtube_video(text: str) -> bool:
    """بررسی اینکه آیا لینک به یک ویدیو یا میکس در یوتیوب اشاره می‌کند."""
    return bool(YOUTUBE_VIDEO_RE.match(text.strip()))


def new_releases(last_release_id: str | None, albums: list[Album]) -> list[Album]:
    """
    انتشارهای تازه‌ی یک هنرمند از آخرین باری که دیده‌ایم.

    هر سه فراهم‌کننده‌ی دارای صفحه‌ی هنرمند (دیزر/اسپاتیفای/اپل‌موزیک) لیست را
    تازه‌به‌قدیم و با تاریخِ کامل مرتب می‌دهند، پس «تازه‌ها» یعنی همه‌ی ردیف‌های
    قبل از آخرین شناسه‌ی دیده‌شده. دو حالتِ لبه:

    - هنوز هیچ انتشاری ندیده‌ایم (آخرین شناسه خالی است): چیزی تازه نیست — این
      فقط اولین پرکردنِ وضعیت است، نه انبوهی از تاریخچه.
    - آخرین شناسه در لیست نیست (آی‌دی‌های قدیمی گاهی عوض می‌شوند): فقط
      تازه‌ترین را تازه حساب می‌کنیم، تا یک جابه‌جاییِ فهرست کلِ دیسکوگرافی را
      دوباره «منتشرشده» نکند و چت کاربر را پر نکند.
    """
    if not albums or not last_release_id:
        return []
    fresh: list[Album] = []
    for album in albums:
        if album.id == last_release_id:
            return fresh
        fresh.append(album)
    return fresh[:1]


def _truncate(label: str, limit: int = BUTTON_LABEL_MAX) -> str:
    if len(label) <= limit:
        return label
    return label[: limit - 1] + "…"


def format_track_button(track: Track) -> str:
    """برچسبِ دکمه‌ی انتخاب: عنوان — هنرمند، کوتاه‌شده اگر لازم بود."""
    return _truncate(f"{track.title} — {track.artist}")


def format_artist_button(name: str) -> str:
    """برچسبِ دکمه‌ی انتخابِ هنرمند در `/follow`، همان قاعده‌ی کوتاه‌سازیِ ترک‌ها."""
    return _truncate(name)


def format_artist_search_button(artist: Artist) -> str:
    """برچسبِ دکمه‌ی انتخابِ هنرمند در مرورگرِ پروفایل — با آمار (subtitle) کنارش."""
    return _truncate(f"{artist.name} — {artist.subtitle}")


def format_album_button(album: Album) -> str:
    return _truncate(f"{album.title} — {album.artist}")


def format_playlist_button(playlist: Playlist) -> str:
    return _truncate(f"{playlist.title} — {playlist.owner}")


def too_large_for_telegram(size_bytes: int) -> bool:
    return size_bytes > TELEGRAM_FILE_LIMIT


def clean_filename_part(text: str) -> str:
    r"""کاراکترهای غیرمجاز در نام فایل (مثل / و \) را با خط فاصله جایگزین می‌کند."""
    text = re.sub(r'[\\/:*?"<>|\r\n]', "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:100] or "track"


def audio_filename(track: Track, format_label: str | None) -> str:
    """
    نامِ فایلی که برای کاربر نمایش داده می‌شود.

    `format_label` گزارشِ واقعیِ سرور است (مثلاً «mp3 320»)، نه کیفیتِ
    درخواستی — همان قراردادِ بقیه‌ی UI. پسوند همان بخش اولش است.
    """
    ext = (format_label or "mp3").split()[0].lstrip(".")
    artist = clean_filename_part(track.artist)
    title = clean_filename_part(track.title)
    return f"{artist} - {title}.{ext}"


def track_lyrics_hash(track_id: str) -> str:
    """هش کوتاه و یکتا از شناسه ترک برای callback_data دکمه‌های تلگرام (زیر ۶۴ بایت)."""
    return hashlib.sha256(track_id.encode("utf-8")).hexdigest()[:16]


def clean_lrc_lyrics(raw_lrc: str) -> str:
    """
    پاک‌سازی برچسب‌های زمانی و متادیتای فایل LRC برای نمایش خوانا و زیبای متن ترانه.
    """
    if not raw_lrc:
        return ""
    lines: list[str] = []
    for line in raw_lrc.splitlines():
        line = line.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        # حذف متادیتاهای استاندارد مثل [ti:...], [ar:...], [al:...], [by:...]
        if re.match(r"^\[[a-zA-Z]{2,}:.*\]$", line):
            continue
        # حذف تایم‌استمپ‌های [01:23.45] یا [01:23] یا چندتایی
        cleaned = re.sub(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines).strip()


INSTAGRAM_RE = re.compile(
    r"""^https?://(?:www\.|m\.)?(?:instagram\.com|instagr\.am)/(?:reel|p|tv)/""",
    re.IGNORECASE,
)
TIKTOK_RE = re.compile(
    r"""^https?://(?:www\.|m\.|vm\.)?tiktok\.com/""",
    re.IGNORECASE,
)


def looks_like_social_media_video(text: str) -> bool:
    """بررسی لینک ریلز اینستاگرام یا تیک‌تاک برای استخراج ساندترک."""
    t = text.strip()
    return bool(INSTAGRAM_RE.match(t) or TIKTOK_RE.match(t))


def paginate_slice(total_items: int, page: int, page_size: int = 8) -> tuple[int, int, int, int]:
    """
    (start_idx, end_idx, valid_page, total_pages)
    محاسبه‌ی بازه‌ی ایندکس‌های صفحه‌ی جاری به شکل امن و استاندارد.
    """
    if total_items <= 0:
        return 0, 0, 1, 1
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    valid_page = max(1, min(page, total_pages))
    start_idx = (valid_page - 1) * page_size
    end_idx = min(start_idx + page_size, total_items)
    return start_idx, end_idx, valid_page, total_pages


