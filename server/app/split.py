"""
تکه‌کردنِ میکس‌های بلند به ترک‌های جدا.

«۲ ساعت بهترین‌های فلانی» یک فایلِ دویست‌مگابایتی است که هیچ پلیری نمی‌تواند
ترکِ ششم را در آن پیدا کند. ولی همان ویدیو معمولاً چپتر دارد — یعنی خودِ
آپلودکننده مرزها و نام‌ها را نوشته. اینجا از همان استفاده می‌کنیم: یک بار
دانلود، بعد بریدن با ffmpeg، و هر تکه یک ردیفِ کاملِ کتابخانه با تگ و متن آهنگ.

چرا یک تسکِ جدا و نه چند جابِ معمولی: هر جاب یک دانلود است. اگر برای هر چپتر یک
جاب می‌ساختیم، همان فایلِ دو ساعته بیست بار دانلود می‌شد. پس دانلود یک‌بار
اتفاق می‌افتد و تکه‌ها مستقیم به‌شکلِ ردیف‌های *آماده* در دیتابیس می‌نشینند —
از آن به بعد برای بقیه‌ی سیستم (کتابخانه، پخش، ZIP، حذف) هیچ فرقی با یک دانلودِ
عادی ندارند.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from yt_dlp import YoutubeDL

from . import db, downloader, jobs, loudness, mood, ydl
from .config import FFMPEG_BIN, LOUDNESS_ENABLED, MOOD_ENABLED
from .models import Quality, Track

# تکه‌ی کوتاه‌تر از این معمولاً اینترو/تیتراژ است، نه آهنگ
MIN_CHAPTER_SECONDS = 30.0
# سقفِ تعداد تکه در یک درخواست — جلوگیری از قفل‌شدنِ سرور روی یک ویدیوی ۸ ساعته
MAX_CHAPTERS = 60

# «۰۱.» ، «۰۱ -» ، «1)» ، «[03]» در ابتدای نام چپتر. عددِ بی‌قلاب فقط وقتی
# شماره حساب می‌شود که جداکننده‌ای پشتش باشد، وگرنه «50 Cent» می‌شد «Cent».
_LEADING_INDEX = re.compile(r"^\s*(?:[\[(]\s*\d{1,3}\s*[\])]|\d{1,3}\s*[-–—.:)])\s*")
# «0:00» یا «00:03:21» که بعضی آپلودکننده‌ها داخل نام چپتر هم می‌گذارند
_TIMESTAMP = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
# دنباله‌های تبلیغاتی
_NOISE = re.compile(
    r"\((?:official|lyrics?|audio|video|hd|hq|full)[^)]*\)"
    r"|\[(?:official|lyrics?|audio|video)[^\]]*\]",
    re.IGNORECASE,
)
_SEPARATORS = (" - ", " – ", " — ", " | ", " ~ ")


@dataclass
class Chapter:
    index: int
    title: str
    start_ms: int
    end_ms: int
    artist: str | None
    song_title: str


@dataclass
class SplitSource:
    url: str
    title: str
    uploader: str
    duration_ms: int
    artwork_url: str | None
    chapters: list[Chapter]


def clean_title(raw: str) -> tuple[str | None, str]:
    """
    (هنرمند، عنوان) از روی نامِ یک چپتر.

    قرارداد رایج «۰۱. هنرمند - عنوان» است، ولی نه همیشه: بعضی فقط عنوان
    می‌نویسند. وقتی جداکننده‌ای نباشد هنرمند None می‌ماند و صدازننده هنرمندِ
    خودِ ویدیو را جایش می‌گذارد — بهتر از حدسِ اشتباه.
    """
    text = _NOISE.sub(" ", raw)
    text = _TIMESTAMP.sub(" ", text)
    text = _LEADING_INDEX.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—|.")

    for separator in _SEPARATORS:
        if separator in text:
            left, _, right = text.partition(separator)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return None, text or raw.strip()


def _chapters_from(info: dict) -> list[Chapter]:
    total = float(info.get("duration") or 0)
    raw = info.get("chapters") or []
    out: list[Chapter] = []

    for index, entry in enumerate(raw):
        start = float(entry.get("start_time") or 0)
        end = float(entry.get("end_time") or 0) or total
        if end - start < MIN_CHAPTER_SECONDS:
            continue
        name = (entry.get("title") or "").strip()
        if not name:
            continue
        artist, song = clean_title(name)
        out.append(
            Chapter(
                index=index,
                title=name,
                start_ms=int(start * 1000),
                end_ms=int(end * 1000),
                artist=artist,
                song_title=song,
            )
        )
    return out[:MAX_CHAPTERS]


def probe(url: str, user_id: str = db.GUEST_ID) -> SplitSource | None:
    """
    چپترهای یک لینک. None یعنی لینک باز نشد؛ لیستِ خالیِ chapters یعنی باز شد
    ولی چپتری نداشت. بلاک‌کننده است — در thread صدا زده شود.
    """
    try:
        with YoutubeDL(ydl.opts(user_id=user_id, skip_download=True)) as y:
            info = y.extract_info(url, download=False)
    except Exception:
        return None
    if not info or info.get("_type") == "playlist":
        return None

    return SplitSource(
        url=info.get("webpage_url") or url,
        title=info.get("title") or "میکس",
        uploader=info.get("uploader") or info.get("channel") or "ناشناس",
        duration_ms=int(float(info.get("duration") or 0) * 1000),
        artwork_url=info.get("thumbnail"),
        chapters=_chapters_from(info),
    )


def _cut(source: Path, chapter: Chapter, target: Path) -> bool:
    """
    یک بازه را بدون ترنسکد بیرون می‌کشد.

    `-c copy` یعنی همان بیت‌های اصلی — نه افتِ کیفیتِ دوباره، نه چند دقیقه CPU
    به‌ازای هر تکه. دقتِ برش به مرزِ فریمِ صوتی گره می‌خورد (~۲۶ میلی‌ثانیه در
    mp3) که برای مرزِ آهنگ‌ها کاملاً کافی است.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    duration = (chapter.end_ms - chapter.start_ms) / 1000
    try:
        subprocess.run(
            [
                FFMPEG_BIN, "-nostdin", "-hide_banner", "-y",
                "-ss", f"{chapter.start_ms / 1000:.3f}",
                "-t", f"{duration:.3f}",
                "-i", str(source),
                "-map", "a:0", "-c", "copy",
                str(target),
            ],
            capture_output=True,
            timeout=300,
            check=True,
        )
        return target.exists() and target.stat().st_size > 0
    except Exception:
        target.unlink(missing_ok=True)
        return False


