"""
تفکیک «خطای گذرا» از «پاسخِ معتبرِ خالی».

مشکلی که این فایل قفل می‌کند: Providerهای واقعی هر خطا را می‌بلعیدند و `None`
می‌دادند، پس Manager از بیرون نمی‌توانست «LRCLIB قطع بود» را از «LRCLIB گفت
متنی ندارم» تشخیص دهد — و هر دو را «خالی» حساب می‌کرد، یعنی یک قطعیِ گذرا
متنِ موجود را چند دقیقه پنهان می‌کرد.

اینجا هیچ Providerای mock نمی‌شود؛ **لایهٔ HTTP** mock می‌شود (همان
`httpx.Client` که خودِ Providerها استفاده می‌کنند). پس مسیرِ واقعیِ
خطا-به-`ProviderError` سنجیده می‌شود، نه یک شبیه‌سازیِ دلبخواه.
"""

from __future__ import annotations

import httpx
import pytest

from app.lyrics.manager import LyricsManager
from app.lyrics.registry import ProviderError
from app.models import Track
from app.providers import genius, lrclib


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


def _row(duration=180, *, synced=None, plain=None) -> dict:
    return {"duration": duration, "syncedLyrics": synced, "plainLyrics": plain}


class _Client:
    """کلاینت جعلیِ httpx — هندلر واقعیِ درخواست را می‌گیرد."""

    def __init__(self, handler):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, params=None, headers=None):
        return self._handler(url, params or {}, headers or {})


def _resp(status: int, *, json_body=None, text: str = "", raw: str | None = None):
    request = httpx.Request("GET", "https://x.test")
    if raw is not None:
        return httpx.Response(status, content=raw.encode(), request=request)
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=request)
    return httpx.Response(status, text=text, request=request)


def _patch_lrclib(monkeypatch, handler, calls: list | None = None):
    def wrapped(url, params, headers):
        if calls is not None:
            calls.append(url)
        return handler(url, params)

    monkeypatch.setattr(lrclib.httpx, "Client", lambda **_: _Client(wrapped))


def _patch_genius(monkeypatch, handler, calls: list | None = None):
    monkeypatch.setattr(genius, "GENIUS_ACCESS_TOKEN", "test-token")

    def wrapped(url, params, headers):
        if calls is not None:
            calls.append(url)
        return handler(url, params)

    monkeypatch.setattr(genius.httpx, "Client", lambda **_: _Client(wrapped))


# ---------------------------------------------------------------- LRCLIB strict


