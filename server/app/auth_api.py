"""
اندپوینت‌های حساب کاربری و ورود.

دومین `APIRouter` پروژه است (اولی `setup.py`). منطقِ رمز/توکن در `auth.py`
می‌نشیند و این‌جا فقط HTTP است: اعتبارسنجیِ ورودی، کوئری، و ساختنِ پاسخ.

ورود عمداً *اختیاری* است. هیچ اندپوینتی این‌جا وجودِ کاربر را الزام نمی‌کند
مگر آن‌هایی که با `Depends(current_user)` علامت خورده‌اند، و اپِ بدونِ ورود هم
کامل کار می‌کند — همان‌طور که تا امروز کار می‌کرد.
"""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from . import auth, avatar, db, reach
from .auth import GUEST
from .config import (
    AUTH_BASE_URL,
    GOOGLE_AUTH_URL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    INTRANET_DETAIL,
)
from .models import (
    AuthCredentials,
    AuthLogin,
    AuthProfilePatch,
    AuthProviders,
    AuthSession,
    AuthUser,
    MediaToken,
)

router = APIRouter()
log = logging.getLogger(__name__)

# stateِ ورودِ گوگل — کوتاه‌عمر و در حافظه، مثل کدِ وصل‌شدنِ تلگرام
# (`telegram.py`). گم‌شدنش با ری‌استارت بی‌ضرر است: کاربر یک دکمه دوباره می‌زند.
#
# هر ورودی `(زمانِ ساخت، مقصد، ریشه‌ای که با آن شروع شد)` است. ریشه اینجا
# نگه داشته می‌شود چون `redirect_uri` در تبادلِ کد باید *مو‌به‌مو* همانی باشد
# که در درخواستِ اول به گوگل داده شد — و بسته به اینکه کاربر از دامنه آمده یا
# از `localhost`، فرق می‌کند.
_STATE_TTL = 10 * 60
_states: dict[str, tuple[float, str, str]] = {}


def _prune_states(now: float) -> None:
    for key in [k for k, (born, _, _) in _states.items() if now - born > _STATE_TTL]:
        del _states[key]


def reset() -> None:
    """فقط برای تست."""
    _states.clear()


# ---------------------------------------------------------------- کمکی


def _public(row) -> AuthUser:
    """ردیفِ دیتابیس → ساختارِ عمومی. تنها جایی که هشِ رمز دور انداخته می‌شود."""
    return AuthUser(
        id=row["id"],
        kind=row["kind"],
        username=row["username"],
        displayName=auth.display_name_of(row),
        email=row["email"],
        avatarUrl=avatar.public_url(row),
        hasPassword=bool(row["password_hash"]),
        createdAt=float(row["created_at"]),
    )


def _session_response(row) -> AuthSession:
    token, expires = auth.mint_session(row["id"])
    return AuthSession(token=token, expiresAt=expires, user=_public(row))


def _user_or_401(user_id: str):
    row = db.user_by_id(user_id)
    if row is None:
        raise auth.AuthError(401, "این حساب دیگر وجود ندارد")
    return row


# ---------------------------------------------------------------- وضعیت


@router.get("/api/auth/providers", response_model=AuthProviders)
async def providers() -> AuthProviders:
    """
    کدام راه‌های ورود روی این سرور زنده‌اند.

    فرانت با این پاسخ تصمیم می‌گیرد دکمه‌ی گوگل را نشان بدهد یا نه — بدونش
    کاربری که کلید گوگل ندارد، دکمه‌ای می‌بیند که همیشه خطا می‌دهد.
    """
    if not auth.google_configured():
        return AuthProviders(google=False, googleReason="not_configured")
    if not auth.google_callback_is_reachable():
        # گوگل برای redirect فقط https را قبول می‌کند؛ روی آدرسِ LAN درخواستِ
        # کاربر به صفحه‌ی خطای گوگل می‌رسد و هیچ‌وقت برنمی‌گردد
        return AuthProviders(google=False, googleReason="needs_https")
    return AuthProviders(google=True)


