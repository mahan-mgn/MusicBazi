"""دانلود با yt-dlp، ترنسکد با ffmpeg، تگ‌گذاری با mutagen."""

from __future__ import annotations

import base64
import logging
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    USLT,
)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus

from . import artcache, artwork, ydl
from .config import DOWNLOAD_DIR, FFMPEG_BIN, LYRICS_ENABLED, PROXY, YTDLP_PROXY
from .models import Quality, Track
from .providers import genius, lrclib

log = logging.getLogger(__name__)

ProgressFn = Callable[[float], None]


class DownloadCanceled(Exception):
    """
    کاربر وسط کار لغو کرده.

    لغو کردن تسکِ asyncio نخِ دانلود را نمی‌کشد — `to_thread` بلافاصله
    CancelledError می‌دهد ولی yt-dlp در نخِ خودش تا آخر ادامه می‌دهد و فایل را
    می‌نویسد. تنها راه متوقف کردنش، پرت کردن استثنا از داخل progress hook است.
    """

# mp3 با بیت‌ریت مشخص
BITRATE = {"128": "128", "192": "192", "320": "320"}

# کدک‌های دیگر. opus بیت‌ریت می‌خواهد (ffmpeg برایش quality-scale ندارد)؛
# flac و m4a نه — flac بی‌اتلاف است و m4a وقتی منبع خودش aac باشد فقط کپی می‌شود.
CODEC_BITRATE: dict[str, str | None] = {"m4a": None, "opus": "160", "flac": None}

# پسوندی که از هر کیفیت انتظار داریم — برای انتخاب فایل درست بعد از ترنسکد
EXT: dict[str, str] = {
    **{q: ".mp3" for q in BITRATE},
    "m4a": ".m4a",
    "opus": ".opus",
    "flac": ".flac",
}


def safe_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:120] or "track"


def _ydl_opts(
    out_stem: Path,
    quality: Quality,
    on_progress: ProgressFn,
    should_abort: Callable[[], bool] | None = None,
) -> dict:
    def hook(d: dict) -> None:
        # تنها نقطه‌ای که به‌طور مرتب داخل نخ دانلود اجرا می‌شود
        if should_abort is not None and should_abort():
            raise DownloadCanceled
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        done = d.get("downloaded_bytes") or 0
        if total:
            on_progress(min(99.0, done / total * 100))

    opts = ydl.opts(
        outtmpl=f"{out_stem}.%(ext)s",
        progress_hooks=[hook],
        format="bestaudio/best",
        # بین فرمت‌های صوتی، بیشترین بیت‌ریت را بردار — پیش‌فرض yt-dlp
        # گاهی استریم کم‌حجم‌تر را انتخاب می‌کند
        format_sort=["abr", "asr"],
        concurrent_fragment_downloads=4,
        postprocessors=[],
    )

    if quality in BITRATE:
        opts["postprocessors"].append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": BITRATE[quality],
            }
        )
    elif quality in CODEC_BITRATE:
        if quality == "m4a":
            # اگر منبع از قبل aac باشد، yt-dlp فقط ظرف را عوض می‌کند و
            # ترنسکد دوباره‌ی لاسی‌به‌لاسی اتفاق نمی‌افتد
            opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
        step: dict = {"key": "FFmpegExtractAudio", "preferredcodec": quality}
        if bitrate := CODEC_BITRATE[quality]:
            step["preferredquality"] = bitrate
        opts["postprocessors"].append(step)
    else:
        # «اورجینال»: بدون ترنسکد، فقط در ظرف m4a قرار می‌گیرد اگر ممکن باشد
        opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"

    return opts


# کاورِ این CDNها روی همان شبکه‌ای است که خودِ فایل صوتی از آن می‌آید، پس باید
# از همان پروکسی برود. `UNSTREAM_YTDLP_PROXY` دقیقاً برای همین حالت هست — وقتی
# فقط ساندکلاد/یوتیوب پروکسی می‌خواهند و کاتالوگ‌ها مستقیم در دسترس‌اند. با
# `PROXY`ِ خالی، متادیتای ترک از پروکسی می‌آمد ولی کاورش مستقیم، و مستقیم یعنی
# هیچ: فایل بی‌کاور می‌شد بدون اینکه چیزی خطا بدهد.
_YTDLP_CDNS = ("sndcdn.com", "ytimg.com", "googleusercontent.com", "ggpht.com")


