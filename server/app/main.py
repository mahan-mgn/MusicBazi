from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from . import (
    artblur,
    artcache,
    catalog,
    clientlog,
    catcache,
    db,
    downloader,
    identify,
    jobs,
    loudness,
    paths,
    reach,
    releases,
    resolver,
    setup,
    split,
    stream_cache,
    telegram,
    verify,
    vibe,
    ydl,
)
from .config import (
    ALLOWED_ORIGINS,
    ART_MIRROR_ENABLED,
    ART_WARM_BATCH,
    ART_WARM_ENABLED,
    ART_WARM_INTERVAL,
    AUDIO_SOURCES,
    CATALOG_CACHE_ENABLED,
    DEFER_DOWNLOADS,
    DOWNLOAD_DIR,
    FFMPEG_LOCATION,
    FILE_RETENTION_SECONDS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    HTTP_TIMEOUT,
    JS_RUNTIME,
    LOUDNESS_ENABLED,
    LYRICS_ENABLED,
    M3U_ENABLED,
    PATH_TEMPLATE,
    PROXY,
)
from .downloader import safe_name
from .jobs import TERMINAL, manager
from .models import (
    AlbumDetail,
    ArtistDetail,
    CandidateOption,
    CandidateRequest,
    ClientError,
    ChapterInfo,
    ChaptersInfo,
    DailyMix,
    DownloadAccepted,
    DownloadRequest,
    Follow,
    FollowRequest,
    FollowState,
    IdentifyMatch,
    IdentifyResult,
    LibraryItem,
    LibraryPage,
    PlayEvent,
    PlayRecord,
    PlaylistCreate,
    PlaylistItemsRequest,
    PlaylistUpdate,
    ReleaseInfo,
    SearchResults,
    SongInfo,
    SplitRequest,
    SplitStatus,
    Stats,
    TelegramHeartbeat,
    TelegramJob,
    TelegramJobResult,
    TelegramPairClaim,
    TelegramPairing,
    TelegramSend,
    TelegramSendRequest,
    TelegramStatus,
    TopArtist,
    TopTrack,
    Track,
    TrackRef,
    UserPlaylist,
    UserPlaylistDetail,
    VibeRequest,
    VibeSuggestion,
    ZipReady,
    ZipRequest,
)
from .providers import audd, genius, spotify

USER_AGENT = "Unstream/0.2 (+local)"

# ارسال‌های تمام‌شده‌ی قدیمی‌تر از این پاک می‌شوند — فقط برای اینکه جدولِ صف
# بی‌نهایت رشد نکند؛ وب فقط تا وقتی دکمه روی صفحه است سراغشان می‌رود.
TELEGRAM_SEND_TTL = 24 * 3600


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers={"user-agent": USER_AGENT},
        follow_redirects=True,
        # همه‌ی providerها از همین کلاینت استفاده می‌کنند، پس پروکسی یک‌جا بس است
        proxy=PROXY,
    )

    db.connect()
    # کاری که موقع خاموش شدن سرور نیمه‌کاره مانده هیچ‌وقت خودش تمام نمی‌شود
    db.mark_interrupted()
    # صفِ تلگرام هم همین‌طور: ردیفی که دستِ باتِ رفته مانده، دوباره در انتظار
    db.requeue_telegram()
    await asyncio.to_thread(jobs.sweep_disk)

    # حلقه‌های پس‌زمینه. `reach` باید اول باشد: بقیه بر اساسِ وضعیتی که او
    # می‌سنجد تصمیم می‌گیرند، و تا اولین پروبش تمام نشده همه خوش‌بینانه
    # «آنلاین» فرض می‌کنند.
    background = [
        asyncio.create_task(reach.loop()),
        asyncio.create_task(jobs.sweep_loop()),
    ]
    if DEFER_DOWNLOADS:
        background.append(asyncio.create_task(jobs.defer_loop()))
    if ART_MIRROR_ENABLED and ART_WARM_ENABLED:
        background.append(
            asyncio.create_task(artcache.warm_loop(ART_WARM_INTERVAL, ART_WARM_BATCH))
        )

    yield

    for task in background:
        task.cancel()
    await app.state.http.aclose()
    db.close()


app = FastAPI(title="Unstream API", lifespan=lifespan)

# ویزاردِ راه‌اندازی. جدا از `app` تعریف شده تا `main.py` بزرگ‌تر نشود؛
# اندپوینت‌هایش بی‌احراز هویت‌اند (عمدی — تصمیمِ کاربر) و کلیدها را بیرون
# نمی‌دهند، فقط ماسکِ ۴ رقمِ آخر.
app.include_router(setup.router)

# فرانت در دِو روی 5174 است و از پروکسی Vite می‌آید، ولی اجرای مستقیم هم باید کار کند
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
    # پخش با Web Audio از مبدأ دیگر (اپ اندروید) المنت صوتی را با
    # crossorigin=anonymous می‌سازد؛ آن‌وقت مرورگر فقط همان هدرهایی را به
    # صفحه می‌دهد که صریح expose شده باشند. بدون این دوتا، جابه‌جایی روی نوار
    # پخش کار نمی‌کند چون پاسخِ Range از دید صفحه بی‌هویت است.
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Disposition"],
)


@app.get("/api/health")
async def health() -> dict:
    # آمارِ کش دو تا COUNT(*) است و `catalog_entity` می‌تواند ده‌ها هزار ردیف
    # شود؛ در نخِ جدا می‌رود تا حلقه‌ی asyncio — که همان لحظه استریمِ صوت را هم
    # سرو می‌کند — پشتش نایستد
    cached, art = await asyncio.gather(
        asyncio.to_thread(catcache.stats),
        asyncio.to_thread(_artwork_stats),
    )
    return {
        "ok": True,
        "ffmpeg": FFMPEG_LOCATION or "یافت نشد",
        "audioSources": list(AUDIO_SOURCES),
        # بدون نام‌کاربری و رمز — /health احراز هویت ندارد
        "proxy": ydl.proxy_label(),
        # یوتیوب هر سه را می‌خواهد؛ اگر یکی نباشد عملاً فقط ساندکلاد می‌ماند
        "youtube": {
            "cookies": ydl.has_cookies(),
            "poToken": ydl.has_potoken(),
            "jsRuntime": JS_RUNTIME or False,
        },
        # وضعیتِ اینترنتِ بین‌الملل. جدا از `ok` است و باید جدا بماند: سرور
        # کاملاً سالم است، فقط دنیای بیرون در دسترس نیست.
        "net": reach.snapshot(),
        "intranet": {
            "artMirror": ART_MIRROR_ENABLED,
            "catalogCache": CATALOG_CACHE_ENABLED,
            "deferDownloads": DEFER_DOWNLOADS,
            "cached": cached,
            "artwork": art,
        },
        # این‌ها اختیاری‌اند و نبودنشان فقط قابلیت را خاموش می‌کند، نه سرور را
        "features": {
            "lyrics": LYRICS_ENABLED,
            "geniusLyrics": genius.enabled(),
            "pathTemplate": PATH_TEMPLATE,
            "m3u": M3U_ENABLED,
            "spotify": spotify.enabled(),
            "acoustid": verify.available(),
            # شناسایی دو مسیر دارد و کاملاً یک کار نمی‌کنند: AudD روی ضبطِ
            # میکروفون، AcoustID روی فایلِ کامل (پایین‌تر در README)
            "identify": identify.available(),
            "identifyMic": audd.enabled(),
            "identifyFile": identify.acoustid_available(),
            "loudness": LOUDNESS_ENABLED and bool(FFMPEG_LOCATION),
            "split": bool(FFMPEG_LOCATION),
            "fileRetentionDays": round(FILE_RETENTION_SECONDS / 86400, 1),
            # بدون این، چت‌بات وایب فقط با نگاشت کلیدواژه‌ای کار می‌کند
            "vibeLlm": bool(GEMINI_API_KEY),
            # نامِ مدل فقط وقتی کلید هست معنا دارد؛ فرانت با آن می‌گوید
            # «Gemini فعال است» یا «حالتِ ساده (کلیدواژه)»
            "vibeModel": GEMINI_MODEL if GEMINI_API_KEY else None,
        },
    }


# ---------- توزیعِ نسخه‌ی اندروید و گزارشِ خطا ----------


@app.get("/api/release", response_model=ReleaseInfo | None)
async def release_latest() -> ReleaseInfo | None:
    """
    آخرین APKِ منتشرشده، یا null یعنی چیزی منتشر نشده.

    اپ با `versionCode` خودش مقایسه می‌کند؛ این‌جا فقط خبر می‌دهیم، تصمیم
    نمی‌گیریم — نسخه‌ی نصب‌شده را فقط خودِ اپ می‌داند.
    """
    info = await asyncio.to_thread(releases.current)
    if info is None:
        return None
    size = info.apk.stat().st_size if info.apk else 0
    return ReleaseInfo(
        versionCode=info.version_code,
        versionName=info.version_name,
        notes=info.notes,
        apkUrl="/api/release/apk" if info.apk else None,
        bytes=size,
    )


