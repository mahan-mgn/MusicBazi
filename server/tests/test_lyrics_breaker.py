"""
قطع‌کننده‌ی مدار و تشخیصِ نتیجه‌ی تکراری (فاز ۲B.4.x).

قطع‌کننده با ساعتِ تزریقی سنجیده می‌شود — نه `time.sleep`. تستی که می‌خوابد
کند و شکننده است و نمی‌تواند مرزِ دقیقِ بازه را بسنجد.
"""

from __future__ import annotations

import httpx
import pytest

from app.lyrics.manager import LyricsManager
from app.lyrics.matching import looks_like_a_duplicate
from app.lyrics.models import LyricLine, Lyrics
from app.lyrics.registry import (
    CircuitBreaker,
    ProviderEntry,
    ProviderError,
    ProviderRegistry,
)
from app.models import Track
from app.providers import genius, lrclib


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


class _Clock:
    """ساعتِ دستی — فقط با `now += n` جلو می‌رود."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------- CircuitBreaker


class TestCircuitBreakerStates:
    def test_it_starts_closed(self):
        assert CircuitBreaker().is_open("anything") is False

    def test_it_stays_closed_below_the_threshold(self):
        breaker = CircuitBreaker(threshold=3, cooldown_s=60)

        breaker.record_failure("p")
        breaker.record_failure("p")

        assert breaker.is_open("p") is False

    def test_it_opens_at_the_threshold(self):
        breaker = CircuitBreaker(threshold=3, cooldown_s=60)

        for _ in range(3):
            breaker.record_failure("p")

        assert breaker.is_open("p") is True

    def test_a_success_resets_the_failure_count(self):
        breaker = CircuitBreaker(threshold=3, cooldown_s=60)

        breaker.record_failure("p")
        breaker.record_failure("p")
        breaker.record_success("p")
        breaker.record_failure("p")

        assert breaker.is_open("p") is False
        assert breaker.failures("p") == 1

    def test_it_stays_open_inside_the_cooldown(self):
        clock = _Clock()
        breaker = CircuitBreaker(threshold=1, cooldown_s=60, clock=clock)

        breaker.record_failure("p")
        clock.now += 59

        assert breaker.is_open("p") is True

    def test_it_closes_again_after_the_cooldown(self):
        clock = _Clock()
        breaker = CircuitBreaker(threshold=1, cooldown_s=60, clock=clock)

        breaker.record_failure("p")
        clock.now += 61

        assert breaker.is_open("p") is False

    def test_the_failure_count_is_reset_when_it_closes(self):
        """نصف‌باز: بعد از خنک‌شدن، Provider باید از صفر دوباره شانس بگیرد."""
        clock = _Clock()
        breaker = CircuitBreaker(threshold=2, cooldown_s=60, clock=clock)

        breaker.record_failure("p")
        breaker.record_failure("p")
        clock.now += 61
        breaker.is_open("p")

        assert breaker.failures("p") == 0

    def test_each_provider_has_its_own_state(self):
        breaker = CircuitBreaker(threshold=1, cooldown_s=60)

        breaker.record_failure("a")

        assert breaker.is_open("a") is True
        assert breaker.is_open("b") is False

    def test_a_zero_cooldown_disables_the_breaker(self):
        """cooldown صفر یعنی «هرگز قطع نکن» — راهِ فرار."""
        breaker = CircuitBreaker(threshold=1, cooldown_s=0)

        breaker.record_failure("p")

        assert breaker.is_open("p") is False

    def test_a_threshold_below_one_is_clamped(self):
        breaker = CircuitBreaker(threshold=0, cooldown_s=60)

        breaker.record_failure("p")

        assert breaker.is_open("p") is True


class TestCircuitBreakerThroughTheRegistry:
    def test_an_open_provider_disappears_from_available(self):
        breaker = CircuitBreaker(threshold=1, cooldown_s=60)
        entry = ProviderEntry("p", lambda *_: Lyrics(plain="x"))
        registry = ProviderRegistry([entry], ("p",), breaker=breaker)

        assert [e.name for e in registry.available()] == ["p"]

        breaker.record_failure("p")

        assert registry.available() == []

    def test_a_closed_provider_is_back_in_available(self):
        clock = _Clock()
        breaker = CircuitBreaker(threshold=1, cooldown_s=60, clock=clock)
        entry = ProviderEntry("p", lambda *_: Lyrics(plain="x"))
        registry = ProviderRegistry([entry], ("p",), breaker=breaker)

        breaker.record_failure("p")
        clock.now += 61

        assert [e.name for e in registry.available()] == ["p"]


class TestCircuitBreakerThroughTheManager:
    def test_a_provider_that_keeps_failing_stops_being_called(self):
        """
        سه درخواستِ پیاپی، هر سه ناموفق → درخواستِ چهارم نباید Provider را
        صدا بزند. این همان چیزی است که پخش را از یک تایم‌اوتِ کامل در هر
        ترک نجات می‌دهد.
        """
        clock = _Clock()
        calls: list[int] = []

        def broken(*_):
            calls.append(1)
            raise ProviderError("p", "network", detail="boom")

        breaker = CircuitBreaker(threshold=3, cooldown_s=60, clock=clock)
        registry = ProviderRegistry(
            [ProviderEntry("p", broken)], ("p",), breaker=breaker
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)

        for i in range(3):
            manager.fetch(_track(f"t{i}"))

        assert len(calls) == 3
        manager.fetch(_track("t4"))
        assert len(calls) == 3  # دیگر صدا زده نشد

    def test_the_provider_returns_after_the_cooldown(self):
        clock = _Clock()
        calls: list[int] = []

        def broken(*_):
            calls.append(1)
            raise ProviderError("p", "network", detail="boom")

        breaker = CircuitBreaker(threshold=1, cooldown_s=60, clock=clock)
        registry = ProviderRegistry(
            [ProviderEntry("p", broken)], ("p",), breaker=breaker
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)

        manager.fetch(_track("a"))
        assert len(calls) == 1
        manager.fetch(_track("b"))
        assert len(calls) == 1  # قطع است

        clock.now += 61
        manager.fetch(_track("c"))
        assert len(calls) == 2  # برگشت

    def test_a_successful_provider_is_never_evicted(self):
        breaker = CircuitBreaker(threshold=2, cooldown_s=60)
        registry = ProviderRegistry(
            [ProviderEntry("p", lambda *_: Lyrics(plain="ok"))], ("p",), breaker=breaker
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)

        for i in range(5):
            assert manager.fetch(_track(f"t{i}")) is not None

        assert registry.breaker.is_open("p") is False

    def test_an_empty_answer_resets_the_counter_not_evicts(self):
        """
        «نتیجه نداشتم» یعنی سرویس سالم است. اگر خالی هم خطا شمرده شود،
        Providerی که برای بیشتر ترک‌ها متن ندارد بی‌دلیل اخراج می‌شود.
        """
        breaker = CircuitBreaker(threshold=2, cooldown_s=60)
        calls: list[int] = []

        def empty(*_):
            calls.append(1)
            return None

        registry = ProviderRegistry(
            [ProviderEntry("p", empty)], ("p",), breaker=breaker
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)

        for i in range(5):
            manager.fetch(_track(f"t{i}"))

        assert len(calls) == 5
        assert breaker.is_open("p") is False

    def test_only_the_broken_provider_is_evicted(self):
        clock = _Clock()
        health: list[str] = []

        def broken(*_):
            raise ProviderError("bad", "http", status=500)

        def good(*_):
            health.append("good")
            return Lyrics(plain="found")

        breaker = CircuitBreaker(threshold=1, cooldown_s=60, clock=clock)
        registry = ProviderRegistry(
            [ProviderEntry("bad", broken), ProviderEntry("good", good)],
            ("bad", "good"),
            breaker=breaker,
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)

        assert manager.fetch(_track("a")).plain == "found"
        assert breaker.is_open("bad") is True
        assert breaker.is_open("good") is False

        manager.fetch(_track("b"))
        assert health == ["good", "good"]


# ------------------------------------------------- breaker vs. negative cache

class _FakeClient:
    def __init__(self, handler):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, params=None, headers=None):
        return self._handler(url, params or {}, headers or {})


def _resp(status: int, *, json_body=None) -> httpx.Response:
    request = httpx.Request("GET", "https://x.test")
    return httpx.Response(status, json=json_body, request=request)


class TestBreakerDoesNotPoisonTheNegativeCache:
    """
    Providerی که به‌خاطرِ breakerِ باز از `available()` غایب است، «رد شده»
    است نه «خالی». اگر مثلِ خالی شمرده شود، `LyricsManager` کشِ منفی
    می‌نویسد و یک قطعیِ گذرا متنِ موجود را چند دقیقه پنهان می‌کند — همان
    باگِ اصلیِ ۲B.0.1 که این بار از راهِ breaker برمی‌گشت.
    """

    def test_an_evicted_provider_does_not_write_a_negative_cache_entry(self):
        clock = _Clock()
        calls: list[int] = []
        now = [1000.0]

        def broken(*_):
            calls.append(1)
            raise ProviderError("p", "network", detail="down")

        breaker = CircuitBreaker(threshold=1, cooldown_s=60, clock=clock)
        registry = ProviderRegistry(
            [ProviderEntry("p", broken)], ("p",), breaker=breaker
        )
        # کشِ منفی روشن است — دقیقاً همان حالتی که نباید نوشته شود
        manager = LyricsManager(registry=registry, miss_ttl_s=300, clock=lambda: now[0])

        manager.fetch(_track("a"))  # خطا → breaker باز
        assert breaker.is_open("p") is True

        calls.clear()
        manager.fetch(_track("a"))  # بار دوم: Provider غایب است

        # اگر «خالی» شمرده شده بود، کش نوشته می‌شد و اینجا هیچ تلاشی نمی‌شد.
        # درخواست بعدیِ *همان ترک* پس از بسته‌شدنِ breaker باید دوباره برود.
        clock.now += 61
        manager.fetch(_track("a"))
        assert calls != [], "کشِ منفی نوشته شد — Providerِ ردشده «خالی» شمرده شده"

    def test_an_evicted_provider_blocks_the_cache_even_with_a_healthy_empty_one(self):
        """
        Providerِ سالمی که خالی جواب می‌دهد و Providerی که breaker اخراجش
        کرده، *با هم* «خالیِ معتبر» نمی‌سازند: اخراج‌شده «خطا» است، پس کشِ
        منفی نوشته نمی‌شود و درخواستِ بعدی دوباره تلاش می‌کند.

        جهتِ خطا محافظه‌کارانه است — هزینه‌اش چند جستجوی تکراری به Providerِ
        سالم است، نه پنهان‌کردنِ متنِ موجود.
        """
        clock = _Clock()
        calls: list[str] = []

        def empty(*_):
            calls.append("empty")
            return None

        def broken(*_):
            calls.append("broken")
            raise ProviderError("broken", "http", status=500)

        breaker = CircuitBreaker(threshold=1, cooldown_s=60, clock=clock)
        registry = ProviderRegistry(
            [ProviderEntry("empty", empty), ProviderEntry("broken", broken)],
            ("empty", "broken"),
            breaker=breaker,
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=300)

        manager.fetch(_track("a"))
        assert breaker.is_open("broken") is True

        calls.clear()
        manager.fetch(_track("a"))
        assert calls == ["empty"]

        calls.clear()
        manager.fetch(_track("a"))
        assert calls == ["empty"], "اخراج‌شده «خطا» است — نباید کشِ منفی نوشته شود"


class TestEmptyAnswersNeverOpenTheBreaker:
    """«نتیجه‌ای نیست» یعنی سرویس سالم است. نباید breaker را باز کند."""

    def test_a_404_does_not_open_the_breaker(self, monkeypatch):
        breaker = CircuitBreaker(threshold=1, cooldown_s=60)

        def handler(url, params, headers):
            return _resp(404)  # فقط /api/get؛ قبل از جستجو برمی‌گردد

        monkeypatch.setattr(lrclib.httpx, "Client", lambda **_: _FakeClient(handler))
        registry = ProviderRegistry(
            [ProviderEntry("lrclib", lrclib.fetch, None, lrclib.fetch_strict)],
            ("lrclib",),
            breaker=breaker,
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)

        for i in range(5):
            manager.fetch(_track(f"t{i}"))

        assert breaker.is_open("lrclib") is False
        assert breaker.failures("lrclib") == 0

    def test_an_empty_search_list_does_not_open_the_breaker(self, monkeypatch):
        breaker = CircuitBreaker(threshold=1, cooldown_s=60)

        def handler(url, params, headers):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[])

        monkeypatch.setattr(lrclib.httpx, "Client", lambda **_: _FakeClient(handler))
        registry = ProviderRegistry(
            [ProviderEntry("lrclib", lrclib.fetch, None, lrclib.fetch_strict)],
            ("lrclib",),
            breaker=breaker,
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)

        for i in range(5):
            manager.fetch(_track(f"t{i}"))

        assert breaker.is_open("lrclib") is False


class TestLrclibAndGeniusKeepTheirOldBehaviour:
    """
    رفتارِ *قبل از* ۲B.4 برای lrclib/genius دقیقاً همان بود: خطا → Providerِ
    بعدی، و اگر همه خطا/خالی بودند → کشِ منفی. breaker نباید این را عوض کند.

    سناریوی خواسته‌شده: lrclib با breakerِ باز + genius بدون توکن → درخواستِ
    بعدی باید دوباره تلاش کند و کشِ منفی ننویسد.
    """

    def test_open_breaker_on_lrclib_plus_tokenless_genius_retries(self, monkeypatch):
        clock = _Clock()
        now = [1000.0]
        calls: list[str] = []

        def handler(url, params, headers):
            calls.append(url)
            raise httpx.ConnectTimeout("down")

        monkeypatch.setattr(lrclib.httpx, "Client", lambda **_: _FakeClient(handler))
        monkeypatch.setattr(genius, "GENIUS_ACCESS_TOKEN", None)

        # breaker برای lrclib روشن است (چون فقط lrclib صدا زده می‌شود)
        manager = LyricsManager(miss_ttl_s=300, clock=lambda: now[0])
        manager.registry.breaker = CircuitBreaker(threshold=1, cooldown_s=60, clock=clock)

        for i in range(3):
            manager.fetch(_track(f"t{i}"))

        calls.clear()
        # بعد از بازشدنِ breaker، درخواستِ تازه باید دوباره تلاش کند
        manager.fetch(_track("fresh"))

        assert calls != [], "کشِ منفی نوشته شد در حالی که lrclib فقط خطا داده بود"


# ---------------------------------------------------------------- duplicates


class TestDuplicateDetection:
    def test_it_is_never_consulted_by_the_manager(self, monkeypatch):
        """
        تشخیصِ تکراری روی مسیرِ `lrclib → genius` **بی‌اثر** است.

        اثباتِ رفتاری، نه فقط نبودنِ فراخوان: هر دو Provider همان متن را
        می‌دهند؛ اگر منطقِ تکراری‌بودن در مسیر بود، Providerِ دوم صدا زده
        نمی‌شد. اینجا باید صدا زده شود — چون lrclib اوّل برنده می‌شود و
        هرگز نوبت به genius نمی‌رسد. پس ترتیب دست‌نخورده است.
        """
        from app.lyrics.manager import LyricsManager
        from app.lyrics.registry import ProviderEntry, ProviderRegistry

        calls: list[str] = []
        same_text = "[00:01.00]same line"

        def lrclib_like(*_):
            calls.append("lrclib")
            return Lyrics(plain="same line", synced=same_text)

        def genius_like(*_):
            calls.append("genius")
            return Lyrics(plain="same line")

        registry = ProviderRegistry(
            [ProviderEntry("lrclib", lrclib_like), ProviderEntry("genius", genius_like)],
            ("lrclib", "genius"),
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)

        found = manager.fetch(_track())

        assert found is not None
        assert found.provider_id == "lrclib"
        assert calls == ["lrclib"], "Providerِ دوم نباید صدا زده شود"

    def test_the_helper_itself_still_detects_identical_text(self):
        assert looks_like_a_duplicate("[00:01.00]x", "[00:01.00]x") is True

    def test_the_same_text_is_a_duplicate(self):
        assert looks_like_a_duplicate("one two three", "one two three") is True

    def test_a_different_line_break_is_still_the_same_text(self):
        """دو mirror می‌توانند یک متن را با شکستِ خطِ متفاوت بدهند."""
        assert looks_like_a_duplicate("one two\nthree", "one\ntwo three") is True

    def test_different_words_are_not_duplicates(self):
        assert looks_like_a_duplicate("one two", "one three") is False

    def test_a_studio_and_a_live_version_are_not_duplicates(self):
        """
        آستانه سخت‌گیر است: دو اجرای همان آهنگ کلمه‌های زیادی مشترک دارند
        ولی یکی نیستند. اگر «تکراری» شمرده شوند، نسخه‌ی درست دور می‌افتد.
        """
        studio = "hold me now i need you here tonight"
        live = "hold me now i need you here tonight everybody sing"

        assert looks_like_a_duplicate(studio, live) is False

    def test_an_empty_side_is_never_a_duplicate(self):
        assert looks_like_a_duplicate("", "one two") is False
        assert looks_like_a_duplicate("one two", "") is False
        assert looks_like_a_duplicate(None, None) is False

    def test_extra_punctuation_does_not_matter(self):
        assert looks_like_a_duplicate("one, two!", "one two") is True

    def test_persian_text_is_compared_word_wise(self):
        assert looks_like_a_duplicate("سلام دنیا", "دنیا سلام") is True