class TestLrclibStrictTransientErrors:
    def test_a_timeout_raises_a_provider_error(self, monkeypatch):
        def handler(url, params):
            raise httpx.ConnectTimeout("timed out")

        _patch_lrclib(monkeypatch, handler)

        with pytest.raises(ProviderError):
            lrclib.fetch_strict("Song", "Artist", None, 180_000)

    def test_a_connection_error_raises_a_provider_error(self, monkeypatch):
        def handler(url, params):
            raise httpx.ConnectError("no route")

        _patch_lrclib(monkeypatch, handler)

        with pytest.raises(ProviderError):
            lrclib.fetch_strict("Song", "Artist", None, 180_000)

    @pytest.mark.parametrize("status", [429, 500, 503, 403, 401])
    def test_an_error_status_raises_a_provider_error(self, monkeypatch, status):
        def handler(url, params):
            return _resp(status)

        _patch_lrclib(monkeypatch, handler)

        with pytest.raises(ProviderError):
            lrclib.fetch_strict("Song", "Artist", None, 180_000)

    def test_a_malformed_json_body_raises_a_provider_error(self, monkeypatch):
        def handler(url, params):
            return _resp(200, raw="{not json")

        _patch_lrclib(monkeypatch, handler)

        with pytest.raises(ProviderError):
            lrclib.fetch_strict("Song", "Artist", None, 180_000)

    @pytest.mark.parametrize("row", ["not-a-dict", 1, None, ["nested"]])
    def test_a_search_row_with_an_unexpected_shape_raises_a_body_error(self, monkeypatch, row):
        """
        JSON معتبر است ولی ردیف‌ها دیکشنری نیستند. این خطای *ساختاری* است نه
        شبکه: باید `ProviderError(kind="body")` بدهد، نه یک `AttributeError`
        خام که هیچ مصرف‌کننده‌ای دسته‌بندی‌اش نمی‌کند. مسیر جستجو خطای
        `_pick_by_duration` را بیرون از try داشت، پس همین‌جا سرریز می‌کرد.
        """

        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[row])

        _patch_lrclib(monkeypatch, handler)

        with pytest.raises(ProviderError) as info:
            lrclib.fetch_strict("Song", "Artist", None, 180_000)
        assert info.value.kind == "body"

    @pytest.mark.parametrize("bad_duration", ["180", [180], {"s": 180}])
    def test_a_truthy_non_numeric_duration_raises_a_body_error(self, monkeypatch, bad_duration):
        """
        `abs("180" - 180)` یک TypeError خام می‌داد؛ باید ProviderError باشد.

        فقط مقادیرِ *truthy* اینجا هستند: مقدارِ falsy (خالی/صفر/None) از قبل
        «مدتِ نامعلوم» حساب می‌شود و رد نمی‌کند — آن قرارداد در
        `test_lrclib.py::test_a_row_with_no_duration_is_still_accepted` قفل است
        و این تغییر نباید عوضش کند.
        """

        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[_row(bad_duration, synced="[00:01.00]x")])

        _patch_lrclib(monkeypatch, handler)

        with pytest.raises(ProviderError) as info:
            lrclib.fetch_strict("Song", "Artist", None, 180_000)
        assert info.value.kind == "body"

    @pytest.mark.parametrize("falsy_duration", [[], {}, 0])
    def test_a_falsy_duration_is_still_treated_as_unknown_not_as_an_error(
        self, monkeypatch, falsy_duration
    ):
        """
        قراردادِ قبلی دست‌نخورده: falsy یعنی «Provider مدتی نگفت»، نه «بدنه
        خراب است». اینجا پذیرش درست است و نباید با اصلاح بالا عوض شود.
        """

        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[_row(falsy_duration, synced="[00:01.00]x")])

        _patch_lrclib(monkeypatch, handler)

        found = lrclib.fetch_strict("Song", "Artist", None, 180_000)
        assert found is not None and found.synced == "[00:01.00]x"

    def test_the_public_fetch_still_swallows_a_structural_error(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=["not-a-dict"])

        _patch_lrclib(monkeypatch, handler)

        assert lrclib.fetch("Song", "Artist", None, 180_000) is None


class TestLrclibStrictValidEmpty:
    def test_a_404_returns_none_not_an_error(self, monkeypatch):
        def handler(url, params):
            return _resp(404)

        _patch_lrclib(monkeypatch, handler)

        assert lrclib.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_an_empty_search_list_returns_none(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[])

        _patch_lrclib(monkeypatch, handler)

        assert lrclib.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_a_result_with_a_conflicting_duration_returns_none(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[_row(300, synced="[00:01.00]other")])

        _patch_lrclib(monkeypatch, handler)

        assert lrclib.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_a_matching_row_is_returned(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[_row(180, synced="[00:01.00]good")])

        _patch_lrclib(monkeypatch, handler)

        found = lrclib.fetch_strict("Song", "Artist", None, 180_000)
        assert found is not None and found.synced == "[00:01.00]good"


class TestLrclibPublicFetchIsUnchanged:
    """قرارداد قدیمی: هر خطایی → None. هیچ استثنایی بیرون نمی‌زند."""

    def test_a_timeout_returns_none(self, monkeypatch):
        def handler(url, params):
            raise httpx.ConnectTimeout("timed out")

        _patch_lrclib(monkeypatch, handler)

        assert lrclib.fetch("Song", "Artist", None, 180_000) is None

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_an_error_status_returns_none(self, monkeypatch, status):
        def handler(url, params):
            return _resp(status)

        _patch_lrclib(monkeypatch, handler)

        assert lrclib.fetch("Song", "Artist", None, 180_000) is None

    def test_a_malformed_body_returns_none(self, monkeypatch):
        def handler(url, params):
            return _resp(200, raw="nope")

        _patch_lrclib(monkeypatch, handler)

        assert lrclib.fetch("Song", "Artist", None, 180_000) is None

    def test_a_valid_result_is_still_returned(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[_row(180, synced="[00:01.00]ok")])

        _patch_lrclib(monkeypatch, handler)

        assert lrclib.fetch("Song", "Artist", None, 180_000).synced == "[00:01.00]ok"


