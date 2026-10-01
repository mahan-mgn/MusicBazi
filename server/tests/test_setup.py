"""
آزمونِ ویزاردِ راه‌اندازی.

سرویس‌های بیرونی در این فایل *هیچ‌وقت* صدا زده نمی‌شوند: آزمایِش‌ها با
`httpx.MockTransport` جای‌گذار می‌شوند تا هم قطعی باشند هم روی سهمیه‌ی کسی
حساب نشوند. تنها چیزی که آزمایش می‌شود منطقِ خودِ کد است — قالبِ پاسخ،
مرزهایِ نوشتنِ `.env`، و اینکه چه چیزی به مرورگر بیرون می‌رود.

بدونِ پلاگینِ async: خودِ `asyncio.run` هر آزمایِش را اجرا می‌کند، چون
`pytest-asyncio` در حالتِ strict بدونِ مارکر هیچی اجرا نمی‌کند و افزودنش به
`pytest.ini` برای چند تابع ارزش نداشت.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import setup as su


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """`.env` و کوکی را به جای موقت می‌بریم؛ وگرنه روی `server/data/` واقعی می‌نویسیم."""
    path = tmp_path / ".env"
    monkeypatch.setattr(su, "ENV_PATH", path)
    monkeypatch.setattr(su, "COOKIES_PATH", tmp_path / "cookies.txt")
    return path


@pytest.fixture
def clean_env(monkeypatch):
    for key in su.ALLOWED_KEYS:
        monkeypatch.delenv(key, raising=False)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(su.router)
    app.state.http = _client(lambda r: httpx.Response(200, json={"ok": True}))
    return app


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- نوشتن


def test_write_env_creates_and_updates(env_file):
    assert su.write_env({"MUSICBAZI_AUDD_TOKEN": "abc"}) == ["MUSICBAZI_AUDD_TOKEN"]
    assert "MUSICBAZI_AUDD_TOKEN=abc" in env_file.read_text(encoding="utf-8")
    # همان مقدار دوباره = هیچ تغییری = هیچ ری‌استارتی
    assert su.write_env({"MUSICBAZI_AUDD_TOKEN": "abc"}) == []
    assert su.write_env({"MUSICBAZI_AUDD_TOKEN": "xyz"}) == ["MUSICBAZI_AUDD_TOKEN"]
    assert env_file.read_text(encoding="utf-8").count("MUSICBAZI_AUDD_TOKEN") == 1


def test_write_env_keeps_foreign_lines(env_file):
    env_file.write_text("# توضیحِ دستی\nMUSICBAZI_CONCURRENCY=9\n", encoding="utf-8")
    su.write_env({"MUSICBAZI_AUDD_TOKEN": "abc"})
    text = env_file.read_text(encoding="utf-8")
    assert "MUSICBAZI_CONCURRENCY=9" in text and "# توضیحِ دستی" in text


def test_restart_needed_detects_drift(env_file, monkeypatch, clean_env):
    assert su._restart_needed() is False
    su.write_env({"MUSICBAZI_AUDD_TOKEN": "abc"})
    # روی دیسک هست، در محیطِ این فرایند نیست → سرور هنوز نخوانده
    assert su._restart_needed() is True
    monkeypatch.setenv("MUSICBAZI_AUDD_TOKEN", "abc")
    assert su._restart_needed() is False


def test_save_rejects_keys_outside_the_allowlist(env_file):
    """`PATH` یا `MUSICBAZI_DB` اگر باز بودند، یک درخواستِ HTTP می‌توانست مسیرِ دیتابیس را عوض کند."""
    client = TestClient(_app())
    for bad in ({"PATH": "/tmp"}, {"MUSICBAZI_DB": "/tmp/evil.db"}, {"PYTHONPATH": "/tmp"}):
        r = client.post("/api/setup/save", json={"values": bad, "restart": False})
        assert r.status_code == 400, bad
    assert not env_file.exists()


def test_test_rejects_unknown_group_and_key():
    client = TestClient(_app())
    assert client.post("/api/setup/test", json={"key": "nope", "values": {}}).status_code == 400
    r = client.post(
        "/api/setup/test", json={"key": "genius", "values": {"MUSICBAZI_DB": "x"}}
    )
    assert r.status_code == 400


def test_save_rejects_multiline_values(env_file):
    """
    حفره‌ی واقعی: کلید در allowlist است ولی *مقدار* خطِ دومِ دلخواه می‌آورد.

    `MUSICBAZI_PROXY = "socks5://x\\nMUSICBAZI_DB=/evil"` یک خط مجاز می‌نویسد و
    کنارش یک خطِ کاملاً خارجِ allowlist — چون allowlist فقط نامِ کلیدِ ارسالی را
    می‌بیند، نه چیزی که روی دیسک می‌نشیند. اندپوینت احراز هویت ندارد، پس تنها
    دفاع، ردّکردنِ خودِ مقدارِ چندخطی است.
    """
    client = TestClient(_app())
    r = client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_PROXY": "socks5://127.0.0.1:1080\nMUSICBAZI_DB=/evil.db"}},
    )
    assert r.status_code == 400
    assert not env_file.exists()
    # مقدارِ تک‌خطیِ عادی نباید با این بررسی رد شود
    ok = client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_PROXY": "socks5://127.0.0.1:1080"}, "restart": False},
    )
    assert ok.status_code == 200
    assert env_file.read_text(encoding="utf-8").count("\n") == 1


# ---------------------------------------------------------------- آزمایِش‌ها


def test_spotify_needs_both_parts():
    ok, detail = run(su._test_spotify(_client(lambda r: httpx.Response(200, json={})), {}))
    assert not ok and "لازم" in detail
    ok, _ = run(
        su._test_spotify(
            _client(lambda r: httpx.Response(200, json={})),
            {"MUSICBAZI_SPOTIFY_CLIENT_ID": "id"},
        )
    )
    assert not ok


def test_spotify_sends_basic_auth_and_reads_status():
    seen = {}

    def tok(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"access_token": "t"})

    ok, detail = run(
        su._test_spotify(
            _client(tok),
            {"MUSICBAZI_SPOTIFY_CLIENT_ID": "id", "MUSICBAZI_SPOTIFY_CLIENT_SECRET": "sh"},
        )
    )
    assert ok and seen["auth"].startswith("Basic ")

    ok, detail = run(
        su._test_spotify(
            _client(lambda r: httpx.Response(400, json={"error": "invalid_client"})),
            {"MUSICBAZI_SPOTIFY_CLIENT_ID": "id", "MUSICBAZI_SPOTIFY_CLIENT_SECRET": "bad"},
        )
    )
    assert not ok and "غلط" in detail


def test_telegram_reports_username():
    ok, detail = run(
        su._test_telegram(
            _client(
                lambda r: httpx.Response(200, json={"ok": True, "result": {"username": "musicbazi_bot"}})
            ),
            {"MUSICBAZI_TELEGRAM_BOT_TOKEN": "123:abc"},
        )
    )
    assert ok and detail == "@musicbazi_bot"

    ok, detail = run(
        su._test_telegram(
            _client(lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})),
            {"MUSICBAZI_TELEGRAM_BOT_TOKEN": "nope"},
        )
    )
    assert not ok and "Unauthorized" in detail


def test_acoustid_separates_key_from_fpcalc(monkeypatch):
    good = lambda r: httpx.Response(200, json={"status": "ok"})  # noqa: E731
    monkeypatch.setattr(su.cfg, "FPCALC", "/usr/bin/fpcalc")
    ok, _ = run(su._test_acoustid(_client(good), {"MUSICBAZI_ACOUSTID_KEY": "k"}))
    assert ok

    # کلید سالم است ولی ابزارش نیست — پیام باید همین را بگوید، نه «کلید غلط»
    monkeypatch.setattr(su.cfg, "FPCALC", None)
    ok, detail = run(su._test_acoustid(_client(good), {"MUSICBAZI_ACOUSTID_KEY": "k"}))
    assert ok and "fpcalc" in detail

    ok, _ = run(
        su._test_acoustid(
            _client(lambda r: httpx.Response(200, json={"status": "error", "error": "No client key"})),
            {"MUSICBAZI_ACOUSTID_KEY": "k"},
        )
    )
    assert not ok


def test_gemini_distinguishes_model_from_key():
    """
    گوگل برای «مدل نیست» و «کلید غلط» هر دو 400 می‌دهد؛ تفکیک فقط از روی
    متنِ error ممکن است و کاربرِ ایرانی باید بداند کدام بوده.
    """
    ok, detail = run(
        su._test_gemini(
            _client(
                lambda r: httpx.Response(
                    400,
                    json={"error": {"message": "models/gemini-9-flash is not found for API version"}},
                )
            ),
            {"MUSICBAZI_GEMINI_API_KEY": "AIza-x"},
        )
    )
    assert not ok and "مدل" in detail

    ok, detail = run(
        su._test_gemini(
            _client(
                lambda r: httpx.Response(400, json={"error": {"message": "API key not valid."}})
            ),
            {"MUSICBAZI_GEMINI_API_KEY": "bad"},
        )
    )
    assert not ok and "کلید" in detail

    ok, empty = run(su._test_gemini(_client(lambda r: httpx.Response(200, json={})), {}))
    assert not ok and "خالی" in empty


def test_proxy_checks_shape_before_touching_the_network():
    ok, detail = run(su._test_proxy(_client(lambda r: httpx.Response(200)), {"MUSICBAZI_PROXY": "nope"}))
    assert not ok and "قالب" in detail
    ok, _ = run(su._test_proxy(_client(lambda r: httpx.Response(200)), {}))
    assert not ok


def test_network_failure_is_not_reported_as_a_bad_key():
    """فرقی که کاربر ایرانی باید ببیند: «به سرویس وصل نشد» ≠ «کلید غلط»."""

    def boom(request):
        raise httpx.ConnectError("no route")

    client = TestClient(_app())
    client.app.state.http = _client(boom)
    r = client.post(
        "/api/setup/test", json={"key": "genius", "values": {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "t"}}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "وصل نشد" in body["detail"]


# ---------------------------------------------------------------- اندپوینتِ وضعیت


def test_state_masks_keys(env_file, clean_env, monkeypatch):
    monkeypatch.setenv("MUSICBAZI_AUDD_TOKEN", "supersecretvalue")
    body = TestClient(_app()).get("/api/setup").json()
    assert body["set"]["MUSICBAZI_AUDD_TOKEN"] == "…alue"
    assert "supersecretvalue" not in json.dumps(body)
    assert "restartNeeded" in body and "env" in body


def test_gate_opens_for_an_install_that_was_already_configured(env_file, clean_env, monkeypatch):
    """
    باگِ واقعی: `server/.env` از قبل پر از کلید بود، ولی چون ویزارد هیچ‌وقت دیده
    نشد پرچمِ DONE ست نبود — و اپی که کامل کار می‌کرد ناگهان پشتِ دروازه ماند.
    """
    monkeypatch.setattr(su.cfg, "SETUP_DONE", False)
    monkeypatch.setenv("MUSICBAZI_SPOTIFY_CLIENT_ID", "89ce-real-looking-id")
    assert TestClient(_app()).get("/api/setup").json()["done"] is True


def test_gate_stays_shut_on_a_genuinely_fresh_install(env_file, clean_env, monkeypatch):
    monkeypatch.setattr(su.cfg, "SETUP_DONE", False)
    assert TestClient(_app()).get("/api/setup").json()["done"] is False


def test_done_flag_alone_opens_the_gate(env_file, clean_env, monkeypatch):
    """«رد کردن» با کلیدِ خالی هم باید دروازه را برای همیشه باز کند."""
    monkeypatch.setattr(su.cfg, "SETUP_DONE", False)
    monkeypatch.setenv("MUSICBAZI_SETUP_DONE", "1")
    assert TestClient(_app()).get("/api/setup").json()["done"] is True


def test_save_writes_done_flag(env_file, clean_env):
    r = TestClient(_app()).post(
        "/api/setup/save", json={"values": {}, "restart": False, "done": True}
    )
    assert r.status_code == 200 and r.json()["restarting"] is False
    assert "MUSICBAZI_SETUP_DONE=1" in env_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------- کوکی


def test_cookies_rejects_wrong_format(env_file):
    r = TestClient(_app()).post(
        "/api/setup/cookies", files={"file": ("cookies.txt", b'{"cookies": []}', "text/plain")}
    )
    assert r.status_code == 400 and "Netscape" in r.json()["detail"]
    assert not su.COOKIES_PATH.exists()


def test_cookies_accepts_netscape_and_registers_the_path(env_file):
    body = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tSID\tabc\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tk\tv\n"
    )
    r = TestClient(_app()).post("/api/setup/cookies", files={"file": ("c.txt", body, "text/plain")})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cookies"] == 2 and data["youtube"] == 1
    assert su.COOKIES_PATH.read_text(encoding="utf-8").startswith("# Netscape")
    assert f"MUSICBAZI_COOKIES_FILE={su.COOKIES_PATH}" in env_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------- ری‌استارت


def test_restart_inside_container_only_exits(monkeypatch):
    """داکر خودش سرور را برگرد می‌گرداند؛ ساختنِ فرایندِ دوم یعنی دو سرور روی یک پورت."""
    exits, spawns = [], []
    monkeypatch.setattr(su, "_in_container", lambda: True)
    monkeypatch.setattr(su, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(su, "_spawn_detached", lambda cmd: spawns.append(cmd))
    assert su.spawn_relauncher() is True
    run(su.die(delay=0))
    assert exits == [0] and spawns == []


def test_restart_outside_container_relaunches_the_same_command(monkeypatch):
    exits, spawns = [], []
    monkeypatch.setattr(su, "_in_container", lambda: False)
    monkeypatch.setattr(su, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(su, "_spawn_detached", lambda cmd: spawns.append(cmd))
    assert su.spawn_relauncher() is True
    run(su.die(delay=0))
    assert exits == [0] and len(spawns) == 1
    cmd = spawns[0]
    assert cmd[0] == su._LAUNCH[0] == su.sys.executable
    # بارِ فرمان (مسیر و argvِ خودِ پروسه) در JSON است، نه در shell string — تا
    # یک کلیدِ حاویِ فاصله یا `\` نتواند فرمانِ دیگری بسازد
    payload = json.loads(cmd[-2])
    assert payload["cmd"] == su._LAUNCH and "cwd" in payload
    # نگهبان یک آرگومانِ آخر هم دارد: جایی که خروجیِ سرورِ تازه برود. بدونش
    # شکستِ ری‌استارت کاملاً بی‌صدا می‌ماند (و یک بار دقیقاً همین شد).
    assert cmd[-1].endswith("server.log")


@pytest.mark.parametrize(
    "argv0",
    [
        # `python -m uvicorn app.main:app --port 9000` — argv0 به پوشه‌ی
        # site-packages/uvicorn اشاره می‌کند
        "C:\\x\\site-packages\\uvicorn\\__main__.py",
        "C:/x/site-packages/uvicorn/__main__.py",
    ],
)
def test_launch_rewrites_uvicorn_dunder_main_to_dash_m(monkeypatch, argv0):
    """
    تله‌ای که ری‌استارت را بی‌صدا می‌کُشت: `python <site-packages>/uvicorn/__main__.py`
    با `AttributeError: module 'logging' has no attribute 'Formatter'` می‌میرد.
    """
    monkeypatch.setattr(su.sys, "argv", [argv0, "app.main:app", "--port", "9000"])
    launch = su.launch_command()
    assert launch[1:3] == ["-m", "uvicorn"]
    assert launch[-2:] == ["--port", "9000"]
    assert "__main__.py" not in " ".join(launch)


def test_launch_keeps_a_plain_script_invocation(monkeypatch):
    monkeypatch.setattr(su.sys, "argv", ["C:/srv/run.py", "--port", "9000"])
    assert su.launch_command() == [su.sys.executable, "C:/srv/run.py", "--port", "9000"]


def test_save_stays_alive_when_the_relauncher_cannot_spawn(env_file, clean_env, monkeypatch):
    """
    مهم‌ترین رفتارِ این ماژول: اگر سرورِ تازه ساخته نشود، سرورِ فعلی نباید بمیرد.

    کاربر آن‌وقت «برنامه کلاً از دست رفت» دارد به‌جای «ری‌استارت نشد، خودت بزن».
    """
    monkeypatch.setattr(su, "_in_container", lambda: False)
    monkeypatch.setattr(su, "_spawn_detached", lambda cmd: (_ for _ in ()).throw(OSError("denied")))
    exits = []
    monkeypatch.setattr(su, "_exit", lambda code: exits.append(code))
    r = TestClient(_app()).post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_AUDD_TOKEN": "x"}, "restart": True, "done": False},
    )
    body = r.json()
    assert body["restarting"] is False and body["manualRestart"] is True
    assert exits == []
    # ولی مقدار روی دیسک نشسته و از اجرایِ بعدی خوانده می‌شود
    assert "MUSICBAZI_AUDD_TOKEN=x" in env_file.read_text(encoding="utf-8")


def test_launch_reuses_the_running_invocation(monkeypatch):
    """`--port 9000` اجرا شده باشد، ری‌استارت هم باید روی ۹۰۰۰ برگرداند."""
    monkeypatch.setattr(su.sys, "argv", ["X:\\uvicorn\\__main__.py", "app.main:app", "--port", "9000"])
    launch = [su.sys.executable, *su.sys.argv]
    assert launch[-2:] == ["--port", "9000"]