@app.get("/api/release/apk")
async def release_apk() -> FileResponse:
    """خودِ فایل. `Content-Disposition` نام می‌دهد تا مرورگر/اندروید درستش کنند."""
    info = await asyncio.to_thread(releases.current)
    if info is None or info.apk is None:
        raise HTTPException(404, "نسخه‌ای منتشر نشده")
    return FileResponse(
        info.apk,
        filename=info.apk.name,
        media_type="application/vnd.android.package-archive",
    )


@app.post("/api/client-error")
async def client_error(req: ClientError) -> dict:
    """
    دریافتِ خطای WebView. همیشه ۲۰۰ — حتی اگر نوشتن شکست خورد.

    فرانت این را در `window.onerror` صدا می‌زند؛ پاسخِ خطا خودش یک خطای دیگر
    می‌سازد و چرخه ادامه پیدا می‌کند. اینجا سکوت، درست‌ترین جواب است.
    """
    ok = await asyncio.to_thread(clientlog.record, req.model_dump())
    return {"ok": ok}


@app.get("/api/client-error/recent")
async def client_error_recent(limit: int = 50) -> list[dict]:
    """چند خطای آخر برای نگاه‌کردنِ آدمِ مسئولِ سرور (نه اپ)."""
    return await asyncio.to_thread(clientlog.recent, max(1, min(limit, 200)))


@app.get("/api/net")
async def net_status() -> dict:
    """
    «اینترنتِ بین‌الملل هست یا نه؟» — سبک‌ترین اندپوینتِ سرور، چون فرانت مرتب
    می‌پرسدش. فقط وضعیتِ در حافظه را می‌خواند و خودش هیچ پروبی نمی‌زند؛ آن کار
    مالِ حلقه‌ی پس‌زمینه‌ی `reach` است.
    """
    return reach.snapshot()


@app.post("/api/net/check")
async def net_check() -> dict:
    """
    پروبِ فوری، برای وقتی کاربر خودش دکمه‌ی «دوباره امتحان کن» را می‌زند.

    انتظارِ سی‌ثانیه‌ایِ دورِ بعدیِ حلقه، در لحظه‌ای که کاربر می‌داند اینترنتش
    برگشته، به‌شکلِ یک برنامه‌ی گیرکرده دیده می‌شود.
    """
    online = await reach.check()
    if online and DEFER_DOWNLOADS:
        # همان‌جا صف را راه بینداز — کاربری که دکمه را زده دقیقاً منتظرِ همین است
        manager.resume_deferred()
    return reach.snapshot()


# کاور محتوا-آدرس است (کلید از خودِ آدرسِ اصلی ساخته می‌شود)، پس هیچ‌وقت زیرِ
# همان کلید عوض نمی‌شود و مرورگر می‌تواند تا ابد نگهش دارد. بدون این هدر، هر
# اسکرول در کتابخانه ده‌ها درخواستِ ۳۰۴ به سرورِ خانگی می‌زد.
ART_CACHE_CONTROL = "public, max-age=31536000, immutable"


@app.get("/api/art/{sha}")
async def artwork_file(sha: str):
    """
    کاور از آینه‌ی محلی.

    اولین بار تصویر را از CDN می‌گیرد و روی دیسک می‌نشاند؛ دفعات بعد — و مهم‌تر
    از همه، موقعِ قطعیِ بین‌الملل — مستقیم از دیسک می‌آید. `artcache` توضیح
    می‌دهد چرا این هدایت لازم است.

    نبودنِ کاور ۴۰۴ می‌گیرد و همان درست است: کامپوننتِ `Artwork` در فرانت
    گرادیانِ جایگزین را نشان می‌دهد، که از یک آیکونِ شکسته بهتر است.
    """
    if not artcache.LOCAL.match(f"/api/art/{sha}"):
        raise HTTPException(404, "شناسه‌ی کاور نامعتبر است")

    if path := await asyncio.to_thread(artcache.stored, sha):
        return FileResponse(
            path, media_type=artcache.sniff(path), headers={"cache-control": ART_CACHE_CONTROL}
        )

    if not reach.online():
        # در حالتِ اینترانت گرفتنش فقط یک تایم‌اوت است؛ صفحه‌ای که سی کاورِ
        # نگرفته دارد، سی تایم‌اوتِ هم‌زمان می‌شد
        raise HTTPException(404, "این کاور هنوز ذخیره نشده")

    if path := await asyncio.to_thread(artcache.fetch, sha):
        return FileResponse(
            path, media_type=artcache.sniff(path), headers={"cache-control": ART_CACHE_CONTROL}
        )

    raise HTTPException(404, "کاور در دسترس نیست")


@app.get("/api/art-blur/{sha}")
async def artwork_blur(sha: str):
    """
    نسخه‌ی بلورشده‌ی همان کاور — پس‌زمینه‌ی هیرو.

    بلورِ CSS بین مرورگرها یک‌دست نیست (هر موتوری فیلتر گاوسی خودش را دارد و
    با DPR هم جابه‌جا می‌شود)؛ برای اینکه هیرو در کروم و اج و فایرفاکس یک شکل
    دیده شود، بلور یک‌بار اینجا ساخته و همان فایل به همه داده می‌شود. خودِ
    گرادیان‌ها و scrimها در CSS می‌مانند.

    کاورِ نبوده، بلور هم ندارد — ۴۰۴ و فرانت به CSS blur برمی‌گردد.
    """
    if not artcache.LOCAL.match(f"/api/art/{sha}"):
        raise HTTPException(404, "شناسه‌ی کاور نامعتبر است")

    path = artblur.blur_path(sha)
    if not path.exists():
        path = await asyncio.to_thread(artblur.build, sha)
    if path is None or not path.exists():
        raise HTTPException(404, "این کاور هنوز ذخیره نشده")

    return FileResponse(path, media_type=artblur.MIME, headers={"cache-control": ART_CACHE_CONTROL})


def _artwork_stats() -> dict:
    done, todo, size = db.artwork_stats()
    return {"stored": done, "pending": todo, "bytes": size}


# پیامی که در حالتِ اینترانت به‌جای خطای شبکه بالا می‌رود. کد ۵۰۳ عمدی است و
# نه ۵۰۲: مشکل از بالادست نیست، این *سرویس* موقتاً نمی‌تواند کاری بکند — و
# فرانت با همین کد تشخیص می‌دهد که پیامِ «اینترانت» نشان بدهد نه «خطا».
INTRANET_DETAIL = "اینترنت بین‌الملل در دسترس نیست — فقط چیزهای ذخیره‌شده باز می‌شوند"


def _intranet() -> HTTPException:
    """خطای «اینترانت» — صداکننده خودش `raise` می‌کند تا زنجیره‌ی علت حفظ شود."""
    return HTTPException(503, INTRANET_DETAIL)


# سنِ مجازِ آخرین بررسی، قبل از اینکه سرِ یک درخواستِ بی‌نتیجه دوباره پروب بزنیم.
RECHECK_MAX_AGE = 20.0


def _has_rows(results: SearchResults) -> bool:
    return bool(results.tracks or results.albums or results.artists or results.playlists)


async def _still_offline() -> bool:
    """
    قبل از تسلیم شدن، یک بار دیگر مطمئن شو.

    این دریچه‌ی فرار است و از یک باگِ واقعی درآمده: نسخه‌ی اول، پروب را روی
    خودِ `itunes.apple.com` و `api.deezer.com` می‌زد — دو دامنه‌ای که از آی‌پیِ
    ایران تحریم و geo-block شده‌اند. برنامه بی‌دلیل «قطع» اعلام می‌کرد، و چون
    در آن حالت دیگر هیچ‌وقت مسیرِ زنده را امتحان نمی‌کرد، راهی برای فهمیدنِ
    اشتباهش نداشت. کاربر تا ابد در حالتِ اینترانت گیر می‌کرد.

    آدرس‌های پروب عوض شده‌اند، ولی درسِ ساختاری‌اش می‌ماند: هیچ تشخیصِ
    خودکاری نباید تنها راهِ برگشت باشد. پس هر بار که کش دستِ خالی است — یعنی
    دقیقاً همان‌جا که کاربر چیزی از دست می‌دهد — دوباره می‌پرسیم، و اگر
    اشتباه کرده بودیم همان درخواست از مسیرِ زنده جواب می‌گیرد.
    """
    return not await reach.verify(RECHECK_MAX_AGE)


