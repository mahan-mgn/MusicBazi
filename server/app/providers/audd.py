"""
شناساییِ آهنگ از روی یک تکه‌ی کوتاه — AudD.

چرا کنارِ AcoustID و نه به‌جایش: این دو اصلاً یک کار نمی‌کنند.

AcoustID فینگرپرینتِ کروماپرینت می‌سازد و آن را با ایندکسِ *فایل‌های کامل*
می‌سنجد؛ برای «این mp3 بی‌تگ کدام آهنگ است؟» عالی است و رایگان. ولی صدایی که
با میکروفون از بلندگو ضبط شده — با نویزِ اتاق، اکو و کلیپینگ — دیگر همان سیگنال
نیست، و یک تکه‌ی بیست‌ثانیه‌ای هم مدت‌زمانش با هیچ ترکِ کاملی نمی‌خواند. یعنی
همان حالتی که کاربر انتظار دارد (شزم) دقیقاً همان حالتی است که AcoustID در آن
جواب نمی‌دهد.

AudD برای همین ساخته شده. رایگان نیست (توکن آزمایشی دارد) و ترافیک صوت به سرور
خودش می‌رود، پس اختیاری است: بدون توکن، هیچ‌چیز به بیرون نمی‌رود و مسیر به همان
AcoustID برمی‌گردد.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from .. import credentials
from ..config import AUDD_API, PROXY
from ..db import GUEST_ID

# آپلودِ فایل به‌علاوه‌ی تشخیص؛ تنگ‌تر از این روی شبکه‌ی معمولی زود می‌برد
_TIMEOUT = 60.0


class AuddError(Exception):
    """
    سرویس درخواست را رد کرد — توکن غلط، سهمیه تمام، یا خطای خودشان.

    از «نشناخت» جدا نگه داشته می‌شود: آن یکی جواب است، این یکی یعنی اصلاً
    جوابی گرفته نشده و کاربر باید چیزی را درست کند.
    """


@dataclass
class AuddMatch:
    title: str
    artist: str
    album: str | None = None
    release_date: str | None = None


def enabled(uid: str = GUEST_ID) -> bool:
    return credentials.audd_token(uid) is not None


def recognize(path: Path, uid: str = GUEST_ID) -> AuddMatch | None:
    """
    None یعنی نشناخت (که یک جوابِ معتبر است).

    ولی ردِ سرویس — توکنِ غلط، سهمیه‌ی تمام‌شده، شبکه‌ی قطع — `AuddError`
    می‌دهد. یکسان نشان دادنِ این دو دقیقاً همان اشتباهی است که یک بار
    «کلید نامعتبر» را به‌شکلِ «نشناختم» نشان داد.

    بلاک‌کننده است — باید در thread صدا زده شود.
    """
    token = credentials.audd_token(uid)
    if not token or not path.exists():
        return None

    try:
        with path.open("rb") as handle:
            res = httpx.post(
                AUDD_API,
                data={"api_token": token},
                files={"file": (path.name, handle)},
                timeout=_TIMEOUT,
                proxy=PROXY,
            )
        res.raise_for_status()
        body = res.json()
    except Exception as exc:
        raise AuddError(f"به AudD وصل نشد: {exc}") from exc

    # پاسخِ «پیدا نشد» هم status=success است، فقط result خالی دارد
    if body.get("status") != "success":
        message = (body.get("error") or {}).get("error_message") or "AudD درخواست را رد کرد"
        raise AuddError(f"AudD: {message}")
    result = body.get("result")
    if not result or not result.get("title"):
        return None

    return AuddMatch(
        title=str(result["title"]).strip(),
        artist=str(result.get("artist") or "").strip() or "ناشناس",
        album=(str(result.get("album")).strip() or None) if result.get("album") else None,
        release_date=result.get("release_date"),
    )
