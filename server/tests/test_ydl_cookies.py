"""
کوکیِ یوتیوب — **مشترک** و بی‌ری‌استارت.

این کوکی عمداً شخصی نیست: به حسابِ یوتیوبِ سازنده‌اش گره خورده و درست کار
کردنش به همان حساب و دستگاه بستگی دارد، پس یک فایل روی سرور می‌ماند و هر
حسابی که وارد شود از آن استفاده می‌کند. `user_id` در امضا مانده چون لایه‌های
بالاتر یک‌شکل صدا می‌زنند، ولی نتیجه برای همه یکی است.
"""

from __future__ import annotations

import pytest

from app import ydl


@pytest.fixture
def cookie_file(tmp_path, monkeypatch):
    path = tmp_path / "youtube.txt"
    path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("MUSICBAZI_COOKIES_FILE", str(path))
    monkeypatch.delenv("MUSICBAZI_COOKIES_BROWSER", raising=False)
    monkeypatch.setattr(ydl, "COOKIES_BROWSER", None)
    return path


def test_every_account_uses_the_same_cookie(cookie_file):
    """قلبِ تصمیم: دو حساب مختلف یک کوکی می‌گیرند."""
    assert ydl.auth_opts("u_one")["cookiefile"] == str(cookie_file)
    assert ydl.auth_opts("u_two")["cookiefile"] == str(cookie_file)
    assert ydl.has_cookies("u_one") is True
    assert ydl.has_cookies("u_two") is True


def test_no_cookie_means_no_cookiefile(monkeypatch):
    monkeypatch.delenv("MUSICBAZI_COOKIES_FILE", raising=False)
    monkeypatch.delenv("MUSICBAZI_COOKIES_BROWSER", raising=False)
    monkeypatch.setattr(ydl, "COOKIES_FILE", None)
    monkeypatch.setattr(ydl, "COOKIES_BROWSER", None)
    assert "cookiefile" not in ydl.auth_opts("local")
    assert ydl.has_cookies("local") is False


def test_the_env_wins_so_an_upload_takes_effect_without_a_restart(monkeypatch):
    """
    `setup.py` مسیر را در `os.environ` می‌نشاند. اگر `config` برنده می‌شد،
    کوکیِ تازه تا ری‌استارتِ بعدی دیده نمی‌شد — همان «کوکی دادم ولی یوتیوب
    نشکست».
    """
    monkeypatch.setattr(ydl, "COOKIES_FILE", "/old/path.txt")
    monkeypatch.setenv("MUSICBAZI_COOKIES_FILE", "/data/db/youtube.txt")
    assert ydl.auth_opts("local")["cookiefile"] == "/data/db/youtube.txt"


def test_browser_cookies_are_the_fallback(monkeypatch):
    monkeypatch.delenv("MUSICBAZI_COOKIES_FILE", raising=False)
    monkeypatch.setattr(ydl, "COOKIES_FILE", None)
    monkeypatch.setattr(ydl, "COOKIES_BROWSER", None)
    monkeypatch.setenv("MUSICBAZI_COOKIES_BROWSER", "firefox")
    assert ydl.auth_opts("local").get("cookiesfrombrowser") == ("firefox", None, None, None)

    # کوکیِ فایل برتر است اگر هر دو باشند — کسی عمداً آپلودش کرده
    monkeypatch.setenv("MUSICBAZI_COOKIES_FILE", "/data/db/youtube.txt")
    opts = ydl.auth_opts("local")
    assert opts["cookiefile"] == "/data/db/youtube.txt"
    assert "cookiesfrombrowser" not in opts