@app.get("/api/search", response_model=SearchResults)
async def search(q: str, request: Request) -> SearchResults:
    """
    جستجوی زنده، با برگشت به کشِ محلی وقتی بین‌الملل قطع است.

    ترتیب مهم است: وقتی از قبل می‌دانیم قطع است اصلاً به کاتالوگ‌ها دست نمی‌زنیم
    (هر کدام یک تایم‌اوتِ سی‌ثانیه‌ای است و کاربر نیم‌دقیقه منتظرِ چیزی می‌ماند
    که جوابش از قبل معلوم است). ولی به آن حدس هم تکیه نمی‌کنیم: اگر پروب هنوز
    نرسیده بود و درخواستِ واقعی شکست خورد، همان‌جا به کش برمی‌گردیم.
    """
    query = q.strip()
    if not query:
        raise HTTPException(400, "عبارت جستجو خالی است")

    if CATALOG_CACHE_ENABLED and not reach.online():
        cached = await asyncio.to_thread(catcache.search, query)
        # کشی که جواب دارد، جواب است — پروبِ اضافه فقط تأخیر می‌شد
        if _has_rows(cached) or await _still_offline():
            return artcache.localize(cached)
        # اشتباه می‌کردیم؛ بیفت روی مسیرِ زنده

    try:
        results = await catalog.search(request.app.state.http, query)
    except HTTPException:
        raise
    except Exception as exc:
        if CATALOG_CACHE_ENABLED and reach.note_unreachable(exc):
            return artcache.localize(await asyncio.to_thread(catcache.search, query))
        raise HTTPException(502, f"جستجو ناموفق بود: {exc}") from exc

    reach.note_reachable()
    if CATALOG_CACHE_ENABLED:
        # قبل از محلی‌سازیِ کاور — کش باید آدرسِ اصلیِ CDN را نگه دارد
        await asyncio.to_thread(catcache.remember_search, query, results)
    return artcache.localize(results)


@app.post("/api/vibe", response_model=VibeSuggestion)
async def vibe_suggest(req: VibeRequest, request: Request) -> VibeSuggestion:
    """چت‌بات پیشنهاد پلی‌لیست: پیامِ آزاد یا کلیدِ یک چیپ، پلی‌لیستِ پیشنهادی برمی‌گردد."""
    if not (req.message or "").strip() and not req.vibe:
        raise HTTPException(400, "متن یا وایب باید مشخص باشد")
    # سقفِ نگارشی: پیامِ چند ده‌هزار‌تایی هم هزینه‌ی Gemini است و هم بدنه‌ی
    # درخواستِ هر درخواستِ بعدی (تاریخچه همین متن‌ها را دوباره می‌برند)
    if req.message and len(req.message) > 500:
        req.message = req.message[:500]

    return artcache.localize(await vibe.build_playlist(request.app.state.http, req))


@app.get("/api/album", response_model=AlbumDetail)
async def album(ref: str, request: Request) -> AlbumDetail:
    """آلبوم/پلی‌لیست/تک‌آهنگ — در حالتِ اینترانت از کشِ همان صفحه."""
    if CATALOG_CACHE_ENABLED and not reach.online():
        if cached := await asyncio.to_thread(catcache.album, ref):
            return artcache.localize(cached)
        if await _still_offline():
            raise _intranet()

    try:
        detail = await catalog.resolve_ref(request.app.state.http, ref)
    except Exception as exc:
        if CATALOG_CACHE_ENABLED and reach.note_unreachable(exc):
            if cached := await asyncio.to_thread(catcache.album, ref):
                return artcache.localize(cached)
            raise _intranet() from exc
        raise HTTPException(502, f"دریافت آلبوم ناموفق بود: {exc}") from exc

    if detail is None:
        raise HTTPException(404, "این لینک شناخته نشد یا محتوایی نداشت")
    reach.note_reachable()
    if CATALOG_CACHE_ENABLED:
        await asyncio.to_thread(catcache.remember_ref, ref, "album", detail)
    return artcache.localize(detail)


@app.get("/api/artist", response_model=ArtistDetail)
async def artist(ref: str, request: Request) -> ArtistDetail:
    """
    صفحه‌ی هنرمند — آنلاین همیشه از پلتفرم تازه می‌آید.

    کش فقط برای قطعیِ بین‌الملل است (و فالبک وقتی واکشی تازه شکست بخورد).
    بازگرداندنِ صفحه‌ی یک‌ساعته باعث می‌شد انتشارِ تازه تا رفرشِ دستی دیده نشود.
    """
    if CATALOG_CACHE_ENABLED and not reach.online():
        if cached := await asyncio.to_thread(catcache.artist, ref):
            return artcache.localize(cached)
        if await _still_offline():
            raise _intranet()

    try:
        detail = await catalog.resolve_artist(request.app.state.http, ref)
    except Exception as exc:
        if CATALOG_CACHE_ENABLED and reach.note_unreachable(exc):
            if cached := await asyncio.to_thread(catcache.artist, ref):
                return artcache.localize(cached)
            raise _intranet() from exc
        raise HTTPException(502, f"دریافت هنرمند ناموفق بود: {exc}") from exc

    if detail is None:
        raise HTTPException(404, "این هنرمند پیدا نشد")
    reach.note_reachable()
    if CATALOG_CACHE_ENABLED:
        await asyncio.to_thread(catcache.remember_ref, ref, "artist", detail)
    return artcache.localize(detail)


@app.get("/api/songinfo", response_model=SongInfo)
async def song_info(title: str, artist: str) -> SongInfo:
    """
    آهنگساز/تهیه‌کننده/آلبوم — فقط Genius این‌ها را می‌دهد، هیچ کاتالوگ دیگری نه.
    بات تلگرام برای کارتِ اطلاعاتِ کنار فایل استفاده می‌کند؛ وب چیزی از این
    نمی‌خواهد، پس اینجا مصرف‌کننده‌ی دیگری ندارد.
    """
    if not genius.enabled():
        raise HTTPException(404, "Genius تنظیم نشده")
    info = await asyncio.to_thread(genius.song_info, title, artist)
    if info is None:
        raise HTTPException(404, "چیزی پیدا نشد")
    return SongInfo(**info.__dict__)


@app.post("/api/downloads", response_model=DownloadAccepted)
async def create_download(req: DownloadRequest, request: Request) -> DownloadAccepted:
    track = await _track_for(request, req)
    job, reused = manager.create(track, req.quality, req.candidateUrl)
    return DownloadAccepted(jobId=job.id, reused=reused)


@app.post("/api/candidates", response_model=list[CandidateOption])
async def candidates(req: CandidateRequest, request: Request) -> list[CandidateOption]:
    """
    نسخه‌های موجود برای یک ترک — وقتی انتخاب خودکار اشتباه بوده.

    resolver از قبل لیست برمی‌گرداند و تا اولین موفقیت پایین می‌رود؛ اینجا فقط
    همان لیست را بدون آستانه به کاربر نشان می‌دهیم. تصمیم با اوست، نه با امتیاز.
    """
    if req.source and req.source not in AUDIO_SOURCES:
        raise HTTPException(400, "این منبع فعال نیست")

    track = await _track_for(request, req)
    try:
        found = await asyncio.to_thread(resolver.browse, track, req.source)
    except Exception as exc:
        raise HTTPException(502, f"جستجوی نسخه‌ها ناموفق بود: {exc}") from exc

    return [
        CandidateOption(
            url=c.url,
            title=c.title,
            uploader=c.uploader,
            durationMs=c.duration_ms,
            score=round(c.score, 1),
            source=c.source,
        )
        for c in found
    ]


# ---------- کتابخانه ----------


def _library_item(row) -> LibraryItem:
    # حس‌وحال جدا از متادیتای اصلیِ ترک ذخیره می‌شود (ستون‌های خودِ جاب، نه
    # track_json) چون بعد از ساختِ ردیف و با تحلیلِ فایل به‌دست می‌آید؛ اینجا
    # روی همان Track سرهم می‌شود تا فرانت یک‌جا ببیندش.
    track = Track.model_validate_json(row["track_json"]).model_copy(
        update={"valence": row["valence"], "energy": row["energy"]}
    )
    # play_count فقط از کوئریِ کتابخانه می‌آید (زیرکوئری در db.library)؛ بقیه‌ی
    # مسیرها (پلی‌لیست، split) آن را ندارند و صفر می‌گیرند — که درست است، چون
    # آن‌ها «فهرستِ پخش»‌اند نه «کتابخانه».
    play_count = row["play_count"] if "play_count" in row.keys() else 0
    # مثل play_count: فقط کوئری‌های کتابخانه/لایک این ستون را دارند
    keys = row.keys()
    last_played = float(row["last_played_at"]) if "last_played_at" in keys and row["last_played_at"] is not None else None
    return LibraryItem(
        jobId=row["id"],
        track=track,
        quality=row["quality"],
        format=row["format"],
        bytes=int(row["bytes"] or 0),
        fileUrl=jobs.file_url(row["id"]),
        streamUrl=jobs.stream_url(row["id"]),
        lyricsUrl=jobs.lyrics_url(row["id"]) if row["lyrics_path"] else None,
        createdAt=float(row["created_at"]),
        gainDb=loudness.gain_db(row["loudness"], row["peak"]),
        favorite=bool(row["favorite"]),
        playCount=int(play_count),
        lastPlayedAt=last_played,
    )


