"""
P1 — انتخاب‌پذیریِ منابع، مستقل از زنجیرهٔ خودکار.

قاعدهٔ موردنظر:
  - انتخابِ دستی به `default_enabled` یا عضویت در زنجیرهٔ خودکار وابسته
    **نیست**.
  - `env` فقط kill-switch است: Providerی را از فهرست بیرون می‌برد.
  - Providerی که خودش کلید می‌خواهد (`needs_setup`) یا ممنوع است (`blocked`)
    قابلِ انتخاب نیست، ولی **در فهرست با علت** می‌آید.
  - انتخابِ دستی هرگز Provider را به زنجیرهٔ خودکار اضافه نمی‌کند.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.lyrics.manager import LyricsManager
from app.lyrics.models import Lyrics
from app.lyrics.registry import ProviderEntry, ProviderRegistry
from app.lyrics.sources import (
    STATUS_AVAILABLE,
    STATUS_BLOCKED,
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


def _entry(name, *, enabled=None, default_enabled=True, label=None) -> ProviderEntry:
    return ProviderEntry(
        name,
        lambda *a, **k: Lyrics(plain="x", synced="[00:01.00]x"),
        enabled,
        lambda *a, **k: Lyrics(plain="x", synced="[00:01.00]x"),
        default_enabled=default_enabled,
        label=label,
    )


def _sources(entries, order=None) -> LyricsSources:
    return LyricsSources(
        manager=LyricsManager(
            registry=ProviderRegistry(list(entries), order or tuple(e.name for e in entries))
        )
    )


class TestSelectionIsIndependentOfTheAutoChain:
    def test_a_dark_by_default_provider_is_still_selectable(self):
        """
        قلبِ اصلاح: Providerی که فقط پیش‌فرض خاموش است باید قابلِ انتخاب باشد.
        قبلاً `is_selectable` روی `default_enabled` هم گیت می‌گذاشت و همهٔ
        منابعِ تازه از UI غایب می‌شدند.
        """
        sources = _sources([_entry("dark", default_enabled=False)])

        row = sources.list_sources(_track())[0]

        assert row["selectable"] is True
        assert row["in_auto_chain"] is False
        assert row["status"] == STATUS_AVAILABLE

    def test_the_auto_chain_is_not_widened_by_selectability(self):
        sources = _sources(
            [_entry("auto"), _entry("dark", default_enabled=False)],
            order=("auto", "dark"),
        )

        assert [e.name for e in sources._manager.registry.available()] == ["auto"]

    def test_the_env_kill_switch_removes_it_from_the_list_and_selection(self):
        """`env` خاموش = حذف. نه «پیش‌فرض خاموش»، بلکه خاموشِ صریح."""
        import os

        os.environ["MUSICBAZI_LYRICS_PROVIDER_HIDDEN_ENABLED"] = "0"
        try:
            sources = _sources([_entry("hidden", default_enabled=True)])
            row = sources.list_sources(_track())[0]
            assert row["selectable"] is False
        finally:
            os.environ.pop("MUSICBAZI_LYRICS_PROVIDER_HIDDEN_ENABLED", None)

    def test_a_provider_needing_a_key_is_not_selectable_with_reason(self):
        sources = _sources([_entry("needy", enabled=lambda: False)])

        row = sources.list_sources(_track())[0]

        assert row["selectable"] is False
        assert row["status"] == STATUS_NEEDS_SETUP
        assert row["unavailable_reason"]

    def test_a_blocked_provider_is_listed_but_not_selectable(self):
        sources = _sources([_entry("banned", enabled=lambda: False)])

        row = sources.list_sources(_track())[0]

        assert row["selectable"] is False
        assert row["status"] in (STATUS_NEEDS_SETUP, STATUS_BLOCKED)

    def test_manual_selection_never_adds_to_the_auto_chain(self):
        import asyncio

        sources = _sources(
            [_entry("auto"), _entry("dark", default_enabled=False)], order=("auto", "dark")
        )

        asyncio.run(sources.fetch_from("dark", _track()))

        assert [e.name for e in sources._manager.registry.available()] == ["auto"]


class TestRealRegistrySelectability:
    """روی رجیستریِ واقعی — همان چیزی که UI می‌بیند."""

    def test_dark_providers_are_selectable(self, monkeypatch):
        for name in ("lyricsplus", "unison", "betterlyrics", "binilyrics", "lrc_red", "paxsenix"):
            monkeypatch.delenv(f"MUSICBAZI_LYRICS_PROVIDER_{name.upper()}_ENABLED", raising=False)
        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDERS_ORDER", raising=False)

        manager = LyricsManager()

        for name in ("lyricsplus", "unison", "betterlyrics", "binilyrics", "lrc_red", "paxsenix"):
            assert manager.registry.is_selectable(name) is True, name

    def test_musixmatch_without_a_key_is_not_selectable(self, monkeypatch):
        monkeypatch.setattr("app.providers.musixmatch.MUSIXMATCH_API_KEY", None)

        assert LyricsManager().registry.is_selectable("musixmatch") is False

    def test_genius_without_a_token_is_not_selectable(self, monkeypatch):
        monkeypatch.setattr("app.providers.genius.GENIUS_ACCESS_TOKEN", None)

        assert LyricsManager().registry.is_selectable("genius") is False

    def test_genius_with_a_token_is_selectable_but_not_automatic(self, monkeypatch):
        monkeypatch.setattr("app.providers.genius.GENIUS_ACCESS_TOKEN", "t")
        monkeypatch.delenv("MUSICBAZI_LYRICS_GENIUS_POLICY", raising=False)

        manager = LyricsManager()

        assert manager.registry.is_selectable("genius") is True
        assert "genius" not in [e.name for e in manager.registry.available()]

    def test_the_auto_chain_stays_just_lrclib(self, monkeypatch):
        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDERS_ORDER", raising=False)

        assert [e.name for e in LyricsManager().registry.available()] == ["lrclib"]


class TestSourcesEndpointReportsBlockedAndNeedsSetup:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch, fresh_db):
        from app import main

        return TestClient(main.app)

    def _params(self) -> dict:
        return {
            "track_id": "spotify:track:1",
            "title": "Song",
            "artist": "Artist",
            "duration_ms": 180000,
        }

    def test_prohibited_sources_appear_with_a_reason(self, client):
        """KuGou و Megalobiz کد ندارند ولی باید در فهرست با علت بیایند."""
        body = client.get("/api/lyrics/sources", params=self._params()).json()
        ids = {s["id"] for s in body["sources"]}

        assert "kugou" in ids
        assert "megalobiz" in ids
        for row in body["sources"]:
            if row["id"] in ("kugou", "megalobiz"):
                assert row["selectable"] is False
                assert row["status"] == STATUS_BLOCKED
                assert row["unavailable_reason"]

    def test_dark_providers_appear_selectable(self, client):
        body = client.get("/api/lyrics/sources", params=self._params()).json()
        row = next(s for s in body["sources"] if s["id"] == "lyricsplus")

        assert row["selectable"] is True

    def test_the_endpoint_still_makes_no_provider_request(self, client, monkeypatch):
        from app.lyrics import sources as sources_module

        def explode(*_a, **_k):
            raise AssertionError("must not call a provider")

        monkeypatch.setattr(sources_module.LyricsSources, "_run", explode)

        assert client.get("/api/lyrics/sources", params=self._params()).status_code == 200


class TestStatusLabelsComeFromBackend:
    """برچسب‌ها باید از بک‌اند بیایند، نه در فرانت سخت‌کد شوند."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch, fresh_db):
        from app import main

        return TestClient(main.app)

    def _rows(self, client) -> dict:
        body = client.get(
            "/api/lyrics/sources",
            params={
                "track_id": "spotify:track:1",
                "title": "Song",
                "artist": "Artist",
                "duration_ms": 180000,
            },
        ).json()
        return {r["id"]: r for r in body["sources"]}

    def test_each_row_carries_terms_and_experimental_flags(self, client):
        rows = self._rows(client)

        for row in rows.values():
            assert "terms_note" in row
            assert "experimental" in row

    def test_paxsenix_and_lrc_red_are_experimental(self, client):
        rows = self._rows(client)

        assert rows["paxsenix"]["experimental"] is True
        assert rows["lrc_red"]["experimental"] is True
        assert rows["betterlyrics"]["experimental"] is True

    def test_genius_carries_a_terms_warning(self, client):
        rows = self._rows(client)

        assert rows["genius"]["terms_note"]

    def test_a_stable_source_is_not_marked_experimental(self, client):
        rows = self._rows(client)

        assert rows["lrclib"]["experimental"] is False
