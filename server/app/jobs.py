"""
صف کارهای دانلود.

هر کار یک state ماشین است: queued → searching → downloading → tagging → ready | error.
yt-dlp بلاک‌کننده است، پس در thread اجرا می‌شود و پیشرفت را به حلقه‌ی asyncio پس می‌دهد.

دیتابیس منبع حقیقت است و حافظه فقط کش. کار تمام‌شده بعد از مدتی از کش بیرون
می‌رود ولی ردیفش می‌ماند — «کتابخانه» دقیقاً همین ردیف‌های موفق‌اند.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import db, downloader, loudness, mood, reach, resolver, verify
from .config import (
    DEFER_DOWNLOADS,
    DOWNLOAD_DIR,
    FILE_RETENTION_SECONDS,
    JOB_TTL_SECONDS,
    LOUDNESS_ENABLED,
    LYRICS_ENABLED,
    MAX_CONCURRENT_DOWNLOADS,
    MOOD_ENABLED,
)
from .models import DownloadProgress, Quality, Track

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    track: Track
    quality: Quality
    progress: DownloadProgress
    path: Path | None = None
    lyrics_path: Path | None = None
    bytes: int = 0
    valence: float | None = None
    energy: float | None = None
    # بلندیِ ادراکی و اوجِ واقعی (EBU R128) — خامْ ذخیره می‌شوند و تبدیلشان به
    # «چند دسی‌بل تقویت» موقع تحویل انجام می‌شود، چون هدفِ نرمال‌سازی قابل
    # تغییر است و فایل‌های قدیمی نباید با عوض شدنش دوباره اندازه‌گیری شوند
    loudness: float | None = None
    peak: float | None = None
    created_at: float = field(default_factory=time.time)
    task: asyncio.Task | None = None
    # نخِ دانلود این را می‌خواند تا خودش را جمع کند؛ لغو تسک به آن نمی‌رسد
    canceled: bool = False
    finished_at: float | None = None
    # نسخه‌ای که کاربر خودش انتخاب کرده — resolver اصلاً صدا زده نمی‌شود
    candidate_url: str | None = None
    subscribers: set[asyncio.Queue[DownloadProgress]] = field(default_factory=set)


TERMINAL = ("ready", "error", "canceled")

# خطاهای خام yt-dlp برای کاربر بی‌معنی‌اند؛ به پیام قابل‌فهم ترجمه می‌شوند
_ERROR_HINTS = (
    ("not a bot", "یوتیوب احراز هویت می‌خواهد — UNSTREAM_COOKIES_BROWSER را ست کن"),
    ("DRM", "این نسخه DRM دارد و قابل دانلود نیست"),
    ("Private video", "این ویدیو خصوصی است"),
    ("Video unavailable", "این ویدیو در دسترس نیست"),
    ("HTTP Error 404", "لینک منبع پیدا نشد"),
    ("Requested format", "فرمت صوتی قابل دانلودی ارائه نشد"),
)


def _readable(raw: str) -> str:
    for needle, message in _ERROR_HINTS:
        if needle.lower() in raw.lower():
            return message
    return raw.replace("ERROR: ", "").strip()[:200] or "دانلود ناموفق بود"


def file_url(job_id: str) -> str:
    return f"/api/downloads/{job_id}/file"


def stream_url(job_id: str) -> str:
    """
    آدرس پخش، جدا از آدرس ذخیره.

    `/file` با `content-disposition: attachment` و mime عمومی می‌آید تا مرورگر
    ذخیره‌اش کند؛ `<audio>` به mime واقعی نیاز دارد وگرنه بعضی مرورگرها اصلاً
    رمزگشایی را شروع نمی‌کنند. هر دو روی همان فایل‌اند.
    """
    return f"/api/downloads/{job_id}/stream"


def lyrics_url(job_id: str) -> str:
    return f"/api/downloads/{job_id}/lyrics"


def job_dir(job_id: str) -> Path:
    """
    هر جاب پوشه‌ی خودش را دارد.

    اسم فایل فقط «هنرمند - عنوان» است و کیفیت را در خود ندارد؛ در یک پوشه‌ی
    مشترک، دانلود همان ترک با کیفیت دیگر فایل قبلی را پاک می‌کرد و ردیف قدیمی
    به فایل جدید اشاره می‌ماند — یعنی کتابخانه یک فایل را دو بار با دو برچسب
    نشان می‌داد. با پوشه‌ی جدا، نام فایل تمیز می‌ماند و برخوردی هم نیست.
    """
    return DOWNLOAD_DIR / job_id


def _rmdir_if_empty(folder: Path) -> None:
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass  # هنوز چیزی تویش هست — بماند برای پاک‌سازی دیسک


# کاتالوگ کاور داشت ولی گرفتنش نشد. متنش عمداً می‌گوید فایل سالم است: بدون آن،
# تنها نشانه‌ی این اتفاق یک پلیرِ بی‌تصویر بود که کاربر آن را «فایل خراب»
# می‌خواند — همان چیزی که با UNSTREAM_YTDLP_PROXYِ تنها یا یک ۴۰۴ِ CDN رخ می‌داد.
NO_COVER = "کاور این آهنگ از منبع گرفته نشد؛ فایل سالم است ولی تصویر ندارد"


def _file_duration_ms(path: Path) -> int | None:
    """مدتِ فایلِ دانلودشده با mutagen؛ خوانده نشد None — هشدار جا نمی‌افتد."""
    try:
        from mutagen import File as mutagen_file

        audio = mutagen_file(path)
        return int(audio.info.length * 1000) if audio and audio.info else None
    except Exception:  # noqa: BLE001 — فایل عجیب == بدون هشدارِ مدت
        return None


def _substitution(track: Track, used: resolver.Candidate | None) -> str | None:
    """
    وقتی فایل از جایی جز لینکِ خودِ ترک آمده.

    ترکی که از یوتیوب/ساندکلاد آمده خودش لینکِ همان آپلود را دارد و resolver
    هم فقط همان را می‌دهد. اگر آن لینک دانلود نشد و جایگزینی نشست، فایل یک
    آپلودِ *دیگر* از همان آهنگ است: بازنشرِ دستکاری‌شده، ریمستر، یا کاتِ دیگر.
    تگ‌ها از خودِ Track نوشته می‌شوند، پس نه اسم فایل نه کاور نه متن چیزی لو
    نمی‌دهد — کاربر تازه موقع پخش می‌فهمید صدا آنی نیست که در آن صفحه دیده.

    برای ترک‌های اپل/دیزر/اسپاتیفای بی‌معنی است: آن‌ها اصلاً فایل صوتی ندارند
    و `sourceUrl` شان صفحه‌ی کاتالوگ است، پس هر دانلودی «جایگزین» است.
    """
    if used is None or track.source not in ("youtube", "soundcloud"):
        return None
    if not track.sourceUrl or used.url == track.sourceUrl:
        return None
    where = used.uploader or used.source
    return f"لینک خودِ این ترک دانلود نشد؛ این فایل نسخه‌ی «{used.title}» از {where} است"

def _discard(path: Path | None) -> None:
    """فایل را می‌برد و اگر پوشه‌ی اختصاصی جاب خالی شد، خودش را هم."""
    if path is None:
        return
    path.unlink(missing_ok=True)
    parent = path.parent
    if parent != DOWNLOAD_DIR and parent.parent == DOWNLOAD_DIR:
        _rmdir_if_empty(parent)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        self._loop: asyncio.AbstractEventLoop | None = None
        # کارهای پس‌زمینه‌ای که به جابِ در جریان بند نیستند (مثل گرفتنِ دوباره‌ی
        # متن). بدون نگه‌داشتنِ ارجاع، asyncio وسطِ کار جمعشان می‌کند.
        self._background: set[asyncio.Task] = set()
        # متن‌گیریِ دوباره باید یواش باشد: «دانلودِ همه»ی یک آلبومِ بی‌متن وگرنه
        # ده‌ها درخواستِ هم‌زمان به LRCLIB/Genius می‌زد و همان محدودشدنی که
        # اول باعثِ نبودنِ متن شده بود، دوباره تکرار می‌شد
        self._lyric_slots = asyncio.Semaphore(2)

    # ---------- ورودی عمومی ----------

    def create(
        self, track: Track, quality: Quality, candidate_url: str | None = None
    ) -> tuple[Job, bool]:
        """(کار، آیا از کتابخانه بازاستفاده شد)."""
        self._loop = asyncio.get_running_loop()
        self._sweep()

        # انتخاب دستی یعنی «همانی که داری غلط است» — بازاستفاده دقیقاً همان
        # فایلِ ناخواسته را برمی‌گرداند و کاربر فکر می‌کند دکمه کار نکرد
        if candidate_url is None and (existing := self._reusable(track.id, quality)):
            self._backfill(existing, track)
            self._refresh_lyrics(existing)
            return existing, True

        # موقعِ قطعیِ بین‌الملل هیچ‌کدام از منابعِ صوتی در دسترس نیستند و اجرای
        # جاب فقط یک تایم‌اوتِ چندده‌ثانیه‌ای است که به `error` ختم می‌شود. صف
        # کردنش هم صادقانه‌تر است هم مفیدتر: کاربر یک بار می‌زند و شب که
        # اینترنت برگشت، فایل آماده است.
        deferred = DEFER_DOWNLOADS and not reach.online()
        status = "deferred" if deferred else "queued"

        job = Job(
            id=uuid.uuid4().hex[:12],
            track=track,
            quality=quality,
            progress=DownloadProgress(status=status, percent=0),
            candidate_url=candidate_url,
        )
        self._jobs[job.id] = job
        db.insert_job(job.id, track, quality, status, job.created_at, candidate_url)
        if not deferred:
            job.task = asyncio.create_task(self._run(job))
        return job, False

    def start_deferred(self, job: Job) -> bool:
        """
        یک کارِ معوق را راه می‌اندازد. برای هر جاب فقط یک بار اثر دارد.

        شرطِ وضعیت لازم است چون هم حلقه‌ی پس‌زمینه صدایش می‌زند هم می‌شود از
        بیرون دستی زد؛ بدونش دو تسکِ موازی روی یک فایل می‌نشستند.
        """
        if job.progress.status != "deferred":
            return False
        # `_emit` هم ردیفِ دیتابیس را می‌نویسد هم به مشترک‌های SSE خبر می‌دهد —
        # کلاینتی که از دیشب روی همین جاب باز مانده، بدون رفرش راه‌افتادنش را
        # می‌بیند
        self._loop = asyncio.get_running_loop()
        self._emit(job, status="queued", percent=0, error=None)
        job.task = asyncio.create_task(self._run(job))
        return True

    def resume_deferred(self) -> int:
        """
        هرچه در صفِ معوق مانده را راه می‌اندازد. تعدادِ شروع‌شده برمی‌گردد.

        از دیتابیس می‌خواند نه از کشِ حافظه: صف عمداً از ری‌استارت جان سالم به
        در می‌برد، و بعد از ری‌استارت این ردیف‌ها در حافظه نیستند.
        """
        started = 0
        for row in db.deferred_jobs():
            job = self._jobs.get(row["id"]) or self._from_row(row)
            self._jobs[job.id] = job
            if self.start_deferred(job):
                started += 1
        return started

    def get(self, job_id: str) -> Job | None:
        """کش، وگرنه دیتابیس. بعد از ری‌استارت سرور هم فایل‌های قدیمی پیدا می‌شوند."""
        if job := self._jobs.get(job_id):
            return job
        row = db.get_job(job_id)
        if row is None:
            return None
        job = self._from_row(row)
        self._jobs[job.id] = job
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.progress.status in TERMINAL:
            return False
        # قبل از لغو تسک: نخِ دانلود فقط از همین پرچم خبردار می‌شود
        job.canceled = True
        if job.task:
            job.task.cancel()
        return True

    def forget(self, job_id: str) -> bool:
        """حذف کامل: فایل، متن، و ردیف دیتابیس."""
        job = self.get(job_id)
        if job is None:
            return False
        self.cancel(job_id)
        for path in (job.path, job.lyrics_path):
            _discard(path)
        self._jobs.pop(job_id, None)
        db.delete_job(job_id)
        return True

    async def subscribe(self, job: Job) -> asyncio.Queue[DownloadProgress]:
        """
        صف رویداد یک مشترک. وضعیت فعلی بلافاصله فرستاده می‌شود تا اگر کلاینت
        دیر وصل شد (یا کار خیلی زود تمام شد) هیچ رویدادی را از دست ندهد.
        """
        queue: asyncio.Queue[DownloadProgress] = asyncio.Queue()
        await queue.put(job.progress)
        if job.progress.status not in TERMINAL:
            job.subscribers.add(queue)
        return queue

    def unsubscribe(self, job: Job, queue: asyncio.Queue[DownloadProgress]) -> None:
        job.subscribers.discard(queue)

    # ---------- داخلی ----------

    def _from_row(self, row: sqlite3.Row) -> Job:
        path = db.row_path(row)
        lyrics = Path(row["lyrics_path"]) if row["lyrics_path"] else None
        return Job(
            id=row["id"],
            track=Track.model_validate_json(row["track_json"]),
            quality=row["quality"],
            path=path,
            lyrics_path=lyrics,
            bytes=int(row["bytes"] or 0),
            valence=row["valence"],
            energy=row["energy"],
            loudness=row["loudness"],
            peak=row["peak"],
            created_at=float(row["created_at"]),
            finished_at=row["finished_at"],
            candidate_url=row["candidate_url"],
            progress=DownloadProgress(
                status=row["status"],
                percent=100.0 if row["status"] == "ready" else 0.0,
                error=row["error"],
                warning=row["warning"],
                format=row["format"],
                fileUrl=file_url(row["id"]) if path else None,
                streamUrl=stream_url(row["id"]) if path else None,
                lyricsUrl=lyrics_url(row["id"]) if lyrics else None,
                gainDb=loudness.gain_db(row["loudness"], row["peak"]),
            ),
        )

    def _reusable(self, track_id: str, quality: Quality) -> Job | None:
        """
        همین ترک با همین کیفیت از قبل دانلود شده؟ پس دوباره نگیرش.

        این تنها جایی است که کتابخانه واقعاً به کار می‌آید: «دانلود همه»ی یک
        آلبومی که نصفش را قبلاً گرفته‌ای، فقط بقیه‌اش را می‌گیرد.
        """
        row = db.find_ready(track_id, quality)
        if row is None:
            return None
        job = self._jobs.get(row["id"]) or self._from_row(row)
        if job.path is None or not job.path.exists():
            # ردیف هست ولی فایل نیست (پاک‌سازی دیسک یا حذف دستی) — ردیف را هم ببر
            db.delete_job(row["id"])
            self._jobs.pop(row["id"], None)
            return None
        self._jobs[job.id] = job
        return job

    # متادیتایی که فقط آلبوم می‌داند و نتیجه‌ی جستجوی تکی نمی‌دانست
    _BACKFILLABLE = ("album", "albumId", "albumArtist", "trackNumber", "discNumber", "year", "genre")

    def _backfill(self, job: Job, track: Track) -> None:
        """
        فیلدهای غایبِ ترکِ ذخیره‌شده را از درخواستِ تازه پر می‌کند.

        بازاستفاده یعنی فایل از قبل روی دیسک است، با تگ‌های همان روز. کسی که
        ترکی را از نتیجه‌ی جستجو گرفته و حالا کل آلبوم را می‌گیرد، بدون این،
        همان فایلِ بی‌شماره و بی‌هنرمندِ آلبوم را در ZIP می‌گرفت و آلبومش در
        پلیر تکه‌تکه می‌ماند.

        فقط غایب‌ها پر می‌شوند — چیزی که مقدار دارد دست‌نخورده می‌ماند، مگر
        اینکه ترکی قبلاً به‌عنوان سینگل ذخیره شده بود (album خالی یا برابر با عنوان ترک)
        و حالا با یک آلبومِ واقعی و کاورِ آن آلبوم دوباره خواسته شده است.
        """
        filled: dict[str, Any] = {}
        for field in self._BACKFILLABLE:
            val = getattr(track, field)
            if val is not None and getattr(job.track, field) is None:
                filled[field] = val

        # اگر قبلاً سینگل بود (یا نام آلبوم همان نام ترک بود) و حالا نام آلبوم واقعی آمده
        if track.album and (job.track.album is None or job.track.album == job.track.title):
            filled["album"] = track.album
            if track.albumArtist:
                filled["albumArtist"] = track.albumArtist
            if track.albumId:
                filled["albumId"] = track.albumId
            if track.trackNumber:
                filled["trackNumber"] = track.trackNumber

        # کاور: اگر کاور جدیدی از آلبوم آمده
        artwork_changed = False
        if track.artworkUrl and track.artworkUrl != job.track.artworkUrl:
            # اگر فایل قبلی کاور نداشت یا ترک در قالب یک آلبوم خواسته شده
            if job.track.artworkUrl is None or track.album:
                filled["artworkUrl"] = track.artworkUrl
                artwork_changed = True

        if not filled and not artwork_changed:
            return

        if filled:
            job.track = job.track.model_copy(update=filled)
            db.update_track(job.id, job.track)

        if job.path and job.path.exists():
            downloader.retag_album(job.path, job.track)
            if artwork_changed and track.artworkUrl:
                downloader.retag_artwork(job.path, track.artworkUrl)

    def _refresh_lyrics(self, job: Job) -> None:
        """
        فایلِ بازاستفاده‌شده‌ای که متن ندارد، یک بار دیگر شانسش را امتحان می‌کند.

        متن اختیاری است و ممکن است روزِ دانلود نبوده باشد — سرویس بالا نبوده،
        کلیدِ Genius هنوز ست نشده بود، یا متن آن‌وقت اصلاً خاموش بود. بدون این،
        «دانلودِ دوباره» همان فایلِ بی‌متن را برمی‌گرداند و تنها راهِ باقی‌مانده
        پاک کردنِ دستیِ ترک و گرفتنِ دوباره‌اش بود.

        در پس‌زمینه می‌رود چون بازاستفاده باید فوری جواب بدهد: کاربر منتظرِ
        دکمه است، نه منتظرِ دو درخواستِ شبکه.
        """
        if not LYRICS_ENABLED or job.path is None or not job.path.exists():
            return
        if job.lyrics_path and job.lyrics_path.exists():
            return

        async def run() -> None:
            async with self._lyric_slots:
                try:
                    lyrics = await asyncio.to_thread(downloader.fetch_lyrics, job.track)
                    if not lyrics or job.path is None:
                        return
                    await asyncio.to_thread(downloader.attach_lyrics, job.path, lyrics)
                    job.lyrics_path = await asyncio.to_thread(
                        downloader.write_lrc, job.path, lyrics
                    )
                    db.update_job(
                        job.id,
                        lyrics_path=str(job.lyrics_path) if job.lyrics_path else None,
                    )
                    # جابِ بازاستفاده‌شده از قبل ready است؛ فقط مشترک‌ها باید
                    # بفهمند که حالا متنی هم هست تا دکمه‌اش ظاهر شود
                    if job.lyrics_path:
                        self._emit(job, lyricsUrl=lyrics_url(job.id))
                except Exception:
                    pass  # متن اختیاری است — شکستش نباید جایی دیده شود

        task = asyncio.create_task(run())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _emit(self, job: Job, **changes) -> None:
        job.progress = job.progress.model_copy(update=changes)
        if job.progress.status in TERMINAL:
            job.finished_at = time.time()

        # درصد عمداً ذخیره نمی‌شود: صدها نوشتن در ثانیه برای عددی که
        # بعد از ری‌استارت هیچ معنایی ندارد.
        if "status" in changes:
            db.update_job(
                job.id,
                status=job.progress.status,
                error=job.progress.error,
                warning=job.progress.warning,
                format=job.progress.format,
                path=str(job.path) if job.path else None,
                lyrics_path=str(job.lyrics_path) if job.lyrics_path else None,
                bytes=job.bytes,
                finished_at=job.finished_at,
                valence=job.valence,
                energy=job.energy,
                loudness=job.loudness,
                peak=job.peak,
            )

        for queue in list(job.subscribers):
            queue.put_nowait(job.progress)

    def _emit_threadsafe(self, job: Job, **changes) -> None:
        """از داخل thread دانلود صدا زده می‌شود."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(lambda: self._emit(job, **changes))

    async def _attempt(
        self, job: Job, candidates: list[resolver.Candidate]
    ) -> tuple[Path | None, resolver.Candidate | None, str]:
        """
        کاندیدها را به‌ترتیبِ امتیاز امتحان می‌کند تا اولین موفقیت؛ در شکستِ
        کامل (None, None, پیامِ آخرین خطا) — کاندید با بالاترین امتیاز لزوماً
        دانلودشدنی نیست (گیت ضدربات، DRM، لینک مرده).

        خودِ کاندیدِ موفق هم برمی‌گردد، نه فقط مسیر: صدازننده باید بداند فایل
        از کدام نسخه آمده تا اگر آنی نبود که کاربر خواسته، بتواند بگوید.
        """
        last_error = ""
        for candidate in candidates:
            sent = [0.0]  # throttle: پروگرس‌هوک yt-dlp خیلی پرتکرار است

            def on_progress(pct: float) -> None:
                if pct - sent[0] >= 1.0 or pct >= 99:
                    sent[0] = pct
                    self._emit_threadsafe(job, status="downloading", percent=pct)

            self._emit(job, status="downloading", percent=0)
            try:
                path = await asyncio.to_thread(
                    downloader.download,
                    job.track,
                    candidate.url,
                    job.quality,
                    on_progress,
                    job_dir(job.id),
                    lambda: job.canceled,
                )
                return path, candidate, ""
            except downloader.DownloadCanceled:
                # نخ به‌موقع خودش را جمع کرد — کاندید بعدی معنی ندارد
                raise asyncio.CancelledError from None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return None, None, last_error

    async def _run(self, job: Job) -> None:
        try:
            async with self._slots:
                self._emit(job, status="searching", percent=0)

                if job.candidate_url:
                    # کاربر انتخاب کرده؛ جستجوی دوباره فقط وقت تلف کردن است و
                    # ممکن است همان انتخاب را دوباره کنار بگذارد
                    candidates = [
                        resolver.Candidate(
                            url=job.candidate_url,
                            title=job.track.title,
                            uploader=job.track.artist,
                            duration_ms=job.track.durationMs,
                            score=100.0,
                        )
                    ]
                else:
                    candidates = await asyncio.to_thread(resolver.resolve, job.track)
                if not candidates:
                    self._emit(
                        job,
                        status="error",
                        error="نسخه‌ی قابل دانلودی برای این آهنگ پیدا نشد",
                    )
                    return

                path, used, last_error = await self._attempt(job, candidates)

                # همه‌ی کاندیدهای resolve() شکست خوردند (DRM، گیتِ ضدربات،
                # حذف‌شده) — چه آن کاندیدها لینکِ مستقیمِ یوتیوب/ساندکلاد بودند
                # چه نتیجه‌ی زودهنگامِ «قانع‌کننده»ی یک منبع که مانع پرسیدن از
                # بقیه‌ی AUDIO_SOURCES شد (مثلاً ساندکلاد امتیازِ بالا داد ولی آن
                # نسخه DRM داشت، درحالی‌که یوتیوب اصلاً پرسیده نشده بود). آخرین
                # راه، جستجوی منبع(های)ی است که هنوز امتحان نشده‌اند.
                # کاربری که خودش نسخه را انتخاب کرده (candidate_url) از این
                # قاعده جدا می‌ماند: انتخابش را دور نمی‌زنیم.
                if path is None and not job.candidate_url:
                    tried_sources = frozenset(c.source for c in candidates)
                    fallback = await asyncio.to_thread(
                        resolver.resolve_fallback, job.track, tried_sources
                    )
                    if fallback:
                        self._emit(job, status="searching", percent=0)
                        path, used, fallback_error = await self._attempt(job, fallback)
                        if fallback_error:
                            last_error = fallback_error

                if path is None:
                    # هیچ کاندیدی نگرفت — پوشه‌ی خالی‌اش نباید بماند
                    _rmdir_if_empty(job_dir(job.id))
                    self._emit(
                        job,
                        status="error",
                        percent=0,
                        error=_readable(last_error),
                    )
                    return

                # مسیر قبل از emit ست می‌شود تا ردیف دیتابیس همان‌جا صاحب فایل
                # بشناسد؛ وگرنه کرشِ وسط تگ‌گذاری یک فایل بی‌صاحب جا می‌گذارد
                job.path = path
                self._emit(job, status="tagging", percent=100)
                final = await asyncio.to_thread(downloader.finalize, path, job.track)
                job.lyrics_path = final.lyrics_path
                job.bytes = path.stat().st_size

                # فینگرپرینت صوتی فایل را رد نمی‌کند، فقط هشدار می‌دهد —
                # AcoustID روی موسیقی غیرغربی پوشش کاملی ندارد
                warning = await asyncio.to_thread(
                    verify.check, path, job.track.title, job.track.artist
                )
                # ترکِ ۲۹۲ ثانیه‌ای با فایلِ ۳۰ ثانیه‌ایِ بدون‌هشدار ready شد —
                # مدتِ واقعی فایل را با mutagen می‌خوانیم: اگر یک‌سومِ انتظار
                # نشد، فایل سگمنت است (پیش‌نمایش/کلیپ) و کاربر باید بداند.
                if (expected := job.track.durationMs) and (
                    actual := await asyncio.to_thread(_file_duration_ms, path)
                ) and actual < expected / 3:
                    short = (
                        f"فایل فقط {max(1, round(actual / 1000))} ثانیه است "
                        f"درحالی‌که آهنگ {round(expected / 1000)} ثانیه‌ست — "
                        "احتمالاً پیش‌نمایش دانلود شده"
                    )
                    warning = f"{short} — {warning}" if warning else short
                # کاورِ نیامده هم همین‌طور: فایل سالم است ولی در پلیر بی‌تصویر
                # می‌ماند. شرطِ `artworkUrl` عمدی است — وقتی کاتالوگ اصلاً کاوری
                # نداده، نیامدنش خبر نیست.
                if job.track.artworkUrl and not final.cover:
                    warning = f"{NO_COVER} — {warning}" if warning else NO_COVER
                if job.candidate_url is None and (swap := _substitution(job.track, used)):
                    # جایگزینی مهم‌تر از تردیدِ فینگرپرینت است — اول بیاید
                    warning = f"{swap} — {warning}" if warning else swap

                # اختیاری و بی‌صدا: بدون librosa یا با فایلِ عجیب، None برمی‌گردد
                # و شافل همان تصادفیِ قبلی می‌ماند — چیزی را نباید بترکاند
                if MOOD_ENABLED:
                    detected = await asyncio.to_thread(mood.analyze, path)
                    if detected:
                        job.valence, job.energy = detected

                # همان قرارداد: اگر ffmpeg نبود یا فایل خوانده نشد، None
                # می‌ماند و پخش‌کننده بدون تنظیمِ بلندی کار می‌کند
                if LOUDNESS_ENABLED:
                    measured = await asyncio.to_thread(loudness.analyze, path)
                    if measured:
                        job.loudness, job.peak = measured

                self._emit(
                    job,
                    status="ready",
                    percent=100,
                    warning=warning,
                    format=await asyncio.to_thread(downloader.describe, path),
                    fileUrl=file_url(job.id),
                    streamUrl=stream_url(job.id),
                    lyricsUrl=lyrics_url(job.id) if job.lyrics_path else None,
                    gainDb=loudness.gain_db(job.loudness, job.peak),
                )

        except asyncio.CancelledError:
            # کار نیمه‌تمام فایل نیمه‌تمام دارد؛ نگه داشتنش فقط دیسک را پر می‌کند.
            # کل پوشه می‌رود نه فقط مسیرهای شناخته‌شده: نخِ دانلود ممکن است تا
            # لحظه‌ی دیدنِ پرچمِ لغو چیزی نوشته باشد که این‌طرف اسمش را نمی‌داند.
            # اگر ویندوز به‌خاطر هندلِ باز نگذاشت، پاک‌سازی دیسک بعداً می‌بردش.
            job.path = job.lyrics_path = None
            shutil.rmtree(job_dir(job.id), ignore_errors=True)
            self._emit(job, status="canceled", percent=0)
            raise
        except Exception as exc:  # noqa: BLE001 — هر خطایی باید به کلاینت برسد
            self._emit(job, status="error", error=_readable(str(exc)))

    def _sweep(self) -> None:
        """
        کش حافظه را کوتاه نگه می‌دارد. ردیف دیتابیس دست نمی‌خورد — کار موفق
        باید در کتابخانه بماند و `get()` هر وقت لازم شد دوباره از دیسک می‌خواندش.
        """
        cutoff = time.time() - JOB_TTL_SECONDS
        stale = [
            jid
            for jid, j in self._jobs.items()
            if j.finished_at is not None and j.finished_at < cutoff and not j.subscribers
        ]
        for jid in stale:
            del self._jobs[jid]