@router.get("/api/auth/me", response_model=AuthUser)
async def me(user_id: str = Depends(auth.current_user)) -> AuthUser:
    return _public(_user_or_401(user_id))


@router.patch("/api/auth/me", response_model=AuthUser)
async def update_me(
    patch: AuthProfilePatch,
    user_id: str = Depends(auth.current_user),
) -> AuthUser:
    """
    نامِ نمایشی و نامِ کاربری.

    نامِ کاربری اختیاری است و می‌شود پاکش کرد (`username: ""`) — کاربری که با
    گوگل وارد شده ممکن است اصلاً نخواهد یکی داشته باشد.
    """
    row = _user_or_401(user_id)

    if patch.username is not None:
        wanted = patch.username.strip()
        if not wanted:
            db.set_user_username(user_id, None)
        else:
            name = auth.normalize_username(wanted)
            existing = db.user_by_username(name)
            if existing is not None and existing["id"] != user_id:
                raise auth.AuthError(409, "این نام کاربری قبلاً گرفته شده")
            db.set_user_username(user_id, name)

    if patch.displayName is not None:
        db.set_user_display_name(user_id, patch.displayName.strip()[:60])

    return _public(_user_or_401(user_id))


@router.post("/api/auth/logout")
async def logout() -> dict:
    """
    توکنِ خودبسنده است، پس «خروج» سمتِ سرور کاری برای کردن ندارد.

    اندپوینت وجود دارد تا کلاینت یک نقطه‌ی پایان داشته باشد و اگر روزی باطل‌کردنِ
    واقعی لازم شد، جای اضافه‌کردنش همین باشد نه دوباره‌نویسیِ فرانت.
    """
    return {"ok": True}


# ---------------------------------------------------------------- ورودِ محلی


@router.post("/api/auth/local/register", response_model=AuthSession)
async def register(creds: AuthCredentials) -> AuthSession:
    """
    ساختِ حسابِ محلی.

    ثبت‌نام باز است (تصمیمِ کاربر). روی شبکه‌ی خانه بی‌ضرر است؛ اگر روزی سرور
    روی تونل باز شد، بستنش یک چکِ ساده همین‌جاست.
    """
    username = auth.normalize_username(creds.username)
    auth.check_password_strength(creds.password)

    if db.user_by_username(username) is not None:
        raise auth.AuthError(409, "این نام کاربری قبلاً گرفته شده")

    row = db.create_user(
        uuid.uuid4().hex[:12],
        "local",
        username=username,
        display_name=(creds.displayName or "").strip()[:60] or username,
        password_hash=auth.hash_password(creds.password),
    )
    return _session_response(row)


@router.post("/api/auth/local/login", response_model=AuthSession)
async def login(creds: AuthLogin) -> AuthSession:
    """
    ورودِ محلی — تنها راهِ ورودِ تازه وقتی اینترنتِ بین‌الملل قطع است.

    نامِ کاربریِ ناموجود و رمزِ غلط یک پیام می‌گیرند: تفکیکشان به مهاجم
    می‌گوید کدام نام‌های کاربری وجود دارند.
    """
    row = db.user_by_username(creds.username)
    if row is None or not auth.verify_password(creds.password, row["password_hash"]):
        raise auth.AuthError(401, "نام کاربری یا رمز اشتباه است")
    if auth.is_guest(row["id"]):
        # ردیفِ مهمان رمز ندارد؛ رسیدن به این‌جا یعنی چیزی عوض شده
        raise auth.AuthError(401, "نام کاربری یا رمز اشتباه است")
    return _session_response(row)


# ---------------------------------------------------------------- توکنِ مدیا


@router.post("/api/auth/media", response_model=MediaToken)
async def media_token(user_id: str = Depends(auth.current_user)) -> MediaToken:
    """
    توکنِ کوتاه‌عمر برای آدرس‌هایی که هدر نمی‌فرستند.

    `<audio src>`، `<img src>` و `EventSource` از کنترلِ ما بیرونند. توکنِ
    نشست نمی‌تواند در URL برود (ماه‌ها زنده است و در لاگ می‌نشیند)، پس این
    توکنِ یک‌ساعته ساخته می‌شود.
    """
    token, expires = auth.mint_media(user_id)
    return MediaToken(token=token, expiresAt=expires)


