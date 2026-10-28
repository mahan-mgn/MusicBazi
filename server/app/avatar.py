"""
عکس‌های پروفایل.

یک فایل برای هر کاربر زیر `DATA_DIR/avatars/`، با نامِ شناسه‌ی کاربر. برخلافِ
کاورهای آلبوم که محتوامحور و تغییرناپذیرند (`sha` به‌عنوان نام)، آواتار عوض
می‌شود — و آدرس‌دهیِ محتوامحور یعنی هر تغییر یک فایلِ تازه و یک زباله‌روبِ
تازه. با نامِ کاربر، جایگزینی همان نوشتنِ روی فایل قبلی است.

`avatar_file` در دیتابیس نامِ فایلِ *واقعی* را نگه می‌دارد. اگر پسوند همیشه
`.jpg` باشد و کاربر PNG بفرستد، فرانت با mimeِ غلط سرو می‌کند — پس پسوند از
نوعِ واقعیِ بایت‌ها می‌آید، نه از نامِ فایلِ آپلودی.
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from pathlib import Path

import httpx
from fastapi import UploadFile

from . import artcache, db
from .config import AVATAR_DIR, AVATAR_MAX_BYTES, FFMPEG_BIN

log = logging.getLogger(__name__)

# اندازه‌ی ضلعِ مربعِ آواتارِ خروجی. ۲۵۶ برای آواتاری که بزرگ‌ترین جا نمایشش
# `size-44` (۱۷۶ پیکسل) است کافی است، حتی روی صفحه‌ی رتینا.
_SIDE = 256

# حداکثر چیزی که از گوگل می‌پذیریم — `picture` معمولاً ۱۰۰ پیکسلی است ولی
# کسی که `=s1000-c` را دستی بزند هم باید رد شود، نه اینکه سرور را ببلعد.
_MAX_REMOTE = 8 * 1024 * 1024

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def path_for(user_id: str) -> Path | None:
    """
    فایلِ آواتارِ کاربر روی دیسک، اگر باشد.

    نامِ فایل از دیتابیس می‌آید ولی مسیر با `resolve` داخلِ پوشه قفل می‌شود:
    یک ردیفِ دست‌کاری‌شده نباید بتواند مسیرِ دلخواه را بخواند.
    """
    row = db.user_by_id(user_id)
    if row is None or not row["avatar_file"]:
        return None
    candidate = (AVATAR_DIR / row["avatar_file"]).resolve()
    try:
        candidate.relative_to(AVATAR_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() else None


def public_url(row) -> str | None:
    """
    آدرسی که فرانت می‌تواند مستقیم در `<img>` بگذارد.

    ترتیب: فایلِ محلی اول (آفلاین هم کار می‌کند)، بعد آدرسِ گوگل. `?v=` از
    زمانِ تغییر می‌آید تا با عوض‌شدنِ عکس، کشِ مرورگر عکسِ قبلی را نشان ندهد.
    """
    if row["avatar_file"]:
        path = path_for(row["id"])
        if path is None:
            # ردیف می‌گوید فایل هست ولی روی دیسک نیست (بکاپِ ناقص، پاک‌شدن
            # دستی). `None` یعنی «عکس نداریم» و فرانت می‌رود سراغِ حرفِ اول؛
            # برگرداندنِ آدرسِ فایلِ ناموجود یعنی آیکونِ شکسته.
            return None
        try:
            stamp = int(path.stat().st_mtime)
        except OSError:
            stamp = 0
        return f"/api/avatar/{row['id']}?v={stamp}"
    return row["avatar_url"] or None


def media_type(path: Path) -> str:
    return artcache.sniff(path) or "image/jpeg"


# ---------------------------------------------------------------- نوشتن


def _write(user_id: str, source: Path, media_type: str) -> None:
    """
    فایلِ منبع را کوچک و مربع می‌کند و سرِ جایش می‌نشاند.

    ffmpeg فقط وقتی هست که باشد. روی نبودنش فایلِ خام کپی می‌شود: یک سرورِ
    بدونِ ffmpeg باید هنوز بتواند عکسِ پروفایل بگیرد، فقط بدونِ بهینه‌سازی.
    """
    ext = _EXT.get(media_type, ".jpg")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    target = AVATAR_DIR / f"{user_id}{ext}"
    tmp = AVATAR_DIR / f".{user_id}-{uuid.uuid4().hex[:8]}.tmp"

    if _shrink(source, tmp):
        source = tmp
    else:
        tmp.unlink(missing_ok=True)

    # آواتارِ قبلی با پسوندِ دیگری ممکن است مانده باشد (PNG → JPG)؛ اگر
    # پاکش نکنیم فایلِ بی‌صاحب روی دیسک می‌ماند
    for other, other_ext in _EXT.items():
        if other_ext != ext:
            (AVATAR_DIR / f"{user_id}{other_ext}").unlink(missing_ok=True)

    if source != target:
        target.write_bytes(source.read_bytes())
    tmp.unlink(missing_ok=True)

    db.set_user_avatar(user_id, avatar_file=target.name, avatar_url=None)


def _shrink(source: Path, target: Path) -> bool:
    """کوچک و مربع می‌کند؛ `False` یعنی نشد و باید فایلِ خام را برداشت."""
    try:
        result = subprocess.run(
            [
                FFMPEG_BIN, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source),
                # force_original_aspect_ratio + crop: کادرِ پرتره‌ی بلند کشیده
                # نمی‌شود، وسطش بریده می‌شود
                "-vf", f"scale={_SIDE}:{_SIDE}:force_original_aspect_ratio=increase,crop={_SIDE}:{_SIDE}",
                "-frames:v", "1",
                str(target),
            ],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("کوچک‌سازیِ آواتار با ffmpeg نشد: %s", exc)
        return False
    return result.returncode == 0 and target.exists() and target.stat().st_size > 0


async def store_upload(client: httpx.AsyncClient, user_id: str, upload: UploadFile) -> None:
    """
    عکسِ آپلودیِ کاربر.

    کلِ بدنه در حافظه خوانده می‌شود ولی سقف دارد — `UploadFile` خودش روی دیسک
    بافر می‌کند، پس نگرانیِ حجمِ حافظه نیست؛ نگرانی این است که یک فایلِ ۲
    گیگابایتی واردِ خطِ پردازش شود.
    """
    raw = await upload.read()
    if not raw:
        raise _bad("فایلی فرستاده نشد")
    if len(raw) > AVATAR_MAX_BYTES:
        raise _too_big(len(raw))

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    staging = AVATAR_DIR / f".{uuid.uuid4().hex}.incoming"
    try:
        staging.write_bytes(raw)
        # نوع از بایت‌ها، نه از نام یا از هدرِ content-type که کلاینت می‌فرستد
        media_type = artcache.sniff(staging)
        if media_type is None:
            raise _bad("فایلِ فرستاده‌شده تصویر نیست")
        _write(user_id, staging, media_type)
    finally:
        staging.unlink(missing_ok=True)


async def import_google(client: httpx.AsyncClient, row, picture: str | None) -> None:
    """
    عکسِ حسابِ گوگل را یک‌بار روی دیسک می‌آورد.

    چرا کپی می‌کنیم به‌جای اینکه فقط آدرس را نگه داریم: `googleusercontent.com`
    روی اینترنتِ بین‌الملل است و در قطعیِ شبکه دیده نمی‌شود — یعنی کتابخانه‌ای
    که کاملاً آفلاین کار می‌کند، پروفایلش عکس نداشت. شکستِ دانلود ولی ورود را
    نمی‌شکند: آدرس در `avatar_url` می‌ماند و فرانت همان را نشان می‌دهد.
    """
    url = (picture or "").strip()
    if not url.startswith("http"):
        return

    # کاربری که خودش عکس گذاشته، با عکسِ گوگل بازنویسی نمی‌شود
    if row["avatar_file"] and path_for(row["id"]) is not None:
        return

    try:
        res = await client.get(url, follow_redirects=True)
        res.raise_for_status()
        raw = res.content
    except httpx.HTTPError as exc:
        log.info("عکسِ گوگل دانلود نشد: %s", exc)
        db.set_user_avatar(row["id"], avatar_file=None, avatar_url=url)
        return

    if not raw or len(raw) > _MAX_REMOTE:
        db.set_user_avatar(row["id"], avatar_file=None, avatar_url=url)
        return

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    staging = AVATAR_DIR / f".{uuid.uuid4().hex}.incoming"
    try:
        staging.write_bytes(raw)
        media_type = artcache.sniff(staging)
        if media_type is None:
            db.set_user_avatar(row["id"], avatar_file=None, avatar_url=url)
            return
        _write(row["id"], staging, media_type)
        # آدرسِ گوگل هم می‌ماند: اگر عکسِ محلی روزی پاک شد، فرانت بی‌عکس نمی‌ماند
        db.set_user_avatar(row["id"], avatar_file=f"{row['id']}{_EXT.get(media_type, '.jpg')}", avatar_url=url)
    finally:
        staging.unlink(missing_ok=True)


async def remove(user_id: str) -> None:
    """حذفِ کامل — هر دو منبع، تا کاربر به حرفِ اول برگردد."""
    for ext in _EXT.values():
        (AVATAR_DIR / f"{user_id}{ext}").unlink(missing_ok=True)
    db.clear_user_avatar(user_id)


def _bad(detail: str):
    from .auth import AuthError

    return AuthError(400, detail)


def _too_big(size: int):
    from .auth import AuthError

    mb = AVATAR_MAX_BYTES // (1024 * 1024)
    return AuthError(413, f"حجم عکس باید کمتر از {mb} مگابایت باشد (این یکی {size // (1024 * 1024)} مگابایت است)")
