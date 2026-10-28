"""
S2 — سرویسِ منابع: فهرست‌کردن و واکشیِ تک‌منبعی.

هیچ درخواست شبکه‌ای زده نمی‌شود. Providerها ساختگی‌اند و آن‌هایی که واقعی
هستند HTTPشان mock است.
"""

from __future__ import annotations

import asyncio

import pytest

from app.lyrics.manager import LyricsManager
from app.lyrics.models import Lyrics
from app.lyrics.registry import ProviderEntry, ProviderError, ProviderRegistry
from app.lyrics.sources import (
    STATUS_AVAILABLE,
    STATUS_CACHED,
    STATUS_DISABLED,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_NEEDS_SETUP,
    LyricsSources,
)
from app.models import Track


def _track(track_id: str = "t1") -> Track:
    return Track(
        id=track_id,
        title="Song",
        artist="Artist",
        album="Album",
        durationMs=180_000,
        source="spotify",
        sourceUrl=f"https://example.test/{track_id}",
    )


def _entry(name: str, fn, *, enabled=None, default_enabled=True, caps=frozenset()) -> ProviderEntry:
    return ProviderEntry(
        name, fn, enabled, fn, default_enabled=default_enabled, capabilities=caps
    )


def _sources(entries, order=None, **kw) -> LyricsSources:
    registry = ProviderRegistry(list(entries), order or tuple(e.name for e in entries))
    return LyricsSources(manager=LyricsManager(registry=registry), **kw)


def _ok(text: str = "line"):
    def fn(*a, **k):
        return Lyrics(plain=text, synced=f"[00:01.00]{text}")

    return fn


class TestListSourcesMakesNoRequest:
    """باز کردنِ منو نباید به هیچ Providerی درخواست بزند."""

    def test_listing_never_calls_a_provider(self):
        calls: list[str] = []

        def exploding(*a, **k):
            calls.append("called")
            raise AssertionError("list_sources must not call providers")

        sources = _sources([_entry("a", exploding), _entry("b", exploding)])

        rows = sources.list_sources(_track())

        # دو Providerِ ثبت‌شده + دو ورودیِ متادیتاییِ ممنوع (بدونِ کد)
        assert [r["id"] for r in rows][:2] == ["a", "b"]
        assert calls == []

    def test_listing_reports_every_registered_provider(self):
        sources = _sources([_entry("a", _ok()), _entry("b", _ok())])

        names = [row["id"] for row in sources.list_sources(_track())]

        assert names[:2] == ["a", "b"]

    def test_listing_follows_the_registry_order(self):
        sources = _sources(
            [_entry("a", _ok()), _entry("b", _ok())], order=("b", "a")
        )

        assert [row["id"] for row in sources.list_sources(_track())][:2] == ["b", "a"]

    def test_the_metadata_fields_are_exposed(self):
        sources = _sources(
            [_entry("a", _ok(), caps=frozenset({"line", "word"}))]
        )

        row = sources.list_sources(_track())[0]

        assert row["capabilities"] == ["line", "word"]
        assert "in_auto_chain" in row and "selectable" in row
        assert "terms_note" in row and "setup_hint" in row


class TestStatusReporting:
    def test_a_ready_provider_is_available(self):
        sources = _sources([_entry("a", _ok())])

        assert sources.list_sources(_track())[0]["status"] == STATUS_AVAILABLE

    def test_a_provider_needing_a_token_is_needs_setup(self):
        sources = _sources([_entry("a", _ok(), enabled=lambda: False)])

        assert sources.list_sources(_track())[0]["status"] == STATUS_NEEDS_SETUP

    def test_a_dark_by_default_provider_is_selectable_but_not_automatic(self):
        """
        P1: پیش‌فرض‌خاموش یعنی «در زنجیرهٔ خودکار نیست»، نه «از UI غایب است».
        کاربر باید بتواند آگاهانه انتخابش کند.
        """
        sources = _sources([_entry("a", _ok(), default_enabled=False)])

        row = sources.list_sources(_track())[0]

        assert row["selectable"] is True
        assert row["in_auto_chain"] is False
        assert row["status"] == STATUS_AVAILABLE

    def test_a_cached_result_shows_as_cached(self):
        sources = _sources([_entry("a", _ok())])
        track = _track()

        asyncio.run(sources.fetch_from("a", track))

        assert sources.list_sources(track)[0]["status"] == STATUS_CACHED

    def test_an_empty_result_shows_as_empty(self):
        def empty(*a, **k):
            return None

        sources = _sources([_entry("a", empty)])
        track = _track()
        asyncio.run(sources.fetch_from("a", track))

        assert sources.list_sources(track)[0]["status"] == STATUS_EMPTY

    def test_an_error_shows_as_error(self):
        def broken(*a, **k):
            raise ProviderError("a", "http", status=503)

        sources = _sources([_entry("a", broken)])
        track = _track()
        asyncio.run(sources.fetch_from("a", track))

        assert sources.list_sources(track)[0]["status"] == STATUS_ERROR

    def test_status_is_per_track(self):
        sources = _sources([_entry("a", _ok())])
        asyncio.run(sources.fetch_from("a", _track("one")))

        assert sources.list_sources(_track("two"))[0]["status"] == STATUS_AVAILABLE