# ---------------------------------------------------------------- گوگل


@router.get("/api/auth/google/start")
async def google_start(request: Request, return_to: str = "/") -> RedirectResponse:
    """
    کاربر را به گوگل می‌فرستد.

    `return_to` نسبی نگه داشته می‌شود (بدونِ دامنه) تا کسی نتواند با دست‌کاریِ
    پارامتر، کاربر را بعدِ ورود به سایتِ دیگری پرت کند.
    """
    if not auth.google_configured():
        raise HTTPException(400, "ورود با گوگل روی این سرور تنظیم نشده است")

    # ریشه از روی همان درخواست انتخاب می‌شود تا هم دامنه و هم `localhost` کار
    # کنند؛ گوگل `redirect_uri` را دقیق مچ می‌کند و این دو URI جدا هستند.
    origin = auth.pick_google_origin(request)
    if origin is None or not auth.google_is_reachable_origin(origin):
        raise HTTPException(
            400,
            "ورود با گوگل به آدرسِ https نیاز دارد. آدرسِ سرور را در تنظیمات به دامنه‌ی تونل تغییر بده یا از حساب محلی استفاده کن",
        )
    if not reach.online():
        # صفحه‌ی گوگل اصلاً باز نمی‌شود؛ فرستادنِ کاربر به آن فقط یک تایم‌اوت است
        raise HTTPException(503, INTRANET_DETAIL)

    now = time.time()
    _prune_states(now)
    state = secrets.token_urlsafe(24)
    _states[state] = (now, return_to if return_to.startswith("/") else "/", origin)

    params = urlencode(
        {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": auth.google_redirect_uri(origin),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            # کاربری که چند حسابِ گوگل دارد باید بتواند انتخاب کند
            "prompt": "select_account",
        }
    )
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}", status_code=302)