@dataclass
class SplitTask:
    id: str
    total: int
    status: str = "queued"  # queued | downloading | cutting | done | error
    percent: float = 0.0
    done: int = 0
    error: str | None = None
    job_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    task: asyncio.Task | None = None
    # صاحبِ تسک: پولینگ و قطعه‌های تازه فقط برای همین کاربر دیده می‌شوند
    user_id: str = db.GUEST_ID


_tasks: dict[str, SplitTask] = {}
TASK_TTL = 3600.0


def get(task_id: str) -> SplitTask | None:
    return _tasks.get(task_id)


def _sweep() -> None:
    cutoff = time.time() - TASK_TTL
    for key in [k for k, t in _tasks.items() if t.created_at < cutoff]:
        _tasks.pop(key, None)


def start(
    source: SplitSource,
    chapters: list[Chapter],
    quality: Quality,
    user_id: str = db.GUEST_ID,
) -> SplitTask:
    """تسک را می‌سازد و در پس‌زمینه اجرا می‌کند. پیشرفتش با polling خوانده می‌شود."""
    _sweep()
    task = SplitTask(id=uuid.uuid4().hex[:12], total=len(chapters), user_id=user_id)
    _tasks[task.id] = task
    task.task = asyncio.create_task(_run(task, source, chapters, quality))
    return task


def _source_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _child_track(source: SplitSource, chapter: Chapter, quality: Quality) -> Track:
    """
    متادیتای یک تکه.

    هنرمند از خودِ نامِ چپتر درمی‌آید اگر «هنرمند - عنوان» بوده باشد، وگرنه
    آپلودکننده‌ی ویدیو. شماره‌ی ترک از ترتیبِ چپترها می‌آید تا آلبومِ حاصل در
    هر پلیری به همان ترتیبِ میکس بماند.
    """
    return Track(
        # شناسه باید بینِ ری‌استارت‌ها هم یکی بماند تا تکه‌کردنِ دوباره‌ی همان
        # میکس در کتابخانه دوتا نشود — hash() داخلیِ پایتون هر پروسه عوض می‌شود.
        # کیفیت هم داخلش هست چون find_ready روی (track_id, quality) کار می‌کند.
        id=f"split:{quality}:{_source_key(source.url)}:{chapter.index}",
        title=chapter.song_title,
        artist=chapter.artist or source.uploader,
        album=source.title,
        durationMs=chapter.end_ms - chapter.start_ms,
        artworkUrl=source.artwork_url,
        source="youtube" if "youtu" in source.url else "soundcloud",
        sourceUrl=f"{source.url}#t={chapter.start_ms // 1000}",
        trackNumber=chapter.index + 1,
    )


