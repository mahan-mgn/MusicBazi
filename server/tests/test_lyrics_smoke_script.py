"""
اسکریپت smoke test — اثباتِ اینکه بدونِ `--live` هیچ مسیرِ شبکه‌ای اجرا نمی‌شود.

اسکریپت **اجرا نمی‌شود** (بندِ B.4/D.7). فقط رفتارش با mock سنجیده می‌شود:
`httpx.Client` و `socket` طوری جایگزین می‌شوند که هر تماسِ شبکه‌ای یک
`AssertionError` بدهد. پس اگر مسیری به شبکه برود، تست می‌شکند.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "lyrics_smoke.py"


@pytest.fixture(scope="module")
def smoke():
    """اسکریپت را import می‌کند بدونِ اجرای `main`."""
    spec = importlib.util.spec_from_file_location("lyrics_smoke_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def boom(monkeypatch):
    """
    هر مسیرِ شبکه‌ای را می‌بندد.

    `httpx.Client` (که همهٔ Providerها استفاده می‌کنند) و `socket.socket`
    (که زیرِ httpx است) هر دو منفجر می‌شوند.
    """
    import httpx

    def explode(*_args, **_kwargs):
        raise AssertionError("NETWORK ATTEMPTED")

    monkeypatch.setattr(httpx, "Client", explode)
    monkeypatch.setattr(httpx, "get", explode)
    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)


@pytest.fixture
def tracks_file(tmp_path):
    path = tmp_path / "smoke-tracks.json"
    path.write_text(
        json.dumps(
            {
                "tracks": [
                    {"title": "Sample", "artist": "Someone", "album": "Album", "duration_ms": 185000},
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


class TestDryRunTouchesNoNetwork:
    def test_the_default_run_makes_no_network_call(self, smoke, tracks_file, boom, capsys):
        exit_code = smoke.main(["--tracks", str(tracks_file)])

        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["mode"] == "dry-run"

    def test_the_default_run_is_dry_even_with_live_absent(self, smoke, tracks_file, boom, capsys):
        smoke.main(["--tracks", str(tracks_file)])

        assert json.loads(capsys.readouterr().out)["note"].startswith("هیچ")

    def test_a_missing_file_exits_without_network(self, smoke, tmp_path, boom):
        assert smoke.main(["--tracks", str(tmp_path / "nope.json")]) == 2

    def test_the_dry_run_lists_providers_without_calling_them(self, smoke, tracks_file, boom, capsys):
        smoke.main(["--tracks", str(tracks_file)])

        payload = json.loads(capsys.readouterr().out)
        # فهرست از Registry می‌آید، ولی هیچ Providerی صدا زده نمی‌شود
        assert isinstance(payload["providers"], list)

    def test_an_explicit_provider_list_still_makes_no_call(self, smoke, tracks_file, boom, capsys):
        smoke.main(["--tracks", str(tracks_file), "--providers", "unison,lyricsplus"])

        payload = json.loads(capsys.readouterr().out)
        assert payload["providers"] == ["unison", "lyricsplus"]


class TestTheShippedSampleFile:
    """
    فایلِ نمونه‌ی واقعیِ ریپو (`smoke-tracks.json`) باید **فقط متادیتا** باشد.

    اگر روزی کسی متنِ آهنگ را در آن بگذارد، یک فایلِ کپی‌رایت‌دار وارد ریپو
    می‌شود — دقیقاً چیزی که این اسکریپت باید از آن پرهیز کند.
    """

    _SAMPLE = Path(__file__).resolve().parent.parent.parent / "smoke-tracks.json"

    _TEXT_KEYS = {"lyrics", "plain", "synced", "text", "lines", "words"}

    def test_the_file_exists(self):
        assert self._SAMPLE.exists(), f"فایلِ نمونه پیدا نشد: {self._SAMPLE}"

    def test_it_parses_and_has_tracks(self):
        data = json.loads(self._SAMPLE.read_text(encoding="utf-8"))
        assert isinstance(data.get("tracks"), list) and data["tracks"]

    def test_no_entry_carries_lyric_text(self):
        data = json.loads(self._SAMPLE.read_text(encoding="utf-8"))
        allowed = {"title", "artist", "album", "duration_ms"}

        for entry in data["tracks"]:
            fields = {k for k in entry if not k.startswith("_")}
            assert fields <= allowed, f"فیلدِ غیرمنتظره: {fields - allowed}"
            assert not (fields & self._TEXT_KEYS)

    def test_it_has_a_persian_and_a_version_variant(self):
        """خواسته‌ی D.7: یک نمونهٔ فارسی و یک نسخه‌ی Live/Remix."""
        data = json.loads(self._SAMPLE.read_text(encoding="utf-8"))
        titles = " ".join(e.get("title", "") for e in data["tracks"])
        artists = " ".join(e.get("artist", "") for e in data["tracks"])
        combined = f"{titles} {artists}"

        assert any(marker in titles for marker in ("Live", "Remix", "live", "remix"))
        # نمونه‌ی فارسی: نامِ هنرمندِ لاتین ولی متنِ درخواستی فارسی است — همان
        # چیزی که رومانیزه‌ی نامطمئن را می‌سنجد
        assert "Tlkhoon" in combined or "Farhad" in combined


class TestTheLivePathIsTheOnlyNetworkPath:
    def test_live_actually_reaches_the_probe(self, smoke, tracks_file, monkeypatch, capsys):
        """
        عکسِ تستِ بالا: با `--live` باید *تلاشِ* شبکه بشود. اگر این هم سبز
        شود بدونِ هیچ تماسی، یعنی محافظِ `boom` بی‌اثر است و تستِ بالا
        بی‌ارزش می‌شود.
        """
        reached: list[str] = []

        def fake_probe(name, track):
            reached.append(name)
            return {"provider": name, "status": "ok"}

        monkeypatch.setattr(smoke, "_probe", fake_probe)
        monkeypatch.setattr(smoke.time, "sleep", lambda *_: None)

        smoke.main(["--tracks", str(tracks_file), "--live", "--providers", "lrclib"])

        assert reached == ["lrclib"]

    def test_without_live_the_probe_is_never_reached(self, smoke, tracks_file, monkeypatch, boom):
        reached: list[str] = []

        def fake_probe(name, track):
            reached.append(name)
            return {"provider": name, "status": "ok"}

        monkeypatch.setattr(smoke, "_probe", fake_probe)

        smoke.main(["--tracks", str(tracks_file)])

        assert reached == []