@router.get("/api/auth/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """
    بازگشت از گوگل: کد را با رازِ سرور مبادله می‌کند و کاربر را می‌سازد.

    تأییدِ `id_token` لازم نیست چون کد با `client_secret` سمتِ سرور مبادله
    می‌شود — پاسخِ گوگل از کانالِ خودمان می‌آید و کسی نمی‌تواند جعلش کند. یک
    فراخوانیِ `userinfo` با همان توکنِ تازه، پروفایل را می‌دهد و تمام.
    """
    # ریشه پیش از هر کاری از state خوانده می‌شود تا حتی مسیرِ خطا هم کاربر را به
    # همان جایی برگرداند که از آن آمده، نه به یک ریشه‌ی ثابتِ احتملاً غلط.
    stored = _states.get(state) if state else None
    origin = stored[2] if stored else (auth.pick_google_origin(request) or "")

    if error:
        # کاربر روی صفحه‌ی گوگل «انصراف» زده — خطا نیست، انتخاب است
        return _back("denied", origin=origin)
    if not code or not state:
        return _back("invalid", origin=origin)

    now = time.time()
    _prune_states(now)
    stored = _states.pop(state, None)
    if stored is None:
        # stateِ یک‌بارمصرف: یا منقضی شده یا قبلاً خرج شده (تلاشِ بازپخش)
        return _back("expired", origin=origin)
    return_to = stored[1]
    origin = stored[2]

    try:
        profile = await _exchange(request, code, origin)
        row = await _upsert_google(request, profile)
    except httpx.HTTPError as exc:
        log.warning("تبادلِ کد گوگل شکست خورد: %s", exc)
        return _back("unreachable", origin=origin)
    except ValueError as exc:
        # پروفایلِ ناقص یا پاسخِ ناخوانا — نه خطای سرور، نه «شبکه نیست»
        log.warning("پاسخِ پروفایلِ گوگل ناخوانا بود: %s", exc)
        return _back("invalid", origin=origin)

    token, _ = auth.mint_session(row["id"])
    return _back(None, token=token, to=return_to, origin=origin)


async def _exchange(request: Request, code: str, origin: str) -> dict:
    """کد → توکنِ دسترسی → پروفایل."""
    client: httpx.AsyncClient = request.app.state.http
    res = await client.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            # همان ریشه‌ای که در `start` فرستادیم — گوگل این را مچ می‌کند
            "redirect_uri": auth.google_redirect_uri(origin),
            "grant_type": "authorization_code",
        },
    )
    res.raise_for_status()
    access_token = res.json().get("access_token")
    if not access_token:
        raise ValueError("پاسخِ گوگل توکنِ دسترسی نداشت")

    info = await client.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    info.raise_for_status()
    return info.json()


async def _upsert_google(request: Request, profile: dict):
    """
    کاربرِ گوگل را می‌سازد یا پیدایش می‌کند.

    کلیدِ تشخیص `sub` است نه ایمیل: ایمیل در گوگل قابلِ تغییر است و دو حسابِ
    متفاوت هم می‌توانند ایمیلِ یکسانی داشته باشند. `sub` تا ابد ثابت است.
    """
    sub = str(profile.get("sub") or "").strip()
    if not sub:
        raise ValueError("پروفایلِ گوگل شناسه نداشت")

    existing = db.user_by_google_sub(sub)
    if existing is None:
        row = db.create_user(
            uuid.uuid4().hex[:12],
            "google",
            display_name=(profile.get("name") or "").strip()[:60],
            email=profile.get("email"),
            google_sub=sub,
        )
    else:
        row = existing
        # نامِ نمایشی و ایمیلِ گوگل ممکن است عوض شده باشند؛ نامِ کاربریِ
        # انتخابیِ خودِ کاربر ولی دست‌نخورده می‌ماند
        if not row["username"]:
            name = (profile.get("name") or "").strip()[:60]
            if name:
                db.set_user_display_name(row["id"], name)

    # عکسِ گوگل: یک‌بار روی دیسک می‌آید تا موقعِ قطعیِ بین‌الملل هم دیده شود.
    # شکستش ورود را نمی‌شکند — فرانت همان آدرسِ گوگل را نشان می‌دهد.
    await avatar.import_google(request.app.state.http, row, profile.get("picture"))

    fresh = db.user_by_id(row["id"])
    assert fresh is not None
    return fresh


def _back(
    status: str | None, token: str | None = None, to: str = "/", origin: str = ""
) -> RedirectResponse:
    """
    بازگشت به فرانت — با fragment، نه query.

    توکن در `#auth=...` می‌آید چون مرورگر fragment را به سرور نمی‌فرستد: نه در
    لاگِ nginx می‌نشیند، نه در `Referer` به سایتِ بعدی می‌رود.

    `origin` همان ریشه‌ای است که کاربر ورود را از آن شروع کرد، تا بازگشت به
    همان دامنه/پورت باشد (کوکی و ذخیره‌سازی مرورگر به مبدأ گره خورده‌اند).
    """
    base = origin or AUTH_BASE_URL or ""
    if status:
        return RedirectResponse(f"{base}/?login=1#auth_error={quote(status)}", status_code=302)
    return RedirectResponse(f"{base}{to}#auth={quote(token or '')}", status_code=302)


# ---------------------------------------------------------------- آواتار


@router.post("/api/auth/avatar", response_model=AuthUser)
async def upload_avatar(
    request: Request,
    file: UploadFile,
    user_id: str = Depends(auth.current_user),
) -> AuthUser:
    """آپلودِ عکسِ پروفایل — اعتبارسنجی و کوچک‌سازی در `avatar.py`."""
    await avatar.store_upload(request.app.state.http, user_id, file)
    return _public(_user_or_401(user_id))


@router.delete("/api/auth/avatar", response_model=AuthUser)
async def delete_avatar(user_id: str = Depends(auth.current_user)) -> AuthUser:
    await avatar.remove(user_id)
    return _public(_user_or_401(user_id))


__all__ = ["router", "reset", "GUEST"]
