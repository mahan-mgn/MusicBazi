"""
S3 — APIِ منابع و ترجیحِ هر آهنگ.

با `TestClient` و دیتابیس/کشِ موقت. هیچ Providerی واقعاً صدا زده نمی‌شود.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.lyrics.models import Lyrics


@pytest.fixture
def client(tmp_path, monkeypatch, fresh_db):
    """کلاینت با دیتابیسِ موقت — کشِ کاربر لمس نمی‌شود."""
    from app import main

    return TestClient(main.app)


def _params(**extra) -> dict:
    base = {
        "track_id": "spotify:track:1",
        "title": "Song",
        "artist": "Artist",
        "duration_ms": 180000,
    }
    base.update(extra)
    return base


class TestSourcesEndpoint:
    def test_it_returns_the_source_list(self, client):
        response = client.get("/api/lyrics/sources", params=_params())

        assert response.status_code == 200
        body = response.json()
        assert body["trackId"] == "spotify:track:1"
        assert isinstance(body["sources"], list) and body["sources"]
        assert "preferred" in body

    def test_it_makes_no_provider_request(self, client, monkeypatch):
        """
        باز کردنِ منو نباید به هیچ Providerی درخواست بزند. اگر بزند، این
        تست با AssertionError می‌شکند.
        """
        from app.lyrics import sources as sources_module

        def explode(*_a, **_k):
            raise AssertionError("list_sources must not call a provider")

        monkeypatch.setattr(sources_module.LyricsSources, "_run", explode)

        assert client.get("/api/lyrics/sources", params=_params()).status_code == 200

    def test_each_source_carries_status_and_capabilities(self, client):
        body = client.get("/api/lyrics/sources", params=_params()).json()

        row = next(s for s in body["sources"] if s["id"] == "lrclib")
        assert row["status"] in ("available", "cached", "empty", "error")
        assert "line" in row["capabilities"]

    def test_the_response_never_contains_a_token(self, client):
        text = client.get("/api/lyrics/sources", params=_params()).text

        assert "token" not in text.lower().replace("token in the server", "")
        assert "apikey" not in text.lower()


class TestPreferenceEndpoints:
    def test_the_default_is_automatic(self, client):
        body = client.get("/api/lyrics/preference", params={"track_id": "t1"}).json()

        assert body["provider"] is None

    def test_a_preference_can_be_saved_and_read(self, client):
        client.put("/api/lyrics/preference", params={"track_id": "t1", "provider": "lrclib"})

        body = client.get("/api/lyrics/preference", params={"track_id": "t1"}).json()
        assert body["provider"] == "lrclib"

    def test_an_empty_provider_clears_the_preference(self, client):
        client.put("/api/lyrics/preference", params={"track_id": "t1", "provider": "lrclib"})
        client.put("/api/lyrics/preference", params={"track_id": "t1", "provider": ""})

        assert (
            client.get("/api/lyrics/preference", params={"track_id": "t1"}).json()["provider"]
            is None
        )

    def test_delete_clears_the_preference(self, client):
        client.put("/api/lyrics/preference", params={"track_id": "t1", "provider": "lrclib"})
        response = client.delete("/api/lyrics/preference", params={"track_id": "t1"})

        assert response.status_code == 200
        assert (
            client.get("/api/lyrics/preference", params={"track_id": "t1"}).json()["provider"]
            is None
        )

    def test_an_unknown_provider_is_rejected(self, client):
        response = client.put(
            "/api/lyrics/preference", params={"track_id": "t1", "provider": "nope"}
        )

        assert response.status_code == 400

    def test_preferences_are_per_track(self, client):
        client.put("/api/lyrics/preference", params={"track_id": "t1", "provider": "lrclib"})

        assert (
            client.get("/api/lyrics/preference", params={"track_id": "t2"}).json()["provider"]
            is None
        )

    def test_the_preference_is_reported_in_the_sources_list(self, client):
        client.put("/api/lyrics/preference", params={"track_id": "spotify:track:1", "provider": "lrclib"})

        body = client.get("/api/lyrics/sources", params=_params()).json()

        assert body["preferred"] == "lrclib"


class TestStreamLyricsWithProvider:
    def test_without_a_provider_the_old_contract_holds(self, client, monkeypatch):
        """بدونِ `provider` هیچ چیز عوض نمی‌شود — همان ۴۰۴/۲۰۰ قبلی."""
        from app import stream_cache

        monkeypatch.setattr(stream_cache, "get_or_fetch_lyrics", _async(lambda _t, _uid="local": "[00:01.00]x"))

        response = client.get("/api/stream/lyrics", params=_params())

        assert response.status_code == 200
        assert response.text == "[00:01.00]x"
        assert "x-lyrics-source" not in response.headers

    def test_a_named_provider_is_used(self, client, monkeypatch):
        from app.lyrics import sources as sources_module

        async def fake_fetch(name, track, uid="local", *, force=False):
            return sources_module.SourceResult(
                provider=name, lyrics=Lyrics(plain="t", synced="[00:02.00]named")
            )

        monkeypatch.setattr(sources_module.lyrics_sources, "fetch_from", fake_fetch)

        response = client.get("/api/stream/lyrics", params=_params(provider="lrclib"))

        assert response.status_code == 200
        assert response.text == "[00:02.00]named"
        assert response.headers["x-lyrics-source"] == "lrclib"

    def test_an_unknown_provider_is_a_4xx(self, client):
        response = client.get("/api/stream/lyrics", params=_params(provider="nope"))

        assert 400 <= response.status_code < 500

    def test_a_needs_setup_provider_is_409(self, client, monkeypatch):
        from app.lyrics import sources as sources_module

        async def fake_fetch(name, track, uid="local", *, force=False):
            return sources_module.SourceResult(provider=name, lyrics=None, error="needs-setup")

        monkeypatch.setattr(sources_module.lyrics_sources, "fetch_from", fake_fetch)

        response = client.get("/api/stream/lyrics", params=_params(provider="musixmatch"))

        assert response.status_code == 409

    def test_a_provider_error_is_502_without_details(self, client, monkeypatch):
        from app.lyrics import sources as sources_module

        async def fake_fetch(name, track, uid="local", *, force=False):
            return sources_module.SourceResult(provider=name, lyrics=None, error="network")

        monkeypatch.setattr(sources_module.lyrics_sources, "fetch_from", fake_fetch)

        response = client.get("/api/stream/lyrics", params=_params(provider="lrclib"))

        assert response.status_code == 502
        assert "network" not in response.text.lower()

    def test_an_empty_source_result_is_404(self, client, monkeypatch):
        from app.lyrics import sources as sources_module

        async def fake_fetch(name, track, uid="local", *, force=False):
            return sources_module.SourceResult(provider=name, lyrics=None)

        monkeypatch.setattr(sources_module.lyrics_sources, "fetch_from", fake_fetch)

        response = client.get("/api/stream/lyrics", params=_params(provider="lrclib"))

        assert response.status_code == 404

    def test_a_word_timed_result_is_rendered_as_lrc(self, client, monkeypatch):
        from app.lyrics import sources as sources_module
        from app.lyrics.models import LyricLine, LyricWord

        async def fake_fetch(name, track, uid="local", *, force=False):
            return sources_module.SourceResult(
                provider=name,
                lyrics=Lyrics(
                    lines=(
                        LyricLine(
                            start_ms=1000,
                            text="a b",
                            words=(LyricWord(start_ms=1000, text="a "), LyricWord(start_ms=1500, text="b")),
                        ),
                    ),
                    sync_type="word",
                ),
            )

        monkeypatch.setattr(sources_module.lyrics_sources, "fetch_from", fake_fetch)
        monkeypatch.delenv("MUSICBAZI_LYRICS_ENHANCED_LRC", raising=False)

        response = client.get("/api/stream/lyrics", params=_params(provider="lyricsplus"))

        assert response.status_code == 200
        assert response.text.startswith("[00:01.00]")
        assert "<" not in response.text  # پیش‌فرض: خطی


def _async(fn):
    async def wrapper(*a, **k):
        return fn(*a, **k)

    return wrapper
