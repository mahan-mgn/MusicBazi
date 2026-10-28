"""
آزمونِ ویزاردِ راه‌اندازی — نسخه‌ی «هر حساب جدا».

سرویس‌های بیرونی در این فایل *هیچ‌وقت* صدا زده نمی‌شوند: آزمایِش‌ها با
`httpx.MockTransport` جای‌گذار می‌شوند تا هم قطعی باشند هم روی سهمیه‌ی کسی
حساب نشوند. تنها چیزی که آزمایش می‌شود منطقِ خودِ کد است — قالبِ پاسخ، مرزهای
نوشتن، و اینکه چه چیزی به مرورگر بیرون می‌رود.

تفاوتِ کلیدی با نسخه‌ی قبلی: نه `.env`، نه ری‌استارت. مقدار در `user_secrets`
به‌ازای همان `user_id` می‌نشیند و بلافاصله از `credentials.effective` خوانده
می‌شود. پس این فایل به‌جای «آیا فایل نوشته شد» می‌پرسد «آیا حسابِ همین کاربر
مقدار را گرفت و حسابِ دیگری نه».

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

from app import auth
from app import config as cfg
from app import credentials
from app import setup as su


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def client(fresh_db):
    """اپِ کوچک با همان روترِ ستاپ — بی‌نیاز از بالا آوردنِ کلِ `main`."""
    app = FastAPI()
    app.include_router(su.router)
    app.state.http = _client(lambda r: httpx.Response(200, json={"ok": True}))
    return TestClient(app)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _auth(user_id: str) -> dict[str, str]:
    token, _ = auth.mint_session(user_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def users(fresh_db):
    """دو حسابِ واقعی — جداسازی فقط با دو ردیفِ موجود معنا دارد."""
    fresh_db.create_user(
        "u_one", "password", username="alice", password_hash=auth.hash_password("password123")
    )
    fresh_db.create_user(
        "u_two", "password", username="bob", password_hash=auth.hash_password("password123")
    )
    return "u_one", "u_two"


# ---------------------------------------------------------------- نوشتن


def test_save_stores_under_the_account_not_in_a_file(client, users):
    uid, _ = users
    r = client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_AUDD_TOKEN": "abc"}},
        headers=_auth(uid),
    )
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == ["MUSICBAZI_AUDD_TOKEN"]
    assert credentials.get(uid, "audd_token") == "abc"


def test_save_never_touches_the_global_env_file(client, users, tmp_path, monkeypatch):
    """قلبِ جداسازی: هیچ نوشتنی در `.env` رخ نمی‌دهد، حتی برای مهمان."""
    env = tmp_path / ".env"
    monkeypatch.setattr(su, "DATA_DIR", tmp_path)
    uid, _ = users
    client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "t"}},
        headers=_auth(uid),
    )
    assert not env.exists()


def test_save_rejects_keys_outside_the_allowlist(client, users):
    """`PATH` یا `MUSICBAZI_DB` اگر باز بودند، یک درخواست می‌توانست مسیرِ دیتابیس را عوض کند."""
    uid, _ = users
    for bad in ({"PATH": "/tmp"}, {"MUSICBAZI_DB": "/tmp/evil.db"}, {"PYTHONPATH": "/tmp"}):
        r = client.post("/api/setup/save", json={"values": bad}, headers=_auth(uid))
        assert r.status_code == 400, bad


def test_save_rejects_multiline_values(client, users):
    """
    کلید در allowlist است ولی *مقدار* خطِ دومِ دلخواه می‌آورد. با DB این حفره
    دیگر مسیرِ کد اجرا نمی‌شود، ولی ردکردنش ارزان است و عادتِ بد را می‌گیرد.
    """
    uid, _ = users
    r = client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "t\nMUSICBAZI_DB=/evil.db"}},
        headers=_auth(uid),
    )
    assert r.status_code == 400
    assert credentials.get(uid, "genius_access_token") is None


def test_test_rejects_unknown_group_and_key(client, users):
    uid, _ = users
    assert (
        client.post("/api/setup/test", json={"key": "nope"}, headers=_auth(uid)).status_code
        == 400
    )
    r = client.post(
        "/api/setup/test",
        json={"key": "genius", "values": {"MUSICBAZI_DB": "x"}},
        headers=_auth(uid),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------- احراز هویت


def test_save_test_and_cookies_need_an_account(client):
    """
    روی دامنه، اندپوینتِ بی‌احراز هویت یعنی هر بازدیدکننده می‌تواند کلید و
    کوکیِ حسابِ دیگری را عوض کند.

    استثنا: مهمان می‌تواند ویزارد را *رد* کند (بی‌مقدار). ردیفِ مهمان بینِ همه
    مشترک است، پس اگر می‌توانست کلید بنویسد، کلیدش برای همه دیده می‌شد.
    """
    r = client.post("/api/setup/save", json={"values": {"MUSICBAZI_AUDD_TOKEN": "x"}})
    assert r.status_code == 401
    assert client.post("/api/setup/test", json={"key": "genius"}).status_code == 401
    r = client.post(
        "/api/setup/cookies", files={"file": ("c.txt", b"a\tb\tc\td\te\tf\tg", "text/plain")}
    )
    assert r.status_code == 401


# ---------------------------------------------------------------- آزمایِش‌ها


def test_spotify_needs_both_parts():
    ok, detail = run(su._test_spotify(_client(lambda r: httpx.Response(200, json={})), {}, "local"))
    assert not ok and "لازم" in detail
    ok, _ = run(
        su._test_spotify(
            _client(lambda r: httpx.Response(200, json={})),
            {"MUSICBAZI_SPOTIFY_CLIENT_ID": "id"},
            "local",
        )
    )
    assert not ok


def test_spotify_sends_basic_auth_and_reads_status():
    seen = {}

    def tok(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"access_token": "t"})

    ok, _ = run(
        su._test_spotify(
            _client(tok),
            {"MUSICBAZI_SPOTIFY_CLIENT_ID": "id", "MUSICBAZI_SPOTIFY_CLIENT_SECRET": "sh"},
            "local",
        )
    )
    assert ok and seen["auth"].startswith("Basic ")

    ok, detail = run(
        su._test_spotify(
            _client(lambda r: httpx.Response(400, json={"error": "invalid_client"})),
            {"MUSICBAZI_SPOTIFY_CLIENT_ID": "id", "MUSICBAZI_SPOTIFY_CLIENT_SECRET": "bad"},
            "local",
        )
    )
    assert not ok and "غلط" in detail


def test_acoustid_separates_key_from_fpcalc(monkeypatch):
    good = lambda r: httpx.Response(200, json={"status": "ok"})  # noqa: E731
    monkeypatch.setattr(cfg, "FPCALC", "/usr/bin/fpcalc")
    ok, _ = run(su._test_acoustid(_client(good), {"MUSICBAZI_ACOUSTID_KEY": "k"}, "local"))
    assert ok

    # کلید سالم است ولی ابزارش نیست — پیام باید همین را بگوید، نه «کلید غلط»
    monkeypatch.setattr(cfg, "FPCALC", None)
    ok, detail = run(su._test_acoustid(_client(good), {"MUSICBAZI_ACOUSTID_KEY": "k"}, "local"))
    assert ok and "fpcalc" in detail

    ok, _ = run(
        su._test_acoustid(
            _client(lambda r: httpx.Response(200, json={"status": "error", "error": "No client key"})),
            {"MUSICBAZI_ACOUSTID_KEY": "k"},
            "local",
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
            "local",
        )
    )
    assert not ok and "مدل" in detail

    ok, detail = run(
        su._test_gemini(
            _client(lambda r: httpx.Response(400, json={"error": {"message": "API key not valid."}})),
            {"MUSICBAZI_GEMINI_API_KEY": "bad"},
            "local",
        )
    )
    assert not ok and "کلید" in detail

    ok, empty = run(su._test_gemini(_client(lambda r: httpx.Response(200, json={})), {}, "local"))
    assert not ok and "خالی" in empty


def test_network_failure_is_not_reported_as_a_bad_key(client, users):
    """فرقی که کاربر ایرانی باید ببیند: «به سرویس وصل نشد» ≠ «کلید غلط»."""

    def boom(request):
        raise httpx.ConnectError("no route")

    uid, _ = users
    client.app.state.http = _client(boom)
    r = client.post(
        "/api/setup/test",
        json={"key": "genius", "values": {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "t"}},
        headers=_auth(uid),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "وصل نشد" in body["detail"]


# ---------------------------------------------------------------- وضعیت


def test_state_masks_keys_and_hides_the_raw_value(client, users):
    uid, _ = users
    credentials.set_many(uid, {"MUSICBAZI_AUDD_TOKEN": "supersecretvalue"}, 1.0)
    body = client.get("/api/setup", headers=_auth(uid)).json()
    assert body["set"]["MUSICBAZI_AUDD_TOKEN"] == "…alue"
    assert "supersecretvalue" not in json.dumps(body)
    assert "env" in body
    # دیگر ری‌استارتی در کار نیست
    assert "restartNeeded" not in body


def test_state_shows_only_the_callers_keys(client, users):
    """
    حسابِ دوم نباید هیچ نشانه‌ای از کلیدهای حسابِ اول ببیند — حتی ماسک‌شده.
    `…alue` هم یک نشت است: به مهاجم می‌گوید کلیدِ درست را حدس زده.
    """
    uid, other = users
    credentials.set_many(uid, {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "tok_abcdefgh"}, 1.0)
    body = client.get("/api/setup", headers=_auth(other)).json()
    assert body["set"] == {}


def test_state_includes_server_only_status(client):
    """وضعیتِ سرور باید دیده شود ولی قابلِ نوشتن نباشد."""
    body = client.get("/api/setup").json()
    assert set(body["env"]) >= {"ffmpeg", "jsRuntime", "potoken", "proxy", "internet", "container"}
    assert body["telegram"]["botTokenSet"] in (True, False)
    assert isinstance(body["telegram"]["connected"], bool)


def test_personal_wizard_cannot_see_or_set_telegram(client, users):
    """
    توکنِ بات مالِ سرور است: یک بات، یک پروسه. اگر در allowlist بود، اولین
    کاربری که ذخیره می‌کرد باتِ همه را می‌دزدید.
    """
    uid, _ = users
    r = client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_TELEGRAM_BOT_TOKEN": "123:abc"}},
        headers=_auth(uid),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------- دروازه‌ی done


def test_done_is_per_account(client, users):
    uid, other = users
    assert client.get("/api/setup", headers=_auth(uid)).json()["done"] is False
    client.post("/api/setup/save", json={"values": {}, "done": True}, headers=_auth(uid))
    assert client.get("/api/setup", headers=_auth(uid)).json()["done"] is True
    # «رد کردنِ» یک حساب نباید ویزاردِ حسابِ دیگر را ببندد
    assert client.get("/api/setup", headers=_auth(other)).json()["done"] is False


def test_saving_a_key_alone_does_not_close_the_gate(client, users):
    """`done` یعنی «کاربر این مرحله را دید»، نه «کلید دارد»."""
    uid, _ = users
    client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_AUDD_TOKEN": "x"}},
        headers=_auth(uid),
    )
    assert client.get("/api/setup", headers=_auth(uid)).json()["done"] is False


def test_gate_opens_for_a_preexisting_single_user_install(client, monkeypatch):
    """
    نصبِ موجودی که `.env` پرش را از قبل دارد نباید بعدِ ارتقا ناگهان «اول
    تنظیم کن» بگوید — این همان معنای تک‌کاربره‌ی امروز است.
    """
    monkeypatch.setattr(cfg, "SPOTIFY_CLIENT_ID", "89ce-real-looking-id")
    assert client.get("/api/setup").json()["done"] is True


def test_gate_stays_shut_on_a_genuinely_fresh_install(client):
    assert client.get("/api/setup").json()["done"] is False


def test_done_flag_alone_opens_the_gate_for_guest(client, monkeypatch):
    """«رد کردن» با کلیدِ خالی هم باید دروازه را برای مهمان باز کند."""
    monkeypatch.setenv("MUSICBAZI_SETUP_DONE", "1")
    assert client.get("/api/setup").json()["done"] is True


def test_guest_skip_writes_the_flag_so_it_survives_a_restart(client, tmp_path, monkeypatch):
    """
    تنها جایی که یک مقدار باید در `.env` بنشیند: ردیفِ مهمان بینِ همه‌ی
    بازدیدکننده‌های بی‌حساب مشترک است، پس `setup_done_at` یعنی «اولین نفر برای
    همه رد کرد».
    """
    monkeypatch.setattr(su, "DATA_DIR", tmp_path)
    monkeypatch.delenv("MUSICBAZI_SETUP_DONE", raising=False)
    # مهمان توکن ندارد، پس save برایش ۴۰۱ است؛ مسیرِ رد کردن از توکنِ مهمان می‌آید
    r = client.post(
        "/api/setup/save", json={"values": {}, "done": True}, headers=_auth(auth.GUEST)
    )
    assert r.status_code == 200 and r.json()["done"] is True
    assert "MUSICBAZI_SETUP_DONE=1" in (tmp_path / ".env").read_text(encoding="utf-8")


# ---------------------------------------------------------------- کوکی


def test_cookies_rejects_wrong_format(client, users):
    uid, _ = users
    r = client.post(
        "/api/setup/cookies",
        files={"file": ("cookies.txt", b'{"cookies": []}', "text/plain")},
        headers=_auth(uid),
    )
    assert r.status_code == 400 and "Netscape" in r.json()["detail"]


def test_cookies_are_shared_and_take_effect_without_a_restart(
    client, users, tmp_path, monkeypatch
):
    """
    کوکی **مشترک** است، به‌خلاف کلیدها: یک فایل روی سرور، برای همه‌ی حساب‌ها.
    گرفتنِ کوکیِ درست سخت است و تکرارش برای هر حساب فقط یوتیوب را برای همه
    می‌شکند.
    """
    import os

    from app import ydl

    uid, other = users
    monkeypatch.setattr(su, "COOKIE_PATH", tmp_path / "cookies" / "youtube.txt")
    monkeypatch.delenv("MUSICBAZI_COOKIES_FILE", raising=False)

    body = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tSID\tabc\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tk\tv\n"
    )
    r = client.post(
        "/api/setup/cookies",
        files={"file": ("c.txt", body, "text/plain")},
        headers=_auth(uid),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cookies"] == 2 and data["youtube"] == 1
    assert os.environ["MUSICBAZI_COOKIES_FILE"] == str(su.COOKIE_PATH)

    # هر دو حساب از همان فایل استفاده می‌کنند، و بی‌ری‌استارت
    assert ydl.auth_opts(uid)["cookiefile"] == str(su.COOKIE_PATH)
    assert ydl.auth_opts(other)["cookiefile"] == str(su.COOKIE_PATH)


def test_the_shared_cookie_shows_up_in_the_server_status(client, users, tmp_path, monkeypatch):
    monkeypatch.setattr(su, "COOKIE_PATH", tmp_path / "cookies" / "youtube.txt")
    assert client.get("/api/setup").json()["env"]["cookies"] is False
    su.COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
    su.COOKIE_PATH.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    assert client.get("/api/setup").json()["env"]["cookies"] is True

