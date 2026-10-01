"""
توزیعِ نسخه‌ی اندروید — نسخه‌ی APKeای که سرور میزبانی می‌کند.

چرا روی سرور و نه Play Store: توزیعِ اصلیِ موزیک بازی خودمیزبان است (APK روی
تلگرام/سایت). بدونِ این، کاربرِ روی نسخه‌ی قدیمی هیچ‌وقت نمی‌فهمد چیزی جا
انداخته — هیچ کانالی برای «بروزرسانی هست» وجود ندارد.

دو چیز لازم است و هر دو در `DATA_DIR/releases/` می‌نشینند:

    latest.json   {"versionCode": 3, "versionName": "1.2", "notes": "...",
                   "file": "musicbazi-1.2.apk"}
    musicbazi-1.2.apk

`file` اختیاری است؛ نبودنش یعنی نامِ فایل از `versionName` ساخته می‌شود
(همان قالبی که `scripts/android-release.mjs` تولید می‌کند).

`versionCode` باید عدد باشد — مقایسه‌اش رشته‌ای یعنی «۱۰» قدیمی‌تر از «۹»
به نظر برسد و اپ برای همیشه بنرِ دروغین نشان بدهد.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR

RELEASES_DIR = DATA_DIR / "releases"
MANIFEST = RELEASES_DIR / "latest.json"


@dataclass(frozen=True)
class Release:
    version_code: int
    version_name: str
    notes: str
    apk: Path | None


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def current() -> Release | None:
    """آخرین نسخه، یا None اگر چیزی منتشر نشده (یا manifest خراب است)."""
    if not MANIFEST.exists():
        return None
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # manifestِ نیمه‌نوشته نباید سرور را بالا نیاورد — فقط یعنی «چیزی نیست»
        return None
    if not isinstance(data, dict):
        return None

    name = str(data.get("versionName") or "")
    apk_name = str(data.get("file") or (f"musicbazi-{name}.apk" if name else ""))
    apk = RELEASES_DIR / Path(apk_name).name
    return Release(
        version_code=_as_int(data.get("versionCode")),
        version_name=name,
        notes=str(data.get("notes") or ""),
        apk=apk if apk_name and apk.exists() else None,
    )
