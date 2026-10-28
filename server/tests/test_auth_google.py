"""
آزمونِ جریانِ کاملِ ورود با گوگل.

سرویسِ بیرونی هرگز صدا زده نمی‌شود: `app.state.http` با `httpx.MockTransport`
جای‌گذاری می‌شود (همان الگوی `test_setup.py`). چیزی که محافظت می‌شود: کلیدِ
تشخیصِ کاربرِ بازگشتی، و اینکه داراییِ ورودی (`sub`) با ایمیل قاطی نشود.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, auth_api, config, main
from tests.test_avatar import PNG

PROFILE = {
    "sub": "google-user-1",
    "email": "malicious@example.com",
    "name": "مهان",
    "picture": "https://lh3.googleusercontent.com/avatar",
}


@pytest.fixture
def client(fresh_db, monkeypatch):
    auth.reset_secret_cache()
    auth_api.reset()
    monkeypatch.setattr(main.reach, "REACH_PROBES", ())
    monkeypatch.setattr(auth, "google_configured", lambda: True)
    # ریشه‌ی ورود از تنظیمات می‌آید، نه از یک پرچمِ ساده؛ تست همان چیزی را
    # می‌چیند که کاربر واقعاً می‌چیند.
    monkeypatch.setattr(config, "AUTH_BASE_URL", "https://music.example.com")
    monkeypatch.setattr(config, "AUTH_ALLOWED_ORIGINS", ("http://localhost:8080",))
    monkeypatch.setattr(main.reach, "online", lambda: True)
    with TestClient(main.app) as c:
        yield c


def install_google(monkeypatch, profile: dict | None = None, *, token_ok: bool = True):
    """شبکه‌ی گوگل را با پاسخ‌های ثابت جای‌گذاری می‌کند."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in request.url.host:
            return httpx.Response(200, json={"access_token": "at-1"} if token_ok else {})
        return httpx.Response(200, json=profile or PROFILE)

    original = main.app.state.http
    main.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return original


def start_and_state(client) -> str:
    res = client.get("/api/auth/google/start", follow_redirects=False)
    assert res.status_code == 302
    return parse_qs(urlparse(res.headers["location"]).query)["state"][0]


def test_full_google_roundtrip_creates_a_user(client, monkeypatch):
    original = install_google(monkeypatch)
    try:
        state = start_and_state(client)
        res = client.get(
            f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False
        )
    finally:
        main.app.state.http = original

    assert res.status_code == 302
    location = res.headers["location"]
    assert "#auth=" in location
    # توکن در fragment می‌آید، نه query — fragment در لاگِ سرور نمی‌نشیند
    assert "?auth=" not in location

    token = parse_qs(urlparse(location).query).get("auth")
    assert token is None
    token = unquote(location.split("#auth=", 1)[1])
    assert auth.read_session(token) is not None


def test_google_signin_reuses_the_same_user_by_sub(client, monkeypatch):
    """
    کلیدِ تشخیص `sub` است، نه ایمیل.

    اگر ایمیل کلید بود، دو حسابِ گوگل با ایمیلِ یکسان (یا کسی که ایمیلش را
    عوض کرده) می‌توانستند به حسابِ همدیگر برسند.
    """
    original = install_google(monkeypatch)
    try:
        first = client.get(
            f"/api/auth/google/callback?code=a&state={start_and_state(client)}",
            follow_redirects=False,
        )
        first_token = unquote(first.headers["location"].split("#auth=", 1)[1])

        # همان کاربر، ولی نام و ایمیل در گوگل عوض شده
        changed = {"sub": "google-user-1", "email": "new@example.com", "name": "نام تازه"}

        def renamed(request: httpx.Request) -> httpx.Response:
            if "oauth2" in request.url.host:
                return httpx.Response(200, json={"access_token": "at-2"})
            return httpx.Response(200, json=changed)

        main.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(renamed))
        second = client.get(
            f"/api/auth/google/callback?code=b&state={start_and_state(client)}",
            follow_redirects=False,
        )
        second_token = unquote(second.headers["location"].split("#auth=", 1)[1])
    finally:
        main.app.state.http = original

    assert auth.read_session(first_token) == auth.read_session(second_token)


