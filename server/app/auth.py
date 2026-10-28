"""
احراز هویت — تنهای ماژولی که رمز، توکن و امضا می‌شناسد.

سه تصمیم که این فایل را این‌شکل کرده:

۱. **بدونِ وابستگی.** سرور باید داخلِ Termux هم بالا بیاید و آن‌جا نصبِ بسته‌ی
   کامپایل‌شده (bcrypt، cryptography، Pillow) یا شکست می‌خورد یا نیم ساعت طول
   می‌کشد. پس هش رمز با `hashlib.scrypt` است (خودِ stdlib، مقاوم به GPU) و
   توکن با `hmac` امضا می‌شود — نه JWT، چون JWT فقط همین را با یک وابستگیِ
   تازه می‌فروشد.

۲. **توکنِ خودبسنده، بدونِ جدولِ نشست.** `<user_id>.<exp>.<امضا>` — اعتبارش از
   خودش می‌آید، پس نه ستونِ تازه لازم است نه کوئریِ اضافه سرِ هر درخواست. ته‌مانده‌اش
   این است که «خروج» واقعاً فقط دور انداختنِ توکن سمتِ کلاینت است. برای پروژه‌ی
   شخصی روی شبکه‌ی خانه می‌ارزد؛ اگر روزی «خروجِ همه‌ی دستگاه‌ها» خواستی، یک
   `token_version` روی جدولِ کاربران کافی است.

۳. **دو نوع توکن با پیشوندِ متفاوت.** توکنِ نشست ماه‌ها زنده است و توکنِ مدیا یک
   ساعت؛ اگر یکی به‌جای دیگری قبول شود، یا یک URLِ نشتیِ مدیا دسترسیِ کامل
   می‌دهد یا پخش زودتر از موعد قطع می‌شود. پیشوند، جا‌به‌جایی را ناممکن می‌کند.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from typing import Final

from fastapi import HTTPException, Request

from . import db
from .config import AUTH_MEDIA_TTL, AUTH_SECRET_PATH, AUTH_SESSION_DAYS

# کاربری که همه‌ی درخواست‌های بی‌توکن به آن تفسیر می‌شوند — یعنی «مهمان».
#
# یک ردیفِ *واقعی* در دیتابیس است، نه حالتِ خاص. این‌طور هیچ کوئری‌ای شاخه‌ی
# «کاربر ندارد» لازم نمی‌شود و داده‌ی نسخه‌ی تک‌کاربره هم بدونِ کدِ مهاجرتِ جدا
# به همین کاربر می‌رسد.
GUEST: Final = "local"

# پارامترهای scrypt. `n=2**14` یعنی ~۱۶ مگابایت حافظه برای هر هش — برای یک
# سرورِ خانگی بی‌هزینه، و برای حمله‌ی سخت‌افزاری گران.
_SCRYPT_N: Final = 2**14
_SCRYPT_R: Final = 8
_SCRYPT_P: Final = 1
_SCRYPT_DKLEN: Final = 32

_SESSION: Final = "s"
_MEDIA: Final = "m"

_secret_cache: bytes | None = None

# نامِ کاربری در UI و در URL می‌آید، پس عمداً تنگ است: بدونِ فاصله، بدونِ
# کاراکترِ کنترلی، بدونِ چیزی که بشود با `@` قاطی کرد.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,24}$")
MIN_PASSWORD = 8


class AuthError(HTTPException):
    """خطای احراز هویت با پیامِ فارسیِ آماده‌ی نمایش.

    `HTTPException`ِ خالی همین کار را می‌کند؛ زیرکلاس فقط برای این است که
    صدازننده بتواند این‌ها را از خطاهای دیگرِ اندپوینت جدا کند.
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(status_code=status, detail=detail)


# ---------------------------------------------------------------- رازِ امضا


def secret() -> bytes:
    """
    رازِ امضای توکن‌ها — یک‌بار ساخته و بعد همیشه خوانده می‌شود.

    اگر این راز گم شود، همه‌ی نشست‌های زنده باطل می‌شوند؛ اگر جعل شود، هر کسی
    می‌تواند توکنِ هر کاربری را بسازد. پس روی دیسک و زیرِ `DATA_DIR` است (که در
    داکر volume است و در Termux زیرِ `$HOME/musicbazi`) ولی هرگز جایی فرستاده
    نمی‌شود.
    """
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    path = AUTH_SECRET_PATH
    try:
        if path.exists():
            raw = path.read_bytes()
            if len(raw) >= 32:
                _secret_cache = raw
                return raw
        # 0600: این فایل هم‌ارزِ کلیدِ امضاست، نه یک فایلِ تنظیمات
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = secrets.token_bytes(48)
        path.write_bytes(raw)
        try:
            path.chmod(0o600)
        except OSError:
            # ویندوز و بعضی فایل‌سیستم‌ها chmod را جدی نمی‌گیرند؛ نبودش
            # نباید جلوی بالا آمدنِ سرور را بگیرد
            pass
        _secret_cache = raw
        return raw
    except OSError as exc:
        # شکستِ بی‌صدا این‌جا بدترین حالت است: رازِ تازه در هر ری‌استارت یعنی
        # کاربر هر بار از حساب بیرون می‌افتد و هیچ‌کس نمی‌فهمد چرا.
        raise RuntimeError(
            f"نتوانستم رازِ احراز هویت را در {path} بنویسم — مطمئن شو پوشه‌ی داده‌ها قابلِ نوشتن است"
        ) from exc