manager = JobManager()


# ---------- نگهداری ----------


def sweep_disk() -> dict[str, int]:
    """
    فایل‌های منقضی و یتیم را از دیسک پاک می‌کند.

    قبلاً هیچ‌کس این کار را نمی‌کرد: جاب از حافظه می‌رفت ولی فایلش می‌ماند و
    `server/downloads/` تا آخر عمر پروژه بزرگ می‌شد.
    """
    now = time.time()
    removed_files = 0
    removed_rows = 0

    if FILE_RETENTION_SECONDS > 0:
        for row in db.expired_files(now - FILE_RETENTION_SECONDS):
            for value in (row["path"], row["lyrics_path"]):
                if value:
                    _discard(Path(value))
            db.delete_job(row["id"])
            manager._jobs.pop(row["id"], None)
            removed_files += 1

    for job_id in db.expired_failures(now - JOB_TTL_SECONDS):
        db.delete_job(job_id)
        manager._jobs.pop(job_id, None)
        removed_rows += 1

    # فایلی که هیچ ردیفی مالکش نیست، بازمانده‌ی دانلود شکست‌خورده یا نسخه‌ی
    # قبل از دیتابیس است. مهلت یک‌ساعته می‌دهیم تا دانلود در جریان قربانی نشود.
    known = db.known_paths()
    orphans = 0
    for entry in DOWNLOAD_DIR.iterdir():
        try:
            if entry.is_dir():
                # پوشه‌ی یک جاب. فقط وقتی می‌رود که هیچ فایلش صاحب نداشته باشد —
                # وگرنه پوشه‌ی جابی که هنوز در کتابخانه است را می‌بردیم.
                inside = [p for p in entry.rglob("*") if p.is_file()]
                if any(str(p) in known for p in inside):
                    continue
                newest = max((p.stat().st_mtime for p in inside), default=None)
                if now - (newest if newest is not None else entry.stat().st_mtime) < 3600:
                    continue
                shutil.rmtree(entry, ignore_errors=True)
                orphans += 1
                continue

            if not entry.is_file() or str(entry) in known:
                continue
            if now - entry.stat().st_mtime < 3600:
                continue
            entry.unlink(missing_ok=True)
            orphans += 1
        except OSError:
            continue

    return {"files": removed_files, "rows": removed_rows, "orphans": orphans}