def test_google_account_keeps_a_chosen_username(client, monkeypatch):
    """ورودِ دوباره نباید نام کاربریِ انتخابیِ کاربر را پاک کند."""
    from app import db

    original = install_google(monkeypatch)
    try:
        res = client.get(
            f"/api/auth/google/callback?code=a&state={start_and_state(client)}",
            follow_redirects=False,
        )
        token = unquote(res.headers["location"].split("#auth=", 1)[1])
        user_id = auth.read_session(token)
        db.set_user_username(user_id, "mahan")

        main.app.state.http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={"access_token": "at-2"} if "oauth2" in r.url.host else PROFILE,
                )
            )
        )
        client.get(
            f"/api/auth/google/callback?code=b&state={start_and_state(client)}",
            follow_redirects=False,
        )
    finally:
        main.app.state.http = original

    assert db.user_by_id(user_id)["username"] == "mahan"


def test_google_avatar_is_cached_on_disk(client, monkeypatch):
    """
    عکسِ گوگل روی دیسک می‌آید تا در قطعیِ بین‌الملل هم دیده شود.

    `googleusercontent.com` روی اینترنتِ بین‌الملل است؛ اگر فقط آدرس را نگه
    داریم، پروفایلِ کتابخانه‌ای که کاملاً آفلاین کار می‌کند بی‌عکس می‌شود.
    """
    from app import avatar, db

    def handler(request: httpx.Request) -> httpx.Response:
        if "googleusercontent" in request.url.host:
            return httpx.Response(200, content=PNG)
        if "oauth2" in request.url.host:
            return httpx.Response(200, json={"access_token": "at-1"})
        return httpx.Response(200, json=PROFILE)

    original = main.app.state.http
    main.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        res = client.get(
            f"/api/auth/google/callback?code=a&state={start_and_state(client)}",
            follow_redirects=False,
        )
        token = unquote(res.headers["location"].split("#auth=", 1)[1])
        user_id = auth.read_session(token)
    finally:
        main.app.state.http = original

    assert db.user_by_id(user_id)["avatar_file"]
    assert avatar.path_for(user_id) is not None


def test_missing_access_token_is_reported_not_crashed(client, monkeypatch):
    """پاسخِ ناقصِ گوگل نباید ۵۰۰ بدهد؛ باید برگردد به صفحه‌ی ورود با دلیل."""
    original = install_google(monkeypatch, token_ok=False)
    try:
        res = client.get(
            f"/api/auth/google/callback?code=a&state={start_and_state(client)}",
            follow_redirects=False,
        )
    finally:
        main.app.state.http = original
    assert res.status_code == 302
    assert "auth_error=invalid" in res.headers["location"]


def test_profile_without_sub_is_rejected(client, monkeypatch):
    original = install_google(monkeypatch, {"email": "x@example.com", "name": "x"})
    try:
        res = client.get(
            f"/api/auth/google/callback?code=a&state={start_and_state(client)}",
            follow_redirects=False,
        )
    finally:
        main.app.state.http = original
    assert "auth_error=invalid" in res.headers["location"]


def test_state_expires(client, monkeypatch):
    """stateِ کهنه نباید قابل خرج شدن باشد."""
    original = install_google(monkeypatch)
    try:
        state = start_and_state(client)
        # ساعت را جلو می‌بریم تا TTL رد شود
        born, target, origin = auth_api._states[state]
        auth_api._states[state] = (born - auth_api._STATE_TTL - 1, target, origin)
        res = client.get(
            f"/api/auth/google/callback?code=a&state={state}", follow_redirects=False
        )
    finally:
        main.app.state.http = original
    assert "auth_error=expired" in res.headers["location"]


def test_return_to_cannot_leave_the_site(client, monkeypatch):
    """
    `return_to` باید نسبی بماند.

    بدونِ این، یک لینکِ دست‌کاری‌شده می‌تواند کاربر را بعدِ ورود به سایتِ
    دیگری پرت کند — و آن سایت توکن را از fragment برمی‌دارد.
    """
    original = install_google(monkeypatch)
    try:
        res = client.get(
            "/api/auth/google/start?return_to=https://evil.example.com",
            follow_redirects=False,
        )
        state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
        back = client.get(
            f"/api/auth/google/callback?code=a&state={state}", follow_redirects=False
        )
    finally:
        main.app.state.http = original
    assert "evil.example.com" not in back.headers["location"]