# ---------------------------------------------------------------- Genius strict


class TestGeniusStrictTransientErrors:
    def test_a_timeout_raises_a_provider_error(self, monkeypatch):
        def handler(url, params):
            raise httpx.ConnectTimeout("timed out")

        _patch_genius(monkeypatch, handler)

        with pytest.raises(ProviderError):
            genius.fetch_strict("Song", "Artist", None, 180_000)

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_a_search_error_status_raises(self, monkeypatch, status):
        def handler(url, params):
            return _resp(status)

        _patch_genius(monkeypatch, handler)

        with pytest.raises(ProviderError):
            genius.fetch_strict("Song", "Artist", None, 180_000)

    def test_a_page_error_status_raises(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/search"):
                return _resp(200, json_body={"response": {"hits": [_hit("Song", "Artist")]}})
            return _resp(500)

        _patch_genius(monkeypatch, handler)

        with pytest.raises(ProviderError):
            genius.fetch_strict("Song", "Artist", None, 180_000)

    def test_a_404_on_search_raises_rather_than_looking_empty(self, monkeypatch):
        """
        خودِ `/search` گینس ۴۰۴ نمی‌دهد، پس ۴۰۴ یعنی مسیر عوض شده یا پروکسی
        جواب می‌دهد — نشانه‌ی مشکلِ زیرساختی، نه «این ترک را ندارم». اگر آن را
        خالی حساب کنیم، یک خرابیِ پایدار به کشِ منفی می‌رود و متنِ موجودِ
        Provider بعدی هم پنهان می‌شود.
        """

        def handler(url, params):
            return _resp(404)

        _patch_genius(monkeypatch, handler)

        with pytest.raises(ProviderError) as info:
            genius.fetch_strict("Song", "Artist", None, 180_000)
        assert info.value.status == 404

    @pytest.mark.parametrize(
        "hits",
        [["not-a-dict"], [None], [{"result": "oops"}], [{"result": {"url": "u", "title": "Song", "lyrics_state": "complete", "primary_artist": "oops"}}]],
    )
    def test_a_hit_with_an_unexpected_shape_raises_a_body_error(self, monkeypatch, hits):
        """JSON معتبر، ساختار غیرمنتظره — خطای body است نه یک استثنای خام."""

        def handler(url, params):
            return _resp(200, json_body={"response": {"hits": hits}})

        _patch_genius(monkeypatch, handler)

        with pytest.raises(ProviderError) as info:
            genius.fetch_strict("Song", "Artist", None, 180_000)
        assert info.value.kind == "body"


class TestGeniusStrictValidEmpty:
    def test_no_matching_hit_returns_none(self, monkeypatch):
        def handler(url, params):
            return _resp(200, json_body={"response": {"hits": []}})

        _patch_genius(monkeypatch, handler)

        assert genius.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_a_404_page_returns_none(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/search"):
                return _resp(200, json_body={"response": {"hits": [_hit("Song", "Artist")]}})
            return _resp(404)

        _patch_genius(monkeypatch, handler)

        assert genius.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_a_page_without_a_lyrics_container_returns_none(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/search"):
                return _resp(200, json_body={"response": {"hits": [_hit("Song", "Artist")]}})
            return _resp(200, text="<div>nothing here</div>")

        _patch_genius(monkeypatch, handler)

        assert genius.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_a_valid_page_is_returned(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/search"):
                return _resp(200, json_body={"response": {"hits": [_hit("Song", "Artist")]}})
            return _resp(200, text='<div data-lyrics-container="true">line</div>')

        _patch_genius(monkeypatch, handler)

        assert genius.fetch_strict("Song", "Artist", None, 180_000).plain == "line"


class TestGeniusPublicFetchIsUnchanged:
    def test_a_timeout_returns_none(self, monkeypatch):
        def handler(url, params):
            raise httpx.ConnectTimeout("timed out")

        _patch_genius(monkeypatch, handler)

        assert genius.fetch("Song", "Artist", None, 180_000) is None

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_an_error_status_returns_none(self, monkeypatch, status):
        def handler(url, params):
            return _resp(status)

        _patch_genius(monkeypatch, handler)

        assert genius.fetch("Song", "Artist", None, 180_000) is None


def _hit(title: str, artist: str, url: str = "https://genius.com/x") -> dict:
    return {
        "result": {
            "url": url,
            "lyrics_state": "complete",
            "title": title,
            "primary_artist": {"name": artist},
        }
    }


# ------------------------------------------------- Manager integration (the red)


class TestManagerCachesOnlyRealEmptiness:
    """
    تست‌های یکپارچه. اینها همان چیزی‌اند که با کد قبلی red می‌شدند: Provider
    خطا را می‌بلعید، پس Manager فکر می‌کرد «همه خالی گفتند» و کشِ منفی می‌نوشت.
    """

    def _http_calls_on_second_fetch(self, handler, monkeypatch) -> int:
        """
        دو درخواست پشت‌سرهم؛ تعداد HTTP روی درخواست *دوم* برگردانده می‌شود.

        شمارشِ کل عمداً کنار گذاشته شده: بار اول خودش چند درخواست می‌زند و
        جمعِ کل، تفاوتِ «کش شد» و «نشد» را پنهان می‌کرد — یک تستِ سبزِ الکی.
        """
        calls: list[str] = []
        _patch_lrclib(monkeypatch, handler, calls)
        monkeypatch.setattr(genius, "GENIUS_ACCESS_TOKEN", None)

        manager = LyricsManager(miss_ttl_s=300)
        manager.fetch(_track())

        calls.clear()
        manager.fetch(_track())
        return len(calls)

    def test_a_timeout_is_not_negative_cached(self, monkeypatch):
        def handler(url, params):
            raise httpx.ConnectTimeout("timed out")

        # خطاست، پس درخواست دوم باید دوباره تلاش کند
        assert self._http_calls_on_second_fetch(handler, monkeypatch) > 0

    def test_a_500_is_not_negative_cached(self, monkeypatch):
        def handler(url, params):
            return _resp(500)

        assert self._http_calls_on_second_fetch(handler, monkeypatch) > 0

    def test_a_503_is_not_negative_cached(self, monkeypatch):
        def handler(url, params):
            return _resp(503)

        assert self._http_calls_on_second_fetch(handler, monkeypatch) > 0

    def test_a_429_is_not_negative_cached(self, monkeypatch):
        def handler(url, params):
            return _resp(429)

        assert self._http_calls_on_second_fetch(handler, monkeypatch) > 0

    def test_a_malformed_body_is_not_negative_cached(self, monkeypatch):
        def handler(url, params):
            return _resp(200, raw="{oops")

        assert self._http_calls_on_second_fetch(handler, monkeypatch) > 0

    def test_an_http_200_without_any_matching_result_is_negative_cached(self, monkeypatch):
        """۲۰۰ ولی هیچ نتیجه‌ی همخوان — این «خالیِ معتبر» است، پس کش می‌شود."""

        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[_row(300, synced="[00:01.00]wrong version")])

        assert self._http_calls_on_second_fetch(handler, monkeypatch) == 0

    def test_a_404_is_negative_cached(self, monkeypatch):
        """خالیِ معتبر برعکس: باید کش شود تا زنجیره هر بار دوباره زده نشود."""

        def handler(url, params):
            return _resp(404)

        assert self._http_calls_on_second_fetch(handler, monkeypatch) == 0

    def test_an_empty_search_result_is_negative_cached(self, monkeypatch):
        def handler(url, params):
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[])

        assert self._http_calls_on_second_fetch(handler, monkeypatch) == 0

    def test_one_provider_erroring_does_not_block_the_other(self, monkeypatch):
        """خطای LRCLIB نباید مانع رسیدن به Genius شود."""
        from app.lyrics import manager as manager_module
        from app.lyrics.models import Lyrics
        from app.lyrics.registry import ProviderEntry

        def handler(url, params):
            raise httpx.ConnectTimeout("timed out")

        _patch_lrclib(monkeypatch, handler)
        monkeypatch.setattr(
            manager_module,
            "_PROVIDERS",
            (
                ProviderEntry("lrclib", lrclib.fetch, None, lrclib.fetch_strict),
                ProviderEntry("other", genius.fetch, None, lambda *_: Lyrics(plain="g")),
            ),
        )

        manager = LyricsManager(miss_ttl_s=300)

        result = manager.fetch(_track())
        assert result is not None and result.plain == "g"

    def test_a_disabled_provider_does_not_count_as_a_failure(self, monkeypatch):
        """Genius بدون توکن «رد شده» است، نه «خطا» — پس مانع کشِ منفی نیست."""
        calls: list[str] = []

        def handler(url, params):
            return _resp(404)

        _patch_lrclib(monkeypatch, handler, calls)
        monkeypatch.setattr(genius, "GENIUS_ACCESS_TOKEN", None)

        manager = LyricsManager(miss_ttl_s=300)

        assert manager.fetch(_track()) is None
        assert manager.fetch(_track()) is None
        assert len(calls) == 2


class TestEndToEndIntegration:
    """
    دو سناریوی سرتاسری که خواسته شده — با لایه‌ی HTTP mock، نه Provider.
    """

    def test_timeout_then_a_real_answer_is_not_hidden_by_a_cached_miss(self, monkeypatch):
        """
        LRCLIB قطع است، پس نتیجه کش نمی‌شود. درخواست بعدی (وقتی وصل شد) باید
        دوباره Provider را صدا بزند و متن را بگیرد — این تمام ماجرای باگِ
        اصلی است: کشِ منفیِ نادرست، متنِ موجود را پنج دقیقه پنهان می‌کرد.
        """
        state = {"online": False}

        def handler(url, params):
            if not state["online"]:
                raise httpx.ConnectTimeout("timed out")
            if url.endswith("/api/get"):
                return _resp(404)
            return _resp(200, json_body=[_row(180, synced="[00:01.00]recovered")])

        _patch_lrclib(monkeypatch, handler)
        monkeypatch.setattr(genius, "GENIUS_ACCESS_TOKEN", None)

        manager = LyricsManager(miss_ttl_s=300)

        assert manager.fetch(_track()) is None  # قطع بود

        state["online"] = True
        found = manager.fetch(_track())

        assert found is not None
        assert found.synced == "[00:01.00]recovered"

    def test_a_404_with_genius_unconfigured_is_cached_until_ttl(self, monkeypatch):
        """
        LRCLIB گفت ۴۰۴ و Genius بدون توکن رد شد → «خالیِ معتبر». باید کش شود
        و درخواست بعدی تا پایان TTL هیچ Providerی را صدا نزند.
        """
        calls: list[str] = []
        now = [1000.0]

        def handler(url, params):
            return _resp(404)

        _patch_lrclib(monkeypatch, handler, calls)
        monkeypatch.setattr(genius, "GENIUS_ACCESS_TOKEN", None)

        manager = LyricsManager(miss_ttl_s=300, clock=lambda: now[0])

        assert manager.fetch(_track()) is None
        calls.clear()

        assert manager.fetch(_track()) is None
        assert calls == []  # کش شد

        now[0] += 301  # TTL تمام شد
        manager.fetch(_track())
        assert calls != []  # دوباره تلاش شد

    def test_a_timeout_is_retried_immediately_and_is_not_cached(self, monkeypatch):
        calls: list[str] = []

        def handler(url, params):
            raise httpx.ConnectTimeout("timed out")

        _patch_lrclib(monkeypatch, handler, calls)
        monkeypatch.setattr(genius, "GENIUS_ACCESS_TOKEN", None)

        manager = LyricsManager(miss_ttl_s=300)

        manager.fetch(_track())
        calls.clear()
        manager.fetch(_track())

        assert calls != []  # برخلاف ۴۰۴، اینجا کش نشد


class TestProviderErrorShape:
    def test_it_carries_provider_kind_and_status(self):
        err = ProviderError("lrclib", "http", status=503, detail="server")
        assert err.provider == "lrclib"
        assert err.kind == "http"
        assert err.status == 503

    def test_the_message_names_the_provider_and_kind(self):
        err = ProviderError("genius", "network", detail="ConnectTimeout")
        assert "genius" in str(err)
        assert "network" in str(err)

    def test_it_does_not_leak_the_token(self):
        """پیام خطا هرگز نباید توکن یا URL حاوی کلید را چاپ کند."""
        err = ProviderError("genius", "http", status=401)
        assert "token" not in str(err).lower()
        assert "secret" not in str(err).lower()
