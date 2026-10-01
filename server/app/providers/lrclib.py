"""
متن آهنگ از LRCLIB — عمومی، بدون کلید، هم متن ساده می‌دهد هم هم‌زمان‌شده (LRC).

بلاک‌کننده است: از داخل thread دانلود صدا زده می‌شود، درست بعد از اینکه فایل
روی دیسک نشست و قبل از تگ‌گذاری.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..config import LRCLIB_API, PROXY

# LRCLIB در راهنمایش می‌خواهد کلاینت خودش را معرفی کند
_HEADERS = {"user-agent": "MusicBazi/1.4 (https://github.com/mahan-mgn/MusicBazi)"}
_TIMEOUT = 8.0


@dataclass
class Lyrics:
    plain: str | None
    synced: str | None

    def __bool__(self) -> bool:
        return bool(self.plain or self.synced)


def _from_row(row: dict) -> Lyrics:
    return Lyrics(
        plain=(row.get("plainLyrics") or None),
        synced=(row.get("syncedLyrics") or None),
    )


def fetch(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    """
    اول تطابق دقیق (که مدت‌زمان را هم چک می‌کند)، بعد جستجوی آزاد.

    مسیر دقیق ارزش امتحان جدا را دارد: وقتی جواب می‌دهد، همان نسخه‌ی درست است
    و لازم نیست بین چند نتیجه‌ی مشابه حدس بزنیم.
    """
    if not title:
        return None

    seconds = round(duration_ms / 1000) if duration_ms else None

    try:
        with httpx.Client(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True, proxy=PROXY
        ) as client:
            params: dict[str, str] = {"track_name": title, "artist_name": artist}
            if album:
                params["album_name"] = album
            if seconds:
                params["duration"] = str(seconds)

            res = client.get(f"{LRCLIB_API}/api/get", params=params)
            if res.status_code == 200:
                found = _from_row(res.json())
                if found:
                    return found

            res = client.get(
                f"{LRCLIB_API}/api/search",
                params={"track_name": title, "artist_name": artist},
            )
            if res.status_code != 200:
                return None
            rows = res.json()
    except Exception:
        return None

    if not isinstance(rows, list) or not rows:
        return None

    # مدت‌زمان تنها سیگنالِ قابل‌اتکا برای تشخیص نسخه‌ی درست است؛ نتیجه‌ای که
    # بیش از ۵ ثانیه اختلاف دارد احتمالاً ریمیکس یا نسخه‌ی زنده است.
    if seconds:
        rows = [r for r in rows if abs((r.get("duration") or 0) - seconds) <= 5] or rows

    # متن هم‌زمان‌شده ارزش بیشتری دارد، پس اول سراغ ردیف‌هایی می‌رویم که دارندش
    rows.sort(key=lambda r: (not r.get("syncedLyrics"), not r.get("plainLyrics")))
    found = _from_row(rows[0])
    return found or None