class TestFetchFrom:
    def test_it_calls_only_the_named_provider(self):
        calls: list[str] = []

        def a(*_):
            calls.append("a")
            return Lyrics(plain="a")

        def b(*_):
            calls.append("b")
            return Lyrics(plain="b")

        sources = _sources([_entry("a", a), _entry("b", b)])
        result = asyncio.run(sources.fetch_from("b", _track()))

        assert result.ok and result.lyrics.plain == "b"
        assert calls == ["b"]

    def test_manual_selection_works_without_widening_the_auto_chain(self):
        """
        P1: Providerِ پیش‌فرض‌خاموش با انتخابِ دستی **صدا زده می‌شود**، ولی
        زنجیرهٔ خودکار دست‌نخورده می‌ماند.
        """
        calls: list[str] = []
        sources = _sources(
            [
                _entry("auto", _ok("auto")),
                _entry("dark", lambda *a, **k: (calls.append("dark"), Lyrics(plain="d", synced="[00:01.00]d"))[1],
                       default_enabled=False),
            ]
        )
        manager = sources._manager

        result = asyncio.run(sources.fetch_from("dark", _track()))

        assert result.ok and calls == ["dark"]
        assert [e.name for e in manager.registry.available()] == ["auto"]

    def test_an_unknown_provider_is_rejected(self):
        sources = _sources([_entry("a", _ok())])

        result = asyncio.run(sources.fetch_from("nope", _track()))

        assert result.ok is False and result.error == "unknown-provider"

    def test_a_needs_setup_provider_is_rejected_without_a_call(self):
        sources = _sources([_entry("a", _ok(), enabled=lambda: False)])

        result = asyncio.run(sources.fetch_from("a", _track()))

        assert result.ok is False and result.error == "needs_setup"

    def test_a_successful_result_is_cached_in_memory(self):
        calls: list[int] = []

        def counting(*a, **k):
            calls.append(1)
            return Lyrics(plain="x", synced="[00:01.00]x")

        sources = _sources([_entry("a", counting)])
        track = _track()

        asyncio.run(sources.fetch_from("a", track))
        asyncio.run(sources.fetch_from("a", track))

        assert len(calls) == 1

    def test_an_empty_result_is_cached_for_the_ttl(self):
        calls: list[int] = []
        now = [1000.0]

        def empty(*a, **k):
            calls.append(1)
            return None

        sources = _sources([_entry("a", empty)], miss_ttl_s=300, clock=lambda: now[0])
        track = _track()

        asyncio.run(sources.fetch_from("a", track))
        asyncio.run(sources.fetch_from("a", track))
        assert len(calls) == 1

        now[0] += 301
        asyncio.run(sources.fetch_from("a", track))
        assert len(calls) == 2

    def test_force_bypasses_the_empty_cache(self):
        calls: list[int] = []

        def empty(*a, **k):
            calls.append(1)
            return None

        sources = _sources([_entry("a", empty)], miss_ttl_s=300)
        track = _track()

        asyncio.run(sources.fetch_from("a", track))
        asyncio.run(sources.fetch_from("a", track, force=True))

        assert len(calls) == 2

    def test_an_error_is_never_negative_cached(self):
        calls: list[int] = []

        def broken(*a, **k):
            calls.append(1)
            raise ProviderError("a", "network", detail="x")

        sources = _sources([_entry("a", broken)], miss_ttl_s=300)
        track = _track()

        asyncio.run(sources.fetch_from("a", track))
        asyncio.run(sources.fetch_from("a", track))

        assert len(calls) == 2

    def test_an_error_does_not_leak_details(self):
        def broken(*a, **k):
            raise ProviderError("a", "network", detail="ConnectTimeout")

        sources = _sources([_entry("a", broken)])
        result = asyncio.run(sources.fetch_from("a", _track()))

        assert result.error == "network"

    def test_a_provider_exception_that_is_not_a_provider_error_is_reported(self):
        def broken(*a, **k):
            raise ValueError("boom")

        sources = _sources([_entry("a", broken)])
        result = asyncio.run(sources.fetch_from("a", _track()))

        assert result.ok is False
        assert result.error == "ValueError"

    def test_concurrent_identical_requests_are_merged(self):
        calls: list[int] = []

        def slow(*a, **k):
            calls.append(1)
            import time

            time.sleep(0.05)
            return Lyrics(plain="x", synced="[00:01.00]x")

        sources = _sources([_entry("a", slow)])
        track = _track()

        async def both():
            return await asyncio.gather(
                sources.fetch_from("a", track), sources.fetch_from("a", track)
            )

        first, second = asyncio.run(both())

        assert calls == [1]
        assert first.ok and second.ok

    def test_different_providers_are_not_merged(self):
        calls: list[str] = []

        def make(name):
            def fn(*a, **k):
                calls.append(name)
                return Lyrics(plain=name, synced=f"[00:01.00]{name}")

            return fn

        sources = _sources([_entry("a", make("a")), _entry("b", make("b"))])
        track = _track()

        async def both():
            return await asyncio.gather(
                sources.fetch_from("a", track), sources.fetch_from("b", track)
            )

        asyncio.run(both())

        assert sorted(calls) == ["a", "b"]