def _proxy_for(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    if any(host == cdn or host.endswith(f".{cdn}") for cdn in _YTDLP_CDNS):
        return YTDLP_PROXY
    return PROXY


def _fetch_artwork(url: str | None) -> tuple[bytes, str] | None:
    """
    کاور را برای امبد کردن می‌گیرد — بزرگ‌ترین نسخه‌ای که CDN بدهد.

    آدرسی که از کاتالوگ آمده اندازه‌ی نمایش است (۵۰۰). داخل فایل صوتی ولی
    اندازه‌ی نمایش کافی نیست: فایل روی گوشی، دستگاه خانگی و صفحه‌ی بزرگ باز
    می‌شود و برخلاف سایت، دوباره نمی‌شود بهترش کرد. پس اینجا از بزرگ‌ترین
    شروع می‌کنیم و هر کدام نشد می‌رویم سراغ بعدی.
    """
    if not url:
        return None

    failures: list[str] = []
    for candidate in artwork.candidates(url):
        try:
            # کاور از همان کاتالوگی می‌آید که ممکن است مستقیم در دسترس نباشد
            res = httpx.get(
                candidate, timeout=10.0, follow_redirects=True, proxy=_proxy_for(candidate)
            )
            res.raise_for_status()
            mime = res.headers.get("content-type", "image/jpeg").split(";")[0]
            if not mime.startswith("image/"):
                failures.append(f"{candidate} → {mime}")
                continue
            return res.content, mime
        except Exception as exc:
            failures.append(f"{candidate} → {type(exc).__name__}: {exc}")

    # هیچ‌کدام نشد. بدون این خط، تنها نشانه‌اش یک فایلِ بی‌کاور بود و هیچ‌جا
    # ننوشته می‌شد که چرا — نه ۴۰۴ِ یک پله‌ی جعلی، نه پروکسیِ اشتباه.
    log.warning("هیچ‌کدام از نسخه‌های کاور گرفته نشد: %s", " | ".join(failures))
    return None


def _picture(cover: tuple[bytes, str]) -> Picture:
    """بلوک تصویر استاندارد FLAC — در Opus هم همین بلوک base64 می‌شود."""
    data, mime = cover
    pic = Picture()
    pic.data = data
    pic.type = 3  # جلد جلو
    pic.mime = mime
    pic.desc = "Cover"
    return pic


def _id3_album(tags: ID3, track: Track) -> None:
    """
    فریم‌هایی که هویتِ آلبوم را می‌سازند، جدا از بقیه.

    جدا هستند چون `retag_album` فقط همین‌ها را روی فایلی که از قبل تگ خورده
    به‌روز می‌کند و نباید به کاور و متن دست بزند.
    """
    for frame in ("TALB", "TPE2", "TDRC", "TRCK", "TPOS", "TCON"):
        tags.delall(frame)

    album_name = track.album.strip() if track.album else None
    if album_name:
        tags.add(TALB(encoding=3, text=album_name))
        # هنرمندِ آلبوم، نه هنرمندِ ترک: پلیر آلبوم را با همین فریم گروه می‌کند و
        # اگر مهمانِ هر ترک تویش بنشیند، آلبوم به چند تکه‌ی هم‌نام می‌شکند
        album_artist = (track.albumArtist or track.artist).strip()
        tags.add(TPE2(encoding=3, text=album_artist))
    if track.trackNumber:
        tags.add(TRCK(encoding=3, text=str(track.trackNumber)))
    if track.discNumber:
        tags.add(TPOS(encoding=3, text=str(track.discNumber)))
    if track.year:
        tags.add(TDRC(encoding=3, text=str(track.year)))
    if track.genre:
        tags.add(TCON(encoding=3, text=track.genre.strip()))


def _id3(tags: ID3, track: Track, cover, lyrics) -> None:
    """فریم‌های ID3. بازنویسی می‌کند، نه اضافه — فایل ممکن است از قبل تگ داشته باشد."""
    for frame in ("TIT2", "TPE1", "APIC", "USLT"):
        tags.delall(frame)

    tags.add(TIT2(encoding=3, text=track.title))
    tags.add(TPE1(encoding=3, text=track.artist))
    _id3_album(tags, track)
    if cover:
        data, mime = cover
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
    if lyrics and lyrics.plain:
        # USLT متنِ بدون زمان است؛ نسخه‌ی هم‌زمان‌شده در فایل .lrc کنارش می‌نشیند
        tags.add(USLT(encoding=3, lang="und", desc="", text=lyrics.plain))


def _tag_mp3(path: Path, track: Track, cover, lyrics) -> None:
    audio = MP3(path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    assert audio.tags is not None
    _id3(audio.tags, track, cover, lyrics)
    audio.save(v2_version=3)


def _drop(audio, *keys: str) -> None:
    """کلیدهایی که این ترک مقدارشان را ندارد؛ مقدارِ کهنه بدتر از نبودن است."""
    for key in keys:
        if key in audio:
            del audio[key]


def _mp4_album(audio, track: Track) -> None:
    """اتم‌های هویتِ آلبوم — همتای `_id3_album` برای ظرفِ iTunes."""
    _drop(audio, "\xa9alb", "aART", "trkn", "disk", "\xa9day", "\xa9gen")

    album_name = track.album.strip() if track.album else None
    if album_name:
        audio["\xa9alb"] = album_name
        audio["aART"] = (track.albumArtist or track.artist).strip()
    # trkn و disk جفتِ (شماره، کل) می‌خواهند؛ صفر یعنی «کل را نمی‌دانیم»
    if track.trackNumber:
        audio["trkn"] = [(track.trackNumber, 0)]
    if track.discNumber:
        audio["disk"] = [(track.discNumber, 0)]
    if track.year:
        audio["\xa9day"] = str(track.year)
    if track.genre:
        audio["\xa9gen"] = track.genre.strip()


def _mp4(audio, track: Track, cover, lyrics) -> None:
    """اتم‌های iTunes — همان چیزی که m4a و mp4 می‌فهمند."""
    audio["\xa9nam"] = track.title
    audio["\xa9ART"] = track.artist
    _mp4_album(audio, track)
    if cover:
        data, mime = cover
        fmt = MP4Cover.FORMAT_PNG if "png" in mime else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(data, imageformat=fmt)]
    if lyrics and lyrics.plain:
        audio["\xa9lyr"] = lyrics.plain


def _tag_mp4(path: Path, track: Track, cover, lyrics) -> None:
    audio = MP4(path)
    _mp4(audio, track, cover, lyrics)
    audio.save()


def _vorbis_album(audio, track: Track) -> None:
    """فیلدهای هویتِ آلبوم در Vorbis comment — همتای `_id3_album`."""
    _drop(audio, "album", "albumartist", "tracknumber", "discnumber", "date", "genre")

    album_name = track.album.strip() if track.album else None
    if album_name:
        audio["album"] = album_name
        audio["albumartist"] = (track.albumArtist or track.artist).strip()
    if track.trackNumber:
        audio["tracknumber"] = str(track.trackNumber)
    if track.discNumber:
        audio["discnumber"] = str(track.discNumber)
    if track.year:
        audio["date"] = str(track.year)
    if track.genre:
        audio["genre"] = track.genre.strip()


def _vorbis(audio, track: Track, lyrics) -> None:
    """
    فیلدهای مشترک FLAC و Opus.

    هر دو Vorbis comment استفاده می‌کنند و تنها فرقشان در کاور است — آنجا که
    FLAC بلوک باینری می‌گیرد و Ogg نه.
    """
    audio["title"] = track.title
    audio["artist"] = track.artist
    _vorbis_album(audio, track)
    if lyrics and lyrics.plain:
        audio["lyrics"] = lyrics.plain


def _tag_flac(path: Path, track: Track, cover, lyrics) -> None:
    audio = FLAC(path)
    _vorbis(audio, track, lyrics)
    if cover:
        audio.clear_pictures()
        audio.add_picture(_picture(cover))
    audio.save()


def _tag_opus(path: Path, track: Track, cover, lyrics) -> None:
    audio = OggOpus(path)
    _vorbis(audio, track, lyrics)
    if cover:
        # Ogg تگ باینری ندارد؛ قرارداد این است که بلوک FLAC را base64 کنیم
        audio["metadata_block_picture"] = [
            base64.b64encode(_picture(cover).write()).decode("ascii")
        ]
    audio.save()


_TAGGERS = {
    ".mp3": _tag_mp3,
    ".m4a": _tag_mp4,
    ".mp4": _tag_mp4,
    ".flac": _tag_flac,
    ".opus": _tag_opus,
}


# ---------- خواندنِ کاور از داخلِ فایل ----------
#
# وارونه‌ی `_TAGGERS`. لازم است چون کاوری که یک‌بار داخل فایل نشسته، تنها نسخه‌ای
# است که *مطمئنیم* هست: نه به CDN بند است، نه به پروکسی، نه به اینکه آن پله‌ی
# اندازه هنوز روی سرورِ کاتالوگ باشد.


def _cover_mp3(path: Path) -> bytes | None:
    tags = MP3(path, ID3=ID3).tags
    frames = tags.getall("APIC") if tags is not None else []
    # جلدِ جلو مقدم است؛ بعضی فایل‌ها عکسِ پشت و لیبل را هم دارند
    ordered = sorted(frames, key=lambda f: f.type != 3)
    return ordered[0].data if ordered else None


def _cover_mp4(path: Path) -> bytes | None:
    covers = (MP4(path).tags or {}).get("covr") or []
    return bytes(covers[0]) if covers else None


def _cover_flac(path: Path) -> bytes | None:
    pictures = sorted(FLAC(path).pictures, key=lambda p: p.type != 3)
    return pictures[0].data if pictures else None


def _cover_opus(path: Path) -> bytes | None:
    blocks = OggOpus(path).get("metadata_block_picture") or []
    if not blocks:
        return None
    return Picture(base64.b64decode(blocks[0])).data


_COVER_READERS = {
    ".mp3": _cover_mp3,
    ".m4a": _cover_mp4,
    ".mp4": _cover_mp4,
    ".flac": _cover_flac,
    ".opus": _cover_opus,
}


def embedded_cover(path: Path) -> bytes | None:
    """کاوری که داخلِ خودِ فایل نشسته، یا None."""
    reader = _COVER_READERS.get(path.suffix.lower())
    if reader is None:
        return None
    try:
        return reader(path)
    except Exception:
        log.warning("خواندنِ کاورِ داخلِ %s نشد", path.name, exc_info=True)
        return None


# تلگرام برای thumbnailِ یک فایل صوتی JPEG می‌خواهد، حداکثر ۳۲۰ پیکسل و زیر
# ۲۰۰ کیلوبایت. کاورِ امبدشده تقریباً همیشه از هر دو بزرگ‌تر است (۱۰۸۰ پیکسل و
# چند صد کیلوبایت)، پس فرستادنِ خامش یعنی تلگرام ردش کند و ردیفِ آهنگ بی‌تصویر
# بماند — همان چیزی که در لیستِ Saved Messages دیده می‌شد.
THUMB_PX = 320
THUMB_MAX_BYTES = 200_000

# q=2 بالاترین کیفیتِ عملیِ mjpeg است و در این ابعاد حدود ۲۰ کیلوبایت درمی‌آید،
# یعنی یک‌دهمِ سقف. پایین‌تر آوردنِ کیفیت هیچ چیزی نمی‌خرد.
_THUMB_QUALITY = "2"


def _scale_thumb(image: bytes | None) -> bytes | None:
    """هر تصویری را به JPEGِ حداکثر ۳۲۰ پیکسل تبدیل می‌کند، یا None."""
    if not image:
        return None
    try:
        proc = subprocess.run(
            [
                FFMPEG_BIN,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                # `decrease` نسبت را نگه می‌دارد؛ کاورِ غیرمربع (بنرِ ساندکلاد)
                # کشیده نمی‌شود و فقط در کادر جا می‌گیرد
                "-vf",
                f"scale={THUMB_PX}:{THUMB_PX}:force_original_aspect_ratio=decrease",
                "-q:v",
                _THUMB_QUALITY,
                "-f",
                "mjpeg",
                "pipe:1",
            ],
            input=image,
            capture_output=True,
            timeout=30,
            check=False,  # returncode را خودمان پایین‌تر چک می‌کنیم
        )
    except (OSError, subprocess.SubprocessError):
        log.warning("کوچک کردنِ کاور برای thumbnail نشد", exc_info=True)
        return None

    if proc.returncode != 0 or not proc.stdout:
        log.warning("ffmpeg موقعِ ساختنِ thumbnail خطا داد: %s", proc.stderr[:200])
        return None
    if len(proc.stdout) > THUMB_MAX_BYTES:
        # نباید در این ابعاد پیش بیاید؛ اگر آمد، فرستادنش یعنی ردِ تلگرام
        log.warning("thumbnail هنوز %d بایت است — رد شد", len(proc.stdout))
        return None
    return proc.stdout


def thumbnail(path: Path, artwork_url: str | None = None) -> bytes | None:
    """
    کاور در ابعادی که تلگرام برای thumbnailِ یک فایل صوتی قبول می‌کند.

    اول از داخلِ خودِ فایل. این مهم‌ترین بخشش است: کاورِ امبدشده هیچ درخواستِ
    شبکه‌ای نمی‌خواهد، پس نه تایم‌اوت می‌دهد، نه به پروکسی بند است، نه به اینکه
    آن پله‌ی اندازه هنوز روی CDN باشد — و دقیقاً همان تصویری است که کاربر موقع
    پخش می‌بیند. گرفتنِ دوباره از CDN فقط برای فایلِ بی‌کاور می‌ماند.

    بلاک‌کننده است — باید در thread صدا زده شود.
    """
    if thumb := _scale_thumb(embedded_cover(path)):
        return thumb
    fetched = _fetch_artwork(artwork_url)
    return _scale_thumb(fetched[0]) if fetched else None


def _retag_mp3(path: Path, track: Track) -> None:
    audio = MP3(path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    assert audio.tags is not None
    _id3_album(audio.tags, track)
    audio.save(v2_version=3)


def _retag_mp4(path: Path, track: Track) -> None:
    audio = MP4(path)
    _mp4_album(audio, track)
    audio.save()


def _retag_flac(path: Path, track: Track) -> None:
    audio = FLAC(path)
    _vorbis_album(audio, track)
    audio.save()


def _retag_opus(path: Path, track: Track) -> None:
    audio = OggOpus(path)
    _vorbis_album(audio, track)
    audio.save()


_RETAGGERS = {
    ".mp3": _retag_mp3,
    ".m4a": _retag_mp4,
    ".mp4": _retag_mp4,
    ".flac": _retag_flac,
    ".opus": _retag_opus,
}


def retag_album(path: Path, track: Track) -> None:
    """
    فقط تگ‌های آلبومیِ یک فایلِ از قبل دانلودشده را به‌روز می‌کند.

    وقتی دانلودِ دوباره‌ی یک آلبوم به فایلِ کهنه‌ی کتابخانه می‌رسد، آن فایل
    تگش را از روزِ دانلودش دارد — و اگر آن روز هنرمندِ آلبوم را نمی‌دانستیم،
    تا ابد در پلیر یک آلبومِ جدا می‌ماند مگر اینکه کاربر دستی پاکش کند.

    عمداً `tag` کامل صدا زده نمی‌شود: آن کاور را دوباره از شبکه می‌گیرد و متنِ
    داخل فایل را — که دیگر در دست نیست — پاک می‌کند.
    """
    retagger = _RETAGGERS.get(path.suffix.lower())
    if retagger is None:
        return
    try:
        retagger(path, track)
    except Exception:
        pass  # فایل صوتی سالم است؛ تگش همان می‌ماند که بود


def _retag_mp3_cover(path: Path, cover: tuple[bytes, str]) -> None:
    audio = MP3(path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    assert audio.tags is not None
    audio.tags.delall("APIC")
    data, mime = cover
    audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
    audio.save(v2_version=3)


def _retag_mp4_cover(path: Path, cover: tuple[bytes, str]) -> None:
    audio = MP4(path)
    data, mime = cover
    fmt = MP4Cover.FORMAT_PNG if "png" in mime else MP4Cover.FORMAT_JPEG
    audio["covr"] = [MP4Cover(data, imageformat=fmt)]
    audio.save()


def _retag_flac_cover(path: Path, cover: tuple[bytes, str]) -> None:
    audio = FLAC(path)
    audio.clear_pictures()
    audio.add_picture(_picture(cover))
    audio.save()


def _retag_opus_cover(path: Path, cover: tuple[bytes, str]) -> None:
    audio = OggOpus(path)
    pic = _picture(cover)
    audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
    audio.save()


_COVER_RETAGGERS = {
    ".mp3": _retag_mp3_cover,
    ".m4a": _retag_mp4_cover,
    ".mp4": _retag_mp4_cover,
    ".flac": _retag_flac_cover,
    ".opus": _retag_opus_cover,
}


def retag_cover(path: Path, cover: tuple[bytes, str]) -> bool:
    retagger = _COVER_RETAGGERS.get(path.suffix.lower())
    if retagger is None:
        return False
    try:
        retagger(path, cover)
        return True
    except Exception:
        log.warning("به‌روزرسانی کاورِ %s شکست خورد", path.name, exc_info=True)
        return False


def retag_artwork(path: Path, artwork_url: str | None) -> bool:
    """
    کاورِ فایلِ از قبل دانلودشده را با کاورِ جدید به‌روز می‌کند، بدون دست زدن به بقیه‌ی تگ‌ها و لیریک.
    """
    if not artwork_url:
        return False
    cover = _fetch_artwork(artwork_url)
    if not cover:
        return False
    artcache.remember_bytes(artwork_url, cover[0], cover[1])
    return retag_cover(path, cover)


def _lyrics_mp3(path: Path, lyrics) -> None:
    audio = MP3(path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    assert audio.tags is not None
    audio.tags.delall("USLT")
    audio.tags.add(USLT(encoding=3, lang="und", desc="", text=lyrics.plain))
    audio.save(v2_version=3)


def _lyrics_mp4(path: Path, lyrics) -> None:
    audio = MP4(path)
    audio["©lyr"] = lyrics.plain
    audio.save()


def _lyrics_flac(path: Path, lyrics) -> None:
    audio = FLAC(path)
    audio["lyrics"] = lyrics.plain
    audio.save()


def _lyrics_opus(path: Path, lyrics) -> None:
    audio = OggOpus(path)
    audio["lyrics"] = lyrics.plain
    audio.save()


_LYRIC_TAGGERS = {
    ".mp3": _lyrics_mp3,
    ".m4a": _lyrics_mp4,
    ".mp4": _lyrics_mp4,
    ".flac": _lyrics_flac,
    ".opus": _lyrics_opus,
}


def attach_lyrics(path: Path, lyrics) -> None:
    """
    متن را به فایلی که از قبل تگ خورده اضافه می‌کند، بدون دست زدن به بقیه.

    همتای `retag_album` برای متن: فایلی که روزِ دانلودش متنی پیدا نشد باید
    بتواند بعداً صاحبش شود، بدون اینکه کاور و تگ‌هایش دوباره ساخته شوند.
    """
    tagger = _LYRIC_TAGGERS.get(path.suffix.lower())
    if tagger is None or not (lyrics and lyrics.plain):
        return
    try:
        tagger(path, lyrics)
    except Exception:
        pass  # متن اختیاری است؛ فایل نباید به‌خاطرش خراب شود


def describe(path: Path) -> str:
    """
    فرمت واقعیِ فایل تولیدشده، مثلاً «mp3 ۱۲۸».

    کیفیتِ درخواستی همیشه به‌دست نمی‌آید: اگر منبع خودش ۱۲۸ باشد، تبدیلش به ۳۲۰
    فقط حجم اضافه می‌کند و yt-dlp درست عمل می‌کند که ترنسکد نکند. ولی UI باید
    چیزی را نشان دهد که واقعاً گرفته، نه چیزی که خواسته بوده.
    """
    ext = path.suffix.lstrip(".")

    # ویندوز گاهی هندل فایل را چند میلی‌ثانیه بعد از بسته‌شدن آزاد می‌کند و
    # خواندن بلافاصله بعد از ffmpeg/mutagen شکست می‌خورد — یک بار دوباره تلاش کن
    for attempt in range(3):
        try:
            if ext == "mp3":
                bitrate = MP3(path).info.bitrate
            elif ext in ("m4a", "mp4"):
                bitrate = MP4(path).info.bitrate
            elif ext == "opus":
                bitrate = OggOpus(path).info.bitrate
            elif ext == "flac":
                info = FLAC(path).info
                # flac بی‌اتلاف است؛ عمق بیت و نرخ نمونه گویاتر از بیت‌ریت‌اند
                return f"flac {info.bits_per_sample}/{int(info.sample_rate / 1000)}"
            else:
                return ext
            return f"{ext} {int(bitrate / 1000)}" if bitrate else ext
        except Exception:
            if attempt == 2:
                return ext
            time.sleep(0.15)
    return ext


def fetch_lyrics(track: Track):
    """
    متن آهنگ، یا None. خطا هیچ‌وقت بالا نمی‌رود — متن جزء اختیاری است.

    اول LRCLIB (بی‌کلید، هم‌زمان‌شده هم می‌دهد)، بعد در صورت نبود نتیجه —
    مثلاً چون Genius بدون کلید کار نمی‌کند — Genius (فقط متن ساده).
    """
    if not LYRICS_ENABLED:
        return None
    try:
        found = lrclib.fetch(track.title, track.artist, track.album, track.durationMs)
    except Exception:
        found = None
    if found:
        return found
    try:
        return genius.fetch(track.title, track.artist, track.album, track.durationMs)
    except Exception:
        return None


def write_lrc(path: Path, lyrics) -> Path | None:
    """
    متن آهنگ را کنار فایل صوتی می‌نویسد — هم‌زمان‌شده اگر بود، وگرنه ساده
    (مثلاً از Genius، که هیچ‌وقت تایم‌استمپ نمی‌دهد).

    هم‌نام بودن با فایل صوتی قرارداد عملاً جهانی است — VLC، foobar2000، Poweramp
    و بقیه بدون تنظیمات پیدایش می‌کنند؛ بدون تایم‌استمپ هم بازش می‌کنند، فقط
    خط‌به‌خط دنبال نمی‌کنند. فرانت‌اندِ خودمان هم همین رفتار را دارد.
    """
    if not lyrics or not (lyrics.synced or lyrics.plain):
        return None
    lrc = path.with_suffix(".lrc")
    try:
        lrc.write_text(lyrics.synced or lyrics.plain, encoding="utf-8")
        return lrc
    except Exception:
        return None


def tag(path: Path, track: Track, lyrics=None) -> bool:
    """
    تگ‌گذاری بر اساس پسوند. خطای تگ نباید کل دانلود را بسوزاند.

    برمی‌گرداند که کاور واقعاً داخل فایل نشست یا نه — تنها تفاوتِ بیرونیِ یک
    فایلِ بی‌کاور با یک فایلِ سالم همین است، و پیش از این هیچ‌کس خبردار نمی‌شد.
    """
    cover = _fetch_artwork(track.artworkUrl)
    if cover:
        # همین بایت‌ها را مجانی در آینه‌ی محلی هم بنشان: ترکی که همین الان
        # دانلود شده باید در کتابخانه کاور داشته باشد حتی اگر پنج دقیقه بعد
        # اینترنتِ بین‌الملل قطع شود
        artcache.remember_bytes(track.artworkUrl, cover[0], cover[1])
    tagger = _TAGGERS.get(path.suffix.lower())
    if tagger is None:
        log.warning("پسوندِ %s تگ‌گذار ندارد — فایل بدون تگ و کاور می‌ماند", path.suffix)
        return False
    try:
        tagger(path, track, cover, lyrics)
    except Exception:
        log.warning("تگ‌گذاریِ %s شکست خورد", path.name, exc_info=True)
        return False  # فایل صوتی سالم است؛ فقط تگ نخورد
    return cover is not None


@dataclass(frozen=True)
class Finalized:
    """
    نتیجه‌ی مرحله‌ی پایانی: مسیر `.lrc` و اینکه کاور داخل فایل نشست یا نه.

    `cover` جداست چون شکستش کشنده نیست ولی بی‌اهمیت هم نیست — فایل پخش می‌شود
    و در پلیر بدون تصویر می‌ماند، و کاربر تنها وقتی می‌فهمد که فایل را باز کند.
    """

    lyrics_path: Path | None
    cover: bool


def finalize(path: Path, track: Track) -> Finalized:
    """متن را می‌گیرد، تگ می‌زند و .lrc را می‌نویسد."""
    lyrics = fetch_lyrics(track)
    cover = tag(path, track, lyrics)
    return Finalized(lyrics_path=write_lrc(path, lyrics), cover=cover)


def download(
    track: Track,
    url: str,
    quality: Quality,
    on_progress: ProgressFn,
    out_dir: Path | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> Path:
    """
    فایل را دانلود و ترنسکد می‌کند و مسیر نهایی را برمی‌گرداند.
    بلاک‌کننده است — باید در thread صدا زده شود.

    `out_dir` پوشه‌ی اختصاصی همین جاب است. اسم فایل فقط از «هنرمند - عنوان»
    ساخته می‌شود و کیفیت را در خود ندارد، پس اگر همه‌ی جاب‌ها در یک پوشه بنویسند
    دانلودِ همان ترک با کیفیت دیگر، فایل قبلی را پاک می‌کند و ردیف قدیمی به فایل
    جدید اشاره می‌ماند. جدا کردن پوشه‌ها هم این را می‌بندد و هم برخورد دو دانلود
    همزمانِ یک ترک را.
    """
    from yt_dlp import YoutubeDL

    base = out_dir or DOWNLOAD_DIR
    base.mkdir(parents=True, exist_ok=True)
    stem = base / safe_name(f"{track.artist} - {track.title}")

    # glob با نام‌هایی که [ یا ] دارند اشتباه می‌گیرد، پس دستی فیلتر می‌کنیم
    def siblings() -> list[Path]:
        return [
            p
            for p in base.iterdir()
            if p.is_file() and p.name.startswith(stem.name + ".")
        ]

    # بازمانده‌ی تلاش قبلی را پاک کن تا yt-dlp فایل تکراری نسازد
    for leftover in siblings():
        leftover.unlink(missing_ok=True)

    # نام محلی عمداً ydl نیست — ماژول ydl را سایه می‌انداخت
    try:
        with YoutubeDL(_ydl_opts(stem, quality, on_progress, should_abort)) as y:
            y.extract_info(url, download=True)
    except DownloadCanceled:
        # پاک‌سازی باید همین‌جا و داخل همین نخ باشد: yt-dlp فایل `.part` را برای
        # ادامه‌ی بعدی نگه می‌دارد، و تا وقتی این نخ زنده است ویندوز هندلش را
        # آزاد نکرده — هر تلاشی از سمت حلقه‌ی asyncio بی‌صدا شکست می‌خورد.
        for leftover in siblings():
            leftover.unlink(missing_ok=True)
        if out_dir is not None:
            try:
                base.rmdir()
            except OSError:
                pass  # خالی نشد — پاک‌سازی دیسک بعداً می‌بردش
        raise

    wanted = EXT.get(quality)
    produced = sorted(
        (p for p in siblings() if p.suffix not in (".part", ".lrc")),
        key=lambda p: (p.suffix != wanted, -p.stat().st_size),
    )
    if not produced:
        raise FileNotFoundError("فایلی تولید نشد")

    return produced[0]
