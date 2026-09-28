"""
کلاینتِ نازکِ HTTP روی همون API که فرانت هم با آن حرف می‌زند — بات مسیر یا
منطق جدایی در بک‌اند باز نمی‌کند، فقط جای مرورگر را می‌گیرد.

هم‌شکلِ src/lib/api/http.ts، فقط سمت پایتون.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..config import API_BASE_URL, PROXY, TELEGRAM_PROXY
from ..models import (
    AlbumDetail,
    ArtistDetail,
    ChaptersInfo,
    DailyMix,
    DownloadProgress,
    Follow,
    FollowRequest,
    FollowState,
    IdentifyResult,
    LibraryItem,
    LibraryPage,
    SearchResults,
    SongInfo,
    SplitStatus,
    TelegramJob,
    Track,
    VibeSuggestion,
    ZipReady,
)


class Unavailable(Exception):
    """سرور این قابلیت را ندارد — پیامش مستقیم به کاربر نشان داده می‌شود."""


def _detail(res: httpx.Response, fallback: str) -> str:
    """دلیلی که FastAPI در `detail` گذاشته، وگرنه یک جمله‌ی عمومی."""
    try:
        body = res.json()
    except ValueError:
        return fallback
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, str) and detail else fallback


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL, proxy: str | None = None) -> None:
        self._base = base_url.rstrip("/")
        proxy_url = proxy or TELEGRAM_PROXY or PROXY
        mounts: dict[str, httpx.AsyncBaseTransport] = {}
        if proxy_url:
            # درخواست‌های محلی به بک‌اند باید مستقیم و بدون پروکسی بروند
            if "localhost" in self._base or "127.0.0.1" in self._base:
                mounts["http://localhost"] = httpx.AsyncHTTPTransport()
                mounts["http://127.0.0.1"] = httpx.AsyncHTTPTransport()
            mounts["all://"] = httpx.AsyncHTTPTransport(proxy=proxy_url)
        self._http = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(60.0, connect=15.0),
            follow_redirects=True,
            mounts=mounts if mounts else None,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search(self, query: str) -> SearchResults:
        res = await self._http.get("/api/search", params={"q": query})
        res.raise_for_status()
        return SearchResults.model_validate(res.json())

    async def vibe(self, text: str) -> VibeSuggestion:
        """پیشنهاد پلی‌لیست و موزیک بر اساس حال‌وهوا (جمینای/کلیدواژه)."""
        res = await self._http.post("/api/vibe", json={"text": text}, timeout=45.0)
        res.raise_for_status()
        return VibeSuggestion.model_validate(res.json())

    async def resolve_ref(self, ref: str) -> AlbumDetail:
        res = await self._http.get("/api/album", params={"ref": ref})
        res.raise_for_status()
        return AlbumDetail.model_validate(res.json())

    async def chapters(self, ref: str) -> ChaptersInfo | None:
        """بررسی چپترهای یک ویدیو یا میکس (مثلاً در یوتیوب). None در صورت عدم وجود یا خطا."""
        try:
            res = await self._http.get("/api/chapters", params={"ref": ref}, timeout=30.0)
            if res.status_code == 200:
                return ChaptersInfo.model_validate(res.json())
        except Exception:
            pass
        return None

    async def create_split(
        self, url: str, quality: str = "320", indexes: list[int] | None = None
    ) -> SplitStatus:
        """شروع بریدن و تفکیک میکس به قطعات مجزا."""
        body = {"url": url, "quality": quality, "indexes": indexes or []}
        res = await self._http.post("/api/downloads/split", json=body, timeout=60.0)
        res.raise_for_status()
        return SplitStatus.model_validate(res.json())

    async def split_status(self, task_id: str) -> SplitStatus:
        """دریافت وضعیت پیشرفت بریدن میکس."""
        res = await self._http.get(f"/api/downloads/split/{task_id}", timeout=15.0)
        res.raise_for_status()
        return SplitStatus.model_validate(res.json())

    async def artist(self, ref: str) -> ArtistDetail | None:
        """صفحه‌ی هنرمند — برای `/follow` و چک‌کردنِ دوره‌ایِ انتشار تازه."""
        res = await self._http.get("/api/artist", params={"ref": ref})
        if res.status_code == 404:
            return None
        res.raise_for_status()
        return ArtistDetail.model_validate(res.json())

    async def create_download(self, track: Track, quality: str) -> str:
        # همون بدنه‌ای که trackRef در http.ts می‌سازد — با متادیتای همراه،
        # سرور مجبور به lookup دوباره نیست و تگ‌های آلبومی هم درست می‌آیند
        body = {
            "trackId": track.id,
            "sourceUrl": track.sourceUrl,
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "albumId": track.albumId,
            "albumArtist": track.albumArtist,
            "durationMs": track.durationMs,
            "artworkUrl": track.artworkUrl,
            "trackNumber": track.trackNumber,
            "discNumber": track.discNumber,
            "year": track.year,
            "genre": track.genre,
            "quality": quality,
        }
        res = await self._http.post("/api/downloads", json=body)
        res.raise_for_status()
        return res.json()["jobId"]

    async def delete_download(self, job_id: str) -> None:
        """حذفِ کاملِ جاب — فایل و ردیف. مسیرِ «فقط تلگرام» بعد از آپلود صدایش می‌زند."""
        res = await self._http.delete(f"/api/downloads/{job_id}", params={"purge": "true"})
        res.raise_for_status()

    async def stream_progress(self, job_id: str) -> AsyncIterator[DownloadProgress]:
        """همون SSE که فرانت با EventSource می‌خواند — اینجا با httpx."""
        async with self._http.stream("GET", f"/api/downloads/{job_id}/events") as res:
            res.raise_for_status()
            async for line in res.aiter_lines():
                if not line.startswith("data: "):
                    continue  # کامنت keep-alive یا خط خالی جداکننده
                yield DownloadProgress.model_validate(json.loads(line[len("data: ") :]))

    def file_url(self, job_id: str) -> str:
        return f"{self._base}/api/downloads/{job_id}/file"

    async def file_bytes(self, job_id: str) -> bytes | None:
        """فایل نهایی؛ None یعنی هنوز روی دیسک نیست."""
        res = await self._http.get(f"/api/downloads/{job_id}/file")
        if res.status_code != 200:
            return None
        return res.content

    async def thumb_bytes(self, job_id: str) -> bytes | None:
        """
        کاورِ همین فایل در ابعادِ thumbnailِ تلگرام — از خودِ سرور، نه از CDN.

        این تفاوتِ اصلی‌اش است: سرور کاور را از داخلِ فایلِ دانلودشده درمی‌آورد،
        پس نه به شبکه‌ی بیرون بند است نه تایم‌اوت می‌دهد. گرفتنش از CDN همان
        کاری بود که گاهی شکست می‌خورد و آهنگ در لیستِ تلگرام بی‌تصویر می‌ماند.
        """
        try:
            res = await self._http.get(f"/api/downloads/{job_id}/thumb")
        except httpx.HTTPError:
            return None
        if res.status_code != 200:
            return None
        return res.content

    async def lyrics_bytes(self, job_id: str) -> bytes | None:
        """فایل .lrc اگر متنی پیدا شده باشد — هم‌زمان‌شده یا ساده."""
        res = await self._http.get(f"/api/downloads/{job_id}/lyrics")
        if res.status_code != 200:
            return None
        return res.content

    async def song_info(self, title: str, artist: str) -> SongInfo | None:
        """آهنگساز/تهیه‌کننده/آلبوم — None یعنی Genius تنظیم نشده یا چیزی پیدا نکرد یا شبکه شکست خورد."""
        try:
            res = await self._http.get("/api/songinfo", params={"title": title, "artist": artist})
        except httpx.HTTPError:
            return None
        if res.status_code != 200:
            return None
        return SongInfo.model_validate(res.json())

    async def library(self, query: str = "") -> LibraryPage:
        res = await self._http.get("/api/library", params={"q": query, "limit": 8})
        res.raise_for_status()
        return LibraryPage.model_validate(res.json())

    async def favorites(self) -> list[LibraryItem]:
        """لیست آهنگ‌های مورد علاقه (لایک‌شده) در کتابخانه."""
        res = await self._http.get("/api/favorites")
        res.raise_for_status()
        return [LibraryItem.model_validate(x) for x in res.json()]

    async def set_favorite(self, job_id: str, favorite: bool) -> bool:
        """تغییر وضعیت لایکِ یک ترک در کتابخانه."""
        res = await self._http.put(f"/api/library/{job_id}/favorite", params={"favorite": favorite})
        res.raise_for_status()
        return bool(res.json().get("favorite"))

    async def daily_mix(self, limit: int = 15) -> DailyMix:
        """دریافت میکس روزانه بر اساس علایق و تاریخچه گوش دادن."""
        res = await self._http.get("/api/mix", params={"limit": limit})
        res.raise_for_status()
        return DailyMix.model_validate(res.json())

    async def create_zip(self, job_ids: list[str], name: str = "musicbazi") -> ZipReady:
        """ساخت آرشیو فشرده ZIP از چندین قطعه."""
        res = await self._http.post("/api/downloads/zip", json={"jobIds": job_ids, "name": name})
        res.raise_for_status()
        return ZipReady.model_validate(res.json())

    async def zip_bytes_by_url(self, relative_url: str) -> bytes | None:
        """دانلود بایت‌های فایل زیپ ساخته‌شده."""
        res = await self._http.get(relative_url)
        if res.status_code != 200:
            return None
        return res.content

    def full_zip_url(self, relative_url: str) -> str:
        """آدرس کامل دانلود مستقیم فایل زیپ."""
        return f"{self._base}{relative_url}"

    async def identify(self, data: bytes, filename: str) -> IdentifyResult:
        """
        شناساییِ یک تکه صدا/ویدیو.

        اگر سرور اصلاً شناسایی نداشته باشد `Unavailable` پرت می‌کند و پیامش
        همان جمله‌ی خودِ سرور است — «نشناختم» و «تنظیم نشده» دو چیز متفاوت‌اند
        و کاربر باید بداند کدامش پیش آمده.

        تایم‌اوتِ جدا دارد چون آپلود و تشخیص روی فایلِ چندمگابایتی چند ثانیه
        وقت می‌گیرند و بعدش هنوز جستجوی کاتالوگ مانده.
        """
        try:
            res = await self._http.post(
                "/api/identify",
                files={"file": (filename, data)},
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            raise Unavailable("سرور جواب نداد — دوباره امتحان کن.") from exc

        if res.status_code == 503:
            raise Unavailable(_detail(res, "شناسایی صوتی روی این سرور تنظیم نشده."))
        if res.status_code != 200:
            raise Unavailable(_detail(res, "شناسایی ناموفق بود."))
        return IdentifyResult.model_validate(res.json())

    # ---------- صفِ «فرستادن به تلگرام» از وب ----------
    #
    # وب توکنِ تلگرام ندارد، پس دکمه‌اش فقط یک ردیف در صفِ سرور می‌گذارد و
    # همین‌جا برداشته می‌شود. بات همان مسیرِ همیشگیِ دانلود/ارسال را می‌رود —
    # نه کدِ موازی، نه کیفیتِ متفاوت.

    async def register(self, username: str | None) -> None:
        """معرفیِ خود به سرور تا وب بداند دکمه‌ی تلگرام کار می‌کند."""
        try:
            await self._http.post("/api/telegram/bot", json={"username": username})
        except httpx.HTTPError:
            pass  # سرور هنوز بالا نیامده؛ long-pollِ بعدی خودش دوباره ثبت می‌کند

    async def claim_pair(self, code: str, chat_id: int, chat_title: str) -> str | None:
        """
        کدی که کاربر در چت فرستاد را خرج می‌کند.

        None یعنی موفق؛ رشته یعنی دلیلِ ردشدن، همان جمله‌ای که به کاربر نشان
        داده می‌شود.
        """
        try:
            res = await self._http.post(
                "/api/telegram/pair/claim",
                json={"code": code, "chatId": chat_id, "chatTitle": chat_title},
            )
        except httpx.HTTPError:
            return "سرور جواب نداد — بعداً دوباره امتحان کن."
        if res.status_code == 200:
            return None
        return _detail(res, "وصل‌شدن ناموفق بود.")

    async def next_telegram_job(self, username: str | None, wait: float) -> TelegramJob | None:
        """
        long-poll روی صف. None یعنی کاری نبود — حالتِ عادی، نه خطا.

        تایم‌اوتِ HTTP باید از خودِ انتظار بیشتر باشد وگرنه هر بار قبل از جواب
        دادنِ سرور قطع می‌شود.
        """
        res = await self._http.get(
            "/api/telegram/outbox/next",
            params={"username": username or "", "wait": wait},
            timeout=wait + 15.0,
        )
        res.raise_for_status()
        body = res.json()
        return TelegramJob.model_validate(body) if body else None

    async def finish_telegram_job(self, send_id: str, error: str | None) -> None:
        try:
            await self._http.post(
                f"/api/telegram/outbox/{send_id}/done", json={"error": error}
            )
        except httpx.HTTPError:
            pass  # فقط وضعیتِ نمایشی در وب است؛ خودِ فایل از قبل رفته

    # ---------- هنرمندهای دنبال‌شده ----------
    #
    # دیتابیسِ سرور منبعِ واحدِ حقیقت است (وب هم از همین‌جا دنبال می‌کند)، پس
    # بات دیگر چیزی در bot.db نمی‌نویسد؛ این‌ها همان CRUDهای `/api/follows`اند.

    async def follows(self, chat_id: int | None = None) -> list[Follow]:
        params = {"chatId": chat_id} if chat_id is not None else {}
        res = await self._http.get("/api/follows", params=params)
        res.raise_for_status()
        return [Follow.model_validate(r) for r in res.json()]

    async def add_follow(self, chat_id: int, req: FollowRequest) -> FollowState:
        res = await self._http.post("/api/follows", params={"chatId": chat_id}, json=req.model_dump())
        res.raise_for_status()
        return FollowState.model_validate(res.json())

    async def remove_follow(self, chat_id: int, artist_id: str) -> bool:
        res = await self._http.delete("/api/follows", params={"chatId": chat_id, "artistId": artist_id})
        res.raise_for_status()
        return bool(res.json().get("ok"))

    async def mark_follow_seen(self, follow_id: int, release_id: str, release_title: str) -> None:
        await self._http.patch(
            "/api/follows/seen",
            params={"id": follow_id, "releaseId": release_id, "releaseTitle": release_title},
        )

    async def raw_bytes(self, url: str) -> bytes | None:
        """
        GET عمومی — نه به API خودمان، به CDN خودِ کاتالوگ (کاور آهنگ).

        httpx با URL مطلق base_url را نادیده می‌گیرد، پس همین کلاینت برای هر
        دو کار کافی است؛ نیازی به کلاینتِ جدا نیست.
        """
        try:
            res = await self._http.get(url, timeout=30.0, follow_redirects=True)
        except Exception:
            return None
        if res.status_code != 200:
            return None
        return res.content
