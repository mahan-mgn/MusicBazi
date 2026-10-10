"""
آینه‌ی محلیِ کاورها.

کاور تنها بخشی از کتابخانه است که روی دیسکِ ما نیست: `Track.artworkUrl` به CDNِ
همان کاتالوگ اشاره می‌کند (`is1-ssl.mzstatic.com`، `i.scdn.co`،
`e-cdns-images.dzcdn.net`). موقع قطعیِ اینترنتِ بین‌الملل، فایل‌های صوتی سرِ
جایشان‌اند و پخش می‌شوند ولی هر کاورِ صفحه سفید می‌شود — یعنی کتابخانه‌ای که
کاملاً سالم است، شکسته دیده می‌شود.

راه‌حل یک هدایت است، نه یک پیش‌دانلودِ بزرگ: هر آدرسی که از کاتالوگ بیرون
می‌رود اول اینجا ثبت و به `/api/art/{sha}` تبدیل می‌شود. اولین باری که مرورگر
آن آدرس را می‌خواهد، سرور تصویر را می‌گیرد، روی دیسک نگه می‌دارد و از همان‌جا
سرو می‌کند. پس کشْ خودش با مرورِ عادیِ کاربر پر می‌شود و دفعه‌ی بعد — با یا
بدون اینترنت — از دیسک می‌آید.

دو فایده‌ی جانبی هم دارد که مستقل از قطعی‌اند: همان کاور بین ترک‌های یک آلبوم
یک‌بار گرفته می‌شود، و درخواست از سرور رد می‌شود پس `MUSICBAZI_PROXY` روی آن هم
اثر دارد — همان CDNها روی خیلی از شبکه‌ها به‌هرحال مستقیم باز نمی‌شوند.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from . import artwork
from .config import ART_MIRROR_ENABLED, DATA_DIR, PROXY

log = logging.getLogger(__name__)

CACHE_DIR = Path(DATA_DIR) / "artwork"

# آدرسِ محلی — همان چیزی که به‌جای آدرسِ CDN به فرانت می‌رود
LOCAL = re.compile(r"^/api/art/([0-9a-f]{20})$")

# همان، ولی با مبدأِ اختیاری.
#
# اپ اندروید صفحه را از `https://localhost` سرو می‌کند و هر `/api/...` را که از
# سرور می‌گیرد به آدرسِ مطلق بازنویسی می‌کند (`src/lib/server.ts`) — وگرنه
# «خودِ اپ» را طلب می‌کند. یعنی موقعِ دانلود همان کاور به‌شکلِ
# `http://127.0.0.1:8000/api/art/{sha}` پس می‌آید. با `LOCAL`ِ لنگردار آن را
# نمی‌شناختیم: `original` به‌جای بازگرداندنِ آدرسِ CDN، خودِ آدرسِ محلی را
# دست‌نخورده می‌داد و `remember` آن را یک منبعِ بیرونی حساب می‌کرد و ردیفی
# می‌ساخت که به خودش اشاره می‌کرد — فایل بی‌کاور و کتابخانه‌ی بی‌کاور، بی‌آنکه
# هیچ‌جا خطایی دیده شود.
_LOCAL_ANY = re.compile(r"^(?:[a-z][a-z0-9+.-]*://[^/]*)?/api/art/([0-9a-f]{20})$", re.IGNORECASE)


def _local_sha(url: str) -> str | None:
    """شناسه‌ی کاورِ محلی، چه نسبی آمده باشد چه مطلق؛ اگر محلی نبود None."""
    match = _LOCAL_ANY.match(url)
    return match.group(1) if match else None

# سقفِ حجمِ یک کاور. بالاتر از این یا تصویر نیست یا چیزی است که نباید در یک
# کارتِ ۲۰۰ پیکسلی بنشیند؛ در هر دو حالت نگه‌داشتنش فقط دیسک را می‌خورد.
MAX_BYTES = 4 * 1024 * 1024

FETCH_TIMEOUT = 15.0


def _sha(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def canonical(url: str) -> str:
    """
    آدرسی که کلید بر اساسش ساخته می‌شود.

    همه‌ی نسخه‌های یک کاور به یک اندازه نرمال می‌شوند، وگرنه همان جلدِ آلبوم که
    در نتیجه‌ی جستجو ۱۰۰ پیکسل و در صفحه‌ی آلبوم ۵۰۰ پیکسل آمده، دو ردیف و دو
    دانلودِ جدا می‌شد. اندازه‌ی نمایش انتخاب شده چون کاربرِ وب دقیقاً همین را
    می‌بیند؛ نسخه‌ی بزرگ فقط موقع امبد کردن در فایل لازم است و آنجا مستقیم از
    `downloader` گرفته می‌شود.
    """
    return artwork.resized(url, artwork.DISPLAY) or url


def path_for(sha: str) -> Path:
    # دو حرفِ اول به‌عنوان پوشه: یک پوشه‌ی تخت با ده‌ها هزار فایل روی NTFS و
    # هر فایل‌سیستمِ دیگری، `readdir` را به زانو درمی‌آورد — و پاک‌سازیِ دیسک
    # دقیقاً همین کار را می‌کند
    return CACHE_DIR / sha[:2] / sha


# قاعده‌ی آینه: بایتِ CDN دست‌نخورده. هیچ برشی در زمانِ ذخیره انجام نمی‌شود —
# خواسته‌ی کاربر «آرت‌ورک دقیقاً مثل پلتفرم» است و اسکن‌های J-card اپل را هم
# اپل با نوارهایشان نشان می‌دهد؛ بریدنشان یعنی انحراف از پلتفرم. (نسخه‌ی قبل
# زمینه‌ی تیره‌ی خودِ جلدها را حاشیه می‌گرفت و کاوری که روی پلتفرم حاشیه داشت
# اینجا زوم‌شده می‌افتاد — قلبِ نئونِ KAASH.) ماژولِ artborder با تست‌هایش
# می‌ماند ولی در این مسیر سیم‌کشی نیست.
def remember(urls: Iterable[str | None]) -> dict[str, str]:
    """
    آدرس‌های کاور را ثبت می‌کند و نگاشتِ «آدرسِ اصلی → آدرسِ محلی» را می‌دهد.

    خودِ تصویر گرفته نمی‌شود؛ فقط ردیفش ساخته می‌شود تا وقتی مرورگر سراغِ
    `/api/art/...` آمد بدانیم از کجا باید بگیریمش. یعنی هزینه‌ی یک جستجوی
    بیست‌تایی، یک `executemany` است نه بیست درخواستِ HTTP.
    """
    from . import db

    mapping: dict[str, str] = {}
    rows: list[tuple[str, str]] = []
    for url in urls:
        # `_local_sha` نه `LOCAL.match`: اپ نیتیو آدرسِ محلی را به‌شکلِ مطلق
        # پس می‌فرستد و اگر اینجا شناخته نشود، خودِ `/api/art` یک «منبعِ بیرونی»
        # حساب می‌شود و ردیفی می‌سازیم که به خودش اشاره می‌کند
        if not url or _local_sha(url) or not url.lower().startswith("http"):
            continue
        target = canonical(url)
        sha = _sha(target)
        mapping[url] = f"/api/art/{sha}"
        rows.append((sha, target))

    if rows:
        # ردیفِ تکراری در همان دسته، `executemany` را با ON CONFLICT گیج نمی‌کند
        # ولی بی‌خود دو بار نوشته می‌شود
        db.remember_artwork(list(dict(rows).items()), time.time())
    return mapping


def original(url: str | None) -> str | None:
    """
    از آدرسِ محلی به آدرسِ اصلیِ CDN.

    لازم است چون فرانت همان `artworkUrl`ی که گرفته را موقع دانلود پس می‌فرستد
    (تا سرور دوباره lookup نکند). بدون این، تگ‌گذار سعی می‌کرد `/api/art/...`
    را با httpx بگیرد و هر فایلِ دانلودشده بی‌کاور می‌شد — درست همان چیزی که
    این ماژول قرار بود درستش کند.

    آدرسِ *مطلقِ* محلی هم شناخته می‌شود: اپ اندروید پیش از فرستادنش `/api/...`
    را به `http://<server>/api/...` تبدیل کرده، و نشناختنش یعنی فایلِ
    دانلودشده روی گوشی برای همیشه بی‌کاور بماند.
    """
    from . import db

    if not url:
        return url
    sha = _local_sha(url)
    if not sha:
        return url
    row = db.artwork_row(sha)
    # نبودنِ ردیف یعنی این کاور هرگز از کاتالوگ نیامده؛ آدرسِ محلی را
    # دست‌نخورده برگرداندن بدتر از None است — تگ‌گذار آن را با httpx می‌گیرد،
    # به خودش درخواست می‌زند و بی‌حاصل می‌ماند
    return row["url"] if row else None


def _rewrite(value: Any, mapping: dict[str, str]) -> None:
    """`artworkUrl`/`bannerUrl`/`artworkUrls` را در جا عوض می‌کند."""
    if isinstance(value, BaseModel):
        current = getattr(value, "artworkUrl", None)
        if isinstance(current, str) and current in mapping:
            value.artworkUrl = mapping[current]
        banner = getattr(value, "bannerUrl", None)
        if isinstance(banner, str) and banner in mapping:
            value.bannerUrl = mapping[banner]
        urls = getattr(value, "artworkUrls", None)
        if isinstance(urls, list):
            value.artworkUrls = [mapping.get(u, u) for u in urls]
        for name in type(value).model_fields:
            _rewrite(getattr(value, name, None), mapping)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _rewrite(item, mapping)


def _collect(value: Any, out: list[str]) -> None:
    if isinstance(value, BaseModel):
        current = getattr(value, "artworkUrl", None)
        if isinstance(current, str):
            out.append(current)
        banner = getattr(value, "bannerUrl", None)
        if isinstance(banner, str):
            out.append(banner)
        urls = getattr(value, "artworkUrls", None)
        if isinstance(urls, list):
            out.extend(u for u in urls if isinstance(u, str))
        for name in type(value).model_fields:
            _collect(getattr(value, name, None), out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect(item, out)


def localize(payload: Any) -> Any:
    """
    هر `artworkUrl`ی را در پاسخ به آدرسِ محلی تبدیل می‌کند.

    روی خودِ مدل کار می‌کند نه روی دیکشنری، چون پاسخ‌ها از قبل مدل‌اند و تبدیل
    رفت‌وبرگشتی فقط هزینه است. خاموش‌بودنِ آینه یعنی همان آدرسِ اصلی برگردد —
    رفتارِ قبلیِ برنامه، بی‌کم‌وکاست.
    """
    if not ART_MIRROR_ENABLED:
        return payload
    urls: list[str] = []
    _collect(payload, urls)
    if not urls:
        return payload
    _rewrite(payload, remember(urls))
    return payload


def sniff(path: Path) -> str | None:
    """
    نوعِ رسانه از خودِ بایت‌ها — نه از نامِ فایل.

    فایل‌های آینه پسوند ندارند (نامشان `sha` است) و `FileResponse` بیِ
    `media_type` آن‌ها را `application/octet-stream` می‌فروشد؛ مرورگر با
    sniffing رندرشان می‌کند ولی هر ابزارِ کنارِ مرورگر (curl، دانلودمنیجر،
    دیباگر) نوعِ غلط می‌بیند. امضا recognizable است و یک readِ ۱۲ بایتی.
    نشناختن = None تا ستونِ db دروغِ «jpeg» نگوییم و همان octet-stream بماند.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(12)
    except OSError:
        return None
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


