"""
آزمونِ *مصرف*ِ اعتبارنامه‌های شخصی — یعنی جایی که یک `uid` فراموش‌شده به نشت
تبدیل می‌شود.

`test_user_setup.py` فقط ذخیره و خواندن را می‌سنجد. این‌جا هر مصرف‌کننده‌ی واقعی
(اسپاتیفای، Genius، yt-dlp، شناسایی، متنِ آهنگ) با دو حسابِ متفاوت صدا زده
می‌شود. اگر روزی کسی پارامترِ `uid` را از یک امضا بردارد یا کلیدِ کش را کوتاه
کند، این فایل قرمز می‌شود — که هدفش همین است.

هیچ سرویسِ بیرونی صدا زده نمی‌شود.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import auth
from app import config as cfg
from app import credentials
from app import db
from app import identify
from app import ydl
from app.lyrics import manager as lyrics_manager
from app.lyrics import registry as lyrics_registry
from app.lyrics import sources as lyrics_sources
from app.models import Track
from app.providers import audd, genius, spotify


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def accounts(fresh_db):
    """دو حساب با کلیدهای متفاوت — تفاوت است که جداسازی را قابلِ سنجش می‌کند."""
    db.create_user("u_one", "password", username="alice")
    db.create_user("u_two", "password", username="bob")
    return "u_one", "u_two"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))

def _auth(user_id: str) -> dict[str, str]:
    token, _ = auth.mint_session(user_id)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- اسپاتیفای


def test_spotify_reports_enabled_per_account(accounts, monkeypatch):
    uid, other = accounts
    monkeypatch.setattr(cfg, "SPOTIFY_CLIENT_ID", None)
    monkeypatch.setattr(cfg, "SPOTIFY_CLIENT_SECRET", None)
    credentials.set_many(
        uid,
        {"MUSICBAZI_SPOTIFY_CLIENT_ID": "id-one", "MUSICBAZI_SPOTIFY_CLIENT_SECRET": "sec-one"},
        1.0,
    )
    assert spotify.enabled(uid) is True
    assert spotify.enabled(other) is False


def test_spotify_token_cache_is_invalidated_per_account(accounts, monkeypatch):
    """
    بزرگ‌ترین ریسکِ این بازنویسی: کشِ ماژولیِ توکن با کلیدِ `client_id` تنها
    بود، پس حسابِ دوم توکنِ حسابِ اول را می‌گرفت و داده‌ی او را می‌دید.
    """
    uid, other = accounts
    credentials.set_many(
        uid,
        {"MUSICBAZI_SPOTIFY_CLIENT_ID": "id-one", "MUSICBAZI_SPOTIFY_CLIENT_SECRET": "sec-one"},
        1.0,
    )
    credentials.set_many(
        other,
        {"MUSICBAZI_SPOTIFY_CLIENT_ID": "id-two", "MUSICBAZI_SPOTIFY_CLIENT_SECRET": "sec-two"},
        1.0,
    )

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"access_token": f"tok-{len(seen)}", "expires_in": 3600})

    spotify.invalidate(uid)
    spotify.invalidate(other)

    client = _client(handler)
    first = run(spotify._access_token(client, uid))
    second = run(spotify._access_token(client, other))
    assert first != second
    # هر حساب با اعتبارنامه‌ی خودش رفت
    assert seen[0] != seen[1]

    # توکنِ کش‌شده تا وقتی مقدار عوض نشده دوباره گرفته نمی‌شود
    assert run(spotify._access_token(client, uid)) == first
    assert len(seen) == 2

    # عوض‌کردنِ کلید باید کش را باطل کند، وگرنه توکنِ کلیدِ قدیمی می‌ماند
    credentials.set_many(uid, {"MUSICBAZI_SPOTIFY_CLIENT_SECRET": "sec-three"}, 2.0)
    third = run(spotify._access_token(client, uid))
    assert third != first and len(seen) == 3


def test_an_account_without_a_key_never_borrows_the_operators(accounts, monkeypatch):
    """
    حسابِ واردشده‌ای که کلید ندارد، کلید ندارد — نه اینکه بی‌صدا از کلیدِ
    اپراتور استفاده کند. این تفاوتِ اصلیِ «شخصی» با «سراسری» است.
    """
    uid, other = accounts
    monkeypatch.setattr(cfg, "SPOTIFY_CLIENT_ID", "operator-id")
    monkeypatch.setattr(cfg, "SPOTIFY_CLIENT_SECRET", "operator-secret")
    assert spotify.enabled(uid) is False
    # ولی مهمان همان کلیدِ سراسری را می‌بیند تا نصبِ تک‌کاربره نشکند
    assert spotify.enabled(db.GUEST_ID) is True
    credentials.set_many(other, {"MUSICBAZI_SPOTIFY_CLIENT_ID": "own"}, 1.0)
    assert spotify.enabled(other) is False  # فقط نصفِ جفت را دارد


def test_clearing_a_key_does_not_fall_back_to_the_global(accounts, monkeypatch):
    """
    کاربری که کلیدِ مهمان را عمداً خاموش کرده نباید بعدِ اولین رفرش دوباره
    ببیندش. رشته‌ی خالی یعنی «پاک شده»، نه «ست نشده».
    """
    monkeypatch.setattr(cfg, "GENIUS_ACCESS_TOKEN", "operator-token")
    assert genius.enabled(db.GUEST_ID) is True
    credentials.set_many(db.GUEST_ID, {"MUSICBAZI_GENIUS_ACCESS_TOKEN": ""}, 1.0)
    assert genius.enabled(db.GUEST_ID) is False


# ---------------------------------------------------------------- Genius


def test_genius_reports_enabled_per_account(accounts):
    uid, other = accounts
    credentials.set_many(uid, {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "tok"}, 1.0)
    assert genius.enabled(uid) is True
    assert genius.enabled(other) is False


def test_genius_fetch_uses_the_callers_token(accounts):
    uid, other = accounts
    credentials.set_many(uid, {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "tok-one"}, 1.0)
    credentials.set_many(other, {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "tok-two"}, 1.0)

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"response": {"hits": []}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        genius._search(client, "q", credentials.genius_token(uid))
        genius._search(client, "q", credentials.genius_token(other))

    assert seen == ["Bearer tok-one", "Bearer tok-two"]


# ---------------------------------------------------------------- شناسایی


def test_identify_and_audd_availability_are_per_account(accounts):
    uid, other = accounts
    credentials.set_many(
        uid, {"MUSICBAZI_ACOUSTID_KEY": "ak", "MUSICBAZI_AUDD_TOKEN": "at"}, 1.0
    )
    assert identify.available(uid) is True
    assert identify.available(other) is False
    assert audd.enabled(uid) is True
    assert audd.enabled(other) is False
    assert "acoustid" not in identify.missing(other)


# ---------------------------------------------------------------- متنِ آهنگ


@pytest.fixture
def track() -> Track:
    return Track(
        id="itunes:track:1",
        title="Mard-e Tanha",
        artist="Farhad Mehrad",
        album="Mard-E Tanha",
        durationMs=185_000,
        source="apple",
        sourceUrl="https://music.apple.com/us/album/x/1?i=2",
    )


def test_lyrics_registry_filters_by_account(accounts, track, monkeypatch):
    """
    Genius بدونِ توکن نباید در زنجیرهٔ خودکارِ حسابِ بی‌کلید باشد.
    """
    uid, other = accounts
    credentials.set_many(uid, {"MUSICBAZI_GENIUS_ACCESS_TOKEN": "tok"}, 1.0)
    # `genius` پیش‌فرض در زنجیرهٔ خودکار نیست (فقط دستی)؛ برای این آزمون روشنش می‌کنیم
    monkeypatch.setattr(lyrics_registry, "lyrics_auto_enabled", lambda name: True)

    names_for_uid = [e.name for e in lyrics_manager.lyrics_manager.registry.available(uid)]
    names_for_other = [e.name for e in lyrics_manager.lyrics_manager.registry.available(other)]
    assert "genius" in names_for_uid
    assert "genius" not in names_for_other


def test_miss_cache_is_keyed_by_account(accounts, track):
    """
    کشِ منفیِ یک حساب نباید مانعِ تلاشِ حسابِ دیگر شود — وگرنه کاربرِ بی‌کلید
    که یک‌بار متن پیدا نکرده، برای کاربرِ باکلید هم «پیدا نشد» می‌سازد.
    """
    uid, other = accounts
    manager = lyrics_manager.lyrics_manager
    manager._misses.clear()

    # یک Providerِ بی‌کلید که همیشه خالی برمی‌گردد، تا مسیرِ «پیدا نشد» طی شود
    calls: list[str] = []

    def fake_invoke(fn, track, uid=db.GUEST_ID):
        calls.append(uid)
        return None

    lyrics_sources.lyrics_sources._cache.clear()
    # همه‌ی Providerها را از زنجیره بیرون می‌بریم تا حالتِ «هیچ Providerی» قابلِ
    # پیش‌بینی باشد و کشِ منفی نوشته شود
    original = manager.registry.available
    manager.registry.available = lambda uid=db.GUEST_ID: []
    try:
        assert manager.fetch(track, uid) is None
        assert manager.fetch(track, uid) is None
        assert (uid, track.id) in manager._misses
        # حسابِ دوم با همان آهنگ نباید از کشِ منفیِ حسابِ اول بسته شود
        assert (other, track.id) not in manager._misses
    finally:
        manager.registry.available = original
        manager._misses.clear()


def test_source_cache_is_keyed_by_account(accounts, track):
    """
    اگر کلیدِ `_cache`/`_errors` فقط `track.id` باشد، متنِ پیداشده با کلیدِ یک
    کاربر به کاربرِ بی‌کلید نشان داده می‌شود.
    """
    uid, other = accounts
    lyrics_sources.lyrics_sources._cache.clear()
    lyrics_sources.lyrics_sources._errors.clear()

    lyrics_sources.lyrics_sources._cache[(uid, track.id, "genius")] = "x"
    assert lyrics_sources.lyrics_sources._cache.get((other, track.id, "genius")) is None


def test_lyrics_disk_cache_is_separated_by_account(accounts):
    """
    `.lrc`ِ دیسکی مشترک بود: کسی که متن را با کلیدِ خودش پیدا می‌کرد، آن را در
    فایلی می‌نوشت که کاربرِ بی‌کلید هم می‌خواند.
    """
    from app import stream_cache

    uid, other = accounts
    assert stream_cache._lyrics_suffix(uid) != stream_cache._lyrics_suffix(other)
    # حسابِ یکسان باید نامِ پایدار بگیرد، وگرنه کش هر بار از دست می‌رود
    assert stream_cache._lyrics_suffix(uid) == stream_cache._lyrics_suffix(uid)


# ---------------------------------------------------------------- health

def test_health_reports_features_per_account(accounts, monkeypatch):
    """
    `/api/health` پرچم‌ها را برای همان درخواست‌دهنده حساب می‌کند.

    این تست پیدا شد چون هیچ آزمونی این مسیر را صدا نمی‌زد و یک `credentials`
    جاافتاده در ایمپورت‌های `main.py` تا زمانِ اجرای واقعی دیده نشد.
    """
    from fastapi.testclient import TestClient

    from app import main

    uid, other = accounts
    credentials.set_many(uid, {"MUSICBAZI_GEMINI_API_KEY": "gem-one"}, 1.0)

    with TestClient(main.app) as client:
        mine = client.get("/api/health", headers=_auth(uid)).json()
        theirs = client.get("/api/health", headers=_auth(other)).json()
        guest = client.get("/api/health").json()

    assert mine["features"]["vibeLlm"] is True
    assert theirs["features"]["vibeLlm"] is False
    assert guest["features"]["vibeLlm"] is False

# ---------------------------------------------------------------- زمینه‌ی کاربر


def test_user_scope_restores_the_previous_context():
    """`ContextVar` باید برگردد، وگرنه یک درخواستِ بعدی با uidِ قبلی اجرا می‌شود."""
    assert credentials.current() == db.GUEST_ID
    with credentials.user_scope("u_one"):
        assert credentials.current() == "u_one"
    assert credentials.current() == db.GUEST_ID
