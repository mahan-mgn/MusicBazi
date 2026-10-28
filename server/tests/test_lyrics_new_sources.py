"""
S1.b/S1.d — منابعِ تازه: PaxSenix، Musixmatch، و سیاستِ Genius.

همه mock در سطح HTTP. هیچ کلید/توکنی چاپ نمی‌شود و هیچ درخواست زنده‌ای زده
نمی‌شود.
"""

from __future__ import annotations

import httpx
import pytest

from app import config
from app.lyrics.manager import LyricsManager
from app.lyrics.models import Lyrics
from app.lyrics.registry import ProviderEntry, ProviderError, ProviderRegistry
from app.models import Track
from app.providers import musixmatch, paxsenix


def _track(**extra) -> Track:
    base = {
        "id": "track-1",
        "title": "Song",
        "artist": "Artist",
        "album": "Album",
        "durationMs": 180_000,
        "source": "spotify",
        "sourceUrl": "https://example.test/1",
    }
    base.update(extra)
    return Track(**base)


class _Client:
    def __init__(self, handler):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, params=None, headers=None, **_):
        return self._handler(url, params or {}, headers or {})


def _resp(status, *, json_body=None, text="", content_type=None):
    request = httpx.Request("GET", "https://x.test")
    headers = {"content-type": content_type} if content_type else None
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=request, headers=headers)
    return httpx.Response(status, text=text, request=request, headers=headers)


def _patch(monkeypatch, module, handler):
    calls: list[str] = []

    def wrapped(url, params, headers):
        calls.append(url)
        return handler(url, params, headers)

    monkeypatch.setattr(module.httpx, "Client", lambda **_: _Client(wrapped))
    return calls


# ---------------------------------------------------------------- PaxSenix


