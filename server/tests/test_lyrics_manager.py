"""
مدیرِ متن: ترتیب Providerها، ادامه پس از استثنا، و کشِ منفیِ کوتاه‌مدت.

Providerها اینجا همیشه ساختگی‌اند — هیچ درخواستی به شبکه زده نمی‌شود.
ساختِ Registry مستقیم (بدون خواندنِ تنظیمات) همان چیزی است که این تست‌ها را
از محیطِ اجرا مستقل می‌کند.
"""

from __future__ import annotations

import pytest

from app.lyrics.manager import LyricsManager
from app.lyrics.models import Lyrics
from app.lyrics.registry import ProviderEntry, ProviderRegistry
from app.models import Track


def _track(track_id: str = "track-1") -> Track:
    return Track(
        id=track_id,
        title="Song",
        artist="Artist",
        album="Album",
        durationMs=180_000,
        source="spotify",
        sourceUrl=f"https://example.test/{track_id}",
    )


def _manager(entries, order=None, **kwargs) -> LyricsManager:
    """Registry ساختگی بساز — بدون دست‌زدن به تنظیماتِ محیط."""
    registry = ProviderRegistry(list(entries), order or tuple(e.name for e in entries))
    return LyricsManager(registry=registry, **kwargs)


def _entry(name, fn, enabled=None) -> ProviderEntry:
    return ProviderEntry(name, fn, enabled)


class TestOrdering:
    def test_the_first_provider_wins_and_is_recorded(self):
        calls = []

        def first(*_):
            calls.append("first")
            return Lyrics(plain="plain", synced="[00:01.00]line")

        def second(*_):
            calls.append("second")
            return Lyrics(plain="fallback")

        manager = _manager([_entry("lrclib", first), _entry("genius", second)])

        result = manager.fetch(_track())

        assert result.plain == "plain"
        assert result.source == "lrclib"
        # provider_id شناسه‌ی Provider است، جدا از source که منبعِ ترک است
        assert result.provider_id == "lrclib"
        assert calls == ["first"]

    def test_a_later_provider_is_reached_after_an_empty_result(self):
        calls = []

        def empty(*_):
            calls.append("lrclib")
            return None

        def second(*_):
            calls.append("genius")
            return Lyrics(plain="fallback")

        manager = _manager([_entry("lrclib", empty), _entry("genius", second)])

        result = manager.fetch(_track())

        assert result.plain == "fallback"
        assert result.source == "genius"
        assert calls == ["lrclib", "genius"]

    def test_a_provider_exception_does_not_stop_the_rest(self):
        calls = []

        def broken(*_):
            calls.append("lrclib")
            raise RuntimeError("provider unavailable")

        def second(*_):
            calls.append("genius")
            return Lyrics(plain="fallback")

        manager = _manager([_entry("lrclib", broken), _entry("genius", second)])

        result = manager.fetch(_track())

        assert result is not None and result.plain == "fallback"
        assert calls == ["lrclib", "genius"]

    def test_order_from_the_registry_decides_the_winner(self):
        def a(*_):
            return Lyrics(plain="a")

        def b(*_):
            return Lyrics(plain="b")

        entries = [_entry("lrclib", a), _entry("genius", b)]

        # ترتیبِ معکوس: جنسیوس باید اول بیاید
        manager = _manager(entries, order=("genius", "lrclib"))

        assert manager.fetch(_track()).plain == "b"


class TestAvailability:
    def test_an_unknown_name_in_the_order_is_ignored(self):
        def a(*_):
            return Lyrics(plain="a")

        manager = _manager([_entry("lrclib", a)], order=("nope", "lrclib"))

        assert manager.registry.order == ("lrclib",)

    def test_a_registered_but_unlisted_provider_lands_last(self):
        def a(*_):
            return Lyrics(plain="a")

        def b(*_):
            return Lyrics(plain="b")

        manager = _manager([_entry("lrclib", a), _entry("genius", b)], order=("genius",))

        assert manager.registry.order == ("genius", "lrclib")

    def test_a_provider_reporting_itself_unavailable_is_skipped(self):
        calls = []

        def disabled(*_):
            calls.append("disabled")
            return Lyrics(plain="should not be used")

        def enabled(*_):
            calls.append("enabled")
            return Lyrics(plain="fallback")

        manager = _manager(
            [_entry("genius", disabled, lambda: False), _entry("lrclib", enabled)]
        )

        assert manager.fetch(_track()).plain == "fallback"
        assert calls == ["enabled"]

    def test_genius_is_skipped_when_its_token_is_absent(self, monkeypatch):
        """
        سیم‌کشیِ واقعیِ Genius: `enabled()` بدون توکن False می‌دهد، پس Provider
        باید بی‌سر‌و‌صدا رد شود. `fetch` ساختگی است ولی خودِ `genius.enabled`
        دست‌نخورده می‌ماند — همین چیزی است که این تست می‌سنجد.
        """
        from app.lyrics import manager as manager_module
        from app.lyrics.registry import ProviderEntry
        from app.providers import genius

        calls = []

        def lrclib_miss(*_):
            calls.append("lrclib")
            return None

        def genius_should_not_run(*_):
            calls.append("genius")
            return Lyrics(plain="unexpected")

        monkeypatch.setattr(
            manager_module,
            "_PROVIDERS",
            (
                ProviderEntry("lrclib", lrclib_miss),
                ProviderEntry("genius", genius_should_not_run, genius.enabled),
            ),
        )
        monkeypatch.setattr(genius, "GENIUS_ACCESS_TOKEN", None)

        manager = LyricsManager()

        assert manager.fetch(_track()) is None
        assert calls == ["lrclib"]


