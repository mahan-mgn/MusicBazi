"""
راه‌اندازی اولیه — ویزاردی که کلیدها را از کاربر می‌گیرد و *قبل از ذخیره* آزمایشان می‌کند.

سه اندپوینت، نه چیز بیشتر:

    GET  /api/setup           چه چیزی از قبل تنظیم است + وضعیتِ محیط
    POST /api/setup/test      یک کلید را با سرویسِ خودش چک کن (بدون ذخیره)
    POST /api/setup/save      بنویس در .env و سرور را ری‌استارت کن
    POST /api/setup/cookies   فایل کوکیِ یوتیوب (Netscape) را بگیر و ذخیره کن

چرا ری‌استارت: `config.py` مقدارها را در زمانِ import می‌خواند و ~۱۵ ماژول
آن‌ها را در سطحِ ماژول نگه داشته‌اند. hot-reload کردنشان یعنی بازنویسیِ همان
۱۵ فایل — در برابرِ یک ری‌استارتِ ۲ ثانیه‌ای که همان نتیجه را می‌دهد.

چرا نوشتن در `DATA_DIR/.env` و نه `server/.env`: در داکر `server/` داخل ایمیج
است و با هر بازسازی می‌پرد؛ `DATA_DIR` همان `/data` است که volume است.

احراز هویت عمداً ندارد (تصمیمِ کاربر: پروژه‌ی شخصی/دوستانه). روی شبکه‌ای که
غریبه به این پورت دسترسی دارد، هر بازدیدکننده‌ای می‌تواند کلیدها را عوض کند —
آن‌جا یا پورت را ببند یا از `MUSICBAZI_ALLOWED_ORIGINS` و یک پروکسیِ احراز هویت‌دار
استفاده کن.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from . import config as cfg
from . import reach
from . import telegram
from .config import DATA_DIR

router = APIRouter()
log = logging.getLogger(__name__)

# فایلِ تنظیماتیِ خودِ ویزارد. `config.py` این را *قبل از* `server/.env` می‌خواند،
# پس مقدارِ ست‌شده اینجا همیشه برنده است.
ENV_PATH = DATA_DIR / ".env"

COOKIES_PATH = DATA_DIR / "cookies.txt"

# هر چیزی که ویزارد اجازه دارد بنویسد. این مجموعه عمداً تنگ است: `PATH` یا
# `MUSICBAZI_DATA_DIR` یا `PYTHONPATH` اگر باز بودند، یک درخواستِ HTTP می‌توانست
# مسیرِ دیتابیس را عوض کند یا باینریِ دلخواه اجرا کند.
ALLOWED_KEYS = frozenset(
    {
        "MUSICBAZI_SPOTIFY_CLIENT_ID",
        "MUSICBAZI_SPOTIFY_CLIENT_SECRET",
        "MUSICBAZI_GENIUS_ACCESS_TOKEN",
        "MUSICBAZI_ACOUSTID_KEY",
        "MUSICBAZI_AUDD_TOKEN",
        "MUSICBAZI_GEMINI_API_KEY",
        "MUSICBAZI_TELEGRAM_BOT_TOKEN",
        "MUSICBAZI_SOUNDCLOUD_CLIENT_ID",
        "MUSICBAZI_PROXY",
        "MUSICBAZI_YTDLP_PROXY",
        "MUSICBAZI_COOKIES_FILE",
        "MUSICBAZI_COOKIES_BROWSER",
        "MUSICBAZI_SETUP_DONE",
    }
)

_ASSIGN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


# ---------------------------------------------------------------- وضعیت


def _masked(value: str | None) -> str | None:
    if not value:
        return None
    return "…" + value[-4:] if len(value) > 8 else "•" * len(value)


def current_values() -> dict[str, str | None]:
    """مقدارِ هر کلیدِ مجاز، با همان اولویتی که سرور واقعاً با آن بالا آمده."""
    out: dict[str, str | None] = {}
    for key in sorted(ALLOWED_KEYS):
        raw = os.getenv(key)
        out[key] = raw.strip() if raw and raw.strip() else None
    return out


def _set_map() -> dict[str, str]:
    return {k: _masked(v) for k, v in current_values().items() if v}


#: پرچمِ «کاربر ویزارد را دیده» — تنها چیزی که با آن دروازه باز می‌ماند
_DONE_FLAG = "MUSICBAZI_SETUP_DONE"


def _setup_done(values: dict[str, str | None]) -> bool:
    """
    آیا باید دروازه‌ی ویزارد باز باشد؟

    دو راهِ «بله»:

      ۱. کاربر خودش ویزارد را رد یا تمام کرده (`MUSICBAZI_SETUP_DONE=1`).
      ۲. نصب **از قبل** تنظیم است. این حالت همان چیزی است که کاربرِ قدیمی را
         پشتِ یک صفحه‌ی خالی می‌نشاند: `server/.env` پر از کلید از قبل بوده،
         ولی چون هیچ‌وقت ویزارد ندیده، پرچمِ ۱ هیچ‌جا ست نشده — و اپی که کاملاً
         کار می‌کرد ناگهان «اول تنظیم کن» می‌گوید. پس اگر هر کلیدِ واقعی
         (یا کوکیِ فایل) موجود باشد، دروازه باز است.

    نصبِ تازه هیچ‌کدام را ندارد و ویزارد را می‌بیند.
    """
    if values.get(_DONE_FLAG):
        return True
    return any(v for k, v in values.items() if k != _DONE_FLAG)


class SaveRequest(BaseModel):
    values: dict[str, str] = {}
    # «بعد از ذخیره سرور را ری‌استارت کن». خاموش فقط وقتی که چیزی عوض نشده.
    restart: bool = True
    # رد کردنِ ویزارد هم همین را True می‌گذارد تا دوباره باز نشود
    done: bool = False


def _restart_needed() -> bool:
    """
    آیا چیزی که روی دیسک است با چیزی که سرور *همین حالا* با آن کار می‌کند فرق دارد؟

    مقایسه با `os.environ` است نه با مقدارهای ماژولِ `config`، چون آن‌ها در زمانِ
    import قفل شده‌اند و خودِ همین مقایسه را بی‌معنا می‌کردند.
    """
    return any(
        (os.getenv(k) or "").strip() != v for k, v in _read_env_file().items() if k in ALLOWED_KEYS
    )


def _read_env_file() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        m = _ASSIGN.match(line)
        if m:
            out[m.group(1)] = line.split("=", 1)[1].strip().strip('"').strip("'")
    return out


def write_env(values: dict[str, str]) -> list[str]:
    """
    کلیدها را داخلِ `DATA_DIR/.env` می‌گذارد و فهرستِ کلیدهایی را برمی‌گرداند که
    واقعاً عوض شده‌اند — تا بی‌دلیل ری‌استارت نشود.

    خط‌های ناشناس (توضیحات، کلیدهایی که کسی دستی اضافه کرده) دست‌نخورده می‌مانند.
    """
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    index: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = _ASSIGN.match(line)
        if m:
            index[m.group(1)] = i

    changed: list[str] = []
    for key, value in values.items():
        if index.get(key) is not None and lines[index[key]].split("=", 1)[1].strip() == value:
            continue
        if key in index:
            lines[index[key]] = f"{key}={value}"
        else:
            lines.append(f"{key}={value}")
            index[key] = len(lines) - 1
        changed.append(key)

    if changed:
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENV_PATH.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return changed


# ---------------------------------------------------------------- آزمودن
#
# هر آزمایِش یک درخواستِ کوچک به همان سرویس است با مقداری که کاربر *همین حالا*
# تایپ کرده — نه چیزی که ذخیره شده. دلیلش: یک رقمِ اشتباهی در Client Secret
# بعداً به‌شکلِ «اسپاتیفای کار نمی‌کند» ظاهر می‌شود و فهمیدنش غیرممکن است.


class TestRequest(BaseModel):
    key: str
    values: dict[str, str] = {}


async def _test_spotify(client: httpx.AsyncClient, v: dict[str, str]) -> tuple[bool, str]:
    cid = (v.get("MUSICBAZI_SPOTIFY_CLIENT_ID") or os.getenv("MUSICBAZI_SPOTIFY_CLIENT_ID") or "").strip()
    secret = (v.get("MUSICBAZI_SPOTIFY_CLIENT_SECRET") or os.getenv("MUSICBAZI_SPOTIFY_CLIENT_SECRET") or "").strip()
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


async def _test_genius(client: httpx.AsyncClient, v: dict[str, str]) -> tuple[bool, str]:
    token = (v.get("MUSICBAZI_GENIUS_ACCESS_TOKEN") or os.getenv("MUSICBAZI_GENIUS_ACCESS_TOKEN") or "").strip()
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


async def _test_acoustid(client: httpx.AsyncClient, v: dict[str, str]) -> tuple[bool, str]:
    key = (v.get("MUSICBAZI_ACOUSTID_KEY") or os.getenv("MUSICBAZI_ACOUSTID_KEY") or "").strip()
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


async def _test_audd(client: httpx.AsyncClient, v: dict[str, str]) -> tuple[bool, str]:
    token = (v.get("MUSICBAZI_AUDD_TOKEN") or os.getenv("MUSICBAZI_AUDD_TOKEN") or "").strip()
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


async def _test_gemini(client: httpx.AsyncClient, v: dict[str, str]) -> tuple[bool, str]:
    key = (v.get("MUSICBAZI_GEMINI_API_KEY") or os.getenv("MUSICBAZI_GEMINI_API_KEY") or "").strip()
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


async def _test_telegram(client: httpx.AsyncClient, v: dict[str, str]) -> tuple[bool, str]:
    token = (v.get("MUSICBAZI_TELEGRAM_BOT_TOKEN") or os.getenv("MUSICBAZI_TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return False, "توکن خالی است"
    res = await client.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15.0)
    try:
        body = res.json()
    except Exception:
        return False, f"پاسخ {res.status_code} — JSON نبود"
    if body.get("ok"):
        return True, f"@{body['result'].get('username', '?')}"
    return False, str(body.get("description") or "توکن پذیرفته نشد")


async def _test_proxy(client: httpx.AsyncClient, v: dict[str, str]) -> tuple[bool, str]:
    proxy = (v.get("MUSICBAZI_PROXY") or os.getenv("MUSICBAZI_PROXY") or "").strip()
    if not proxy:
        return False, "آدرس خالی است"
    if "://" not in proxy:
        return False, "قالب: socks5h://host:port یا http://host:port"
    try:
        async with httpx.AsyncClient(timeout=12.0, proxy=proxy) as own:
            res = await own.get("https://cloudflare.com/cdn-cgi/trace")
    except Exception as exc:
        return False, f"از این پروکسی رد نشد: {type(exc).__name__}"
    if res.status_code == 200:
        # `ip=` و `colo=` در بدنه هست — نشانه‌ی واقعیِ اینکه ترافیک رد شده
        line = next((l for l in res.text.splitlines() if l.startswith("ip=")), "")
        return True, f"وصل شد ({line[3:] or res.status_code})"
    return False, f"پاسخ {res.status_code}"


TESTERS = {
    "spotify": _test_spotify,
    "genius": _test_genius,
    "acoustid": _test_acoustid,
    "audd": _test_audd,
    "gemini": _test_gemini,
    "telegram": _test_telegram,
    "proxy": _test_proxy,
}


# ---------------------------------------------------------------- ری‌استارت

def launch_command() -> list[str]:
    """
    همان فرمانی که سرور الان با آن بالا آمده — برای این‌که ری‌استارت، ری‌استارت
    باشد نه یک اجرایِ دیگر با فلگ‌های دیگر (پورتِ ۹۰۰۰ باید روی ۹۰۰۰ برگردد).

    یک تله‌ی واقعی وسطش هست: `python -m uvicorn …` روی `sys.argv[0]` مسیرِ
    `site-packages/uvicorn/__main__.py` را می‌گذارد. اگر همان مسیر را مستقیم
    به‌عنوان اسکریپت اجرا کنیم، پایتون *پوشه‌ی خودش* را اولِ `sys.path` می‌گذارد
    و `uvicorn/logging.py` جای `logging` استاندارد را می‌گیرد — سرور با
    `AttributeError: module 'logging' has no attribute 'Formatter'` می‌میرد.
    (دقیقاً همین اتفاق افتاد و ری‌استارت بی‌صدا شکست شد.) پس آن حالت را به
    شکلِ درستِ خودش برمی‌گردانیم: `-m uvicorn`.
    """
    argv0 = sys.argv[0] or ""
    stem = argv0.replace("\\", "/").rsplit("/", 1)[-1]
    if stem == "__main__.py" and "/uvicorn/" in argv0.replace("\\", "/"):
        return [sys.executable, "-m", "uvicorn", *sys.argv[1:]]
    # بقیه‌ی حالت‌ها (`python server.py`، gunicorn، اسکریپتِ خودِ کاربر)
    # همان‌طور که هستند درست‌اند
    return [sys.executable, *sys.argv]


_LAUNCH = launch_command()
_LAUNCH_CWD = os.getcwd()


def _in_container() -> bool:
    # /.dockerenv داکر است؛ RAILWAY_ENVIRONMENT یعنی کانتینرِ Railway — آن‌جا
    # هم ارجیستراتور (restartPolicyType=ALWAYS + حلقه‌ی entrypoint) سرور را
    # برمی‌گرداند و نگهبانِ دوم فقط پورت را دعوایی می‌کند.
    return Path("/.dockerenv").exists() or bool(os.getenv("RAILWAY_ENVIRONMENT"))


def _spawn_detached(cmd: list[str]) -> None:
    """
    یک فرایندِ کاملاً مستقل می‌سازد که به مرگِ پدر ربطی ندارد.

    ویندوز دو تله دارد:

      ۱. بیرون از کنسول، فرزندِ detached با `os._exit` هم یتیم می‌ماند و زنده
         است — ولی اگر فرایندِ ما داخل یک **Job Object** باشد (هر چیزی که
         سرور را از بیرون مدیریت می‌کند: Task Scheduler، some CI runners،
         پوشه‌ی `bash` این ترمینال) job فرزند را هم با پدر می‌کُشد. تنها راه،
         فلگِ `CREATE_BREAKAWAY_FROM_JOB` است.
      ۲. آن فلگ فقط وقتی مجاز است که job خودش `BREAKAWAY_OK` را اعلام کرده
         باشد؛ وگرنه `CreateProcess` با `Access is denied` می‌شکند.

    API عمومی برای خواندنِ آن مجوزِ job نیست، پس حدس نمی‌زنیم: با فلگ امتحان
    می‌کنیم و اگر رد شد، بدونش. شکستِ فلگ یعنی «اینجا job اجازه نمی‌دهد» و
    در آن حالت ری‌استارتِ خودکار ممکن نیست — که همان چیزی است که کاربر باید
    بداند، نه اینکه بی‌صدا سرور برنگردد.
    """
    kwargs: dict = {
        "cwd": _LAUNCH_CWD,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        # 0x8 = DETACHED_PROCESS، 0x200 = CREATE_NEW_PROCESS_GROUP
        base = 0x00000008 | 0x00000200
        try:
            subprocess.Popen(cmd, creationflags=base | 0x00000100, **kwargs)
            return
        except OSError as exc:
            log.info("breakaway از job ممکن نشد (%s) — بدونش امتحان می‌شود", exc)
        kwargs["creationflags"] = base
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


# جای‌گذارِ تست‌پذیر (تستِ پایتونِ خالص، بدونِ کشتنِ فرایندِ تست)
_exit = os._exit


def spawn_relauncher() -> bool:
    """
    نگهبانی می‌گذارد که دو ثانیه بعد سرور را از نو بالا می‌آورد. True یعنی موفق.

    *قبل از* پاسخ دادن به درخواست صدا زده می‌شود، نه بعدش: اگر ساختنِ فرایند
    ممکن نباشد و ما باز هم بمیریم، کاربر هیچ سروری ندارد — که از «ری‌استارت نشد،
    خودت انجام بده» خیلی بدتر است.

    دو حالت دارد و تشخیصشان ارزان است: داخل کانتینر خودِ ارجیستراتور سرور را
    برگرد می‌گرداند (`restart: unless-stopped`)، پس هیچ نگهبانی لازم نیست و
    فقط می‌میریم. بیرونش ناظری نیست و نگهبان لازم است.
    """
    if _in_container():
        return True
    payload = json.dumps({"cmd": _LAUNCH, "cwd": _LAUNCH_CWD})
    # خروجیِ سرورِ تازه به یک فایل می‌نشیند، نه DEVNULL: سرورِ قبلی کنسولش را
    # از دست داده و تنها راهِ دیدنِ «چرا بالا نیامد» همین است. بدونش اولین
    # شکستِ ری‌استارت کاملاً بی‌صدا بود.
    log_path = str(DATA_DIR / "server.log")
    try:
        _spawn_detached(
            [
                sys.executable,
                "-c",
                "import json,subprocess,sys,time;"
                "p=json.loads(sys.argv[1]);time.sleep(2);"
                "f=open(sys.argv[2],'ab',buffering=0);"
                "subprocess.Popen(p['cmd'],cwd=p['cwd'],stdin=subprocess.DEVNULL,"
                "stdout=f,stderr=subprocess.STDOUT)",
                payload,
                log_path,
            ]
        )
    except OSError as exc:
        log.error("سرورِ تازه ساخته نشد: %s", exc)
        return False
    return True


async def die(delay: float = 0.35) -> None:
    """مهلت می‌دهد تا پاسخِ HTTP برود، بعد می‌میرد."""
    await asyncio.sleep(delay)
    _exit(0)


# ---------------------------------------------------------------- اندپوینت‌ها


@router.get("/api/setup")
async def setup_state() -> dict:
    values = current_values()
    return {
        "done": _setup_done(values),
        "set": _set_map(),
        "restartNeeded": _restart_needed(),
        "env": {
            "ffmpeg": bool(cfg.FFMPEG_LOCATION),
            "jsRuntime": cfg.JS_RUNTIME or None,
            "potoken": bool(cfg.POT_BASE_URL or cfg.POT_SERVER_HOME),
            "cookies": bool(values.get("MUSICBAZI_COOKIES_FILE"))
            or bool(values.get("MUSICBAZI_COOKIES_BROWSER")),
            "proxy": bool(cfg.PROXY),
            "internet": reach.snapshot()["online"],
            "container": _in_container(),
        },
        "telegram": {
            "botTokenSet": bool(values.get("MUSICBAZI_TELEGRAM_BOT_TOKEN")),
            "connected": telegram.connected(),
            "botUsername": telegram.bot_username(),
        },
    }


@router.post("/api/setup/test")
async def setup_test(req: TestRequest, request: Request) -> dict:
    tester = TESTERS.get(req.key)
    if tester is None:
        raise HTTPException(400, f"آزمایشِ ناشناخته: {req.key}")
    unknown = set(req.values) - ALLOWED_KEYS
    if unknown:
        raise HTTPException(400, "کلیدِ مجاز نیست")

    # پروکسی درخواستی یا ست‌شده را در نظر بگیر تا تست سرویس‌های خارجی فیلتر نشوند
    req_proxy = (req.values.get("MUSICBAZI_PROXY") or "").strip()
    active_proxy = req_proxy or os.getenv("MUSICBAZI_PROXY") or cfg.PROXY

    server_http = getattr(request.app.state, "http", None)
    custom_client: httpx.AsyncClient | None = None
    if req_proxy and req_proxy != cfg.PROXY:
        custom_client = httpx.AsyncClient(timeout=15.0, proxy=req_proxy)
    client = custom_client or server_http
    if client is None:
        client = httpx.AsyncClient(timeout=15.0, proxy=active_proxy)
        custom_client = client

    try:
        ok, detail = await tester(client, req.values)
    except httpx.RequestError as exc:
        # نرسیدن به خودِ سرویس (دیوارِ آتش، DNS، قطعیِ بین‌الملل) با «کلید غلط»
        # یکی نیست — کاربرِ ایرانی باید بداند تقصیرِ شبکه بوده نه تقصیرِ او
        return {"ok": False, "detail": f"به سرویس وصل نشد: {type(exc).__name__}"}
    finally:
        if custom_client is not None and custom_client is not server_http:
            await custom_client.aclose()
    return {"ok": ok, "detail": detail}


@router.post("/api/setup/save")
async def setup_save(req: SaveRequest) -> dict:
    unknown = set(req.values) - ALLOWED_KEYS
    if unknown:
        raise HTTPException(400, "کلیدِ مجاز نیست")
    # مقدارِ چندخطی یعنی تزریق: `MUSICBAZI_PROXY=a\nMUSICBAZI_DB=/evil` یک خط
    # مجاز می‌نویسد و خطِ دومِ دلخواه را کنارش، بیرونِ allowlist. این اندپوینت
    # احراز هویت ندارد، پس تنها دفاع همین است.
    for k, v in req.values.items():
        if any(c in v for c in ("\n", "\r", "\x00")):
            raise HTTPException(400, f"مقدارِ {k} نباید چند خط باشد")
    values = {k: v.strip() for k, v in req.values.items()}
    if req.done:
        values["MUSICBAZI_SETUP_DONE"] = "1"
    changed = write_env(values)
    # مقدارهای تازه را در همین فرایند هم می‌نشینیم تا `restartNeeded` و
    # `GET /api/setup` بی‌ری‌استارت هم درست جواب بدهند؛ ماژول‌های مصرف‌کننده
    # هنوز مقدارِ کهنه را دارند و برای همین ری‌استارت لازم است.
    for k, v in values.items():
        os.environ[k] = v
    restarting = False
    # driftِ اجرایِ قبلی (بنر «ری‌استارت لازم است») هم دلیلِ ری‌استارت است، نه
    # فقط تغییرِ تازه: بی‌این، کاربر «ادامه» را می‌زند، سرور `changed=[]`
    # برمی‌گرداند و ری‌استارتی نمی‌کند — بنر هیچ‌وقت برطرف نمی‌شد
    needs_restart = bool(changed) or _restart_needed()
    if needs_restart and req.restart:
        # اول نگهبان را می‌سازیم، بعد قول می‌دهیم — اگر ساختنش نشد، سرورِ فعلی
        # باید زنده بماند و پیامِ «دستی ری‌استارت کن» برود
        if spawn_relauncher():
            restarting = True
            asyncio.create_task(die())
    return {
        "ok": True,
        "changed": changed,
        "restarting": restarting,
        "manualRestart": needs_restart and req.restart and not restarting,
    }


@router.post("/api/setup/cookies")
async def setup_cookies(file: UploadFile = File(...)) -> dict:
    """
    کوکیِ یوتیوب. فایل را روی دیسک می‌نشاند و `MUSICBAZI_COOKIES_FILE` را ست می‌کند.

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

    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    COOKIES_PATH.write_bytes(raw)
    changed = write_env({"MUSICBAZI_COOKIES_FILE": str(COOKIES_PATH)})
    os.environ["MUSICBAZI_COOKIES_FILE"] = str(COOKIES_PATH)
    return {
        "ok": True,
        "path": str(COOKIES_PATH),
        "cookies": len(lines),
        "youtube": len(yt),
        "changed": changed,
    }
