"""
آزمونِ حساب کاربری و ورود.

چیزی که این فایل از آن محافظت می‌کند: رمز و اعتبارِ توکن. یک اشتباه این‌جا
یعنی یا کسی با رمزِ غلط وارد می‌شود، یا کاربر با هر ری‌استارت از حسابش بیرون
می‌افتد، یا توکنِ یک ساعتهٔ مدیا مثل توکنِ یک‌سالهٔ نشست قبول می‌شود.

هیچ سرویسِ بیرونی صدا زده نمی‌شود.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import auth, config, main


@pytest.fixture
def client(fresh_db, monkeypatch):
    # رازِ امضا زیر `DATA_DIR` موقتِ conftest می‌نشیند، ولی کشِ ماژول بین
    # آزمایِش‌ها می‌ماند — پاکش می‌کنیم تا هر تست از صفر شروع کند
    auth.reset_secret_cache()
    monkeypatch.setattr(main.reach, "REACH_PROBES", ())
    # ریشه‌ی ورودِ گوگل: مسیرهای گوگل به ریشه‌ای نیاز دارند که گوگل بپذیرد،
    # وگرنه همان اول ۴۰۰ می‌گیرند. خودِ این تست‌ها به مقدارش کاری ندارند.
    monkeypatch.setattr(config, "AUTH_BASE_URL", "https://music.example.com")
    with TestClient(main.app) as c:
        yield c


def token_of(res) -> str:
    return res.json()["token"]


# ---------------------------------------------------------------- رمز


def test_password_roundtrip():
    stored = auth.hash_password("correct horse battery")
    assert stored.startswith("scrypt$")
    # نمک باید تصادفی باشد، وگرنه دو کاربرِ هم‌رمز هشِ یکسان می‌گیرند
    assert stored != auth.hash_password("correct horse battery")


def test_password_rejects_wrong_and_malformed():
    stored = auth.hash_password("correct horse battery")
    assert auth.verify_password("wrong horse battery", stored) is False
    assert auth.verify_password("correct horse battery", stored) is True
    # ردیفِ نیمه‌ساخته یا مقدارِ خالی باید «رمز غلط» باشد، نه استثنا
    assert auth.verify_password("x", "") is False
    assert auth.verify_password("x", None) is False
    assert auth.verify_password("x", "bcrypt$whatever") is False


def test_short_password_is_rejected():
    with pytest.raises(auth.AuthError) as exc:
        auth.check_password_strength("short")
    assert exc.value.status_code == 400


@pytest.mark.parametrize("bad", ["ab", "a" * 25, "has space", "bad@sign", "faرسی"])
def test_bad_usernames_rejected(bad):
    with pytest.raises(auth.AuthError):
        auth.normalize_username(bad)


# ---------------------------------------------------------------- توکن


def test_session_token_roundtrip():
    token, expires = auth.mint_session("abc123")
    assert expires > time.time()
    assert auth.read_session(token) == "abc123"


def test_session_rejects_tampering():
    token, _ = auth.mint_session("abc123")
    payload, signature = token.rsplit(".", 1)

    # امضای دست‌کاری‌شده
    assert auth.read_session(f"{payload}.{signature[:-1]}x") is None
    # کاربرِ عوض‌شده با امضای قدیمی — همان حمله‌ای که امضا برایش هست
    assert auth.read_session(f"other:{payload.split(':')[1]}.{signature}") is None
    # بی‌ریخت
    assert auth.read_session("garbage") is None
    assert auth.read_session("") is None
    assert auth.read_session(None) is None


def test_expired_session_is_rejected():
    token, _ = auth.mint_session("abc123", days=0)
    assert auth.read_session(token) is None


def test_media_token_cannot_be_used_as_session():
    """
    دو نوع توکن با دو پیشوند امضا می‌شوند.

    بدونِ این جدایی، یک URLِ پخشِ نشتی (که در لاگِ سرور می‌ماند) دسترسیِ کاملِ
    حساب را می‌داد.
    """
    media, _ = auth.mint_media("abc123")
    session, _ = auth.mint_session("abc123")
    assert auth.read_session(media) is None
    assert auth.read_media(session) is None


def test_media_token_has_short_life():
    media, expires = auth.mint_media("abc123")
    assert auth.read_media(media) == "abc123"
    # پیش‌فرض یک ساعت است، نه ماه‌ها
    assert expires - time.time() < 3700


# ---------------------------------------------------------------- ثبت‌نام و ورود


def test_register_then_login(client):
    res = client.post(
        "/api/auth/local/register",
        json={"username": "mahan", "password": "hunter2hunter2", "displayName": "مهان"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user"]["username"] == "mahan"
    assert body["user"]["displayName"] == "مهان"
    assert body["user"]["kind"] == "local"
    # هشِ رمز هرگز نباید بیرون برود
    assert "password" not in res.text.lower() or "passwordHash" not in res.text

    again = client.post(
        "/api/auth/local/login",
        json={"username": "mahan", "password": "hunter2hunter2"},
    )
    assert again.status_code == 200
    assert again.json()["user"]["id"] == body["user"]["id"]


def test_login_accepts_username_case_insensitively(client):
    client.post("/api/auth/local/register", json={"username": "Mahan", "password": "hunter2hunter2"})
    res = client.post("/api/auth/local/login", json={"username": "mahan", "password": "hunter2hunter2"})
    assert res.status_code == 200


def test_duplicate_username_rejected(client):
    client.post("/api/auth/local/register", json={"username": "mahan", "password": "hunter2hunter2"})
    res = client.post("/api/auth/local/register", json={"username": "MAHAN", "password": "another2pass"})
    assert res.status_code == 409


def test_wrong_password_and_unknown_user_look_the_same(client):
    """
    یک پیام برای هر دو حالت.

    تفکیک‌شان به کسی که رمز حدس می‌زند می‌گوید کدام نام‌های کاربری وجود دارند.
    """
    client.post("/api/auth/local/register", json={"username": "mahan", "password": "hunter2hunter2"})
    wrong = client.post("/api/auth/local/login", json={"username": "mahan", "password": "nope-nope-nope"})
    unknown = client.post("/api/auth/local/login", json={"username": "ghost", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_profile(client):
    token = token_of(
        client.post("/api/auth/local/register", json={"username": "mahan", "password": "hunter2hunter2"})
    )
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["username"] == "mahan"
    assert res.json()["hasPassword"] is True


def test_garbage_token_is_unauthorized(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert res.status_code == 401


def test_token_for_deleted_user_is_unauthorized(client, fresh_db):
    """توکنِ امضاشده ولی متعلق به کاربری که دیگر نیست نباید کار کند."""
    token, _ = auth.mint_session("ghost-user")
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


# ---------------------------------------------------------------- پروفایل


def test_update_username_and_display_name(client):
    token = token_of(
        client.post("/api/auth/local/register", json={"username": "mahan", "password": "hunter2hunter2"})
    )
    headers = {"Authorization": f"Bearer {token}"}
    res = client.patch(
        "/api/auth/me",
        json={"username": "mahnamusic", "displayName": "مهنام"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["username"] == "mahnamusic"
    assert res.json()["displayName"] == "مهنام"


def test_taken_username_rejected_on_update(client):
    client.post("/api/auth/local/register", json={"username": "first", "password": "hunter2hunter2"})
    token = token_of(
        client.post("/api/auth/local/register", json={"username": "second", "password": "hunter2hunter2"})
    )
    res = client.patch(
        "/api/auth/me",
        json={"username": "first"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 409


def test_username_can_be_cleared(client):
    """کاربرِ گوگل ممکن است اصلاً نامِ کاربری نخواهد."""
    token = token_of(
        client.post("/api/auth/local/register", json={"username": "mahan", "password": "hunter2hunter2"})
    )
    res = client.patch(
        "/api/auth/me",
        json={"username": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["username"] is None


# ---------------------------------------------------------------- مهمان


def test_guest_row_exists(client):
    """`local` یک ردیفِ واقعی است — وگرنه هر درخواستِ بی‌توکن به کاربرِ ناموجود اشاره می‌کند."""
    from app import db

    row = db.user_by_id(auth.GUEST)
    assert row is not None
    assert row["kind"] == "guest"


def test_media_token_requires_login(client):
    assert client.post("/api/auth/media").status_code == 401


def test_media_token_issued_for_logged_in_user(client):
    token = token_of(
        client.post("/api/auth/local/register", json={"username": "mahan", "password": "hunter2hunter2"})
    )
    res = client.post("/api/auth/media", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert auth.read_media(body["token"]) is not None


# ---------------------------------------------------------------- گوگل


def test_providers_reports_google_off_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(auth, "google_configured", lambda: False)
    res = client.get("/api/auth/providers")
    assert res.status_code == 200
    assert res.json() == {"google": False, "googleReason": "not_configured"}


def test_providers_reports_google_off_on_lan(monkeypatch):
    """
    گوگل روی `http://192.168.x.x` کار نمی‌کند و باید در UI غیرفعال شود.

    بدونِ این، کاربر به صفحه‌ی گوگل می‌رود و هیچ‌وقت برنمی‌گردد.
    """
    monkeypatch.setattr(auth, "google_configured", lambda: True)
    monkeypatch.setattr(auth, "google_callback_is_reachable", lambda: False)
    from app.auth_api import providers

    body = asyncio.run(providers())
    assert body.google is False
    assert body.googleReason == "needs_https"


def test_google_start_without_config_is_a_clear_error(client, monkeypatch):
    monkeypatch.setattr(auth, "google_configured", lambda: False)
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 400


def test_google_start_offline_reports_intranet(client, monkeypatch):
    monkeypatch.setattr(auth, "google_configured", lambda: True)
    monkeypatch.setattr(auth, "google_callback_is_reachable", lambda: True)
    monkeypatch.setattr(main.reach, "online", lambda: False)
    res = client.get("/api/auth/google/start", follow_redirects=False)
    assert res.status_code == 503


def test_google_start_redirects_with_state(client, monkeypatch):
    monkeypatch.setattr(auth, "google_configured", lambda: True)
    monkeypatch.setattr(auth, "google_callback_is_reachable", lambda: True)
    monkeypatch.setattr(main.reach, "online", lambda: True)
    res = client.get("/api/auth/google/start", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"].startswith("https://accounts.google.com/")
    assert "state=" in res.headers["location"]


def test_google_callback_with_bad_state_fails_closed(client):
    res = client.get("/api/auth/google/callback?code=x&state=nope", follow_redirects=False)
    assert res.status_code == 302
    assert "auth_error=expired" in res.headers["location"]


def test_google_state_is_single_use(client, monkeypatch):
    """state نباید دوباره قابل خرج شدن باشد — وگرنه بازپخشِ callback ممکن می‌شود."""
    import httpx

    from app import auth_api

    auth_api.reset()
    auth_api._states["once"] = (time.time(), "/", "https://music.example.com")

    # شبکه‌ی گوگل در دسترس نیست: state باید با این حال هم مصرف شده باشد
    class Dead:
        async def post(self, *a, **k):
            raise httpx.ConnectError("شبکه نیست")

    original = main.app.state.http
    main.app.state.http = Dead()
    try:
        first = client.get("/api/auth/google/callback?code=x&state=once", follow_redirects=False)
        second = client.get("/api/auth/google/callback?code=x&state=once", follow_redirects=False)
    finally:
        main.app.state.http = original

    second = client.get("/api/auth/google/callback?code=x&state=once", follow_redirects=False)
    assert "auth_error=unreachable" in first.headers["location"]
    assert "auth_error=expired" in second.headers["location"]
    # stateِ مصرف‌شده در حافظه نمی‌ماند
    assert "once" not in auth_api._states