def reset_secret_cache() -> None:
    """فقط برای تست."""
    global _secret_cache
    _secret_cache = None


# ---------------------------------------------------------------- رمز


def hash_password(password: str) -> str:
    """
    `scrypt$N$r$p$<نمک>$<هش>` — پارامترها داخلِ خودِ رشته می‌آیند.

    اگر روزی غلظتِ پیش‌فرض بالا برود، هش‌های قدیمی هم‌چنان کار می‌کنند چون
    پارامترِ زمانِ ساختشان همراهشان است، نه یک ثابتِ سراسری.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """
    مقایسه با `compare_digest` — نه `==`.

    هر خرابیِ قالب `False` می‌دهد، نه استثنا: ردیفِ نیمه‌ساخته یا مقدارِ خالی
    باید «رمز غلط» باشد، نه خطای ۵۰۰ روی صفحه‌ی ورود.
    """
    if not stored or not password:
        return False
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, actual)


def check_password_strength(password: str) -> None:
    """قاعده‌ی رمز در یک جا، تا UI و API یک چیز بگویند."""
    if len(password) < MIN_PASSWORD:
        raise AuthError(400, f"رمز باید حداقل {MIN_PASSWORD} کاراکتر باشد")


def normalize_username(raw: str) -> str:
    """نامِ کاربری را تمیز می‌کند یا خطای فارسی می‌دهد."""
    name = (raw or "").strip()
    if not _USERNAME_RE.match(name):
        raise AuthError(
            400,
            "نام کاربری باید ۳ تا ۲۴ کاراکتر باشد و فقط از حروف انگلیسی، عدد، نقطه، خط تیره و زیرخط تشکیل شود",
        )
    return name


# ---------------------------------------------------------------- توکن


def _b64(raw: bytes) -> str:
    """base64 بیِ `=` — تا در URL و query سالم بماند."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sign(kind: str, payload: str) -> str:
    return _b64(hmac.new(secret(), f"{kind}:{payload}".encode("utf-8"), hashlib.sha256).digest())


def _mint(kind: str, user_id: str, ttl: int) -> tuple[str, float]:
    expires = time.time() + ttl
    payload = f"{user_id}:{int(expires)}"
    return f"{payload}.{_sign(kind, payload)}", expires


def _read(kind: str, token: str | None) -> str | None:
    """
    کاربرِ داخلِ توکن، یا `None` اگر جعلی/منقضی/بی‌ربط بود.

    هر سه حالت عمداً یک جواب دارند: صدازننده نباید از روی پیامِ خطا بفهمد
    توکنِ «تقریباً درست» داده است یا نه.
    """
    if not token:
        return None
    try:
        payload, signature = token.rsplit(".", 1)
        user_id, raw_exp = payload.rsplit(":", 1)
        expires = int(raw_exp)
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(kind, payload), signature):
        return None
    if expires <= time.time():
        return None
    return user_id or None


def mint_session(user_id: str, days: int | None = None) -> tuple[str, float]:
    """(توکن، زمانِ انقضا) — برای فرستادن به کلاینت."""
    return _mint(_SESSION, user_id, (days if days is not None else AUTH_SESSION_DAYS) * 86400)


def read_session(token: str | None) -> str | None:
    return _read(_SESSION, token)


def mint_media(user_id: str, ttl: int | None = None) -> tuple[str, float]:
    return _mint(_MEDIA, user_id, ttl if ttl is not None else AUTH_MEDIA_TTL)


def read_media(token: str | None) -> str | None:
    return _read(_MEDIA, token)


# ---------------------------------------------------------------- وابستگی‌ها


def bearer(request: Request) -> str | None:
    """
    توکنِ نشست از هدرِ `Authorization`.

    کوکی عمداً کنار گذاشته شده: در اپ اندروید صفحه از `https://localhost` سرو
    می‌شود ولی API یک آدرسِ مطلقِ دیگر است، یعنی cross-origin — و کوکیِ
    cross-origin هم به `SameSite=None; Secure` نیاز دارد هم در خیلی از
    WebViewها بی‌صدا دور انداخته می‌شود. هدر چنین مشکلی ندارد.
    """
    raw = request.headers.get("authorization") or ""
    scheme, _, value = raw.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def _known(user_id: str | None) -> str | None:
    """توکنِ امضاشده ولی متعلق به کاربری که دیگر نیست — نامعتبر حساب می‌شود."""
    if not user_id:
        return None
    return user_id if db.user_by_id(user_id) is not None else None


