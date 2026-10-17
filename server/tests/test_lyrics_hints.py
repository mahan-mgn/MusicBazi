"""
S1.a — راهنماهای اختیاری (`videoId`/`isrc`) از Track تا endpoint.

این‌ها همگی additive‌اند: نبودشان رفتارِ قبلی را عوض نمی‌کند. تمرکز روی
سازگاریِ عقب‌رو و روی رسیدنِ قطعیِ `videoId` به Providerی که بدونش کار نمی‌کند.

هیچ درخواست شبکه‌ای زده نمی‌شود؛ لایهٔ Provider در همه‌جا ساختگی است.
"""

from __future__ import annotations

import asyncio

import pytest

from app import stream_cache
from app.lyrics.manager import LyricsManager, _accepts_hints
from app.lyrics.models import Lyrics
from app.lyrics.registry import ProviderEntry, ProviderError, ProviderRegistry
from app.models import Track


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


class TestTrackModelHints:
    def test_the_hints_are_optional_and_default_to_none(self):
        track = _track()

        assert track.videoId is None
        assert track.isrc is None

    def test_the_hints_round_trip(self):
        track = _track(videoId="dQw4w9WgXcQ", isrc="US1234567890")

        assert track.videoId == "dQw4w9WgXcQ"
        assert track.isrc == "US1234567890"

    def test_the_dump_keeps_the_camel_case_names(self):
        """فرانت انتظارِ `videoId`/`isrc` دارد، نه snake_case."""
        payload = _track(videoId="x" * 11, isrc="Y" * 12).model_dump()

        assert payload["videoId"] == "x" * 11
        assert payload["isrc"] == "Y" * 12


class TestProviderSignatureUniformity:
    def test_every_provider_strict_accepts_the_hints(self):
        import inspect

        from app.lyrics.manager import _PROVIDERS

        for entry in _PROVIDERS:
            params = inspect.signature(entry.strict()).parameters
            assert "video_id" in params, entry.name
            assert "isrc" in params, entry.name


class TestManagerPassesHints:
    def test_hints_reach_a_provider_that_accepts_them(self):
        seen: list[dict] = []

        def capturing(title, artist, album, duration_ms, *, video_id=None, isrc=None):
            seen.append({"video_id": video_id, "isrc": isrc})
            return None

        registry = ProviderRegistry(
            [ProviderEntry("p", lambda *a, **k: None, None, capturing)], ("p",)
        )
        LyricsManager(registry=registry, miss_ttl_s=0).fetch(
            _track(videoId="dQw4w9WgXcQ", isrc="US1234567890")
        )

        assert seen == [{"video_id": "dQw4w9WgXcQ", "isrc": "US1234567890"}]

    def test_hints_are_none_when_the_track_has_none(self):
        seen: list[dict] = []

        def capturing(title, artist, album, duration_ms, *, video_id=None, isrc=None):
            seen.append({"video_id": video_id, "isrc": isrc})
            return None

        registry = ProviderRegistry(
            [ProviderEntry("p", lambda *a, **k: None, None, capturing)], ("p",)
        )
        LyricsManager(registry=registry, miss_ttl_s=0).fetch(_track())

        assert seen == [{"video_id": None, "isrc": None}]

    def test_a_provider_without_the_keywords_is_not_broken(self):
        """
        سازگاریِ عقب‌رو: Providerی که چهار آرگومانِ موقعیتی می‌گیرد نباید با
        پاس‌شدنِ کلیدواژه‌ها `TypeError` بدهد — وگرنه Manager آن را «خطای
        غیرمنتظره» می‌شمرد و بیهوده اخراج می‌کرد.
        """

        def four_arg(title, artist, album, duration_ms):
            return Lyrics(plain="ok")

        registry = ProviderRegistry(
            [ProviderEntry("plain", four_arg, None, four_arg)], ("plain",)
        )

        found = LyricsManager(registry=registry, miss_ttl_s=0).fetch(
            _track(videoId="dQw4w9WgXcQ")
        )

        assert found is not None and found.plain == "ok"

    def test_accepts_hints_detects_the_signature(self):
        def with_hints(a, b, c, d, *, video_id=None, isrc=None):
            return None

        def without_hints(a, b, c, d):
            return None

        assert _accepts_hints(with_hints) is True
        assert _accepts_hints(without_hints) is False

    def test_a_provider_error_still_propagates_as_a_skip(self):
        """راهنما نباید تفکیکِ خطا را عوض کند."""
        calls: list[str] = []

        def broken(title, artist, album, duration_ms, *, video_id=None, isrc=None):
            calls.append("broken")
            raise ProviderError("b", "http", status=503)

        def good(title, artist, album, duration_ms, *, video_id=None, isrc=None):
            calls.append("good")
            return Lyrics(plain="found")

        registry = ProviderRegistry(
            [ProviderEntry("b", broken, None, broken), ProviderEntry("g", good, None, good)],
            ("b", "g"),
        )

        found = LyricsManager(registry=registry, miss_ttl_s=0).fetch(_track())

        assert found is not None and calls == ["broken", "good"]