@app.get("/api/library", response_model=LibraryPage)
async def library(q: str = "", limit: int = 50, offset: int = 0) -> LibraryPage:
    limit = max(1, min(limit, 200))
    rows, total, total_bytes = await asyncio.to_thread(
        db.library, q, limit, max(0, offset)
    )

    # ردیفی که فایلش دیگر نیست نباید در کتابخانه دیده شود. حذفش از خروجی کافی
    # نیست: شمارش و حجم از SQL می‌آیند و همان ردیف را می‌شمارند، پس هدر صفحه
    # «۲ آهنگ، ۱۷ مگابایت» می‌گفت درحالی‌که لیست خالی بود. ردیفِ بی‌فایل اصلاً
    # نباید بماند — همین‌جا پاکش می‌کنیم و از جمع هم کمش.
    #
    # کلِ حلقه در یک نخ می‌رود، نه فقط `forget`: هر ردیف یک `exists()` است و
    # `exists()` یک syscall — با صفحه‌ی دویست‌تایی یعنی دویست بار بلاک شدنِ
    # حلقه‌ی asyncio، درست وسطِ همان حلقه‌ای که استریمِ صوت را هم سرو می‌کند.
    def prune() -> tuple[list[LibraryItem], int, int]:
        items: list[LibraryItem] = []
        count, size = total, total_bytes
        for row in rows:
            if row["path"] and Path(row["path"]).exists():
                items.append(_library_item(row))
                continue
            manager.forget(row["id"])
            count -= 1
            size -= int(row["bytes"] or 0)
        return items, count, size

    items, total, total_bytes = await asyncio.to_thread(prune)

    # مهم‌ترین جایی که آینه‌ی کاور به کار می‌آید: کتابخانه چیزی است که موقعِ
    # قطعی باز می‌شود، و بدونِ این هر ردیفش یک مربعِ خالی بود
    return artcache.localize(
        LibraryPage(items=items, total=max(0, total), totalBytes=max(0, total_bytes))
    )


@app.delete("/api/library/{job_id}")
async def library_delete(job_id: str) -> dict:
    if not manager.forget(job_id):
        raise HTTPException(404, "این مورد در کتابخانه نبود")
    return {"ok": True}


@app.put("/api/library/{job_id}/favorite")
async def library_favorite(job_id: str, favorite: bool) -> dict:
    """قلبِ کنارِ ردیف — True یعنی لایک، False یعنی برداشتنش."""
    if not await asyncio.to_thread(db.set_favorite, job_id, favorite):
        raise HTTPException(404, "این مورد در کتابخانه نبود")
    return {"ok": True, "favorite": favorite}


# ---------- پخش‌ها و آمار ----------


@app.post("/api/plays")
async def record_play(req: PlayEvent) -> dict:
    """
    فرانت موقع شروعِ پخشِ یک ترکِ کتابخانه این را می‌فرستد.

    متادیتا از خودِ جاب خوانده می‌شود نه از درخواست: فرانت ممکن است ترک را از
    مسیرهای مختلف (کتابخانه، پلی‌لیست، رادیو) پخش کند و متادیتای همراهش کامل
    نباشد. جاب منبع حقیقت است.
    """
    row = await asyncio.to_thread(db.get_job, req.jobId)
    if row is None:
        raise HTTPException(404, "این مورد در کتابخانه نبود")

    track = Track.model_validate_json(row["track_json"])
    seconds = req.seconds if req.seconds is not None else track.durationMs // 1000
    await asyncio.to_thread(
        db.record_play,
        req.jobId,
        track.id,
        track.title,
        track.artist,
        track.album,
        track.artworkUrl,
        track.durationMs,
        max(0, seconds),
        time.time(),
    )
    return {"ok": True}


@app.get("/api/stats", response_model=Stats)
async def listening_stats(days: int = 7) -> Stats:
    """آمارِ گوش‌دادن برای یک بازه — پیش‌فرض هفت روز."""
    days = max(1, min(days, 365))
    since = time.time() - days * 86400

    def build() -> Stats:
        plays, seconds, unique = db.play_totals(since)
        tracks = db.top_tracks(since, 20)
        artists = db.top_artists(since, 10)
        recent = db.recent_plays(30)
        return Stats(
            plays=plays,
            seconds=seconds,
            uniqueTracks=unique,
            topTracks=[
                TopTrack(
                    trackId=r["track_id"],
                    title=r["title"],
                    artist=r["artist"],
                    album=r["album"],
                    artworkUrl=r["artwork_url"],
                    plays=int(r["plays"]),
                    seconds=int(r["seconds"]),
                    lastAt=float(r["last_at"]),
                )
                for r in tracks
            ],
            topArtists=[
                TopArtist(
                    artist=r["artist"],
                    plays=int(r["plays"]),
                    seconds=int(r["seconds"]),
                )
                for r in artists
            ],
            recent=[
                PlayRecord(
                    jobId=r["job_id"],
                    trackId=r["track_id"],
                    title=r["title"],
                    artist=r["artist"],
                    album=r["album"],
                    artworkUrl=r["artwork_url"],
                    durationMs=int(r["duration_ms"]),
                    seconds=int(r["seconds"]),
                    playedAt=float(r["played_at"]),
                )
                for r in recent
            ],
        )

    return artcache.localize(await asyncio.to_thread(build))


@app.get("/api/favorites", response_model=list[LibraryItem])
async def favorites() -> list[LibraryItem]:
    """ترک‌های لایک‌شده — فایل‌های آماده‌ای که قلب خورده‌اند."""

    def build() -> list[LibraryItem]:
        return [
            _library_item(row)
            for row in db.favorite_jobs()
            if row["path"] and Path(row["path"]).exists()
        ]

    return artcache.localize(await asyncio.to_thread(build))


@app.get("/api/mix", response_model=DailyMix)
async def daily_mix(limit: int = 20, days: int = 7) -> DailyMix:
    """
    میکسِ روزانه: انتخابِ سرور بر اساسِ سلیقه‌ی خودِ کاربر.

    مرکزِ انتخاب میانگینِ والانس/انرژیِ لایک‌هاست، و اگر لایکی نبود، حس‌وحالِ
    بیشترین‌های گوش‌داده‌شده‌ی این بازه. بعد کتابخانه بر اساسِ فاصله از همان
    مرکز مرتب می‌شود. ترک‌هایی که در بازه گوش داده شده‌اند وارد میکس
    نمی‌شوند — آن‌ها را همین چند روز پیش شنیده‌ای.
    """
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 50))
    since = time.time() - days * 86400

    def build() -> DailyMix:
        centers = [
            (float(r["valence"]), float(r["energy"]))
            for r in db.favorite_jobs()
            if r["valence"] is not None and r["energy"] is not None
        ]
        source = "favorites" if centers else "none"
        if not centers:
            centers = [(float(r["valence"]), float(r["energy"])) for r in db.recent_moods(since, 30)]
            if centers:
                source = "recent"

        center = (
            (sum(c[0] for c in centers) / len(centers), sum(c[1] for c in centers) / len(centers))
            if centers
            else None
        )
        exclude = {r["track_id"] for r in db.top_tracks(since, 100)}
        rows = db.daily_mix(center, exclude, limit)
        items = [_library_item(r) for r in rows if r["path"] and Path(r["path"]).exists()]
        # کتابخانه‌ی خالی یا بی‌سیگنال: فرانت باید بداند که چیزی برای نشان‌دادن نیست
        return DailyMix(source=source if items else "none", items=items)

    return artcache.localize(await asyncio.to_thread(build))


# آرشیوهای ساخته‌شده: token -> (مسیر، نام فایل، زمان ساخت)
# تک‌مصرف نیستند چون مرورگر گاهی همان URL دانلود را چند بار می‌زند؛
# با pop کردن، تلاش‌های بعدی ۴۰۴ می‌گرفتند.
_archives: dict[str, tuple[Path, str, float]] = {}
ARCHIVE_TTL = 900.0


def _sweep_archives() -> None:
    cutoff = time.time() - ARCHIVE_TTL
    for token in [t for t, (_, _, at) in _archives.items() if at < cutoff]:
        path, _, _ = _archives.pop(token)
        path.unlink(missing_ok=True)