async def optional_user(request: Request) -> str:
    """
    کاربرِ درخواست، یا `GUEST` اگر توکنی نبود.

    این همان چیزی است که «ورود اختیاری» را ممکن می‌کند: اندپوینت‌های داده این
    وابستگی را می‌گیرند و برایشان مهم نیست کاربر وارد شده یا نه.
    """
    return _known(read_session(bearer(request))) or GUEST


async def current_user(request: Request) -> str:
    """کاربرِ وارد‌شده — وگرنه ۴۰۱."""
    user_id = _known(read_session(bearer(request)))
    if user_id is None:
        raise AuthError(401, "برای این کار باید وارد حساب شوی")
    return user_id


async def media_user(request: Request) -> str:
    """
    کاربرِ یک درخواستِ مدیا — که هدر نمی‌فرستد.

    `<audio src>`، `<img src>` و `EventSource` هر سه از کنترلِ ما بیرونند و
    نمی‌شوند وادارشان کرد `Authorization` بفرستند. پس توکنِ کوتاه‌عمرِ مدیا در
    query می‌آید. اگر توکنِ نشستی هم در هدر بود (مثل درخواستِ fetch عادی)
    همان قبول است.
    """
    from_query = _known(read_media(request.query_params.get("mt")))
    if from_query is not None:
        return from_query
    return _known(read_session(bearer(request))) or GUEST


def is_guest(user_id: str) -> bool:
    return user_id == GUEST


# ---------------------------------------------------------------- گوگل


def google_configured() -> bool:
    from .config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def google_origins() -> tuple[str, ...]:
    """همه‌ی ریشه‌های مجازِ ورود — اصلی اول، بدونِ تکرار."""
    from .config import AUTH_ALLOWED_ORIGINS, AUTH_BASE_URL

    seen: dict[str, None] = {}
    for origin in (AUTH_BASE_URL, *AUTH_ALLOWED_ORIGINS):
        if origin:
            seen.setdefault(origin.rstrip("/"), None)
    return tuple(seen)


def google_is_reachable_origin(origin: str) -> bool:
    """
    آیا گوگل می‌تواند به این ریشه برگردد؟

    گوگل برای redirect فقط `https` یا `localhost` را قبول می‌کند. روی
    `http://192.168.x.x` ورودِ گوگل ذاتاً ممکن نیست — و بهتر است دکمه‌اش در UI
    با یک توضیحِ کوتاه غیرفعال شود تا اینکه کاربر به صفحه‌ی خطای گوگل برود.
    """
    base = origin.lower()
    return (
        base.startswith("https://")
        or base.startswith("http://localhost")
        or base.startswith("http://127.0.0.1")
    )


def pick_google_origin(request) -> str | None:
    """
    ریشه‌ای که این درخواست باید با آن وارد شود.

    گوگل `redirect_uri` را *دقیق* مچ می‌کند، پس هم‌زمانیِ دامنه و `localhost`
    یعنی دو URI ثبت‌شده و انتخابِ درست در هر درخواست. `Origin` مرورگر همان
    چیزی است که کاربر واقعاً از آن آمده، پس اولین ریشه‌ای که هم مجاز باشد و
    هم با آن بخواند برنده است.

    **هرگز از هدر کورکورانه استفاده نمی‌شود:** فقط مقادیر `google_origins()`.
    وگرنه مهاجم با فرستادنِ `Origin` دلخواه، کاربر را به دامنه‌ی خودش می‌کشاند
    و کدِ ورود را می‌قاپد.
    """
    allowed = google_origins()
    request_origin = (request.headers.get("origin") or "").rstrip("/")
    if request_origin and request_origin in allowed:
        return request_origin
    # بدونِ `Origin` (ناوبریِ سطح‌بالا همیشه نمی‌فرستد) به ریشه‌ی اصلی برمی‌گردیم
    for origin in allowed:
        if google_is_reachable_origin(origin):
            return origin
    return allowed[0] if allowed else None


def google_redirect_uri(origin: str | None = None) -> str:
    from .config import AUTH_BASE_URL

    base = origin or AUTH_BASE_URL
    return f"{base}/api/auth/google/callback"


def google_callback_is_reachable() -> bool:
    """آیا *هر* ریشه‌ای هست که گوگل بتواند به آن برگردد؟"""
    return any(google_is_reachable_origin(origin) for origin in google_origins())


def display_name_of(row) -> str:
    """نامِ نمایشی، با fallback به نامِ کاربری و بعد ایمیل."""
    return (row["display_name"] or "").strip() or (row["username"] or "") or (row["email"] or "") or "کاربر"
