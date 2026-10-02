"""
کش موقت و دانلود پایدار برای استریم آنلاین موزیک‌ها.

فایل‌های استریم شده در این کش نگهداری می‌شوند و کاملاً مجزا از کتابخانه دائمی (SQLite jobs)
هستند. در صورت وجود فایل در کتابخانه محلی، مستقیماً از فایل محلی استفاده می‌شود.
سرویس‌دهی فایل‌ها از طریق FileResponse استاندارد با پشتیبانی کامل از Range Requests، اسکراب،
کدهای وضعیت صحیح و هدرهای CORS انجام می‌شود.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Response
from fastapi.responses import FileResponse
from yt_dlp import YoutubeDL

from . import db, resolver, ydl
from .config import STREAM_CACHE_DIR, STREAM_CACHE_MAX_MB
from .models import Track
from .providers import lrclib

log = logging.getLogger(__name__)

AUDIO_MIME: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


class StreamBroadcaster:
    """مدیریت استریم چانک‌های صوتی در حافظه."""

    def __init__(self, cache_key: str, track: Track, quality: str | None = None):
        self.cache_key = cache_key
        self.track = track
        self.quality = quality
        self.chunks: list[bytes] = []
        self.downloaded_bytes: int = 0
        self.total_bytes: int | None = None
        self.ext: str = "m4a"
        self.media_type: str = "audio/mp4"
        self.ready_event = asyncio.Event()
        self.new_chunk_event = asyncio.Event()
        self.finished_event = asyncio.Event()
        self.error: Exception | None = None
        self.final_path: Path | None = None
        self.active_readers: int = 0

    def append_chunk(self, chunk: bytes) -> None:
        self.chunks.append(chunk)
        self.downloaded_bytes += len(chunk)
        self.new_chunk_event.set()
        self.new_chunk_event = asyncio.Event()


async def _stream_generator(
    session: StreamBroadcaster, start_byte: int = 0, end_byte: int | None = None
) -> AsyncIterator[bytes]:
    """تولیدکننده ناهمگام چانک‌های صوتی."""
    try:
        chunk_idx = 0
        current_offset = 0
        while True:
            if chunk_idx < len(session.chunks):
                chunk = session.chunks[chunk_idx]
                chunk_len = len(chunk)
                chunk_start = current_offset
                chunk_end = current_offset + chunk_len
                chunk_idx += 1
                current_offset = chunk_end

                if chunk_end <= start_byte:
                    continue

                offset_in_chunk = max(0, start_byte - chunk_start)
                data = chunk[offset_in_chunk:]

                if end_byte is not None and current_offset > end_byte:
                    bytes_needed = (end_byte + 1) - (chunk_start + offset_in_chunk)
                    if bytes_needed > 0:
                        yield data[:bytes_needed]
                    break

                yield data
                continue

            if session.finished_event.is_set():
                break
            if session.error:
                raise session.error

            await session.new_chunk_event.wait()
    finally:
        session.active_readers -= 1


def _is_direct_audio_format(f: dict) -> bool:
    """بررسی اینکه فرمت حتماً صوت استریم مستقیم (HTTP/HTTPS) باشد نه پلی‌لیست متنی HLS/DASH."""
    proto = (f.get("protocol") or "").lower()
    url = f.get("url") or ""
    if not (url.startswith("http://") or url.startswith("https://")):
        return False
    if proto and proto not in ("http", "https"):
        return False
    if ".m3u8" in url or "manifest" in url or ".mpd" in url:
        return False
    if f.get("acodec") == "none":
        return False
    return True


def _format_quality_score(f: dict) -> float:
    """محاسبه امتیاز کیفیت صوتی یک فرمت بر اساس نرخ بیت، کدک و سمپل‌ریت."""
    is_audio_only = 1 if f.get("vcodec") in ("none", None) else 0

    abr = f.get("abr") or (f.get("tbr") if is_audio_only else 0) or 0
    try:
        abr = float(abr)
    except (ValueError, TypeError):
        abr = 0.0

    acodec = (f.get("acodec") or "").lower()
    ext = (f.get("ext") or "").lower()

    codec_weight = 1.0
    if "flac" in acodec or ext == "flac" or "wav" in acodec:
        codec_weight = 3.0
    elif "opus" in acodec or ext in ("opus", "webm"):
        codec_weight = 1.6
    elif "mp4a" in acodec or "aac" in acodec or ext == "m4a":
        codec_weight = 1.3
    elif "mp3" in acodec or ext == "mp3":
        codec_weight = 1.0

    score = (is_audio_only * 500.0) + (abr * codec_weight)

    if abr <= 0 and is_audio_only:
        score += 100.0

    try:
        asr = float(f.get("asr") or 0)
    except (ValueError, TypeError):
        asr = 0.0
    score += asr / 1000.0

    return score


def _extract_direct_stream_info(url: str, quality: str | None = None) -> dict | None:
    """استخراج مستقیم آدرس استریم صوتی و هدرها با بالاترین کیفیت صوتی ممکن بدون دانلود فایل."""
    ydl_opts = ydl.opts(
        skip_download=True,
        format="bestaudio/best",
        format_sort=["abr", "asr"],
        noplaylist=True,
        quiet=True,
        no_warnings=True,
        noprogress=True,
        check_formats=False,
        youtube_include_dash_manifest=False,
        youtube_include_hls_manifest=False,
    )
    info = None
    try:
        with YoutubeDL(ydl_opts) as y:
            info = y.extract_info(url, download=False)
    except Exception as exc:
        log.warning("استخراج مستقیم با تنظیمات جاری ناموفق بود (%s) — تلاش مجدد بدون کوکی", exc)
        try:
            fallback_opts = {
                k: v for k, v in ydl_opts.items() if k not in ("cookiesfrombrowser", "extractor_args")
            }
            with YoutubeDL(fallback_opts) as y:
                info = y.extract_info(url, download=False)
        except Exception:
            return None

    if not info:
        return None

    all_formats = info.get("formats") or []
    if not all_formats and _is_direct_audio_format(info):
        all_formats = [info]

    valid_formats = [f for f in all_formats if _is_direct_audio_format(f)]
    if not valid_formats:
        if _is_direct_audio_format(info):
            valid_formats = [info]
        else:
            return None

    if quality in ("m4a", "opus", "flac", "mp3"):
        q_norm = quality.lower()
        matching = [
            f
            for f in valid_formats
            if q_norm in (f.get("ext") or "").lower() or q_norm in (f.get("acodec") or "").lower()
        ]
        if matching:
            valid_formats = matching

    valid_formats.sort(key=_format_quality_score, reverse=True)
    chosen = valid_formats[0]

    chosen_info = dict(info)
    chosen_info["url"] = chosen["url"]
    chosen_info["ext"] = chosen.get("ext") or "m4a"
    chosen_info["http_headers"] = chosen.get("http_headers") or info.get("http_headers") or {}
    chosen_info["filesize"] = chosen.get("filesize") or chosen.get("filesize_approx")
    chosen_info["abr"] = chosen.get("abr")
    chosen_info["acodec"] = chosen.get("acodec")
    chosen_info["vcodec"] = chosen.get("vcodec")
    chosen_info["format_id"] = chosen.get("format_id")
    chosen_info["_quality_score"] = _format_quality_score(chosen)
    return chosen_info


_pending_fetches: dict[str, asyncio.Task[Path]] = {}
_guard = asyncio.Lock()


def cache_key_for(track_id: str, quality: str | None = None) -> str:
    """تولید یک کلید مشخص و امن برای فایل کش بر اساس شناسه‌ی ترک و کیفیت."""
    digest = hashlib.sha256(track_id.encode("utf-8")).hexdigest()[:16]
    if quality and quality not in ("best", "original", "320", "flac"):
        return f"str_{digest}_{quality}"
    return f"str_{digest}"


def _ext_quality_rank(path: Path) -> int:
    """رتبه‌بندی کیفی پسوند فایل صوتی."""
    ext = path.suffix.lower()
    ranks = {".flac": 6, ".opus": 5, ".webm": 5, ".m4a": 4, ".mp4": 4, ".mp3": 3, ".ogg": 3}
    return ranks.get(ext, 1)


def _find_cached_audio(cache_key: str) -> Path | None:
    """جستجوی فایل صوتی کش‌شده برای این کلید (با اولویت بالاترین کیفیت در صورت وجود چند فایل)."""
    if not STREAM_CACHE_DIR.exists():
        return None
    found: list[Path] = []
    for p in STREAM_CACHE_DIR.iterdir():
        if (
            p.is_file()
            and p.stem == cache_key
            and not p.name.endswith((".part", ".ytdl", ".lrc", ".tmp"))
            and p.stat().st_size > 1024
        ):
            # بررسی اینکه مبادا پلی‌لیست متنی m3u8 اشتباهاً کش شده باشد
            try:
                with open(p, "rb") as f:
                    head = f.read(16)
                    if head.startswith(b"#EXTM3U") or b"#EXT" in head:
                        p.unlink(missing_ok=True)
                        continue
            except OSError:
                continue
            found.append(p)

    if not found:
        return None
    found.sort(key=_ext_quality_rank, reverse=True)
    return found[0]


def _prune_cache_sync() -> None:
    """پاک‌سازی فایل‌های قدیمی کش در صورت رد شدن از سقف حجم مجاز (LRU)."""
    if not STREAM_CACHE_DIR.exists():
        return

    now = time.time()
    files: list[tuple[Path, float, int]] = []
    total_bytes = 0

    for p in STREAM_CACHE_DIR.iterdir():
        if not p.is_file():
            continue
        try:
            stat = p.stat()
            if p.name.endswith((".part", ".ytdl", ".tmp")) and (now - stat.st_mtime > 3600):
                p.unlink(missing_ok=True)
                continue
            files.append((p, stat.st_atime, stat.st_size))
            total_bytes += stat.st_size
        except OSError:
            continue

    max_bytes = STREAM_CACHE_MAX_MB * 1024 * 1024
    if total_bytes <= max_bytes:
        return

    files.sort(key=lambda x: x[1])
    target_bytes = int(max_bytes * 0.75)

    for path, _, size in files:
        if total_bytes <= target_bytes:
            break
        try:
            path.unlink(missing_ok=True)
            total_bytes -= size
            log.info("فایل قدیمی از کش استریم حذف شد: %s", path.name)
        except OSError:
            pass


def _download_stream_worker(track: Track, out_stem: Path, quality: str | None = None) -> Path:
    """دانلود با yt-dlp برای ذخیره در کش استریم با بالاترین سرعت و کیفیت."""
    STREAM_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    candidates = resolver.resolve(track, use_cache=True)
    if not candidates:
        raise RuntimeError(f"هیچ کاندیدایی برای استریم «{track.title}» پیدا نشد")

    for p in STREAM_CACHE_DIR.iterdir():
        if p.is_file() and p.stem == out_stem.name:
            p.unlink(missing_ok=True)

    format_selector = "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[ext=opus]/bestaudio/best"
    if quality == "m4a":
        format_selector = "bestaudio[ext=m4a]/bestaudio/best"
    elif quality == "opus":
        format_selector = "bestaudio[ext=opus]/bestaudio/best"

    ydl_opts = ydl.opts(
        outtmpl=str(out_stem) + ".%(ext)s",
        format=format_selector,
        format_sort=["abr", "asr"],
        noplaylist=True,
        quiet=True,
        no_warnings=True,
        noprogress=True,
        concurrent_fragment_downloads=4,
    )

    if quality == "flac":
        ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "flac"}]

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            log.info("دانلود استریم برای «%s» از %s (%s)", track.title, candidate.source, candidate.url)
            with YoutubeDL(ydl_opts) as y:
                y.extract_info(candidate.url, download=True)

            cached = _find_cached_audio(out_stem.name)
            if cached and cached.exists():
                return cached
        except Exception as exc:
            last_error = exc
            log.warning("تلاش استریم از %s ناموفق بود: %s", candidate.url, exc)
            continue

    raise RuntimeError(f"دانلود استریم برای «{track.title}» شکست خورد: {last_error}")


async def get_or_fetch(track: Track, quality: str | None = None) -> Path:
    """دریافت مسیر کامل فایل از کتابخانه، کش استریم، یا دانلود جدید."""
    # ۱. بررسی کتابخانه دائمی با اولویت بهترین کیفیت
    ready = db.find_any_ready(track.id, preferred_quality=quality)
    if ready and ready["path"]:
        lib_path = Path(ready["path"])
        if lib_path.exists():
            return lib_path

    cache_key = cache_key_for(track.id, quality=quality)

    # ۲. بررسی فایل کامل در کش استریم
    cached = _find_cached_audio(cache_key)
    if cached and cached.exists():
        try:
            os.utime(cached, None)
        except OSError:
            pass
        return cached

    # ۳. دانلود در صورت عدم وجود (با تجمیع درخواست‌های همزمان)
    async with _guard:
        cached = _find_cached_audio(cache_key)
        if cached and cached.exists():
            return cached

        if cache_key in _pending_fetches:
            task = _pending_fetches[cache_key]
        else:
            out_stem = STREAM_CACHE_DIR / cache_key
            task = asyncio.create_task(
                asyncio.to_thread(_download_stream_worker, track, out_stem, quality)
            )
            _pending_fetches[cache_key] = task

    try:
        path = await task
        asyncio.create_task(asyncio.to_thread(_prune_cache_sync))
        return path
    finally:
        async with _guard:
            if _pending_fetches.get(cache_key) == task and task.done():
                _pending_fetches.pop(cache_key, None)


async def get_stream_response(
    track: Track, range_header: str | None = None, quality: str | None = None
) -> Response:
    """
    ارسال پاسخ صوتی استریم با پشتیبانی کامل از Range و CORS.
    """
    path = await get_or_fetch(track, quality=quality)
    media_type = AUDIO_MIME.get(path.suffix.lower(), "audio/mpeg")
    headers = {
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length, Content-Disposition",
    }
    return FileResponse(path, media_type=media_type, headers=headers)


async def get_or_fetch_lyrics(track: Track) -> str | None:
    """دریافت لیریکس همگام برای ترک استریم‌شده (با کش روی دیسک)."""
    cache_key = cache_key_for(track.id)
    lrc_path = STREAM_CACHE_DIR / f"{cache_key}.lrc"
    if lrc_path.exists():
        try:
            return lrc_path.read_text(encoding="utf-8")
        except OSError:
            pass

    def _fetch_sync():
        try:
            found = lrclib.fetch(track.title, track.artist, track.album, track.durationMs)
            if not found:
                return None
            content = found.synced or found.plain
            if content:
                STREAM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                lrc_path.write_text(content, encoding="utf-8")
            return content
        except Exception:
            return None

    return await asyncio.to_thread(_fetch_sync)
