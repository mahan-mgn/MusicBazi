"""کوکی باید *بی‌ری‌استارت* هم اثر کند — ویزارد فقط os.environ را عوض می‌کند."""

import os

from app import ydl


def test_auth_opts_reads_cookies_from_environment_live(monkeypatch):
    # شبیه‌سازیِ مسیرِ ویزارد: config زمانِ import چیزی ندیده، ولی حالا
    # MUSICBAZI_COOKIES_FILE ست شده (همان کاری که setup_cookies می‌کند)
    monkeypatch.setattr(ydl, "COOKIES_FILE", None)
    monkeypatch.setenv("MUSICBAZI_COOKIES_FILE", "/data/db/cookies.txt")
    assert ydl.auth_opts().get("cookiefile") == "/data/db/cookies.txt"
    assert ydl.has_cookies() is True


def test_auth_opts_falls_back_to_imported_value(monkeypatch):
    monkeypatch.delenv("MUSICBAZI_COOKIES_FILE", raising=False)
    monkeypatch.delenv("MUSICBAZI_COOKIES_BROWSER", raising=False)
    monkeypatch.setattr(ydl, "COOKIES_FILE", "/old/path.txt")
    assert ydl.auth_opts().get("cookiefile") == "/old/path.txt"


def test_browser_cookies_also_live(monkeypatch):
    monkeypatch.setattr(ydl, "COOKIES_FILE", None)
    monkeypatch.setattr(ydl, "COOKIES_BROWSER", None)
    monkeypatch.delenv("MUSICBAZI_COOKIES_FILE", raising=False)
    monkeypatch.setenv("MUSICBAZI_COOKIES_BROWSER", "firefox")
    assert ydl.auth_opts().get("cookiesfrombrowser") == ("firefox", None, None, None)
    # کوکی‌فایل برتر است اگر هر دو باشند
    monkeypatch.setenv("MUSICBAZI_COOKIES_FILE", "/data/db/cookies.txt")
    assert "cookiesfrombrowser" not in ydl.auth_opts()