async def sweep_loop(interval: float = 900.0) -> None:
    """حلقه‌ی پس‌زمینه‌ی نگهداری — در lifespan اپ بالا می‌آید."""
    while True:
        try:
            await asyncio.sleep(interval)
            await asyncio.to_thread(sweep_disk)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — نگهداری نباید سرور را بخواباند
            continue


async def defer_loop(interval: float = 15.0) -> None:
    """
    صفِ دانلودِ معوق را وقتی اینترنت برگشت راه می‌اندازد.

    پرسیدن از `reach` مجانی است (یک بولِ در حافظه) و کوئریِ صف روی
    `idx_jobs_status` می‌نشیند، پس این حلقه در حالتِ عادی تقریباً هیچ هزینه‌ای
    ندارد — و همین اجازه می‌دهد فاصله‌اش کوتاه باشد.

    جدا از `sweep_loop` است چون دوره‌اش سه مرتبه کوچک‌تر است: نگهداریِ دیسک
    ربع‌ساعتی مشکلی ندارد، ولی «اینترنت برگشت و هیچ اتفاقی نیفتاد» را کاربر
    به‌عنوان خرابی می‌بیند.
    """
    while True:
        try:
            await asyncio.sleep(interval)
            if reach.online():
                if started := manager.resume_deferred():
                    log.info("صفِ معوق راه افتاد: %d کار", started)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — همان قاعده‌ی sweep_loop
            continue