def stored(sha: str) -> Path | None:
    """فایلِ روی دیسک، اگر واقعاً آنجا باشد."""
    from . import db

    row = db.artwork_row(sha)
    if row is None or row["fetched_at"] is None:
        return None
    path = path_for(sha)
    if path.exists():
        return path
    # ردیف می‌گفت هست ولی نبود (پاک‌سازیِ دستی، دیسکِ عوض‌شده). برگرداندنِ ۴۰۴
    # یعنی این کاور تا ابد مرده می‌ماند؛ برگرداندن به «نگرفته» یعنی دفعه‌ی بعد
    # که اینترنت بود دوباره گرفته می‌شود.
    db.forget_artwork(sha)
    return None


def fetch(sha: str) -> Path | None:
    """
    تصویر را از CDN می‌گیرد و روی دیسک می‌نشاند. بدون اینترنت `None`.

    همگام است و از مسیرِ درخواست در thread صدا زده می‌شود — تنها راهی که هم
    اولین بازدید تصویر ببیند و هم دفعات بعد از دیسک بیاید.
    """
    from . import db

    row = db.artwork_row(sha)
    if row is None:
        return None

    # ردیفِ مسمومِ نسخه‌های قبل: آدرسِ «منبع»ی که ثبت شده خودِ همین آینه است.
    # تا وقتی `remember` آدرسِ مطلقِ محلی را نمی‌شناخت، اپ نیتیو آن را موقع
    # دانلود پس می‌فرستاد و اینجا ثبتش می‌شد. گرفتنش یعنی سرور وسطِ سروِ یک
    # کاور به خودش درخواست بزند و یک نخِ دیگر قرض بگیرد — هر صفحه‌ی کتابخانه
    # با چند ده کاور، دو برابرِ استخرِ نخ (۴۰تایی) نخ می‌خواهد و وقتی پر شود،
    # درخواست‌ها پشتِ هم می‌میرند: سرور زنده است ولی دیگر به هیچ‌کس جواب
    # نمی‌دهد. ردیف را پاک می‌کنیم تا خودِ داده هم درست شود.
    if _local_sha(row["url"] or ""):
        db.drop_artwork(sha)
        log.warning("ردیفِ کاور به خودش اشاره می‌کرد و پاک شد: %s", sha)
        return None

    # `candidates` از بزرگ به کوچک است و پله‌ی اولش برای نمایش لازم نیست؛
    # اینجا از همان اندازه‌ی نمایش شروع می‌کنیم و آدرسِ خام آخرین پشتیبان است
    for candidate in artwork.at_most(row["url"], artwork.DISPLAY):
        try:
            res = httpx.get(
                candidate, timeout=FETCH_TIMEOUT, follow_redirects=True, proxy=PROXY
            )
            res.raise_for_status()
            mime = res.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not mime.startswith("image/") or len(res.content) > MAX_BYTES:
                continue
            payload = res.content
            path = path_for(sha)
            path.parent.mkdir(parents=True, exist_ok=True)
            # نوشتنِ اتمی: درخواستِ هم‌زمانِ دیگری نباید فایلِ نیمه‌نوشته را
            # ببیند و آن را کاورِ سالم حساب کند
            tmp = path.with_suffix(".part")
            tmp.write_bytes(payload)
            tmp.replace(path)
            db.artwork_stored(sha, mime, len(payload), time.time())
            return path
        except Exception as exc:
            log.debug("کاور %s گرفته نشد: %s", candidate, exc)

    return None


