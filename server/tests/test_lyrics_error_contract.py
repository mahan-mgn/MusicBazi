"""
G2 — قراردادِ خطای ماشین‌خوان برای مسیرِ provider-محور.

مسئله: فرانت فقط `!r.ok` را می‌دید، پس «این آهنگ متن ندارد» (۴۰۴) با «سرویس
خراب است» (۵۰۲) یکی می‌شد و هر دو پیامِ مبهمِ «Selected source was
unavailable» می‌گرفتند.

قرارداد: بدنهٔ خطا فیلدهای اختیاریِ `code` و `provider` می‌گیرد. `detail`
دست‌نخورده می‌ماند تا کلاینتِ قدیمی نشکند.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch, fresh_db):
    from app import main

    return TestClient(main.app)


_counter = {"n": 0}


def _params(track_id: str | None = None) -> dict:
    """
    پارامترهای ترک با شناسهٔ یکتا.

    بدونِ یکتایی، کشِ منفیِ یک تست به تستِ بعدی نشت می‌کند و نتیجه‌ها
    ترتیب‌وابسته می‌شوند: تست تنها سبز، در مجموعه قرمز.
    """
    if track_id is None:
        _counter["n"] += 1
        track_id = f"spotify:track:ec-{_counter['n']}"
    return {
        "track_id": track_id,
        "title": "Song",
        "artist": "Artist",
        "duration_ms": 180000,
    }


class _Client:
    def __init__(self, handler):
        self._h = handler

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, params=None, headers=None, **_):
        return self._h(url, params or {}, headers or {})


def _resp(status: int, *, json_body=None) -> httpx.Response:
    req = httpx.Request("GET", "https://x.test")
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=req)
    return httpx.Response(status, text="", request=req)


def _patch_lrclib(monkeypatch, handler):
    from app.providers import lrclib

    monkeypatch.setattr(lrclib.httpx, "Client", lambda **_: _Client(handler))


class TestMachineReadableCodes:
    def test_an_unknown_provider_has_a_code(self, client):
        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "nope"}).json()

        assert body["code"] == "unknown_provider"

    def test_a_needs_setup_provider_has_a_code(self, client, monkeypatch):
        monkeypatch.setattr("app.providers.musixmatch.MUSIXMATCH_API_KEY", None)

        body = client.get(
            "/api/stream/lyrics", params={**_params(), "provider": "musixmatch"}
        ).json()

        assert body["code"] == "needs_setup"

    def test_a_blocked_source_is_not_reported_as_unknown(self, client):
        """
        `kugou` در رجیستری نیست، پس نگهبانِ `registry.get` آن را «ناشناخته»
        می‌گرفت. ولی کارِ نکردنش «ناشناس بودن» نیست — ممنوع است.
        """
        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "kugou"}).json()

        assert body["code"] == "blocked"

    def test_a_dark_source_is_reported_as_disabled(self, client, monkeypatch):
        """
        منبعی که فقط پیش‌فرض خاموش است، «ناشناخته» نیست — «خاموش» است.
        فرانت باید بتواند بگوید «با env روشنش کن».
        """
        monkeypatch.setenv("MUSICBAZI_LYRICS_PROVIDER_LYRICSPLUS_ENABLED", "0")

        body = client.get(
            "/api/stream/lyrics", params={**_params(), "provider": "lyricsplus"}
        ).json()

        assert body["code"] == "disabled"

    def test_a_missing_lyric_is_not_found(self, client, monkeypatch):
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(404))

        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "lrclib"}).json()

        assert body["code"] == "not_found"

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_a_provider_http_failure_is_a_provider_error(self, client, monkeypatch, status):
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(status))

        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "lrclib"}).json()

        assert body["code"] == "provider_error"

    def test_a_rate_limit_has_its_own_code(self, client, monkeypatch):
        """۴۲۹ «بعداً دوباره امتحان کن» است، نه «سرویس خراب است»."""
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(429))

        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "lrclib"}).json()

        assert body["code"] == "rate_limited"

    def test_a_timeout_is_a_provider_error(self, client, monkeypatch):
        def handler(u, p, h):
            raise httpx.ConnectTimeout("t")

        _patch_lrclib(monkeypatch, handler)

        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "lrclib"}).json()

        assert body["code"] == "provider_error"

    def test_the_code_is_accompanied_by_the_provider_name(self, client, monkeypatch):
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(503))

        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "lrclib"}).json()

        assert body["provider"] == "lrclib"

    def test_an_http_status_is_reported_when_known(self, client, monkeypatch):
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(503))

        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "lrclib"}).json()

        assert body["http_status"] == 503

    def test_no_http_status_for_a_network_error(self, client, monkeypatch):
        def handler(u, p, h):
            raise httpx.ConnectTimeout("t")

        _patch_lrclib(monkeypatch, handler)

        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "lrclib"}).json()

        assert body.get("http_status") is None


class TestBackwardsCompatibility:
    def test_detail_is_still_present(self, client):
        body = client.get("/api/stream/lyrics", params={**_params(), "provider": "nope"}).json()

        assert body["detail"]

    def test_the_auto_path_is_unchanged(self, client, monkeypatch):
        """مسیرِ بدونِ provider هیچ فیلدِ تازه‌ای نمی‌گیرد."""
        from app import stream_cache

        async def fake(_track):
            return "[00:01.00]x"

        monkeypatch.setattr(stream_cache, "get_or_fetch_lyrics", fake)

        response = client.get("/api/stream/lyrics", params=_params())

        assert response.status_code == 200
        assert response.text == "[00:01.00]x"

    def test_the_auto_paths_404_has_no_machine_code(self, client, monkeypatch):
        """
        مسیرِ خودکار اصلاً منبع ندارد، پس کدِ منبع‌محور برایش بی‌معناست و
        نباید اضافه شود (قراردادِ قبلی حفظ می‌شود).
        """
        from app import stream_cache

        async def fake(_track):
            return None

        monkeypatch.setattr(stream_cache, "get_or_fetch_lyrics", fake)

        body = client.get("/api/stream/lyrics", params=_params()).json()

        assert body["detail"]
        assert "code" not in body

    def test_no_error_body_leaks_sensitive_data(self, client, monkeypatch):
        def handler(u, p, h):
            raise httpx.ConnectTimeout("https://x.test/?apikey=SUPERSECRET")

        _patch_lrclib(monkeypatch, handler)

        text = client.get(
            "/api/stream/lyrics", params={**_params(), "provider": "lrclib"}
        ).text

        assert "SUPERSECRET" not in text
        assert "apikey" not in text.lower()


class TestSourcesReportLastOutcome:
    """هر ردیفِ منابع می‌گوید آخرین تلاش چه شد — بدونِ درخواستِ شبکه."""

    def _rows(self, client, track_id: str) -> dict:
        """وضعیتِ منابع برای *همان* آهنگی که واکشی شد."""
        body = client.get("/api/lyrics/sources", params=_params(track_id)).json()
        return {r["id"]: r for r in body["sources"]}

    def test_a_never_tried_source_says_so(self, client):
        rows = self._rows(client, "t-never")

        assert rows["lrclib"]["last_outcome"] == "never_tried"

    def test_after_a_successful_fetch_the_outcome_is_cached(self, client, monkeypatch):
        _patch_lrclib(
            monkeypatch,
            lambda u, p, h: (
                _resp(404) if u.endswith("/api/get") else _resp(200, json_body=[{"duration": 180, "syncedLyrics": "[00:01.00]x"}])
            ),
        )

        _fetch_cached = "t-cached"
        client.get("/api/stream/lyrics", params={**_params(_fetch_cached), "provider": "lrclib"})
        rows = self._rows(client, _fetch_cached)

        assert rows["lrclib"]["last_outcome"] == "cached"

    def test_after_a_not_found_the_outcome_says_not_found(self, client, monkeypatch):
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(404))

        _fetch_miss = "t-miss"
        client.get("/api/stream/lyrics", params={**_params(_fetch_miss), "provider": "lrclib"})
        rows = self._rows(client, _fetch_miss)

        assert rows["lrclib"]["last_outcome"] == "not_found"

    def test_after_an_error_the_outcome_says_error(self, client, monkeypatch):
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(503))

        _fetch_err = "t-err"
        client.get("/api/stream/lyrics", params={**_params(_fetch_err), "provider": "lrclib"})
        rows = self._rows(client, _fetch_err)

        assert rows["lrclib"]["last_outcome"] == "error"

    def test_the_error_kind_is_reported(self, client, monkeypatch):
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(503))

        _fetch_kind = "t-kind"
        client.get("/api/stream/lyrics", params={**_params(_fetch_kind), "provider": "lrclib"})
        rows = self._rows(client, _fetch_kind)

        assert rows["lrclib"]["last_error_kind"] == "http"

    def test_a_rate_limit_is_its_own_kind(self, client, monkeypatch):
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(429))

        _fetch_rl = "t-rl"
        client.get("/api/stream/lyrics", params={**_params(_fetch_rl), "provider": "lrclib"})
        rows = self._rows(client, _fetch_rl)

        assert rows["lrclib"]["last_error_kind"] == "rate_limited"

    def test_the_http_status_is_reported(self, client, monkeypatch):
        _patch_lrclib(monkeypatch, lambda u, p, h: _resp(503))

        _fetch_http = "t-http"
        client.get("/api/stream/lyrics", params={**_params(_fetch_http), "provider": "lrclib"})
        rows = self._rows(client, _fetch_http)

        assert rows["lrclib"]["http_status"] == 503

    def test_listing_sources_still_makes_no_provider_request(self, client, monkeypatch):
        from app.lyrics import sources as sources_module

        def explode(*_a, **_k):
            raise AssertionError("must not call a provider")

        monkeypatch.setattr(sources_module.LyricsSources, "_run", explode)

        assert client.get("/api/lyrics/sources", params=_params()).status_code == 200