# باید قبل از روت‌های /{job_id} بیاید: FastAPI به‌ترتیب تعریف مچ می‌کند و
# وگرنه «zip» را job_id می‌فهمد و ۴۰۵ برمی‌گرداند.
@app.post("/api/downloads/zip", response_model=ZipReady)
async def create_zip(req: ZipRequest) -> ZipReady:
    """
    ZIP را می‌سازد و فقط آدرسش را برمی‌گرداند — نه خود فایل را.

    عمداً دومرحله‌ای است: پاسخی که content-disposition دارد را مرورگر مستقیم
    به‌عنوان دانلود می‌قاپد و fetch هیچ بدنه‌ای نمی‌بیند. با برگرداندن URL،
    کلاینت مرورگر را به آن می‌فرستد و دانلود بومی و بدون مصرف حافظه انجام می‌شود.
    """
    used: set[str] = set()

    def unique(name: str) -> str:
        """
        هم‌نامی ممکن است (همان ترک با دو کیفیت، یا دو ترکِ هم‌عنوان در یک آلبوم).
        بدون شماره‌گذاری، ZIP دو عضو هم‌نام می‌گرفت و باز کردنش یکی را روی
        دیگری می‌ریخت.
        """
        candidate = name
        index = 2
        while candidate in used:
            base = PurePosixPath(name)
            candidate = str(base.with_name(f"{base.stem} ({index}){base.suffix}"))
            index += 1
        used.add(candidate)
        return candidate

    entries: list[tuple[Path, str]] = []  # (روی دیسک، مسیر داخل آرشیو)
    playlist: list[tuple[Track, str]] = []
    seen: set[Path] = set()

    for job_id in req.jobIds:
        job = manager.get(job_id)
        if job is None or job.path is None or not job.path.exists():
            continue
        # با مسیر یکتا می‌شود، نه با نام: هر جاب پوشه‌ی خودش را دارد و دو کیفیتِ
        # یک ترک هم‌نام‌اند. یکتاسازی با نام، دومی را بی‌صدا می‌انداخت.
        if job.path in seen:
            continue
        seen.add(job.path)

        arcname = unique(paths.render(job.track, job.path.suffix))
        entries.append((job.path, arcname))
        playlist.append((job.track, arcname))

        # متن هم‌زمان‌شده باید هم‌نام و کنار فایل صوتی بماند تا پلیرها
        # خودشان پیدایش کنند — پس دنبال نامِ نهاییِ صوت می‌رود، نه نام روی دیسک
        if job.lyrics_path and job.lyrics_path.exists():
            entries.append(
                (job.lyrics_path, str(PurePosixPath(arcname).with_suffix(".lrc")))
            )

    if not entries:
        raise HTTPException(404, "هیچ فایل آماده‌ای برای بسته‌بندی نبود")

    # پلی‌لیست فقط وقتی معنی دارد که چند ترک باشد؛ برای یک فایل نویز است
    m3u_name = f"{safe_name(req.name)}.m3u" if M3U_ENABLED and len(playlist) > 1 else None

    # روی دیسک ساخته می‌شود، نه در حافظه: یک آلبوم می‌تواند صدها مگابایت باشد.
    # ZIP_STORED چون mp3 از قبل فشرده است و دفلیت فقط CPU می‌سوزاند.
    def build() -> Path:
        handle, tmp = tempfile.mkstemp(suffix=".zip", dir=DOWNLOAD_DIR)
        os.close(handle)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as archive:
            for path, arcname in entries:
                archive.write(path, arcname=arcname)
            if m3u_name:
                archive.writestr(m3u_name, paths.m3u(playlist))
        return Path(tmp)

    _sweep_archives()
    archive_path = await asyncio.to_thread(build)
    token = uuid.uuid4().hex[:12]
    _archives[token] = (archive_path, f"{safe_name(req.name)}.zip", time.time())

    return ZipReady(
        url=f"/api/downloads/zip/{token}",
        bytes=archive_path.stat().st_size,
        files=len(entries) + (1 if m3u_name else 0),
    )


@app.get("/api/downloads/zip/{token}")
async def fetch_zip(token: str) -> FileResponse:
    _sweep_archives()
    entry = _archives.get(token)
    if entry is None or not entry[0].exists():
        raise HTTPException(404, "این آرشیو منقضی شده — دوباره بساز")

    path, filename, _ = entry
    return FileResponse(path, filename=filename, media_type="application/zip")