def remember_bytes(url: str | None, data: bytes, mime: str) -> None:
    """
    کاوری که همین الان برای امبد کردن گرفته شده را مجانی در آینه هم می‌نشاند.

    `downloader.tag` به‌هرحال بایت‌ها را دارد؛ نوشتنشان روی دیسک یعنی ترکِ تازه
    دانلودشده حتی اگر همان لحظه اینترنت قطع شود، در کتابخانه کاور دارد. نسخه‌ی
    امبد بزرگ‌تر از نسخه‌ی نمایش است ولی همان تصویر است و مرورگر کوچکش می‌کند —
    یک کاورِ بزرگ بی‌نهایت بهتر از یک مربعِ خالی است.
    """
    if not ART_MIRROR_ENABLED or not url or not data or len(data) > MAX_BYTES:
        return
    from . import db

    sha = _sha(canonical(url))
    try:
        remember([url])
        path = path_for(sha)
        if path.exists():
            return  # نسخه‌ی نمایش از قبل هست — همان بهتر است
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = data
        tmp = path.with_suffix(".part")
        tmp.write_bytes(payload)
        tmp.replace(path)
        db.artwork_stored(sha, mime, len(payload), time.time())
    except Exception:
        log.debug("نوشتنِ کاور در آینه نشد", exc_info=True)