def test_oauth_state_is_cleaned_up_over_time(client):
    """statesِ رهاشده نباید تا ابد در حافظه بمانند."""
    auth_api.reset()
    auth_api._states["old"] = (time.time() - auth_api._STATE_TTL - 1, "/", "https://music.example.com")
    auth_api._states["new"] = (time.time(), "/", "https://music.example.com")
    auth_api._prune_states(time.time())
    assert "old" not in auth_api._states
    assert "new" in auth_api._states


# ---------------------------------------------------------------- انتخابِ ریشه
#
# گوگل `redirect_uri` را *دقیق* مچ می‌کند، پس هم‌زمانیِ دامنه و `localhost` یعنی
# دو URI ثبت‌شده و انتخابِ درست به‌ازای هر درخواست. این تست‌ها همان قرارداد را
# قفل می‌کنند — از جمله سمتِ امنیتی‌اش: ریشه هرگز از هدرِ آزاد گرفته نمی‌شود.


def test_origin_from_the_request_picks_the_matching_registered_root(client):
    """کاربری که از `localhost` می‌آید باید با همان ریشه به گوگل برود."""
    res = client.get(
        "/api/auth/google/start",
        headers={"Origin": "http://localhost:8080"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    params = parse_qs(urlparse(res.headers["location"]).query)
    assert params["redirect_uri"][0] == "http://localhost:8080/api/auth/google/callback"


def test_origin_falls_back_to_the_primary_root_without_the_header(client):
    """ناوبریِ سطح‌بالا همیشه `Origin` نمی‌فرستد — باید به ریشه‌ی اصلی برگردد."""
    res = client.get("/api/auth/google/start", follow_redirects=False)
    assert res.status_code == 302
    params = parse_qs(urlparse(res.headers["location"]).query)
    assert params["redirect_uri"][0] == "https://music.example.com/api/auth/google/callback"


def test_an_unlisted_origin_is_never_used_as_the_redirect(client):
    """
    بسته‌بودنِ لیست، همان مرزِ امنیتی است.

    اگر ریشه از هدرِ آزاد گرفته می‌شد، مهاجم با یک لینکِ
    `/api/auth/google/start` + `Origin` دلخواه، کاربر را به صفحه‌ی رضایت گوگل
    می‌کشاند و کدِ برگشتی را روی دامنه‌ی خودش می‌گرفت.
    """
    res = client.get(
        "/api/auth/google/start",
        headers={"Origin": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    params = parse_qs(urlparse(res.headers["location"]).query)
    assert params["redirect_uri"][0] == "https://music.example.com/api/auth/google/callback"


def test_the_token_exchange_reuses_the_origins_redirect_uri(client, monkeypatch):
    """
    `redirect_uri` در تبادلِ کد باید مو‌به‌مو همانی باشد که در `start` فرستادیم.

    اگر این دو یکی نباشند، گوگل با `redirect_uri_mismatch` رد می‌کند — و
    چون ریشه بسته به دامنه/`localhost` فرق دارد، این تست همان حالتی را
    می‌پوشاند که یک مقدارِ ثابت از دستش می‌داد.
    """
    seen: list[str] = []
    original = main.app.state.http

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in request.url.host:
            seen.append(request.content.decode())
            return httpx.Response(200, json={"access_token": "at-1"})
        return httpx.Response(200, json=PROFILE)

    main.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        res = client.get(
            "/api/auth/google/start",
            headers={"Origin": "http://localhost:8080"},
            follow_redirects=False,
        )
        state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
        back = client.get(
            f"/api/auth/google/callback?code=a&state={state}", follow_redirects=False
        )
    finally:
        main.app.state.http = original

    assert "http%3A%2F%2Flocalhost%3A8080%2Fapi%2Fauth%2Fgoogle%2Fcallback" in seen[0]
    # و بازگشت هم به همان ریشه است، نه به دامنه‌ی اصلی
    assert back.headers["location"].startswith("http://localhost:8080/")