async def _run(
    task: SplitTask, source: SplitSource, chapters: list[Chapter], quality: Quality
) -> None:
    holder = jobs.job_dir(f"split-{task.id}")
    mix_path: Path | None = None
    try:
        task.status = "downloading"

        # ترکِ ساختگی فقط برای نام‌گذاریِ فایلِ موقت است؛ در دیتابیس نمی‌نشیند
        mix = Track(
            id=f"splitsrc:{task.id}",
            title=source.title,
            artist=source.uploader,
            durationMs=source.duration_ms,
            artworkUrl=source.artwork_url,
            source="youtube",
            sourceUrl=source.url,
        )

        def on_progress(pct: float) -> None:
            # دانلود سهمِ شیرِ زمان است ولی تنها نیمی از کار؛ ۷۰٪ برایش
            task.percent = round(pct * 0.7, 1)

        mix_path = await asyncio.to_thread(
            downloader.download,
            mix,
            source.url,
            quality,
            on_progress,
            holder,
            None,
            task.user_id,
        )

        task.status = "cutting"
        for position, chapter in enumerate(chapters):
            job_id = uuid.uuid4().hex[:12]
            track = _child_track(source, chapter, quality)
            target = jobs.job_dir(job_id) / (
                downloader.safe_name(f"{track.artist} - {track.title}") + mix_path.suffix
            )

            if not await asyncio.to_thread(_cut, mix_path, chapter, target):
                continue

            db.insert_job(job_id, track, quality, "queued", time.time(), user_id=task.user_id)
            final = await asyncio.to_thread(
                downloader.finalize, target, track, task.user_id
            )
            lyrics_path = final.lyrics_path

            measured = (
                await asyncio.to_thread(loudness.analyze, target)
                if LOUDNESS_ENABLED
                else None
            )
            detected = (
                await asyncio.to_thread(mood.analyze, target) if MOOD_ENABLED else None
            )

            db.update_job(
                job_id,
                status="ready",
                # کاورِ تکه‌ها از همان مکسِ مادر می‌آید؛ نیامدنش همان‌قدر مهم است
                # که در دانلودِ معمولی — و همان‌قدر بی‌صدا بود
                warning=jobs.NO_COVER if track.artworkUrl and not final.cover else None,
                path=str(target),
                lyrics_path=str(lyrics_path) if lyrics_path else None,
                bytes=target.stat().st_size,
                format=await asyncio.to_thread(downloader.describe, target),
                finished_at=time.time(),
                valence=detected[0] if detected else None,
                energy=detected[1] if detected else None,
                loudness=measured[0] if measured else None,
                peak=measured[1] if measured else None,
            )
            task.job_ids.append(job_id)
            task.done = position + 1
            task.percent = round(70 + 30 * (position + 1) / len(chapters), 1)

        if not task.job_ids:
            task.status = "error"
            task.error = "هیچ تکه‌ای بریده نشد"
            return

        task.status = "done"
        task.percent = 100.0
    except asyncio.CancelledError:
        task.status = "error"
        task.error = "لغو شد"
        raise
    except Exception as exc:  # noqa: BLE001 — خطا باید به کلاینت برسد نه به لاگ
        task.status = "error"
        task.error = str(exc)[:200]
    finally:
        # فایلِ میکسِ کامل بعد از بریدن فقط دیسک می‌خورد؛ چیزی به آن اشاره
        # نمی‌کند و پاک‌سازیِ یتیم‌ها هم یک ساعت بعد سراغش می‌آمد
        if mix_path is not None:
            mix_path.unlink(missing_ok=True)
        try:
            if holder.is_dir() and not any(holder.iterdir()):
                holder.rmdir()
        except OSError:
            pass