class TestGlobalGates:
    def test_a_blank_title_never_reaches_a_provider(self, monkeypatch):
        calls = []

        def provider(*_):
            calls.append("called")
            return Lyrics(plain="should not be used")

        manager = _manager([_entry("lrclib", provider)])
        track = _track()
        track.title = "   "

        assert manager.fetch(track) is None
        assert calls == []

    def test_nothing_runs_when_lyrics_are_disabled_globally(self, monkeypatch):
        calls = []

        def provider(*_):
            calls.append("called")
            return Lyrics(plain="should not be used")

        manager = _manager([_entry("lrclib", provider)])
        monkeypatch.setattr("app.lyrics.manager.LYRICS_ENABLED", False)

        assert manager.fetch(_track()) is None
        assert calls == []

    def test_every_provider_failing_returns_none(self):
        def broken(*_):
            raise RuntimeError("down")

        manager = _manager([_entry("lrclib", broken), _entry("genius", broken)])

        assert manager.fetch(_track()) is None

    def test_a_non_provider_error_does_not_clear_the_negative_cache(self, monkeypatch):
        """
        استثنای غیرِ `ProviderError` هم «خطا» است، نه «خالی». وگرنه یک باگِ
        درونِ Provider (مثلاً AttributeError روی بدنه‌ی غیرمنتظره) به کشِ منفی
        می‌رود و متنِ موجود را تا پایان TTL پنهان می‌کند.
        """
        calls = []
        now = [1000.0]

        def broken(*_):
            calls.append(1)
            raise AttributeError("'str' object has no attribute 'get'")

        manager = _manager([_entry("lrclib", broken)], miss_ttl_s=300, clock=lambda: now[0])

        manager.fetch(_track())
        manager.fetch(_track())
        assert len(calls) == 2


class TestNegativeCache:
    """
    فقط «پاسخِ معتبرِ خالی» کش می‌شود. خطا هرگز — وگرنه یک قطعیِ گذرا متنِ
    موجود را چند دقیقه پنهان می‌کند.
    """

    def test_an_empty_result_is_cached_within_the_ttl(self):
        calls = []
        now = [1000.0]

        def empty(*_):
            calls.append(1)
            return None

        manager = _manager([_entry("lrclib", empty)], miss_ttl_s=300, clock=lambda: now[0])

        assert manager.fetch(_track()) is None
        assert manager.fetch(_track()) is None
        assert len(calls) == 1

    def test_the_cache_expires_after_the_ttl(self):
        calls = []
        now = [1000.0]

        def empty(*_):
            calls.append(1)
            return None

        manager = _manager([_entry("lrclib", empty)], miss_ttl_s=300, clock=lambda: now[0])

        manager.fetch(_track())
        now[0] += 299
        manager.fetch(_track())
        assert len(calls) == 1

        now[0] += 2  # از TTL گذشت
        manager.fetch(_track())
        assert len(calls) == 2

    def test_a_provider_error_is_never_cached(self):
        """خطا یعنی «نمی‌دانیم»، نه «نیست» — پس باید هر بار دوباره تلاش شود."""
        calls = []
        now = [1000.0]

        def broken(*_):
            calls.append(1)
            raise RuntimeError("network down")

        manager = _manager([_entry("lrclib", broken)], miss_ttl_s=300, clock=lambda: now[0])

        manager.fetch(_track())
        manager.fetch(_track())
        assert len(calls) == 2

    def test_a_nonempty_result_is_not_negative_cached(self):
        calls = []
        now = [1000.0]

        def found(*_):
            calls.append(1)
            return Lyrics(plain="text")

        manager = _manager([_entry("lrclib", found)], miss_ttl_s=300, clock=lambda: now[0])

        manager.fetch(_track())
        assert manager.fetch(_track()).plain == "text"
        assert len(calls) == 2

    def test_a_later_success_clears_the_cached_miss(self):
        calls = []
        now = [1000.0]
        results = [None, Lyrics(plain="late")]

        def flaky(*_):
            calls.append(1)
            return results.pop(0)

        manager = _manager([_entry("lrclib", flaky)], miss_ttl_s=300, clock=lambda: now[0])

        assert manager.fetch(_track()) is None
        now[0] += 1
        # کشِ منفی هست ولی نتیجه‌ی موفقِ بعدی باید آن را پاک کند
        manager.forget("track-1")
        assert manager.fetch(_track()).plain == "late"

    def test_the_cache_is_per_track(self):
        calls = []
        now = [1000.0]

        def empty(*_):
            calls.append(1)
            return None

        manager = _manager([_entry("lrclib", empty)], miss_ttl_s=300, clock=lambda: now[0])

        manager.fetch(_track("a"))
        manager.fetch(_track("b"))
        assert len(calls) == 2

    def test_a_zero_ttl_disables_the_cache_entirely(self):
        calls = []

        def empty(*_):
            calls.append(1)
            return None

        manager = _manager([_entry("lrclib", empty)], miss_ttl_s=0)

        manager.fetch(_track())
        manager.fetch(_track())
        assert len(calls) == 2

    def test_an_error_from_one_provider_does_not_cache_when_another_succeeds(self):
        now = [1000.0]
        calls = []

        def broken(*_):
            calls.append("bad")
            raise RuntimeError("down")

        def found(*_):
            calls.append("good")
            return Lyrics(plain="text")

        manager = _manager(
            [_entry("lrclib", broken), _entry("genius", found)],
            miss_ttl_s=300,
            clock=lambda: now[0],
        )

        assert manager.fetch(_track()).plain == "text"
        assert manager.fetch(_track()).plain == "text"
        assert calls.count("good") == 2
