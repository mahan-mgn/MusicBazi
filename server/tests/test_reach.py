"""تشخیصِ «اینترنتِ بین‌الملل هست یا نه»."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app import reach


@pytest.fixture(autouse=True)
def clean_state():
    """هر تست از حالتِ خوش‌بینانه‌ی اولیه شروع شود."""
    reach._set(True, ())
    reach._state.strikes = 0
    yield
    reach._set(True, ())
    reach._state.strikes = 0


def _down() -> httpx.ConnectTimeout:
    return httpx.ConnectTimeout("timed out")


def test_a_single_failure_does_not_flip_the_whole_app():
    """
    یک بسته‌ی گم‌شده نباید برنامه را به حالتِ اینترانت ببرد.

    این دقیقاً همان چیزی است که در عمل اتفاق افتاد: یک قطعیِ چندثانیه‌ای،
    جستجوی زنده را خاموش کرد و دانلودها را به صف فرستاد.
    """
    assert reach.note_unreachable(_down()) is True  # این درخواست به کش می‌رود
    assert reach.online() is True  # ولی بقیه‌ی برنامه دست‌نخورده می‌ماند


def test_consecutive_failures_do_flip_it():
    """قطعیِ واقعی خودش را با شکستِ پیاپی نشان می‌دهد."""
    for _ in range(reach.REACH_STRIKES):
        reach.note_unreachable(_down())
    assert reach.online() is False


def test_one_success_in_between_resets_the_count():
    """
    دو شکستِ بی‌ربط با نیم‌ساعت فاصله، یک قطعی نیستند.

    بدونِ صفر شدنِ شمارنده، هر برنامه‌ای که به‌قدرِ کافی زنده بماند بالاخره به
    حدِ نصاب می‌رسید — و به حالتِ اینترانت می‌رفت بی‌آنکه چیزی قطع شده باشد.
    """
    reach.note_unreachable(_down())
    reach.note_reachable()
    reach.note_unreachable(_down())
    assert reach.online() is True


def test_a_bad_http_status_does_not_mean_intranet():
    """
    ۴۰۳ِ یوتیوب یا ۴۲۹ِ اسپاتیفای یعنی رسیدیم و جواب بدی گرفتیم.

    بردنِ کلِ برنامه به حالتِ اینترانت به‌خاطرِ یک محدودیتِ نرخ، پرهزینه‌ترین
    اشتباهِ ممکنِ این ماژول است: جستجوی زنده و دانلود بی‌دلیل خاموش می‌شدند
    درحالی‌که اینترنت کاملاً برقرار بود.
    """
    response = httpx.Response(429, request=httpx.Request("GET", "https://example.com"))
    error = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
    for _ in range(reach.REACH_STRIKES + 1):
        assert reach.note_unreachable(error) is False
    assert reach.online() is True
    assert reach._state.strikes == 0


def test_a_wrapped_connection_failure_is_still_recognised():
    """
    `asyncio.gather` و httpx خطا را در `__cause__` می‌پیچند.

    بدونِ نگاه به علت، همان قطعی از دیدِ این تابع یک خطای ناشناخته می‌شد و
    مسیرِ برگشت به کش اصلاً فعال نمی‌شد.
    """
    wrapper = RuntimeError("جستجو ناموفق بود")
    wrapper.__cause__ = httpx.ConnectError("no route to host")
    for _ in range(reach.REACH_STRIKES):
        assert reach.note_unreachable(wrapper) is True
    assert reach.online() is False


def test_a_successful_upstream_call_brings_us_back():
    """
    مجانی‌ترین سیگنالِ برگشت: یک درخواستِ واقعی که جواب داد.

    بدونِ آن، کاربر تا دورِ بعدیِ پروب در حالتِ اینترانت گیر می‌کرد — با
    اینترنتی که همان لحظه برگشته بود.
    """
    for _ in range(reach.REACH_STRIKES):
        reach.note_unreachable(httpx.ConnectError("down"))
    assert reach.online() is False

    reach.note_reachable()
    assert reach.online() is True
    assert reach._state.strikes == 0


def test_snapshot_reports_what_it_actually_measured():
    reach._set(False, ())
    snap = reach.snapshot()
    assert snap["online"] is False
    assert snap["reachable"] == []
    assert snap["checkedAt"] > 0


def test_no_probes_configured_means_always_online(monkeypatch):
    """
    خالی گذاشتنِ `MUSICBAZI_REACH_PROBES` یعنی «این قابلیت را نمی‌خواهم».

    آن‌وقت هیچ‌چیز نباید به حالتِ اینترانت برود، وگرنه خاموش‌کردنِ تشخیص، خودش
    برنامه را فلج می‌کرد.
    """
    monkeypatch.setattr(reach, "REACH_PROBES", ())
    reach._set(False, ())
    assert asyncio.run(reach.check()) is True


def test_the_probe_hosts_are_not_geo_blocked_catalogs():
    """
    محافظ در برابر همان اشتباهی که یک‌بار کاربر را در حالتِ اینترانت حبس کرد.

    زدنِ پروب روی خودِ کاتالوگ‌ها وسوسه‌انگیز است («همان چیزی را بسنج که لازم
    داری») ولی از آی‌پیِ ایران، اپل تحریم و دیزر geo-block است — پس برنامه
    قطعی اعلام می‌کرد در حالی که اینترنت سالم بود. پروب باید به سؤالِ
    ساده‌ترِ «مسیری به بیرون هست؟» جواب بدهد.
    """
    blocked = ("apple.com", "deezer.com", "spotify.com", "youtube.com", "googlevideo.com")
    for url in reach.REACH_PROBES:
        assert not any(host in url for host in blocked), url


def test_verify_does_not_reprobe_while_the_answer_is_fresh(monkeypatch):
    """
    دریچه‌ی فرار نباید به هزینه‌ی یک پروب به‌ازای هر درخواست تمام شود.
    """
    calls = 0

    async def counted() -> bool:
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr(reach, "check", counted)
    reach._state.checked_at = time.time()

    assert asyncio.run(reach.verify(20.0)) is True
    assert calls == 0  # جوابِ تازه بود، پروبی لازم نشد


def test_verify_reprobes_once_the_answer_is_stale(monkeypatch):
    """
    و برعکس: جوابِ کهنه باید دوباره پرسیده شود، وگرنه همان حبسِ قبلی تکرار
    می‌شود — یک «قطع»ِ اشتباه که هیچ‌وقت بازبینی نمی‌شود.
    """
    calls = 0

    async def counted() -> bool:
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr(reach, "check", counted)
    reach._state.checked_at = time.time() - 3600

    assert asyncio.run(reach.verify(20.0)) is True
    assert calls == 1
