"""
اعتبارنامه‌های شخصیِ هر حساب.

تا پیش از این، کلیدهای اسپاتیفای/Genius/Gemini/AcoustID/AudD و کوکیِ یوتیوب در
یک فایلِ سراسری (`DATA_DIR/.env`) می‌نشستند و همه‌ی حساب‌ها شریکشان بودند. روی
دامنه‌ای که هر کسی می‌تواند ثبت‌نام کند، این یعنی هر کاربر می‌تواند سهمیه و
کلیدِ پرداختیِ صاحبِ سرور را خرج کند.

این ماژول تنها جایی است که «مقدارِ مؤثرِ یک کلید برای یک کاربر» تعیین می‌شود:

    مقدارِ خودِ کاربر  →  (فقط مهمان) مقدارِ سراسریِ `.env`  →  هیچ

**هیچ مقدارِ import-time ای این‌جا نیست.** مقدارها هر بار از دیتابیس خوانده
می‌شوند، پس ذخیره‌کردنِ یک کلید دیگر به ری‌استارتِ سرور نیاز ندارد — چیزی که
نسخه‌ی `.env` مجبور بود، چون `config.py` مقدارها را هنگامِ import قفل می‌کرد.

`effective()` مقدارِ خالی را «پاک‌شده» می‌بیند و به سراسری برنمی‌گردد؛ وگرنه
کاربری که کلیدِ مهمان را عمداً خاموش کرده بود، بعدِ اولین رفرش دوباره آن را
می‌دید.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from . import config as cfg
from . import db

#: کلیدهای شخصی، با نامِ کوتاه. نامِ کوتاه در DB می‌نشیند و نامِ بلند
#: (`MUSICBAZI_*`) روی سیم — تا API و کلاینت‌های موجود بی‌دردسر بمانند.
#:
#: **کوکیِ یوتیوب عمداً این‌جا نیست.** کوکی به حسابِ یوتیوبِ سازنده‌اش گره
#: خورده و درست کار کردنش به همان حساب و دستگاه بستگی دارد؛ شخصی‌کردنش یعنی
#: هر کاربر همان مراحلِ خطاپذیر را تکرار کند. یک فایل روی سرور می‌ماند و همه
#: از آن استفاده می‌کنند (به `ydl.auth_opts` نگاه کن).
KEYS = (
    "spotify_client_id",
    "spotify_client_secret",
    "genius_access_token",
    "gemini_api_key",
    "acoustid_key",
    "audd_token",
)

#: کوتاه → سراسری. همین نگاشت، مرزِ «چه چیزی شخصی است» را هم تعریف می‌کند:
#: هر کلیدی که این‌جا نیست (پروکسی، کوکیِ یوتیوب، توکنِ بات، Google OAuth،
#: SoundCloud) مالِ خودِ سرور است و کاربر اصلاً نمی‌بیندش.
ENV_OF: dict[str, str] = {key: f"MUSICBAZI_{key.upper()}" for key in KEYS}
ENV_OF["genius_access_token"] = "MUSICBAZI_GENIUS_ACCESS_TOKEN"

SHORT_OF: dict[str, str] = {env: short for short, env in ENV_OF.items()}

#: مقدارِ سراسریِ هر کلید، خوانده‌شده در لحظهِ پرسش (نه import). تست‌ها
#: `cfg.X` را monkeypatch می‌کنند و باید همین را ببینند.
_GLOBAL_OF = {
    "spotify_client_id": lambda: cfg.SPOTIFY_CLIENT_ID,
    "spotify_client_secret": lambda: cfg.SPOTIFY_CLIENT_SECRET,
    "genius_access_token": lambda: cfg.GENIUS_ACCESS_TOKEN,
    "gemini_api_key": lambda: cfg.GEMINI_API_KEY,
    "acoustid_key": lambda: cfg.ACOUSTID_KEY,
    "audd_token": lambda: cfg.AUDD_TOKEN,
}

# شمارنده‌ی تغییرِ هر حساب. کش‌هایی که مقدار را در حافظه نگه می‌دارند (توکنِ
# اسپاتیفای) با همین می‌فهمند که مقدارِ زیرشان عوض شده، بدونِ اینکه این ماژول
# بداند آن کش کجاست.
_versions: dict[str, int] = {}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def get(user_id: str, key: str) -> str | None:
    """مقدارِ خودِ کاربر؛ رشته‌ی خالی یعنی «صریحاً پاک شده»، `None` یعنی «ست نشده»."""
    raw = db.get_user_secret(user_id, key)
    return None if raw is None else raw


def effective(user_id: str, key: str) -> str | None:
    """
    مقداری که سرور باید همین حالا برای این کاربر به کار ببرد.

    fallback فقط برای مهمان است. حسابِ واردشده‌ای که کلید ندارد، کلید ندارد —
    نه اینکه بی‌صدا از کلیدِ اپراتور استفاده کند.
    """
    own = _clean(get(user_id, key))
    if own:
        return own
    # ردیفِ خالی هم یعنی «پاک شده» و باید fallback را ببندد
    if get(user_id, key) == "":
        return None
    if user_id == db.GUEST_ID:
        return _clean(_GLOBAL_OF[key]())
    return None


def set_many(user_id: str, values: dict[str, str], now: float) -> list[str]:
    """
    ذخیره‌ی مقدارها با نامِ بلند (`MUSICBAZI_*`). کلیدِ ناشناس نادیده گرفته
    نمی‌شود — خطا می‌دهد، تا اشتباهِ تایپی بی‌صدا کلیدی را از دست ندهد.
    """
    short = {}
    for env_key, value in values.items():
        name = SHORT_OF.get(env_key)
        if name is None:
            raise ValueError(env_key)
        short[name] = value
    changed = db.put_user_secrets(user_id, short, now)
    if changed:
        bump(user_id)
    return [ENV_OF[name] for name in changed]


def masked_map(user_id: str) -> dict[str, str]:
    """مقدارهایی که برای این حساب ست‌اند — فقط چهار رقمِ آخر، هرگز خودِ کلید."""
    out: dict[str, str] = {}
    for key in KEYS:
        value = effective(user_id, key)
        if value:
            out[ENV_OF[key]] = "…" + value[-4:] if len(value) > 8 else "•" * len(value)
    return out


def is_set(user_id: str, key: str) -> bool:
    return effective(user_id, key) is not None


def bump(user_id: str) -> None:
    """
    می‌گوید مقدارِ زیرِ پایِ یک حساب عوض شد.

    کش‌هایی که مقدار را در حافظه نگه می‌دارند خودشان `version` را در کلیدشان
    می‌آورند، پس این تابع تنها کاری که باید بکند شمردن است.
    """
    _versions[user_id] = _versions.get(user_id, 0) + 1


def version(user_id: str) -> int:
    return _versions.get(user_id, 0)


def reset() -> None:
    """فقط برای تست."""
    _versions.clear()


# ---------------------------------------------------------------- دسترسی‌های پرکاربرد


def spotify_pair(user_id: str) -> tuple[str, str] | None:
    cid = effective(user_id, "spotify_client_id")
    secret = effective(user_id, "spotify_client_secret")
    return (cid, secret) if cid and secret else None


def genius_token(user_id: str) -> str | None:
    return effective(user_id, "genius_access_token")


def gemini_key(user_id: str) -> str | None:
    return effective(user_id, "gemini_api_key")


def acoustid_key(user_id: str) -> str | None:
    return effective(user_id, "acoustid_key")


def audd_token(user_id: str) -> str | None:
    return effective(user_id, "audd_token")




# ---------------------------------------------------------------- زمینه‌ی کاربر
#
# زنجیره‌ی استریم و دانلود چند لایه است (روت → resolver → yt-dlp → thread) و
# بردنِ `user_id` در تمامِ امضاها یعنی هر لایه یک فرصتِ تازه برای فراموش‌کردن.
# این ContextVar همان زمینه را یک بار می‌نشاند و پایینِ زنجیره فقط `current()`
# صدا زده می‌شود.
#
# `asyncio.to_thread` زمینه را کپی می‌کند، پس به‌طور خودکار درست کار می‌کند.
# `ThreadPoolExecutor` دستی این کار را نمی‌کند — آن‌جا `copy_context().run(...)`
# لازم است (به `downloader.py` نگاه کن).

_current: ContextVar[str] = ContextVar("musicbazi_user", default=db.GUEST_ID)


def current() -> str:
    return _current.get()


@contextmanager
def user_scope(user_id: str) -> Iterator[None]:
    token = _current.set(user_id)
    try:
        yield
    finally:
        _current.reset(token)


def effective_current(key: str) -> str | None:
    """`effective()` برای کاربرِ زمینه — پرکاربردترین شکل در کدِ پایینِ زنجیره."""
    return effective(current(), key)
