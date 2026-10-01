"""
پروکسی — یک تنظیم، چند مصرف‌کننده.

نکته‌ی حساسش این است که `proxy` باید در همان dictی بنشیند که دانلود واقعی هم
از آن می‌خواند؛ پروکسی کردن فقط استخراج، لینک مستقیمِ غیرقابل‌دسترس می‌دهد.
"""

from __future__ import annotations

import importlib

import pytest

from app import ydl


@pytest.fixture
def with_proxy(monkeypatch):
    """پروکسی روی همه‌ی مصرف‌کننده‌ها. config در زمان ایمپورت خوانده می‌شود."""

    def apply(value: str) -> None:
        monkeypatch.setattr(ydl, "YTDLP_PROXY", value)

    return apply


def test_proxy_reaches_the_download_options(with_proxy):
    with_proxy("socks5h://127.0.0.1:1080")

    assert ydl.opts()["proxy"] == "socks5h://127.0.0.1:1080"


def test_caller_options_do_not_lose_the_proxy(with_proxy):
    """`opts(**extra)` مرج می‌کند؛ کلیدهای صدازننده نباید پروکسی را بیندازند."""
    with_proxy("http://127.0.0.1:8080")

    merged = ydl.opts(format="bestaudio/best", noplaylist=True)

    assert merged["proxy"] == "http://127.0.0.1:8080"
    assert merged["format"] == "bestaudio/best"


def test_no_proxy_means_no_key(with_proxy):
    """کلیدِ خالی به yt-dlp دادن یعنی «از پروکسیِ محیط استفاده نکن» — فرق دارد."""
    with_proxy(None)

    assert "proxy" not in ydl.opts()


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("socks5h://user:s3cret@10.0.0.1:1080", "socks5h://10.0.0.1:1080"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("127.0.0.1:1080", "127.0.0.1:1080"),
    ],
)
def test_health_never_shows_the_password(with_proxy, value, shown):
    """`/health` احراز هویت ندارد؛ رمز پروکسی نباید از آن بیرون بزند."""
    with_proxy(value)

    assert ydl.proxy_label() == shown


def test_health_reports_absence_as_false(with_proxy):
    with_proxy(None)

    assert ydl.proxy_label() is False


def test_ytdlp_proxy_falls_back_to_the_general_one(monkeypatch):
    """یک متغیر باید برای حالت رایج کافی باشد."""
    monkeypatch.setenv("MUSICBAZI_PROXY", "socks5h://127.0.0.1:1080")
    monkeypatch.delenv("MUSICBAZI_YTDLP_PROXY", raising=False)

    from app import config

    reloaded = importlib.reload(config)
    try:
        assert reloaded.YTDLP_PROXY == "socks5h://127.0.0.1:1080"
    finally:
        # ماژول‌های دیگر مقدارها را در زمان ایمپورت گرفته‌اند؛ بدون برگرداندن،
        # تست‌های بعدی به یک config دستکاری‌شده نگاه می‌کنند
        monkeypatch.delenv("MUSICBAZI_PROXY", raising=False)
        importlib.reload(config)