class TestSimpMusicIsReachableEndToEnd:
    """
    رفعِ UNREACHABLE: با `Track.videoId` و عبورِ Manager، SimpMusic حالا
    واقعاً صدا زده می‌شود.
    """

    def test_a_track_with_a_video_id_reaches_simpmusic(self, monkeypatch):
        from app.providers import simpmusic

        requests: list[str] = []

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def get(self, url, params=None, headers=None, **_):
                requests.append(url)
                import httpx

                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "songTitle": "Song",
                            "artistName": "Artist",
                            "durationSeconds": 180,
                            "syncedLyrics": "[00:01.00]x",
                        },
                    },
                    request=httpx.Request("GET", url),
                )

        monkeypatch.setattr(simpmusic.httpx, "Client", lambda **_: _Client())
        registry = ProviderRegistry(
            [ProviderEntry("simpmusic", simpmusic.fetch, None, simpmusic.fetch_strict)],
            ("simpmusic",),
        )

        found = LyricsManager(registry=registry, miss_ttl_s=0).fetch(
            _track(videoId="dQw4w9WgXcQ")
        )

        assert found is not None
        assert len(requests) == 1 and requests[0].endswith("/v1/dQw4w9WgXcQ")

    def test_without_a_video_id_simpmusic_makes_no_request(self, monkeypatch):
        from app.providers import simpmusic

        monkeypatch.setattr(
            simpmusic.httpx, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("no"))
        )
        registry = ProviderRegistry(
            [ProviderEntry("simpmusic", simpmusic.fetch, None, simpmusic.fetch_strict)],
            ("simpmusic",),
        )

        assert LyricsManager(registry=registry, miss_ttl_s=0).fetch(_track()) is None


class TestVideoIdFromTrackId:
    def test_a_youtube_music_id_is_extracted(self):
        from app.main import _video_id_from_track_id

        assert _video_id_from_track_id("ytm:track:dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_a_youtube_id_is_extracted(self):
        from app.main import _video_id_from_track_id

        assert _video_id_from_track_id("yt:track:dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_a_non_youtube_id_is_not_guessed(self):
        from app.main import _video_id_from_track_id

        assert _video_id_from_track_id("spotify:track:4uLU6hMCjMI75M1A2tKUQC") is None
        assert _video_id_from_track_id("") is None
        assert _video_id_from_track_id("dQw4w9WgXcQ") is None

    def test_a_youtube_id_with_a_bad_tail_is_rejected(self):
        from app.main import _video_id_from_track_id

        assert _video_id_from_track_id("ytm:track:short") is None


class TestStreamLyricsEndpointHints:
    """endpoint راهنماها را می‌پذیرد و رفتارِ قبلی را عوض نمی‌کند."""

    @pytest.fixture
    def temp_cache(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(stream_cache, "STREAM_CACHE_DIR", cache_dir)
        return cache_dir

    def _call(self, **kwargs):
        from app import main

        params = {
            "track_id": "spotify:track:1",
            "title": "Song",
            "artist": "Artist",
        }
        params.update(kwargs)
        return asyncio.run(main.stream_lyrics(**params))

    def test_the_old_contract_without_hints_is_unchanged(self, temp_cache):
        key = stream_cache.cache_key_for("spotify:track:1")
        (temp_cache / f"{key}.lrc").write_text("[00:01.00]x", encoding="utf-8")

        response = self._call()

        assert response.media_type == "text/plain; charset=utf-8"
        assert response.body.decode("utf-8") == "[00:01.00]x"

    def test_the_endpoint_accepts_the_hint_parameters(self, temp_cache):
        key = stream_cache.cache_key_for("ytm:track:dQw4w9WgXcQ")
        (temp_cache / f"{key}.lrc").write_text("[00:01.00]y", encoding="utf-8")

        response = self._call(
            track_id="ytm:track:dQw4w9WgXcQ", videoId="dQw4w9WgXcQ", isrc="US1234567890"
        )

        assert response.body.decode("utf-8") == "[00:01.00]y"

    def test_a_missing_lyric_still_returns_404(self, temp_cache, monkeypatch):
        from fastapi import HTTPException

        from app.lyrics import manager as manager_module

        monkeypatch.setattr(manager_module, "fetch", lambda _t: None)

        with pytest.raises(HTTPException) as info:
            self._call(track_id="fresh:1")

        assert info.value.status_code == 404

    def test_the_video_id_is_derived_from_the_track_id_when_absent(
        self, temp_cache, monkeypatch
    ):
        """
        فرانت لازم نیست regex یوتیوب داشته باشد: سرور خودش از `track_id`
        استخراج می‌کند و به Provider می‌فرستد.
        """
        from app.lyrics import manager as manager_module
        from app.lyrics.models import Lyrics as _Lyrics

        seen: list[object] = []

        def capturing(track):
            seen.append(getattr(track, "videoId", None))
            return _Lyrics(plain="x", synced="[00:01.00]x")

        monkeypatch.setattr(manager_module, "fetch", capturing)

        self._call(track_id="ytm:track:dQw4w9WgXcQ")

        assert seen == ["dQw4w9WgXcQ"]

    def test_an_explicit_video_id_wins_over_the_derived_one(self, temp_cache, monkeypatch):
        from app.lyrics import manager as manager_module
        from app.lyrics.models import Lyrics as _Lyrics

        seen: list[object] = []
        monkeypatch.setattr(
            manager_module,
            "fetch",
            lambda t: (seen.append(t.videoId), _Lyrics(plain="x", synced="[00:01.00]x"))[1],
        )

        self._call(track_id="ytm:track:dQw4w9WgXcQ", videoId="AAAAAAAAAAA")

        assert seen == ["AAAAAAAAAAA"]

    def test_a_non_youtube_track_has_no_video_id(self, temp_cache, monkeypatch):
        from app.lyrics import manager as manager_module
        from app.lyrics.models import Lyrics as _Lyrics

        seen: list[object] = []
        monkeypatch.setattr(
            manager_module,
            "fetch",
            lambda t: (seen.append(t.videoId), _Lyrics(plain="x", synced="[00:01.00]x"))[1],
        )

        self._call(track_id="spotify:track:4uLU6hMCjMI75M1A2tKUQC")

        assert seen == [None]
