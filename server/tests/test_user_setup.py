"""
جداسازیِ ویزاردِ ستاپ بینِ حساب‌ها — از دیدِ HTTP، روی اپِ کامل.

`test_setup.py` منطقِ خودِ ویزارد را می‌سنجد (آزمودنِ کلید، قالبِ کوکی، مرزهای
نوشتن). این فایل همان قرارداد را از بیرون نگاه می‌کند و دقیقاً همان چیزهایی را
می‌پرسد که در تأییدِ پلن آمده بود:

  ۱. دو حساب کلیدِ هم را نمی‌بینند.
  ۲. مهمان کلیدِ `.env` را می‌بیند، ولی نمی‌تواند چیزی بنویسد.
  ۳. پاک‌کردنِ صریح پایدار است و به سراسری برنمی‌گردد.
  ۴. `save`/`test`/`cookies` بی‌توکن ۴۰۱ می‌دهند.
  ۵. `done` per-account است.
  ۶. کوکی **مشترک** است: آپلود از یک حساب، برای حسابِ دیگر هم دیده می‌شود.
  ۷. هیچ نوشتنی در `.env` رخ نمی‌دهد.

هیچ سرویسِ بیرونی صدا زده نمی‌شود.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth
from app import config as cfg
from app import credentials
from app import db
from app import main
from app import setup as su

pytestmark = pytest.mark.usefixtures("fresh_db")


@pytest.fixture
def client(fresh_db, monkeypatch):
    # محیطِ سرور در GET /api/setup خوانده می‌شود؛ شبکه‌ی واقعی لازم نیست
    monkeypatch.setattr(main.reach, "REACH_PROBES", ())
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def users(fresh_db):
    db.create_user(
        "u_one", "password", username="alice", password_hash=auth.hash_password("password123")
    )
    db.create_user(
        "u_two", "password", username="bob", password_hash=auth.hash_password("password123")
    )
    return "u_one", "u_two"


def _auth(user_id: str) -> dict[str, str]:
    token, _ = auth.mint_session(user_id)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- جداسازی


def test_two_accounts_never_see_each_others_keys(client, users):
    """قلبِ پلن: کلیدِ یک حساب در پاسخِ حسابِ دیگر نیست."""
    one, two = users
    client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "alice-secret-key"}},
        headers=_auth(one),
    )

    mine = client.get("/api/setup", headers=_auth(one)).json()
    theirs = client.get("/api/setup", headers=_auth(two)).json()

    assert "MUSICBAZI_GENIUS_ACCESS_TOKEN" in mine["set"]
    assert theirs["set"] == {}
    # حتی چهار رقمِ آخر هم نباید درسمتِ دیگری دیده شود
    assert "alice-secret-key" not in theirs["set"].values()


def test_values_are_stored_against_the_account_not_globally(client, users):
    one, two = users
    client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_AUDD_TOKEN": "audd-one"}},
        headers=_auth(one),
    )
    assert credentials.get(one, "audd_token") == "audd-one"
    assert credentials.get(two, "audd_token") is None


# ---------------------------------------------------------------- مهمان


def test_guest_sees_the_global_env_and_cannot_write(client, monkeypatch):
    monkeypatch.setattr(cfg, "GENIUS_ACCESS_TOKEN", "operator-token")

    state = client.get("/api/setup").json()
    assert "MUSICBAZI_GENIUS_ACCESS_TOKEN" in state["set"]

    r = client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "mine"}},
    )
    assert r.status_code == 401
    # نوشتن رد شد، پس مقدارِ سراسری دست‌نخورده ماند
    assert credentials.effective(db.GUEST_ID, "genius_access_token") == "operator-token"


def test_an_explicit_clear_stays_cleared_for_the_guest(client, monkeypatch):
    """رشته‌ی خالی یعنی «پاک شده» — نه اینکه رفرشِ بعدی سراسری را برگرداند."""
    monkeypatch.setattr(cfg, "GENIUS_ACCESS_TOKEN", "operator-token")
    assert credentials.effective(db.GUEST_ID, "genius_access_token") == "operator-token"

    db.put_user_secrets(db.GUEST_ID, {"genius_access_token": ""}, 1.0)
    assert credentials.effective(db.GUEST_ID, "genius_access_token") is None
    assert "MUSICBAZI_GENIUS_ACCESS_TOKEN" not in credentials.masked_map(db.GUEST_ID)


def test_guest_may_still_skip_the_wizard(client, tmp_path, monkeypatch):
    monkeypatch.setattr(su, "DATA_DIR", tmp_path)
    monkeypatch.delenv("MUSICBAZI_SETUP_DONE", raising=False)

    r = client.post("/api/setup/save", json={"values": {}, "done": True})
    assert r.status_code == 200 and r.json()["done"] is True


# ---------------------------------------------------------------- احراز هویت


def test_save_test_and_cookies_reject_an_anonymous_caller(client):
    """
    سرور عمومی می‌شود؛ بی‌توکن یعنی هیچ‌کس نباید کلید و کوکی عوض کند.

    استثنای عمدی: `save` با بدنه‌ی بی‌کلید برای مهمان مجاز است، چون دروازه
    باید همان‌طور که پلن خواسته با «رد کردن» بسته شود و مهمان حسابی برای
    توکن‌گرفتن ندارد. نوشتنِ مقدار همچنان ۴۰۱ است (تستِ بالا).
    """
    assert (
        client.post(
            "/api/setup/save",
            json={"values": {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "x"}},
        ).status_code
        == 401
    )
    assert client.post("/api/setup/test", json={"key": "genius", "values": {}}).status_code == 401
    assert client.post("/api/setup/cookies").status_code == 401


def test_get_stays_open_for_the_guest(client):
    """صفحه‌ی تنظیمات باید برای بازدیدکننده‌ی بی‌حساب هم وضعیتِ سرور را بدهد."""
    r = client.get("/api/setup")
    assert r.status_code == 200
    assert set(r.json()) >= {"done", "set", "env", "telegram"}


# ---------------------------------------------------------------- done


def test_done_is_per_account(client, users):
    """یک حساب رد می‌کند؛ حسابِ دیگر باید هنوز ویزارد را ببیند."""
    one, two = users
    client.post("/api/setup/save", json={"values": {}, "done": True}, headers=_auth(one))

    assert client.get("/api/setup", headers=_auth(one)).json()["done"] is True
    assert client.get("/api/setup", headers=_auth(two)).json()["done"] is False


def test_done_is_not_implied_by_having_a_key(client, users, monkeypatch):
    """`done` یعنی «کاربر این مرحله را دید»، نه «کلید دارد»."""
    monkeypatch.setattr(cfg, "GEMINI_API_KEY", "operator-key")
    one, _ = users
    client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_GEMINI_API_KEY": "my-key"}},
        headers=_auth(one),
    )
    assert client.get("/api/setup", headers=_auth(one)).json()["done"] is False


# ---------------------------------------------------------------- کوکیِ مشترک


_COOKIE = "\n".join(
    [
        "# Netscape HTTP Cookie File",
        ".youtube.com\tTRUE\t/\tFALSE\t1999999999\tVISITOR_INFO1_LIVE\tabc",
        ".youtube.com\tTRUE\t/\tFALSE\t1999999999\tPREF\tf1=50000000",
    ]
)


def test_the_cookie_is_shared_between_accounts(client, users, tmp_path, monkeypatch):
    """
    تصمیمِ صریحِ این نسخه: کوکیِ یوتیوب مشترک است. یک فایل روی سرور، همه از
    آن استفاده می‌کنند — برخلافِ کلیدهای API که مالِ هر حساب‌اند.
    """
    one, two = users
    shared = tmp_path / "cookies" / "youtube.txt"
    monkeypatch.setattr(su, "COOKIE_PATH", shared)

    r = client.post(
        "/api/setup/cookies",
        files={"file": ("cookies.txt", _COOKIE.encode(), "text/plain")},
        headers=_auth(one),
    )
    assert r.status_code == 200 and r.json()["youtube"] == 2

    # مسیرِ همان فایل برای هر دو حساب یکی است — یک فایل، یک مسیر، همه‌ی حساب‌ها
    assert su.cookies_path(one) == su.cookies_path(two) == shared
    assert shared.exists()

    # و در وضعیتِ سرور (نه در setِ شخصی) دیده می‌شود
    state = client.get("/api/setup", headers=_auth(two)).json()
    assert state["env"]["cookies"] is True
    assert state["set"] == {}


def test_cookies_never_write_the_file_path_into_a_user_row(client, users, tmp_path, monkeypatch):
    """کوکی کلیدِ شخصی نیست؛ نباید در `user_secrets` برود."""
    one, _ = users
    monkeypatch.setattr(su, "COOKIE_PATH", tmp_path / "cookies" / "youtube.txt")
    client.post(
        "/api/setup/cookies",
        files={"file": ("cookies.txt", _COOKIE.encode(), "text/plain")},
        headers=_auth(one),
    )
    assert db.get_user_secret(one, "cookies_file") is None


# ---------------------------------------------------------------- `.env`


def test_saving_never_writes_a_global_env_file(client, users, tmp_path, monkeypatch):
    """تک‌تکِ کلیدها از راهِ API نوشته می‌شوند و هیچ‌کدام `.env` را لمس نمی‌کند."""
    one, _ = users
    monkeypatch.setattr(su, "DATA_DIR", tmp_path)

    for key in su.ALLOWED_KEYS:
        client.post(
            "/api/setup/save",
            json={"values": {key: "value-123456789"}},
            headers=_auth(one),
        )

    assert not (tmp_path / ".env").exists()


def test_a_key_outside_the_allowlist_is_rejected(client, users):
    """پروکسی/توکنِ بات مالِ سرور است — نوشتنشان از این‌جا مسیرِ SSRF می‌شد."""
    one, _ = users
    r = client.post(
        "/api/setup/save",
        json={"values": {"MUSICBAZI_PROXY": "http://127.0.0.1:9"}},
        headers=_auth(one),
    )
    assert r.status_code == 400