class TestPaxSenix:
    def test_without_a_video_id_it_makes_no_request(self, monkeypatch):
        monkeypatch.setattr(
            paxsenix.httpx, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("no"))
        )

        assert paxsenix.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_with_a_video_id_the_lyrics_are_parsed(self, monkeypatch):
        _patch(monkeypatch, paxsenix, lambda *a: _resp(200, text="[00:01.00]hello"))

        found = paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ")

        assert found is not None
        assert len(found.lines) == 1

    def test_the_request_is_one_call_to_the_youtube_path(self, monkeypatch):
        calls = _patch(monkeypatch, paxsenix, lambda *a: _resp(200, text="[00:01.00]x"))

        paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ")

        assert len(calls) == 1
        assert calls[0].endswith("/youtube/lyrics")

    def test_a_ttml_payload_is_parsed(self, monkeypatch):
        ttml = (
            '<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
            '<p begin="1s" end="2s"><span begin="1s">a</span></p>'
            "</div></body></tt>"
        )
        _patch(monkeypatch, paxsenix, lambda *a: _resp(200, text=ttml))

        found = paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ")

        assert found.sync_type == "word"

    def test_a_json_envelope_with_an_error_is_empty(self, monkeypatch):
        _patch(
            monkeypatch,
            paxsenix,
            lambda *a: _resp(200, json_body={"error": True, "message": "nope"}, content_type="application/json"),
        )

        assert paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ") is None

    def test_a_404_is_empty(self, monkeypatch):
        _patch(monkeypatch, paxsenix, lambda *a: _resp(404))

        assert paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ") is None

    @pytest.mark.parametrize("status", [401, 403])
    def test_a_forbidden_endpoint_is_an_error_not_empty(self, monkeypatch, status):
        """
        بعضی مسیرهای این آگهی‌گر عمداً بسته‌اند. `403` یعنی «نمی‌دانم»، نه
        «این ترک را ندارم» — پس نباید کشِ منفی بگیرد.
        """
        _patch(monkeypatch, paxsenix, lambda *a: _resp(status))

        with pytest.raises(ProviderError) as info:
            paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ")
        assert info.value.status == status

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_error_statuses_raise(self, monkeypatch, status):
        _patch(monkeypatch, paxsenix, lambda *a: _resp(status))

        with pytest.raises(ProviderError):
            paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ")

    def test_a_timeout_raises_a_network_error(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ConnectTimeout("t")

        _patch(monkeypatch, paxsenix, handler)

        with pytest.raises(ProviderError) as info:
            paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ")
        assert info.value.kind == "network"

    def test_an_empty_body_is_empty(self, monkeypatch):
        _patch(monkeypatch, paxsenix, lambda *a: _resp(200, text=""))

        assert paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ") is None

    def test_the_public_fetch_swallows_every_error(self, monkeypatch):
        _patch(monkeypatch, paxsenix, lambda *a: _resp(500))

        assert paxsenix.fetch("Song", "Artist", None, 180_000) is None

    def test_an_error_never_leaks_the_key(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ConnectTimeout("https://secret/key=abc")

        _patch(monkeypatch, paxsenix, handler)

        with pytest.raises(ProviderError) as info:
            paxsenix.fetch_strict("Song", "Artist", None, 180_000, video_id="dQw4w9WgXcQ")

        assert info.value.detail == "ConnectTimeout"
        assert "abc" not in str(info.value)


# ---------------------------------------------------------------- Musixmatch


def _mx_envelope(status_code: int, body: dict | None = None) -> dict:
    return {"message": {"header": {"status_code": status_code}, "body": body or {}}}


class TestMusixmatchNeedsSetup:
    def test_without_a_key_it_is_disabled(self, monkeypatch):
        monkeypatch.setattr(musixmatch, "MUSIXMATCH_API_KEY", None)

        assert musixmatch.enabled() is False

    def test_with_a_key_it_is_enabled(self, monkeypatch):
        monkeypatch.setattr(musixmatch, "MUSIXMATCH_API_KEY", "k")

        assert musixmatch.enabled() is True

    def test_without_a_key_no_request_is_made(self, monkeypatch):
        monkeypatch.setattr(musixmatch, "MUSIXMATCH_API_KEY", None)
        monkeypatch.setattr(
            musixmatch.httpx, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("no"))
        )

        assert musixmatch.fetch_strict("Song", "Artist", None, 180_000) is None


class TestMusixmatch:
    @pytest.fixture(autouse=True)
    def key(self, monkeypatch):
        monkeypatch.setattr(musixmatch, "MUSIXMATCH_API_KEY", "test-key")

    def test_a_subtitle_body_is_parsed(self, monkeypatch):
        body = _mx_envelope(200, {"subtitle_body": "[00:01.00]hello\n[00:02.00]world"})
        _patch(monkeypatch, musixmatch, lambda *a: _resp(200, json_body=body))

        found = musixmatch.fetch_strict("Song", "Artist", None, 180_000)

        assert found is not None
        assert len(found.lines) == 2

    def test_the_key_is_sent_but_never_logged(self, monkeypatch):
        seen: list[dict] = []

        def handler(url, params, headers):
            seen.append(dict(params))
            return _resp(200, json_body=_mx_envelope(200, {"subtitle_body": "[00:01.00]x"}))

        _patch(monkeypatch, musixmatch, handler)
        musixmatch.fetch_strict("Song", "Artist", None, 180_000)

        assert seen[0].get("apikey") == "test-key"
        # مقدارِ کلید در هیچ پیامِ خطایی نمی‌آید (تستِ جدا پایین)

    def test_a_404_status_code_in_the_envelope_is_empty(self, monkeypatch):
        _patch(monkeypatch, musixmatch, lambda *a: _resp(200, json_body=_mx_envelope(404)))

        assert musixmatch.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_an_http_404_is_empty(self, monkeypatch):
        _patch(monkeypatch, musixmatch, lambda *a: _resp(404))

        assert musixmatch.fetch_strict("Song", "Artist", None, 180_000) is None

    @pytest.mark.parametrize("code", [401, 402, 403])
    def test_an_insufficient_plan_is_an_error_not_empty(self, monkeypatch, code):
        """
        «پلنِ من این را ندارد» با «این ترک را ندارم» یکی نیست. اگر خطا را
        خالی حساب کنیم، کشِ منفی می‌گیرد و کاربر همیشه «متنی نیست» می‌بیند.
        """
        _patch(monkeypatch, musixmatch, lambda *a: _resp(200, json_body=_mx_envelope(code)))

        with pytest.raises(ProviderError):
            musixmatch.fetch_strict("Song", "Artist", None, 180_000)

    def test_an_http_403_raises(self, monkeypatch):
        _patch(monkeypatch, musixmatch, lambda *a: _resp(403))

        with pytest.raises(ProviderError):
            musixmatch.fetch_strict("Song", "Artist", None, 180_000)

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_error_statuses_raise(self, monkeypatch, status):
        _patch(monkeypatch, musixmatch, lambda *a: _resp(status))

        with pytest.raises(ProviderError):
            musixmatch.fetch_strict("Song", "Artist", None, 180_000)

    def test_a_missing_envelope_raises_a_body_error(self, monkeypatch):
        _patch(monkeypatch, musixmatch, lambda *a: _resp(200, json_body={"nope": 1}))

        with pytest.raises(ProviderError) as info:
            musixmatch.fetch_strict("Song", "Artist", None, 180_000)
        assert info.value.kind == "body"

    def test_a_malformed_body_raises(self, monkeypatch):
        request = httpx.Request("GET", "https://x.test")
        _patch(monkeypatch, musixmatch, lambda *a: httpx.Response(200, content=b"{oops", request=request))

        with pytest.raises(ProviderError):
            musixmatch.fetch_strict("Song", "Artist", None, 180_000)

    def test_an_empty_subtitle_body_is_empty(self, monkeypatch):
        _patch(monkeypatch, musixmatch, lambda *a: _resp(200, json_body=_mx_envelope(200, {})))

        assert musixmatch.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_richsync_body_alone_is_not_treated_as_lrc(self, monkeypatch):
        """
        `richsync_body` یک رشتهٔ **JSON** است نه LRC؛ اگر آن را مثل LRC
        بدهیم پارسر چیزِ بی‌معنی می‌سازد. پس تنها `subtitle_body` خوانده
        می‌شود.
        """
        body = _mx_envelope(200, {"richsync_body": '[{"ts":0,"te":1,"l":"x"}]'})
        _patch(monkeypatch, musixmatch, lambda *a: _resp(200, json_body=body))

        assert musixmatch.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_a_conflicting_duration_is_rejected(self, monkeypatch):
        body = _mx_envelope(200, {"subtitle_body": "[00:01.00]x", "subtitle_length": 300})
        _patch(monkeypatch, musixmatch, lambda *a: _resp(200, json_body=body))

        assert musixmatch.fetch_strict("Song", "Artist", None, 180_000) is None

    def test_a_matching_duration_is_accepted(self, monkeypatch):
        body = _mx_envelope(200, {"subtitle_body": "[00:01.00]x", "subtitle_length": 180})
        _patch(monkeypatch, musixmatch, lambda *a: _resp(200, json_body=body))

        assert musixmatch.fetch_strict("Song", "Artist", None, 180_000) is not None

    def test_the_isrc_is_forwarded_when_present(self, monkeypatch):
        seen: list[dict] = []

        def handler(url, params, headers):
            seen.append(dict(params))
            return _resp(200, json_body=_mx_envelope(200, {"subtitle_body": "[00:01.00]x"}))

        _patch(monkeypatch, musixmatch, handler)
        musixmatch.fetch_strict("Song", "Artist", None, 180_000, isrc="US1234567890")

        assert seen[0].get("track_isrc") == "US1234567890"

    def test_the_public_fetch_swallows_every_error(self, monkeypatch):
        _patch(monkeypatch, musixmatch, lambda *a: _resp(500))

        assert musixmatch.fetch("Song", "Artist", None, 180_000) is None

    def test_a_timeout_raises_a_network_error(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ReadTimeout("t")

        _patch(monkeypatch, musixmatch, handler)

        with pytest.raises(ProviderError) as info:
            musixmatch.fetch_strict("Song", "Artist", None, 180_000)
        assert info.value.kind == "network"


class TestMusixmatchNeverLeaksTheKey:
    def test_a_provider_error_carries_no_key_material(self, monkeypatch):
        monkeypatch.setattr(musixmatch, "MUSIXMATCH_API_KEY", "SUPER-SECRET-KEY")

        def handler(url, params, headers):
            raise httpx.ConnectTimeout("SUPER-SECRET-KEY")

        _patch(monkeypatch, musixmatch, handler)

        with pytest.raises(ProviderError) as info:
            musixmatch.fetch_strict("Song", "Artist", None, 180_000)

        assert "SUPER-SECRET-KEY" not in str(info.value)
        assert info.value.detail == "ConnectTimeout"


# ---------------------------------------------------------------- Genius policy


class TestGeniusManualOnlyPolicy:
    """
    `GENIUS_POLICY=manual_only`: Genius از زنجیرهٔ خودکار بیرون است ولی
    همچنان ثبت‌شده و (با توکن) قابلِ‌صدا‌زدنِ دستی.
    """

    def test_by_default_genius_is_not_automatic(self, monkeypatch):
        monkeypatch.delenv("MUSICBAZI_LYRICS_GENIUS_POLICY", raising=False)

        assert config.lyrics_auto_enabled("genius") is False

    def test_other_providers_are_unaffected(self, monkeypatch):
        monkeypatch.delenv("MUSICBAZI_LYRICS_GENIUS_POLICY", raising=False)

        assert config.lyrics_auto_enabled("lrclib") is True
        assert config.lyrics_auto_enabled("lyricsplus") is True

    def test_keep_auto_restores_the_previous_chain(self, monkeypatch):
        monkeypatch.setenv("MUSICBAZI_LYRICS_GENIUS_POLICY", "keep_auto")

        assert config.lyrics_auto_enabled("genius") is True

    def test_genius_is_absent_from_the_automatic_chain(self, monkeypatch):
        monkeypatch.delenv("MUSICBAZI_LYRICS_GENIUS_POLICY", raising=False)
        monkeypatch.setattr("app.config.GENIUS_ACCESS_TOKEN", "t")

        manager = LyricsManager()

        assert "genius" not in [e.name for e in manager.registry.available()]

    def test_genius_is_still_registered_and_reachable_by_name(self, monkeypatch):
        monkeypatch.delenv("MUSICBAZI_LYRICS_GENIUS_POLICY", raising=False)

        manager = LyricsManager()

        assert manager.registry.get("genius") is not None

    def test_the_manager_does_not_call_genius_when_a_later_provider_can_answer(
        self, monkeypatch
    ):
        monkeypatch.delenv("MUSICBAZI_LYRICS_GENIUS_POLICY", raising=False)
        calls: list[str] = []

        def genius_like(*_):
            calls.append("genius")
            return Lyrics(plain="genius")

        def other(*_):
            calls.append("other")
            return Lyrics(plain="other")

        registry = ProviderRegistry(
            [ProviderEntry("genius", genius_like), ProviderEntry("other", other)],
            ("genius", "other"),
        )

        found = LyricsManager(registry=registry, miss_ttl_s=0).fetch(_track())

        assert found.plain == "other"
        assert calls == ["other"]


class TestNoSecretReachesLogs:
    """
    P5 — هیچ کلید/توکنی نباید به لاگ برسد.

    مسیرِ خطر: `log.warning(..., exc_info=True)` روی استثنای غیرمنتظره. اگر
    یک استثنای خامِ httpx با URLِ حاویِ کلید از Provider بیرون بزند،
    traceback می‌تواند کلید را چاپ کند. Providerها همهٔ استثناها را به
    `ProviderError` (که فقط نامِ کلاس را دارد) تبدیل می‌کنند، پس این تست
    ثابت می‌کند آن مسیر بسته است.
    """

    def test_a_failing_musixmatch_request_logs_no_key(self, monkeypatch, caplog):
        import logging

        from app.lyrics.manager import LyricsManager
        from app.lyrics.registry import ProviderEntry, ProviderRegistry

        monkeypatch.setattr(musixmatch, "MUSIXMATCH_API_KEY", "SUPER-SECRET-KEY-XYZ")

        def handler(url, params, headers):
            raise httpx.ConnectTimeout("https://api.musixmatch.com/?apikey=SUPER-SECRET-KEY-XYZ")

        _patch(monkeypatch, musixmatch, handler)
        registry = ProviderRegistry(
            [ProviderEntry("musixmatch", musixmatch.fetch, None, musixmatch.fetch_strict)],
            ("musixmatch",),
        )

        with caplog.at_level(logging.DEBUG):
            LyricsManager(registry=registry, miss_ttl_s=0).fetch(_track())

        assert "SUPER-SECRET-KEY-XYZ" not in caplog.text

    def test_a_failing_paxsenix_request_logs_no_key(self, monkeypatch, caplog):
        import logging

        from app.lyrics.manager import LyricsManager
        from app.lyrics.registry import ProviderEntry, ProviderRegistry

        def handler(url, params, headers):
            raise httpx.ConnectError("https://lyrics.paxsenix.org/x?secret=SUPER-SECRET-KEY-XYZ")

        _patch(monkeypatch, paxsenix, handler)
        registry = ProviderRegistry(
            [ProviderEntry("paxsenix", paxsenix.fetch, None, paxsenix.fetch_strict)],
            ("paxsenix",),
        )

        with caplog.at_level(logging.DEBUG):
            LyricsManager(registry=registry, miss_ttl_s=0).fetch(
                _track(videoId="dQw4w9WgXcQ")
            )

        assert "SUPER-SECRET-KEY-XYZ" not in caplog.text

    def test_the_sources_service_logs_no_key(self, monkeypatch, caplog):
        import asyncio
        import logging

        from app.lyrics.sources import LyricsSources

        monkeypatch.setattr(musixmatch, "MUSIXMATCH_API_KEY", "SUPER-SECRET-KEY-XYZ")

        def handler(url, params, headers):
            raise httpx.ReadTimeout("x?apikey=SUPER-SECRET-KEY-XYZ")

        _patch(monkeypatch, musixmatch, handler)
        registry = ProviderRegistry(
            [ProviderEntry("musixmatch", musixmatch.fetch, None, musixmatch.fetch_strict)],
            ("musixmatch",),
        )
        sources = LyricsSources(manager=LyricsManager(registry=registry))

        with caplog.at_level(logging.DEBUG):
            asyncio.run(sources.fetch_from("musixmatch", _track()))

        assert "SUPER-SECRET-KEY-XYZ" not in caplog.text
