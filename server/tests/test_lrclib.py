"""
متن آهنگ از LRCLIB.

مهم‌ترین چیزی که اینجا قفل می‌شود انتخابِ نسخه است: LRCLIB برای یک عنوان
چند نسخه (استودیو، لایو، ریمیکس، کاور) دارد و مدت‌زمان تنها سیگنالِ قابل‌اتکا
برای تشخیصشان است. قبلاً وقتی هیچ نتیجه‌ای در بازه‌ی مدت نبود، فیلتر با
`or rows` کنار گذاشته می‌شد و اولین نتیجه‌ی لیست — هر نسخه‌ای که بود — انتخاب
می‌شد؛ یعنی متنِ آهنگِ دیگری روی ترک کاربر می‌نشست.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers import lrclib

_DURATION = 180  # ثانیه — همان ۱۸۰٫۰۰۰ میلی‌ثانیه‌ی ورودی


class _FakeClient:
    def __init__(self, handler):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, params=None):
        return self._handler(url, params or {})


def _response(status: int, *, json_body=None) -> httpx.Response:
    request = httpx.Request("GET", "https://x.test")
    return httpx.Response(status, json=json_body, request=request)


def _row(duration, *, synced=None, plain=None) -> dict:
    return {"duration": duration, "syncedLyrics": synced, "plainLyrics": plain}


def _search_only(rows):
    """`/api/get` خالی می‌ماند تا آزمون واقعاً روی منطق انتخاب جستجو بنشیند."""

    def handler(url, params):
        if url.endswith("/api/get"):
            return _response(404)
        return _response(200, json_body=rows)

    return handler


def _fetch(monkeypatch, handler, duration_ms=_DURATION * 1000):
    monkeypatch.setattr(lrclib.httpx, "Client", lambda **_: _FakeClient(handler))
    return lrclib.fetch("Song", "Artist", None, duration_ms)


class TestDurationMatching:
    def test_a_same_duration_row_wins_over_a_mismatched_one(self, monkeypatch):
        rows = [
            _row(_DURATION + 300, synced="[00:01.00]live"),
            _row(_DURATION, synced="[00:01.00]studio"),
        ]

        found = _fetch(monkeypatch, _search_only(rows))

        assert found.synced == "[00:01.00]studio"

    def test_a_row_with_no_duration_is_still_accepted_when_it_is_all_there_is(self, monkeypatch):
        """
        «بی‌مدت» با «مدتِ متناقض» یکی نیست: ردیفی که اصلاً مدت اعلام نکرده
        چیزی را رد نکرده. نبودِ مدت نباید مثل اختلافِ مدت رد شود.
        """
        rows = [_row(None, synced="[00:01.00]unknown")]

        found = _fetch(monkeypatch, _search_only(rows))

        assert found is not None
        assert found.synced == "[00:01.00]unknown"

    def test_only_mismatched_durations_returns_nothing(self, monkeypatch):
        """
        رگرسیون اصلی: هر ردیف مدت دارد و هیچ‌کدام نمی‌خواند، پس هیچ ردیفی
        انتخاب نمی‌شود. قبلاً همین حالت اولین ردیف را برمی‌گرداند.
        """
        rows = [
            _row(_DURATION + 300, synced="[00:01.00]live"),
            _row(_DURATION - 240, plain="remix"),
        ]

        assert _fetch(monkeypatch, _search_only(rows)) is None

    def test_the_tolerance_boundary_is_inclusive(self, monkeypatch):
        assert _fetch(monkeypatch, _search_only([_row(_DURATION + 5, synced="[00:01.00]x")])) is not None
        assert _fetch(monkeypatch, _search_only([_row(_DURATION + 6, synced="[00:01.00]x")])) is None

    def test_a_known_duration_prefers_a_synced_row_over_plain(self, monkeypatch):
        rows = [
            _row(_DURATION, plain="plain only"),
            _row(_DURATION, synced="[00:01.00]synced"),
        ]

        found = _fetch(monkeypatch, _search_only(rows))

        assert found.synced == "[00:01.00]synced"

    def test_an_unknown_duration_skips_the_filter_entirely(self, monkeypatch):
        """مدت ۰ یعنی «نمی‌دانیم»؛ در آن حالت هیچ فیلتری معنا ندارد."""
        rows = [_row(_DURATION + 300, synced="[00:01.00]whatever")]

        found = _fetch(monkeypatch, _search_only(rows), duration_ms=0)

        assert found is not None
        assert found.synced == "[00:01.00]whatever"


class TestFetchContract:
    def test_the_exact_get_endpoint_still_wins(self, monkeypatch):
        def handler(url, params):
            assert url.endswith("/api/get")
            return _response(200, json_body=_row(_DURATION, synced="[00:01.00]exact"))

        monkeypatch.setattr(
            lrclib.httpx, "Client", lambda **_: _FakeClient(handler)
        )
        found = lrclib.fetch("Song", "Artist", "Album", _DURATION * 1000)

        assert found.synced == "[00:01.00]exact"

    def test_an_empty_title_short_circuits_without_a_request(self, monkeypatch):
        monkeypatch.setattr(
            lrclib.httpx,
            "Client",
            lambda **_: (_ for _ in ()).throw(AssertionError("should not connect")),
        )

        assert lrclib.fetch("", "Artist", None, _DURATION * 1000) is None

    def test_hard_failures_return_none(self, monkeypatch):
        def boom(url, params):
            raise httpx.ConnectError("offline")

        assert _fetch(monkeypatch, boom) is None

    def test_an_empty_result_set_returns_none(self, monkeypatch):
        assert _fetch(monkeypatch, _search_only([])) is None

    def test_a_non_list_body_returns_none(self, monkeypatch):
        assert _fetch(monkeypatch, _search_only({"not": "a list"})) is None

    def test_an_http_error_on_search_returns_none(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/api/get"):
                return _response(404)
            return _response(500)

        assert _fetch(monkeypatch, handler) is None


class TestFormatAnnotation:
    def test_synced_rows_are_marked_as_line_synced_lrc(self, monkeypatch):
        found = _fetch(monkeypatch, _search_only([_row(_DURATION, synced="[00:01.00]x")]))

        assert found.format == "lrc"
        assert found.sync_type == "line"

    def test_plain_rows_are_marked_as_plain(self, monkeypatch):
        found = _fetch(monkeypatch, _search_only([_row(_DURATION, plain="x")]))

        assert found.format == "plain"
        assert found.sync_type == "plain"