class TestHintForwarding:
    def test_the_hints_reach_the_provider(self):
        seen: list[dict] = []

        def capturing(title, artist, album, duration_ms, *, video_id=None, isrc=None):
            seen.append({"v": video_id, "i": isrc})
            return None

        sources = _sources([_entry("a", capturing)])
        track = _track()
        track.videoId = "dQw4w9WgXcQ"
        track.isrc = "US1234567890"

        asyncio.run(sources.fetch_from("a", track))

        assert seen == [{"v": "dQw4w9WgXcQ", "i": "US1234567890"}]


class TestForget:
    def test_forget_clears_the_cache(self):
        calls: list[int] = []

        def counting(*a, **k):
            calls.append(1)
            return Lyrics(plain="x", synced="[00:01.00]x")

        sources = _sources([_entry("a", counting)])
        track = _track()
        asyncio.run(sources.fetch_from("a", track))

        sources.forget(track.id)
        asyncio.run(sources.fetch_from("a", track))

        assert len(calls) == 2

    def test_forget_can_target_one_provider(self):
        calls: list[str] = []

        def make(name):
            def fn(*a, **k):
                calls.append(name)
                return Lyrics(plain=name, synced=f"[00:01.00]{name}")

            return fn

        sources = _sources([_entry("a", make("a")), _entry("b", make("b"))])
        track = _track()
        asyncio.run(sources.fetch_from("a", track))
        asyncio.run(sources.fetch_from("b", track))

        sources.forget(track.id, "a")
        asyncio.run(sources.fetch_from("a", track))

        assert calls.count("a") == 2
        assert calls.count("b") == 1


class TestDuplicateDetection:
    def test_two_providers_with_the_same_text_are_flagged(self):
        text = "same words here"

        def same(*a, **k):
            return Lyrics(plain=text, synced=f"[00:01.00]{text}")

        sources = _sources([_entry("a", same), _entry("b", same)])
        track = _track()
        asyncio.run(sources.fetch_from("a", track))
        asyncio.run(sources.fetch_from("b", track))

        assert sources.duplicate_of("a", track, "b") is True

    def test_different_text_is_not_flagged(self):
        def make(text):
            def fn(*a, **k):
                return Lyrics(plain=text, synced=f"[00:01.00]{text}")

            return fn

        sources = _sources([_entry("a", make("one two")), _entry("b", make("three four"))])
        track = _track()
        asyncio.run(sources.fetch_from("a", track))
        asyncio.run(sources.fetch_from("b", track))

        assert sources.duplicate_of("a", track, "b") is False

    def test_uncached_providers_are_not_flagged(self):
        sources = _sources([_entry("a", _ok("x")), _entry("b", _ok("x"))])
        track = _track()
        asyncio.run(sources.fetch_from("a", track))

        # `b` هنوز واکشی نشده — مقایسه بی‌معناست
        assert sources.duplicate_of("a", track, "b") is False

    def test_duplicate_detection_makes_no_request(self):
        calls: list[str] = []

        def make(name):
            def fn(*a, **k):
                calls.append(name)
                return Lyrics(plain="x", synced="[00:01.00]x")

            return fn

        sources = _sources([_entry("a", make("a")), _entry("b", make("b"))])
        track = _track()
        asyncio.run(sources.fetch_from("a", track))
        calls.clear()

        sources.duplicate_of("a", track, "b")

        assert calls == []