def warm(limit: int) -> int:
    """
    کاورهای ثبت‌شده‌ای که هنوز گرفته نشده‌اند را در پس‌زمینه می‌گیرد.

    مرورِ عادی بیشترشان را پر می‌کند، ولی نه همه: ردیفی که فقط در نتیجه‌ی
    جستجو از جلوی چشم رد شده و کاربر رویش اسکرول نکرده، آدرسش ثبت شده و
    تصویرش نه. موقعِ قطعی دقیقاً همان‌ها هستند که سفید می‌مانند.

    تعدادِ گرفته‌شده برمی‌گردد تا صداکننده بداند کاری مانده یا نه.
    """
    from . import db

    done = 0
    for row in db.artwork_pending(limit):
        if fetch(row["sha"]):
            done += 1
    return done


async def warm_loop(interval: float, batch: int) -> None:
    """
    حلقه‌ی پس‌زمینه‌ی پرکردنِ آینه.

    فقط وقتی کار می‌کند که بین‌الملل برقرار باشد — در حالتِ اینترانت هر تلاش یک
    تایم‌اوتِ بی‌فایده است و ده‌تایی از آن‌ها، thread poolِ سرور را همان‌جا نگه
    می‌دارد که استریمِ صوت هم از آن رد می‌شود.

    دسته‌ای و با فاصله می‌رود نه یک‌جا: بعد از یک جستجوی پرنتیجه ممکن است صدها
    کاورِ نگرفته در صف باشد و گرفتنِ هم‌زمانشان، هم CDN را عصبانی می‌کند هم
    پهنای باندی را می‌خورد که همان لحظه دستِ دانلودِ واقعیِ کاربر است.
    """
    from . import reach

    while True:
        try:
            await asyncio.sleep(interval)
            if not ART_MIRROR_ENABLED or not reach.online():
                continue
            await asyncio.to_thread(warm, batch)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — پرکردنِ کش نباید سرور را بخواباند
            continue
