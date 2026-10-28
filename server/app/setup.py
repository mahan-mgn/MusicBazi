"""
راه‌اندازیِ شخصیِ هر حساب — ویزاردی که کلیدها را از کاربر می‌گیرد و *قبل از
ذخیره* آزمایشان می‌کند.

    GET  /api/setup           چه چیزی برای *این حساب* تنظیم است + وضعیتِ سرور
    POST /api/setup/test      یک کلید را با سرویسِ خودش چک کن (بدونِ ذخیره)
    POST /api/setup/save      در دیتابیسِ همین حساب بنویس
    POST /api/setup/cookies   فایل کوکیِ یوتیوبِ همین حساب را بگیر و ذخیره کن

**چرا دیتابیس و نه `.env`:** پروژه روی دامنه منتشر می‌شود. یک `.env` سراسری یعنی
کلیدِ اسپاتیفای و توکنِ Geniusِ صاحبِ سرور در اختیارِ هر کسی که ثبت‌نام کند، و
یک پرچمِ «ستاپ تمام شد» که با اولین کاربر برای همه بسته می‌شود. این‌جا هر ردیف
مالِ یک `user_id` است (جدولِ `user_secrets`، منطق در `credentials.py`).

**چرا دیگر ری‌استارت لازم نیست:** نسخه‌ی `.env` مجبور بود سرور را دوباره بالا
بیاورد، چون `config.py` مقدارها را هنگامِ import قفل می‌کرد و ~۱۵ ماژول آن‌ها
را در سطحِ ماژول نگه می‌داشتند. حالا هر مصرف‌کننده مقدار را زنده از
`credentials.effective(user_id, …)` می‌پرسد، پس ذخیره یعنی «از همین درخواستِ
بعدی کار می‌کند».

**احراز هویت:** `save`/`test`/`cookies` حسابِ واردشده لازم دارند. روی شبکه‌ی
خانه بی‌ضرر بود که نبود؛ روی دامنه یعنی هر بازدیدکننده‌ای می‌توانست کوکی و
کلیدِ حسابِ دیگری را عوض کند. `GET` اختیاری است چون صفحه باید برای مهمان هم
وضعیتِ سرور را نشان بدهد.

کلیدهایی که این‌جا **نیستند** عمداً مالِ خودِ سرورند: توکنِ باتِ تلگرام (یک
بات، یک پروسه)، Google OAuth، پروکسی، SoundCloud و `COOKIES_BROWSER`. پروکسی
اگر آزاد بود به یک SSRF تبدیل می‌شد که سرور را به هر مقصدِ داخلی می‌رساند.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from . import auth
from . import config as cfg
from . import credentials
from . import db
from . import reach
from . import telegram
from .config import DATA_DIR

router = APIRouter()
log = logging.getLogger(__name__)

#: کلیدهایی که ویزاردِ *شخصی* اجازه دارد بنویسد. نامِ بلند روی سیم می‌ماند تا
#: کلاینت‌ها و تست‌های موجود بی‌دردسر باشند؛ نگاشت به نامِ کوتاهِ دیتابیس در
#: `credentials.ENV_OF` است.
ALLOWED_KEYS = frozenset(credentials.ENV_OF.values())

#: فایلِ کوکیِ یوتیوب — **مشترک میانِ همه‌ی حساب‌ها**.
#:
#: برخلاف کلیدهای API، کوکی به حسابِ یوتیوبِ سازنده‌اش گره خورده و درست کار
#: کردنش به همان حساب و دستگاه بستگی دارد؛ وادار کردنِ هر کاربر به گرفتنِ
#: کوکیِ خودش یعنی تکرارِ همان مراحلِ خطاپذیر و اغلب «یوتیوب کار نمی‌کند».
#: یک فایل روی سرور، همه از آن استفاده می‌کنند.
COOKIE_PATH = DATA_DIR / "cookies" / "youtube.txt"


def cookies_path(user_id: str) -> Path:  # noqa: ARG001 — امضای مشترک با فراخوان‌ها
    return COOKIE_PATH


# ---------------------------------------------------------------- وضعیت


def _server_env() -> dict:
    """
    چیزهایی که به سرور مربوط‌اند، نه به حساب — و کاربر نمی‌تواند عوضشان کند.
    فقط برای این نشان داده می‌شوند که کاربر بفهمد چرا مثلاً یوتیوب جواب نمی‌دهد.
    """
    return {
        "ffmpeg": bool(cfg.FFMPEG_LOCATION),
        "jsRuntime": cfg.JS_RUNTIME or None,
        "potoken": bool(cfg.POT_BASE_URL or cfg.POT_SERVER_HOME),
        "proxy": bool(cfg.PROXY),
        # کوکی مشترک است، پس وضعیتش «وضعیتِ سرور» است نه یک کلیدِ شخصی
        "cookies": cookies_path("").exists() or bool(os.getenv("MUSICBAZI_COOKIES_BROWSER")),
        "internet": reach.snapshot()["online"],
        "container": Path("/.dockerenv").exists() or bool(os.getenv("RAILWAY_ENVIRONMENT")),
    }


def _done(user_id: str) -> bool:
    """
    آیا ویزاردِ این حساب باید بسته بماند؟

    حسابِ واقعی: فقط اگر خودش یک‌بار تمام یا رد کرده باشد. ذخیره‌کردنِ کلید
    به‌تنهایی کافی نیست — `done` یعنی «کاربر این مرحله را دیده»، نه «کلید دارد».

    مهمان: همان قاعده‌ی تک‌کاربره‌ی قبلی حفظ می‌شود — پرچمِ `MUSICBAZI_SETUP_DONE`
    یا وجودِ هر کلیدِ سراسری. بدونِ این، نصبِ موجودی که `.env` پرش را از قبل
    دارد، بعدِ ارتقا ناگهان «اول تنظیم کن» می‌گوید. رد کردنِ ویزارد برای مهمان
    در `MUSICBAZI_SETUP_DONE`ی خودِ `.env` می‌نشیند (تنها جایی که `setup_done_at`
    نمی‌تواند جواب بدهد، چون مهمان با هر مرورگری یک ردیف است).
    """
    if db.setup_done_at(user_id) is not None:
        return True
    if user_id != db.GUEST_ID:
        return False
    return bool(os.getenv("MUSICBAZI_SETUP_DONE")) or any(
        credentials.effective(user_id, key) for key in credentials.KEYS
    )


def _mark_guest_done() -> None:
    """
    رد کردنِ ویزارد برای مهمان.

    تنها جایی که یک مقدار باید در `.env` بنشیند: ردیفِ مهمان بینِ همه‌ی
    بازدیدکننده‌های بی‌حساب مشترک است، پس `setup_done_at` یعنی «اولین نفر برای
    همه رد کرد». پرچم در `.env` دقیقاً همان معنای تک‌کاربره‌ی قبلی را حفظ می‌کند.
    """
    path = DATA_DIR / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for i, line in enumerate(lines):
        if re.match(r"^\s*(?:export\s+)?MUSICBAZI_SETUP_DONE\s*=", line):
            lines[i] = "MUSICBAZI_SETUP_DONE=1"
            break
    else:
        lines.append("MUSICBAZI_SETUP_DONE=1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    os.environ["MUSICBAZI_SETUP_DONE"] = "1"


class TestRequest(BaseModel):
    key: str
    values: dict[str, str] = {}


class SaveRequest(BaseModel):
    values: dict[str, str] = {}
    # رد کردنِ ویزارد هم همین را True می‌گذارد تا دوباره باز نشود
    done: bool = False


# ---------------------------------------------------------------- آزمودن
#
# هر آزمایِش یک درخواستِ کوچک به همان سرویس است با مقداری که کاربر *همین حالا*
# تایپ کرده — نه چیزی که ذخیره شده. دلیلش: یک رقمِ اشتباهی در Client Secret
# بعداً به‌شکلِ «اسپاتیفای کار نمی‌کند» ظاهر می‌شود و فهمیدنش غیرممکن است.
#
# مقدارهایی که کاربر تایپ نکرده از خودِ حسابش می‌آید، نه از `.env` سراسری:
# وگرنه تستِ یک حسابِ تازه با کلیدِ اپراتور «موفق» می‌شد و کاربر کلیدِ خرابش را
# ذخیره می‌کرد.


def _value(v: dict[str, str], user_id: str, key: str) -> str:
    return (v.get(credentials.ENV_OF[key]) or credentials.effective(user_id, key) or "").strip()


async def _test_spotify(client: httpx.AsyncClient, v: dict[str, str], uid: str) -> tuple[bool, str]:
    cid = _value(v, uid, "spotify_client_id")
    secret = _value(v, uid, "spotify_client_secret")
    if not cid or not secret:
        return False, "هر دو فیلد لازم است"
    res = await client.post(
        cfg.SPOTIFY_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(cid, secret),
        timeout=15.0,
    )
    if res.status_code == 200 and res.json().get("access_token"):
        return True, "توکن گرفته شد"
    if res.status_code in (400, 401):
        return False, "Client ID یا Secret غلط است"
    return False, f"پاسخ {res.status_code}"


async def _test_genius(client: httpx.AsyncClient, v: dict[str, str], uid: str) -> tuple[bool, str]:
    token = _value(v, uid, "genius_access_token")
    if not token:
        return False, "کلید خالی است"
    res = await client.get(
        f"{cfg.GENIUS_API}/search",
        params={"q": "shadm"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    )
    if res.status_code == 200:
        return True, "جستجو جواب داد"
    if res.status_code in (401, 403):
        return False, "کلید پذیرفته نشد"
    return False, f"پاسخ {res.status_code}"


async def _test_acoustid(client: httpx.AsyncClient, v: dict[str, str], uid: str) -> tuple[bool, str]:
    key = _value(v, uid, "acoustid_key")
    if not key:
        return False, "کلید خالی است"
    res = await client.get(
        "https://api.acoustid.org/v2/lookup",
        params={"client": key, "meta": "recordings", "format": "json"},
        timeout=15.0,
    )
    try:
        body = res.json()
    except Exception:
        return False, f"پاسخ {res.status_code} — JSON نبود"
    if body.get("status") == "ok":
        if not cfg.FPCALC:
            return True, "کلید سالم است، ولی `fpcalc` نصب نیست — روی سرور نصبش کن"
        return True, "کلید سالم است"
    return False, str(body.get("error") or "کلید نامعتبر است")


async def _test_audd(client: httpx.AsyncClient, v: dict[str, str], uid: str) -> tuple[bool, str]:
    token = _value(v, uid, "audd_token")
    if not token:
        return False, "توکن خالی است"
    # بدونِ فایل می‌فرستیم: سرویس برای توکنِ درست می‌گوید «فایل لازم است» و برای
    # توکنِ غلط می‌گوید «توکن معتبر نیست». هر دو errorاند و تفاوتشان همه‌چیز است.
    res = await client.post(cfg.AUDD_API, data={"api_token": token}, timeout=15.0)
    try:
        body = res.json()
    except Exception:
        return False, f"پاسخ {res.status_code} — JSON نبود"
    message = str((body.get("error") or {}).get("error_message") or "")
    if body.get("status") == "success":
        return True, "توکن پذیرفته شد"
    if "token" in message.lower():
        return False, f"AudD: {message}"
    return True, "توکن پذیرفته شد"


async def _test_gemini(client: httpx.AsyncClient, v: dict[str, str], uid: str) -> tuple[bool, str]:
    key = _value(v, uid, "gemini_api_key")
    if not key:
        return False, "کلید خالی است"
    # کوچک‌ترین درخواستِ ممکن: maxOutputTokens=1 تا سهمیه‌ی رایگان با یک
    # پاسخِ کامل نسوزد — اینجا فقط کلید و مدل بررسی می‌شوند
    res = await client.post(
        cfg.GEMINI_API_URL.format(model=cfg.GEMINI_MODEL),
        headers={"x-goog-api-key": key},
        json={
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        },
        timeout=20.0,
    )
    if res.status_code == 200:
        return True, "کلید سالم است"
    try:
        detail = str(res.json().get("error", {}).get("message", ""))[:160]
    except Exception:  # noqa: BLE001 — پاسخِ HTML/متنی از فیلترِ شبکه
        detail = ""
    # گوگل برای «کلید غلط» و «مدل نیست» هر دو 400 می‌دهد؛ تنها چیزی که جداشان
    # می‌کند متنِ error است، و کاربر باید بداند کدام بوده
    if "not found" in detail or "Supported generative" in detail or res.status_code == 404:
        return False, f"مدلِ «{cfg.GEMINI_MODEL}» در دسترس این کلید نیست"
    if res.status_code in (401, 403) or "API key" in detail or "API_KEY" in detail:
        return False, "کلید پذیرفته نشد"
    return False, detail or f"پاسخ {res.status_code}"


TESTERS = {
    "spotify": _test_spotify,
    "genius": _test_genius,
    "acoustid": _test_acoustid,
    "audd": _test_audd,
    "gemini": _test_gemini,
}


# ---------------------------------------------------------------- اندپوینت‌ها


@router.get("/api/setup")
async def setup_state(user_id: str = Depends(auth.optional_user)) -> dict:
    env = _server_env()
    return {
        "done": _done(user_id),
        "set": credentials.masked_map(user_id),
        # وضعیتِ سرور: کاربر نمی‌تواند عوضش کند، ولی باید بداند چرا کار نمی‌کند
        "env": env,
        # تلگرام مالِ سرور است؛ یک بات وجود دارد و کاربران چتِ خودشان را با
        # کدِ جفت‌سازی وصل می‌کنند. فقط-خواندنی.
        "telegram": {
            "botTokenSet": bool(cfg.TELEGRAM_BOT_TOKEN),
            "connected": telegram.connected(),
            "botUsername": telegram.bot_username(),
        },
    }


@router.post("/api/setup/test")
async def setup_test(req: TestRequest, request: Request, user_id: str = Depends(auth.current_user)) -> dict:
    tester = TESTERS.get(req.key)
    if tester is None:
        raise HTTPException(400, f"آزمایشِ ناشناخته: {req.key}")
    unknown = set(req.values) - ALLOWED_KEYS
    if unknown:
        raise HTTPException(400, "کلیدِ مجاز نیست")

    proxy = cfg.PROXY
    server_http = getattr(request.app.state, "http", None)
    client = server_http or httpx.AsyncClient(timeout=15.0, proxy=proxy)
    try:
        ok, detail = await tester(client, req.values, user_id)
    except httpx.RequestError as exc:
        # نرسیدن به خودِ سرویس (دیوارِ آتش، DNS، قطعیِ بین‌الملل) با «کلید غلط»
        # یکی نیست — کاربرِ ایرانی باید بداند تقصیرِ شبکه بوده نه تقصیرِ او
        return {"ok": False, "detail": f"به سرویس وصل نشد: {type(exc).__name__}"}
    finally:
        if client is not server_http:
            await client.aclose()
    return {"ok": ok, "detail": detail}


@router.post("/api/setup/save")
async def setup_save(req: SaveRequest, user_id: str = Depends(auth.optional_user)) -> dict:
    """
    ذخیره‌ی کلید، یا رد کردنِ ویزارد.

    مهمان فقط می‌تواند رد کند: ردیفِ مهمان بینِ همه‌ی بازدیدکننده‌های بی‌حساب
    مشترک است، پس اگر بتواند کلید بنویسد، کلیدی که یک نفر وارد کرده برای همه
    دیده می‌شود. ولی بستنِ ویزارد باید برایش ممکن باشد، وگرنه صفحه‌ی تنظیمات
    جلوی بازدیدکننده‌ای که حساب ندارد قفل می‌شود.
    """
    if user_id == db.GUEST_ID and req.values:
        raise HTTPException(401, "برای ذخیره‌ی کلید باید وارد حساب شوی")
    unknown = set(req.values) - ALLOWED_KEYS
    if unknown:
        raise HTTPException(400, "کلیدِ مجاز نیست")
    # مقدارِ چندخطی یعنی کلیدِ عوض‌شده در پاسخ‌های بعدی؛ ارزان است و می‌ماند
    for k, v in req.values.items():
        if any(c in v for c in ("\n", "\r", "\x00")):
            raise HTTPException(400, f"مقدارِ {k} نباید چند خط باشد")

    # کلیدهایی که کاربر خالی فرستاده حذف نمی‌شوند: فرم فقط مقدارهای تایپ‌شده را
    # می‌فرستد و رشته‌ی خالی یعنی «پاکش کن» — که عمداً ممکن است.
    values = {k: v.strip() for k, v in req.values.items()}
    changed = credentials.set_many(user_id, values, time.time())
    if req.done:
        if user_id == db.GUEST_ID:
            _mark_guest_done()
        else:
            db.set_setup_done(user_id, time.time())
    return {"ok": True, "changed": changed, "done": _done(user_id)}


@router.post("/api/setup/cookies")
async def setup_cookies(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(auth.current_user),
) -> dict:
    """
    کوکیِ یوتیوب — **مشترک میانِ همه‌ی حساب‌ها**.

    برخلاف کلیدهای API، این کوکی مالِ یک حساب نیست: یک فایل روی سرور است و
    هر حسابی که وارد شود از آن استفاده می‌کند. دلیلش در `ydl.auth_opts`
    توضیح داده شده — کوکی به دستگاه و حسابِ یوتیوبِ سازنده گره خورده و
    شخصی‌کردنش یعنی هر کاربر همان مراحلِ خطاپذیر را تکرار کند.

    احراز هویت هنوز لازم است: روی دامنه، هر بازدیدکننده‌ای نباید بتواند
    کوکیِ مشترک را عوض کند و یوتیوب را برای همه بشکند.

    اعتبارسنجی فقط قالب است، نه اعتبارِ کوکی — فهمیدنِ اینکه کوکی منقضی شده
    یک استخراجِ واقعی از یوتیوب می‌خواهد (چند ثانیه و گاهی «not a bot»). قالبِ
    غلط ولی همان‌جا گرفته می‌شود، که شایع‌ترین خطاست (افزونه‌ی اشتباه، JSON به
    جای Netscape).
    """
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "فایل بیش از حد بزرگ است")
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(400, "فایل متنی نیست")

    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        raise HTTPException(400, "هیچ کوکی‌ای داخل فایل نیست")
    bad = [l for l in lines if len(l.split("\t")) != 7]
    if len(bad) > len(lines) // 2:
        raise HTTPException(
            400, "قالب فایل Netscape نیست — با افزونه‌ی «Get cookies.txt LOCALLY» بگیر"
        )
    yt = [l for l in lines if "youtube" in l or "ytimg" in l]

    path = cookies_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)

    # مسیر در محیط می‌نشیند، نه در ردیفِ یک کاربر: `ydl._live` همین را می‌خواند
    # و با هر درخواست زنده اثر می‌کند، بدونِ ری‌استارت.
    os.environ["MUSICBAZI_COOKIES_FILE"] = str(path)

    # چک‌لیستِ `GET /api/setup` هم همین را نشان می‌دهد؛ این‌جا تلاش می‌کنیم مقدارِ
    # فرایند را هم به‌روز کنیم تا هر مصرف‌کننده‌ای که از `cfg` می‌خواند عقب نماند.
    try:
        cfg.COOKIES_FILE = str(path)
    except AttributeError:  # pragma: no cover — config همیشه این نام را دارد
        pass

    # کش خطاهای قطعیِ همین سرور پاک شود تا درخواستِ بعدی دوباره تلاش کند
    try:
        from .stream.playback import get_live_playback

        get_live_playback().on_session_changed()
    except Exception as exc:
        log.warning("failed to notify stream resolver of cookie update: %s", exc)

    return {
        "ok": True,
        "cookies": len(lines),
        "youtube": len(yt),
        "changed": ["MUSICBAZI_COOKIES_FILE"],
    }
