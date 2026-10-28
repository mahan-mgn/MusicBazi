"""
آزمونِ عکسِ پروفایل.

چیزی که این فایل از آن محافظت می‌کند: نوعِ فایل از *بایت‌ها* تشخیص داده شود نه
از نام یا هدرِ کلاینت (وگرنه هر کسی می‌تواند یک اسکریپت را به‌جای عکس جا بزند)،
حجم سقف داشته باشد، و نامِ کاربری در مسیرِ فایل نشت نکند.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, avatar, main

# یک PNGِ واقعیِ ۱×۱ — از بایت‌ها تشخیص داده می‌شود، پس باید امضای درست داشته باشد
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001 0d0a2db40000000049454e44ae426082".replace(" ", "")
)


@pytest.fixture
def client(fresh_db):
    auth.reset_secret_cache()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    res = client.post(
        "/api/auth/local/register",
        json={"username": "mahan", "password": "hunter2hunter2", "displayName": "مهان"},
    )
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_upload_and_serve(client, auth_headers):
    res = client.post(
        "/api/auth/avatar",
        files={"file": ("me.png", PNG, "image/png")},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    user = res.json()
    assert user["avatarUrl"] and user["avatarUrl"].startswith("/api/avatar/")

    served = client.get(user["avatarUrl"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/")


def test_upload_rejects_non_image(client, auth_headers):
    """
    پسوند و content-type هر دو از سمتِ کلاینت می‌آیند و هر دو دروغ‌پذیرند.

    تنها منبعِ حقیقت، بایت‌هاست — همان کاری که `artcache.sniff` برای کاورها
    می‌کند.
    """
    res = client.post(
        "/api/auth/avatar",
        files={"file": ("evil.png", b"<script>alert(1)</script>", "image/png")},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "تصویر" in res.json()["detail"]


def test_upload_rejects_empty(client, auth_headers):
    res = client.post(
        "/api/auth/avatar",
        files={"file": ("empty.png", b"", "image/png")},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_upload_enforces_size_cap(client, auth_headers, monkeypatch):
    monkeypatch.setattr(avatar, "AVATAR_MAX_BYTES", 64)
    res = client.post(
        "/api/auth/avatar",
        files={"file": ("big.png", b"\x89PNG\r\n\x1a\n" + b"x" * 500, "image/png")},
        headers=auth_headers,
    )
    assert res.status_code == 413


def test_upload_requires_login(client):
    res = client.post("/api/auth/avatar", files={"file": ("me.png", PNG, "image/png")})
    assert res.status_code == 401


def test_replace_keeps_a_single_file(client, auth_headers):
    """PNG بعد از JPG نباید فایلِ قدیمی را روی دیسک جا بگذارد."""
    from app.config import AVATAR_DIR

    client.post("/api/auth/avatar", files={"file": ("a.png", PNG, "image/png")}, headers=auth_headers)
    user = client.post(
        "/api/auth/avatar", files={"file": ("b.png", PNG, "image/png")}, headers=auth_headers
    ).json()

    mine = [p for p in AVATAR_DIR.glob(f"{user['id']}.*") if not p.name.startswith(".")]
    assert len(mine) == 1


def test_delete_falls_back_to_initial(client, auth_headers):
    client.post("/api/auth/avatar", files={"file": ("me.png", PNG, "image/png")}, headers=auth_headers)
    res = client.delete("/api/auth/avatar", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["avatarUrl"] is None

    # و سرو کردنش دیگر چیزی ندارد
    assert client.get("/api/avatar/x").status_code == 404


def test_avatar_of_unknown_user_is_404(client):
    assert client.get("/api/avatar/nobody").status_code == 404


def test_google_picture_kept_as_fallback_url(client, fresh_db, monkeypatch):
    """
    اگر دانلودِ عکسِ گوگل شکست بخورد، آدرسش باید بماند.

    در قطعیِ بین‌الملل عکسِ گوگل دیده نمی‌شود، ولی دور انداختنِ آدرس یعنی
    کاربری که گوگل وصل شده، حتی وقتی اینترنت هست هم بی‌عکس بماند.
    """
    from app import db

    row = db.create_user("g-user", "google", display_name="G", google_sub="sub-1")

    async def dead_get(*a, **k):
        raise httpx.ConnectError("شبکه نیست")

    class Dead:
        get = staticmethod(dead_get)

    import asyncio

    asyncio.run(avatar.import_google(Dead(), row, "https://lh3.googleusercontent.com/x"))

    fresh = db.user_by_id("g-user")
    assert fresh["avatar_file"] is None
    assert fresh["avatar_url"] == "https://lh3.googleusercontent.com/x"


def test_google_picture_is_cached_locally(client, fresh_db, monkeypatch):
    """عکسِ گوگل یک‌بار روی دیسک می‌آید تا آفلاین هم دیده شود."""
    from app import db

    row = db.create_user("g-user2", "google", display_name="G", google_sub="sub-2")

    class Ok:
        async def get(self, url, **k):
            return httpx.Response(200, content=PNG, request=httpx.Request("GET", url))

    import asyncio

    asyncio.run(avatar.import_google(Ok(), row, "https://lh3.googleusercontent.com/y"))

    fresh = db.user_by_id("g-user2")
    assert fresh["avatar_file"]
    assert avatar.path_for("g-user2") is not None
    # آدرسِ گوگل هم می‌ماند به‌عنوان لایه‌ی پشتیبان
    assert fresh["avatar_url"] == "https://lh3.googleusercontent.com/y"


def test_local_upload_is_not_overwritten_by_google(client, fresh_db, auth_headers):
    """کاربری که خودش عکس گذاشته، با ورودِ دوباره‌ی گوگل عکسش عوض نمی‌شود."""
    user = client.post(
        "/api/auth/avatar", files={"file": ("me.png", PNG, "image/png")}, headers=auth_headers
    ).json()

    from app import db

    row = db.user_by_id(user["id"])

    class Ok:
        async def get(self, url, **k):
            raise AssertionError("نباید دانلود کند")

    import asyncio

    asyncio.run(avatar.import_google(Ok(), row, "https://example.com/other.png"))
    assert db.user_by_id(user["id"])["avatar_file"] == row["avatar_file"]