@app.get("/api/downloads/{job_id}/events")
async def download_events(job_id: str, request: Request) -> StreamingResponse:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "این کار پیدا نشد")

    queue = await manager.subscribe(job)

    async def stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    progress = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keep-alive\n\n"  # جلوگیری از بسته شدن اتصال توسط پروکسی
                    continue

                yield f"data: {json.dumps(progress.model_dump(), ensure_ascii=False)}\n\n"
                if progress.status in TERMINAL:
                    break
        finally:
            manager.unsubscribe(job, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


@app.delete("/api/downloads/{job_id}")
async def cancel_download(job_id: str, purge: bool = False) -> dict:
    """
    `purge=False` لغوِ دانلودِ در جریان است. `purge=True` حذفِ کامل — فایل و
    ردیف — برای مسیرِ «فقط تلگرام»ی که بات بعد از آپلودِ موفق صدایش می‌زند.
    """
    removed = manager.forget(job_id) if purge else manager.cancel(job_id)
    if not removed:
        raise HTTPException(404, "کاری برای لغو نبود")
    return {"ok": True}


@app.get("/api/downloads/{job_id}/file")
async def download_file(job_id: str) -> FileResponse:
    job = manager.get(job_id)
    if job is None or job.path is None or not job.path.exists():
        raise HTTPException(404, "فایل آماده نیست")
    return FileResponse(
        job.path,
        filename=job.path.name,
        media_type="application/octet-stream",
    )


# پخش در مرورگر به mime واقعی نیاز دارد. با application/octet-stream فایرفاکس
# اصلاً رمزگشایی را شروع نمی‌کند و کروم فقط گاهی با sniff نجات می‌دهد.
AUDIO_MIME = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


@app.get("/api/downloads/{job_id}/stream")
async def stream_file(job_id: str) -> FileResponse:
    """
    همان فایل، ولی برای `<audio>`.

    `filename` عمداً پاس داده نمی‌شود: با آن، پاسخ `content-disposition: attachment`
    می‌گیرد و دانلودمنیجرهای مرورگر وسط پخش می‌پرند. FileResponse خودش Range را
    جواب می‌دهد، پس جابه‌جایی روی نوار پخش بدون دانلود کل فایل کار می‌کند.
    """
    job = manager.get(job_id)
    if job is None or job.path is None or not job.path.exists():
        raise HTTPException(404, "فایل آماده نیست")
    return FileResponse(
        job.path,
        media_type=AUDIO_MIME.get(job.path.suffix.lower(), "application/octet-stream"),
    )


@app.get("/api/stream")
async def stream_audio(
    track_id: str,
    title: str,
    artist: str,
    request: Request = None,  # type: ignore[assignment]
    album: str | None = None,
    duration_ms: int = 0,
    source: str = "spotify",
    source_url: str = "",
    quality: str | None = None,
) -> Response:
    """
    استریم آنلاین و بلادرنگ صوت بدون نیاز به دانلود دائمی در کتابخانه با بالاترین کیفیت ممکن.
    """
    valid_source = (
        source
        if source in ("apple", "deezer", "soundcloud", "spotify", "youtube")
        else "spotify"
    )
    track = Track(
        id=track_id,
        title=title,
        artist=artist,
        album=album,
        durationMs=duration_ms,
        source=valid_source,  # type: ignore[arg-type]
        sourceUrl=source_url or f"https://musicbazi.local/track/{track_id}",
    )
    try:
        range_header = request.headers.get("range") if request is not None else None
        return await stream_cache.get_stream_response(
            track, range_header=range_header, quality=quality
        )
    except Exception as exc:
        if not reach.online():
            raise HTTPException(
                503, "اینترنت بین‌الملل در دسترس نیست و این ترک در کش ذخیره نشده است"
            ) from exc
        raise HTTPException(502, f"خطا در استریم صوت: {exc}") from exc


@app.get("/api/stream/lyrics")
async def stream_lyrics(
    track_id: str,
    title: str,
    artist: str,
    album: str | None = None,
    duration_ms: int = 0,
) -> Response:
    """متن ترانه همگام برای ترک استریم‌شده."""
    track = Track(
        id=track_id,
        title=title,
        artist=artist,
        album=album,
        durationMs=duration_ms,
        source="spotify",
        sourceUrl=f"https://musicbazi.local/track/{track_id}",
    )
    content = await stream_cache.get_or_fetch_lyrics(track)
    if not content:
        raise HTTPException(404, "متنی برای این آهنگ یافت نشد")
    return Response(content=content, media_type="text/plain; charset=utf-8")


@app.post("/api/stream/prefetch")
async def stream_prefetch(req: TrackRef) -> dict:
    """پری‌فچ ترک بعدی در پس‌زمینه برای حذف تأخیر در تعویض آهنگ."""
    if not (req.title and req.artist):
        return {"ok": False}

    valid_source = (
        req.source
        if req.source in ("apple", "deezer", "soundcloud", "spotify", "youtube")
        else "spotify"
    )
    track = Track(
        id=req.trackId,
        title=req.title,
        artist=req.artist,
        album=req.album,
        durationMs=req.durationMs or 0,
        source=valid_source,  # type: ignore[arg-type]
        sourceUrl=req.sourceUrl or f"https://musicbazi.local/track/{req.trackId}",
    )
    asyncio.create_task(stream_cache.get_or_fetch(track, quality=req.quality))
    return {"ok": True}


@app.get("/api/downloads/{job_id}/thumb")
async def download_thumb(job_id: str) -> Response:
    """
    کاورِ همین فایل، در ابعادی که تلگرام برای thumbnail قبول می‌کند.

    وجودش برای این است که بات نباید موقعِ ارسال دوباره سراغِ CDN برود: آن
    درخواست تایم‌اوت می‌داد یا به پروکسی نمی‌رسید و نتیجه‌اش یک فایل صوتی بود
    که در لیستِ تلگرام بی‌تصویر می‌نشست — با اینکه کاور داخلِ خودش بود. اینجا
    از همان فایل خوانده می‌شود، پس تا وقتی فایل هست، تصویر هم هست.
    """
    job = manager.get(job_id)
    if job is None or job.path is None or not job.path.exists():
        raise HTTPException(404, "فایل آماده نیست")
    thumb = await asyncio.to_thread(downloader.thumbnail, job.path, job.track.artworkUrl)
    if thumb is None:
        raise HTTPException(404, "این فایل کاوری ندارد")
    return Response(
        thumb,
        media_type="image/jpeg",
        # کاورِ یک جاب عوض نمی‌شود — همان قاعده‌ی `/api/art`
        headers={"cache-control": ART_CACHE_CONTROL},
    )


@app.get("/api/downloads/{job_id}/lyrics")
async def download_lyrics(job_id: str) -> FileResponse:
    job = manager.get(job_id)
    if job is None or job.lyrics_path is None or not job.lyrics_path.exists():
        raise HTTPException(404, "متن هم‌زمان‌شده‌ای برای این آهنگ نیست")
    return FileResponse(
        job.lyrics_path,
        filename=job.lyrics_path.name,
        media_type="text/plain; charset=utf-8",
    )


async def _track_for(request: Request, req: TrackRef) -> Track:
    """
    فرانت فقط trackId و sourceUrl می‌فرستد. اگر متادیتا همراهش آمده باشد از آن
    استفاده می‌کنیم، وگرنه از روی id بازسازی‌اش می‌کنیم تا تگ‌ها درست دربیایند.
    """
    if req.title and req.artist:
        return Track(
            id=req.trackId,
            title=req.title,
            artist=req.artist,
            album=req.album,
            albumId=req.albumId,
            albumArtist=req.albumArtist,
            durationMs=req.durationMs or 0,
            # فرانت همان `/api/art/...`ی که گرفته را پس می‌فرستد؛ تگ‌گذار به
            # آدرسِ واقعیِ CDN نیاز دارد وگرنه فایل بی‌کاور می‌ماند
            artworkUrl=artcache.original(req.artworkUrl),
            source=_source_of(req.trackId),
            sourceUrl=req.sourceUrl,
            trackNumber=req.trackNumber,
            discNumber=req.discNumber,
            year=req.year,
            genre=req.genre,
        )

    if found := await _lookup_track(request, req):
        return found

    raise HTTPException(400, "متادیتای این آهنگ پیدا نشد")


def _source_of(track_id: str) -> str:
    prefix = track_id.split(":", 1)[0]
    return {
        "itunes": "apple",
        "deezer": "deezer",
        "sp": "spotify",
        "yt": "youtube",
        "sc": "soundcloud",
    }.get(prefix, "youtube")


async def _lookup_track(request: Request, req: TrackRef) -> Track | None:
    """بازیابی متادیتای ترک از روی شناسه‌ی داخلی."""
    client = request.app.state.http
    provider, _, ident = (req.trackId.split(":", 2) + ["", ""])[:3]

    try:
        if provider == "itunes":
            rows = (
                await client.get(
                    "https://itunes.apple.com/lookup", params={"id": ident}
                )
            ).json().get("results", [])
            if rows:
                from .providers.itunes import _track

                return _track(rows[0])
        elif provider == "deezer":
            row = (await client.get(f"https://api.deezer.com/track/{ident}")).json()
            if row.get("id"):
                from .providers.deezer import _track

                return _track(row)
        elif provider == "sp" and spotify.enabled():
            detail = await spotify.track(client, ident)
            if detail and detail.tracks:
                return detail.tracks[0]
        elif provider in ("yt", "sc"):
            detail = await catalog.resolve_ref(client, req.sourceUrl)
            if detail and detail.tracks:
                return detail.tracks[0]
    except Exception:
        return None
    return None


# ---------- شناسایی با فینگرپرینت ----------

# سقفِ آپلود. یک کلیپِ ده‌ثانیه‌ای چند صد کیلوبایت است؛ این حد برای ویدیوی
# کوتاه هم جا دارد و جلوی پر شدنِ دیسک با یک آپلودِ چندگیگی را می‌گیرد.
MAX_IDENTIFY_BYTES = 25 * 1024 * 1024


@app.post("/api/identify", response_model=IdentifyResult)
async def identify_audio(request: Request, file: UploadFile = File(...)) -> IdentifyResult:
    """
    «این چه آهنگی بود؟» — یک تکه صدا/ویدیو بالا می‌آید و ترکِ شناسایی‌شده
    به‌همراه نتایجِ قابل‌دانلودش برمی‌گردد.

    فایل روی دیسک نوشته می‌شود نه در حافظه: fpcalc و ffmpeg هر دو مسیر
    می‌خواهند، و ویدیوی چند مگابایتی در حافظه نگه داشتن دلیلی ندارد.
    """
    if not identify.available():
        # پیامِ دقیق، نه یک «تنظیم نشده»ی کلی: تفاوتِ «کلید نیست» و «fpcalc
        # نصب نشده» تنها چیزی است که به کاربر می‌گوید بعدش چه کار کند
        raise HTTPException(503, identify.missing())

    suffix = Path(file.filename or "clip").suffix[:10] or ".bin"
    handle, tmp_name = tempfile.mkstemp(suffix=suffix, dir=DOWNLOAD_DIR)
    tmp = Path(tmp_name)
    size = 0
    try:
        with os.fdopen(handle, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_IDENTIFY_BYTES:
                    raise HTTPException(413, "فایل بزرگ‌تر از حد مجاز است — تکه‌ی کوتاه‌تری بفرست")
                out.write(chunk)

        try:
            matches = await asyncio.to_thread(identify.identify, tmp)
        except identify.ServiceError as exc:
            # ردِ سرویس با «چیزی پیدا نشد» یکی نیست و کاربر باید تفاوتش را ببیند
            raise HTTPException(502, str(exc)) from exc

        if not matches:
            return IdentifyResult()

        best = matches[0]
        try:
            found = await catalog.search(
                request.app.state.http, f"{best.artist} {best.title}".strip()
            )
            tracks = found.tracks[:8]
        except Exception:
            # شناسایی موفق بوده؛ اینکه کاتالوگ در دسترس نباشد نباید کلِ پاسخ را
            # از بین ببرد — اسم و هنرمند به‌تنهایی هم به کاربر کمک می‌کند
            tracks = []

        return artcache.localize(IdentifyResult(
            matches=[
                IdentifyMatch(
                    title=m.title, artist=m.artist, score=m.score, durationMs=m.duration_ms
                )
                for m in matches
            ],
            tracks=tracks,
        ))
    finally:
        tmp.unlink(missing_ok=True)


# ---------- تکه‌کردنِ میکس ----------


@app.get("/api/chapters", response_model=ChaptersInfo)
async def chapters(ref: str) -> ChaptersInfo:
    """
    چپترهای یک لینک. لیستِ خالی یعنی چپتری نداشت — که خطا نیست، فقط یعنی
    دکمه‌ی «تکه‌اش کن» نباید نشان داده شود.
    """
    source = await asyncio.to_thread(split.probe, ref)
    if source is None:
        raise HTTPException(404, "این لینک باز نشد")
    return artcache.localize(_chapters_info(source))


def _chapters_info(source: split.SplitSource) -> ChaptersInfo:
    return ChaptersInfo(
        url=source.url,
        title=source.title,
        uploader=source.uploader,
        durationMs=source.duration_ms,
        artworkUrl=source.artwork_url,
        chapters=[
            ChapterInfo(
                index=c.index,
                title=c.title,
                startMs=c.start_ms,
                endMs=c.end_ms,
                songTitle=c.song_title,
                artist=c.artist,
            )
            for c in source.chapters
        ],
    )


@app.post("/api/downloads/split", response_model=SplitStatus)
async def create_split(req: SplitRequest) -> SplitStatus:
    source = await asyncio.to_thread(split.probe, req.url)
    if source is None:
        raise HTTPException(404, "این لینک باز نشد")
    if not source.chapters:
        raise HTTPException(400, "این لینک چپتری ندارد که بشود جدایش کرد")

    wanted = set(req.indexes)
    chosen = [c for c in source.chapters if not wanted or c.index in wanted]
    if not chosen:
        raise HTTPException(400, "هیچ تکه‌ای انتخاب نشده")

    task = split.start(source, chosen, req.quality)
    return await asyncio.to_thread(_split_status, task)


@app.get("/api/downloads/split/{task_id}", response_model=SplitStatus)
async def split_status(task_id: str) -> SplitStatus:
    """
    پیشرفتِ تکه‌کردن.

    عمداً polling است و نه SSE: برخلافِ دانلود که ثانیه‌به‌ثانیه درصد دارد،
    اینجا رویدادهای معنادار به تعدادِ چپترهاست و یک درخواستِ سبک در هر ثانیه
    ارزان‌تر از نگه‌داشتنِ یک اتصالِ باز و یک صفِ مشترک برای هر کلاینت است.
    """
    task = split.get(task_id)
    if task is None:
        raise HTTPException(404, "این کار پیدا نشد یا منقضی شده")
    # یک کوئری و یک `exists()` به‌ازای هر چپتر، و فرانت هر ثانیه می‌پرسد
    return await asyncio.to_thread(_split_status, task)


def _split_status(task: split.SplitTask) -> SplitStatus:
    items: list[LibraryItem] = []
    for job_id in task.job_ids:
        row = db.get_job(job_id)
        if row is not None and row["path"]:
            items.append(_library_item(row))
    return artcache.localize(
        SplitStatus(
            taskId=task.id,
            status=task.status,
            percent=task.percent,
            done=task.done,
            total=task.total,
            error=task.error,
            items=items,
        )
    )


# ---------- پلی‌لیست‌های کاربر ----------

# چند کاور روی کاشیِ یک پلی‌لیست — چهار تا برای شبکه‌ی ۲×۲
_COVER_COUNT = 4


def _rule_of(row) -> dict | None:
    if not row["rule_json"]:
        return None
    try:
        return json.loads(row["rule_json"])
    except ValueError:
        return None


def _playlist_rows(row) -> list:
    """
    اعضای یک پلی‌لیست — دستی از جدول، هوشمند از اجرای قانون.

    ردیفی که فایلش دیگر روی دیسک نیست کنار گذاشته می‌شود ولی حذف نمی‌شود:
    پاک‌سازیِ ردیف کارِ `/api/library` و sweep دیسک است، نه کارِ خواندنِ یک
    پلی‌لیست.
    """
    if row["kind"] == "smart":
        return db.smart_jobs(_rule_of(row) or {})
    return db.playlist_jobs(row["id"])


def _playlist_items(row) -> list[LibraryItem]:
    # روی کلِ فهرست، نه تک‌تکِ ردیف‌ها: هر صداکردنِ `localize` یک نوشتنِ
    # دسته‌ای در SQLite است و به‌ازای هر ترک صدا زدنش، یک پلی‌لیستِ صدتایی را
    # به صد تراکنشِ ریز تبدیل می‌کرد
    return artcache.localize(
        [
            _library_item(job)
            for job in _playlist_rows(row)
            if job["path"] and Path(job["path"]).exists()
        ]
    )


def _playlist_model(row, items: list[LibraryItem]) -> UserPlaylist:
    return UserPlaylist(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        rule=_rule_of(row),
        trackCount=len(items),
        createdAt=float(row["created_at"]),
        artworkUrls=[i.track.artworkUrl for i in items if i.track.artworkUrl][:_COVER_COUNT],
    )


@app.get("/api/playlists", response_model=list[UserPlaylist])
async def list_playlists() -> list[UserPlaylist]:
    # هر پلی‌لیست یک کوئریِ عضوگیری است و هر عضو یک `exists()` — سنگین‌ترین
    # مسیرِ این فایل. یک نخ برای همه‌شان، نه فقط برای گرفتنِ خودِ ردیف‌ها.
    def build() -> list[UserPlaylist]:
        return [_playlist_model(row, _playlist_items(row)) for row in db.playlists()]

    return await asyncio.to_thread(build)


@app.post("/api/playlists", response_model=UserPlaylist)
async def create_playlist(req: PlaylistCreate) -> UserPlaylist:
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "اسم پلی‌لیست خالی است")
    if req.kind not in ("manual", "smart"):
        raise HTTPException(400, "نوع پلی‌لیست نامعتبر است")
    if req.kind == "smart" and req.rule is None:
        raise HTTPException(400, "پلی‌لیست هوشمند بدون قانون معنی ندارد")

    playlist_id = uuid.uuid4().hex[:12]

    def build() -> UserPlaylist:
        db.create_playlist(
            playlist_id,
            name,
            req.kind,
            req.rule.model_dump() if req.rule else None,
            time.time(),
        )
        if req.kind == "manual" and req.jobIds:
            db.add_to_playlist(playlist_id, req.jobIds, time.time())
        row = db.get_playlist(playlist_id)
        return _playlist_model(row, _playlist_items(row))

    return await asyncio.to_thread(build)


@app.get("/api/playlists/{playlist_id}", response_model=UserPlaylistDetail)
async def get_playlist(playlist_id: str) -> UserPlaylistDetail:
    row = await asyncio.to_thread(db.get_playlist, playlist_id)
    if row is None:
        raise HTTPException(404, "این پلی‌لیست پیدا نشد")
    items = await asyncio.to_thread(_playlist_items, row)
    return UserPlaylistDetail(**_playlist_model(row, items).model_dump(), items=items)


@app.patch("/api/playlists/{playlist_id}", response_model=UserPlaylist)
async def patch_playlist(playlist_id: str, req: PlaylistUpdate) -> UserPlaylist:
    def build() -> UserPlaylist | None:
        if db.get_playlist(playlist_id) is None:
            return None
        db.update_playlist(
            playlist_id,
            name=req.name.strip() if req.name and req.name.strip() else None,
            rule=req.rule.model_dump() if req.rule else None,
        )
        row = db.get_playlist(playlist_id)
        return _playlist_model(row, _playlist_items(row))

    updated = await asyncio.to_thread(build)
    if updated is None:
        raise HTTPException(404, "این پلی‌لیست پیدا نشد")
    return updated


@app.delete("/api/playlists/{playlist_id}")
async def remove_playlist(playlist_id: str) -> dict:
    if db.get_playlist(playlist_id) is None:
        raise HTTPException(404, "این پلی‌لیست پیدا نشد")
    db.delete_playlist(playlist_id)
    return {"ok": True}


@app.post("/api/playlists/{playlist_id}/items")
async def add_playlist_items(playlist_id: str, req: PlaylistItemsRequest) -> dict:
    row = db.get_playlist(playlist_id)
    if row is None:
        raise HTTPException(404, "این پلی‌لیست پیدا نشد")
    if row["kind"] == "smart":
        raise HTTPException(400, "پلی‌لیست هوشمند عضوِ دستی نمی‌گیرد — قانونش را عوض کن")

    # شناسه‌ای که در کتابخانه نیست نباید وارد شود، وگرنه پلی‌لیست به ردیفی
    # اشاره می‌کند که هیچ‌وقت پخش نمی‌شود
    valid = [jid for jid in req.jobIds if (job := db.get_job(jid)) and job["status"] == "ready"]
    if not valid:
        raise HTTPException(400, "هیچ‌کدام از این‌ها در کتابخانه آماده نیست")
    added = db.add_to_playlist(playlist_id, valid, time.time())
    return {"added": added}


@app.delete("/api/playlists/{playlist_id}/items/{job_id}")
async def remove_playlist_item(playlist_id: str, job_id: str) -> dict:
    if not db.remove_from_playlist(playlist_id, job_id):
        raise HTTPException(404, "این آهنگ در پلی‌لیست نبود")
    return {"ok": True}


@app.put("/api/playlists/{playlist_id}/order")
async def reorder_playlist(playlist_id: str, req: PlaylistItemsRequest) -> dict:
    if db.get_playlist(playlist_id) is None:
        raise HTTPException(404, "این پلی‌لیست پیدا نشد")
    db.reorder_playlist(playlist_id, req.jobIds)
    return {"ok": True}


# ---------- فرستادن به بات تلگرام ----------
#
# سرور توکنِ تلگرام ندارد و عمداً هم نباید داشته باشد: بات پروسه‌ی جداست (در
# داکر حتی کانتینرِ جدا). پس این مسیرها فقط صف و اتصال را نگه می‌دارند و خودِ
# فرستادن دستِ `app/bot/run.py` است که با long-poll صف را برمی‌دارد.


def _telegram_status() -> TelegramStatus:
    row = db.telegram_chat()
    return TelegramStatus(
        connected=telegram.connected(),
        linked=row is not None,
        chatTitle=row["title"] if row else None,
        chatId=row["chat_id"] if row else None,
        botUsername=telegram.bot_username(),
    )


@app.get("/api/telegram/status", response_model=TelegramStatus)
async def telegram_status() -> TelegramStatus:
    return _telegram_status()


@app.post("/api/telegram/pair", response_model=TelegramPairing)
async def telegram_pair() -> TelegramPairing:
    """کدِ وصل‌شدن برای وب. مصرفش در چت اتفاق می‌افتد، نه اینجا."""
    if not telegram.connected():
        raise HTTPException(503, "بات تلگرام بالا نیست — سرویسش را روشن کن.")
    code = telegram.new_code()
    return TelegramPairing(
        code=code,
        expiresIn=telegram.PAIR_TTL,
        deepLink=telegram.deep_link(code, telegram.bot_username()),
    )


@app.delete("/api/telegram/link")
async def telegram_unlink() -> dict:
    return {"ok": db.unlink_telegram()}


@app.post("/api/telegram/pair/claim", response_model=TelegramStatus)
async def telegram_claim(req: TelegramPairClaim) -> TelegramStatus:
    """از سمتِ بات: کاربر کد را در چت فرستاد و همان چت مقصد می‌شود."""
    if not telegram.claim_code(req.code):
        raise HTTPException(404, "این کد معتبر نیست یا منقضی شده — از وب یکی تازه بگیر.")
    db.link_telegram(req.chatId, req.chatTitle, time.time())
    return _telegram_status()


@app.post("/api/telegram/send", response_model=TelegramSend)
async def telegram_send(req: TelegramSendRequest, request: Request) -> TelegramSend:
    row = db.telegram_chat()
    if row is None:
        raise HTTPException(409, "هنوز به تلگرام وصل نشده‌ای.")
    if not telegram.connected():
        raise HTTPException(503, "بات تلگرام بالا نیست — سرویسش را روشن کن.")

    if req.kind == "track":
        if req.track is None:
            raise HTTPException(400, "خودِ آهنگ نیامده")
        # همین‌جا به ترکِ کامل تبدیل می‌شود نه سمتِ بات: متادیتای فرانت (شماره‌ی
        # ترک، سال، ژانر) اینجا در دسترس است و بات را از یک lookup بی‌مورد
        # نجات می‌دهد — دقیقاً همان کاری که /api/downloads می‌کند
        payload = {"track": (await _track_for(request, req.track)).model_dump()}
    else:
        if not req.ref:
            raise HTTPException(400, "لینک یا شناسه‌ی آلبوم نیامده")
        payload = {"ref": req.ref}
    # کیفیت همان چیزی است که کاربر لحظه‌ی کلیک در هدر انتخاب کرده بود؛ اگر بعداً
    # عوضش کند، کارِ توی صف نباید عوض شود
    payload["quality"] = req.quality
    # False یعنی «فقط تلگرام»: بات بعد از آپلود، فایل و ردیفِ جاب را پاک می‌کند
    payload["keep"] = req.keep

    send_id = uuid.uuid4().hex
    db.enqueue_telegram(send_id, row["chat_id"], req.kind, payload, req.title, time.time())
    # long-pollِ بات همین حالا برگردد، نه بعدِ تایم‌اوتش
    telegram.notify()
    return TelegramSend(id=send_id, status="pending")


@app.get("/api/telegram/sends/{send_id}", response_model=TelegramSend)
async def telegram_send_status(send_id: str) -> TelegramSend:
    row = db.telegram_send(send_id)
    if row is None:
        raise HTTPException(404, "این ارسال پیدا نشد")
    return TelegramSend(id=row["id"], status=row["status"], error=row["error"])


@app.post("/api/telegram/bot", response_model=TelegramStatus)
async def telegram_bot_heartbeat(req: TelegramHeartbeat) -> TelegramStatus:
    """بات موقع بالا آمدن خودش را معرفی می‌کند تا وب بداند دکمه کار می‌کند."""
    telegram.heartbeat(req.username)
    return _telegram_status()


@app.get("/api/telegram/outbox/next", response_model=TelegramJob | None)
async def telegram_next_job(username: str | None = None, wait: float = telegram.OUTBOX_WAIT):
    """
    long-pollِ بات روی صف.

    خالی‌بودن با None جواب داده می‌شود نه ۴۰۴: «کاری نیست» حالتِ عادیِ این مسیر
    است و نباید در لاگِ بات مثل خطا دیده شود.
    """
    telegram.heartbeat(username)

    # قبل از اولین claim: کاری که بینِ این دو خط در صف بنشیند نباید بیدارباشش
    # پاک شود، وگرنه بات تا پایانِ تایم‌اوت بی‌کار می‌ماند
    telegram.arm()
    row = await asyncio.to_thread(db.claim_telegram, time.time())
    if row is None:
        await telegram.wait_for_job(max(0.0, min(wait, telegram.OUTBOX_WAIT)))
        row = await asyncio.to_thread(db.claim_telegram, time.time())
    if row is None:
        return None

    payload = json.loads(row["payload"])
    track = payload.get("track")
    return TelegramJob(
        id=row["id"],
        chatId=row["chat_id"],
        kind=row["kind"],
        quality=payload.get("quality", "320"),
        title=row["title"],
        track=Track.model_validate(track) if track else None,
        ref=payload.get("ref"),
        keep=payload.get("keep", True),
    )


@app.post("/api/telegram/outbox/{send_id}/done", response_model=TelegramSend)
async def telegram_job_done(send_id: str, req: TelegramJobResult) -> TelegramSend:
    if db.telegram_send(send_id) is None:
        raise HTTPException(404, "این ارسال پیدا نشد")
    now = time.time()
    db.finish_telegram(send_id, req.error, now)
    # جدول نباید بی‌نهایت رشد کند؛ تمام‌شده‌های قدیمی دیگر به‌درد کسی نمی‌خورند
    db.prune_telegram(now - TELEGRAM_SEND_TTL)
    row = db.telegram_send(send_id)
    return TelegramSend(id=send_id, status=row["status"], error=row["error"])


# ---------- هنرمندهای دنبال‌شده ----------
#
# مقصدِ اطلاع‌رسانی همیشه چتِ تلگرام است، ولی خودِ ردیف‌ها در دیتابیسِ سرور
# زندگی می‌کنند تا وب هم بتواند هنرمند دنبال کند. `chatId` در درخواست اجباری
# است (وب آن را از وضعیتِ اتصال می‌گیرد) تا سرور حدس نزند «منظورش کدام چت بود».


def _follow_row(row) -> Follow:
    return Follow(
        id=row["id"],
        chatId=row["chat_id"],
        artistId=row["artist_id"],
        artistName=row["artist_name"],
        artistSourceUrl=row["artist_source_url"],
        source=row["source"],
        artworkUrl=row["artwork_url"],
        lastReleaseId=row["last_release_id"],
        lastReleaseTitle=row["last_release_title"],
    )


@app.get("/api/follows", response_model=list[Follow])
async def follows_list(chatId: int | None = None) -> list[Follow]:
    rows = db.follows_for_chat(chatId) if chatId is not None else db.all_follows()
    return [_follow_row(r) for r in rows]


@app.get("/api/follows/state", response_model=FollowState)
async def follows_state(chatId: int, artistId: str) -> FollowState:
    """وضعیتِ دکمه‌ی Follow روی صفحه‌ی هنرمند."""
    rows = db.follows_for_artist(artistId)
    mine = next((r for r in rows if r["chat_id"] == chatId), None)
    return FollowState(followed=mine is not None, follow=_follow_row(mine) if mine else None)


@app.post("/api/follows", response_model=FollowState)
async def follows_add(chatId: int, req: FollowRequest) -> FollowState:
    created = db.add_follow(
        chatId,
        req.artistId,
        req.artistName,
        req.artistSourceUrl,
        req.source,
        req.artworkUrl,
        req.lastReleaseId,
        req.lastReleaseTitle,
        time.time(),
    )
    # ردیفِ از قبل موجود هم باید برگردد — کلیکِ دوباره خطا نیست، «دنبال می‌شود» است
    [row] = [r for r in db.follows_for_artist(req.artistId) if r["chat_id"] == chatId]
    return FollowState(followed=True, follow=_follow_row(row), created=created)


@app.delete("/api/follows")
async def follows_remove(chatId: int, artistId: str) -> dict:
    return {"ok": db.remove_follow(chatId, artistId)}


@app.patch("/api/follows/seen")
async def follows_seen(id: int, releaseId: str, releaseTitle: str) -> dict:
    """بات بعد از تحویلِ موفقِ یک انتشار علامت می‌زند — همان `mark_seen` قبلی."""
    db.follow_mark_seen(id, releaseId, releaseTitle)
    return {"ok": True}
