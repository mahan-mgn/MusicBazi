"""
F2 — قراردادِ واقعیِ `GET /api/lyrics/sources`.

چرا این فایل جداگانه است: تست‌های DOM مرحلهٔ قبل ماژولِ کلاینت را mock
می‌کردند، پس هیچ‌وقت نپرسیدند «آیا پاسخِ واقعیِ بک‌اند همان چیزی است که فرانت
انتظار دارد؟». این فایل همان شکاف را می‌بندد.

روش: پاسخِ واقعی از `TestClient` گرفته می‌شود و به‌صورت fixture ذخیره می‌شود؛
سپس تست‌های فرانت (vitest) همان fixture را از مسیرِ واقعیِ کلاینت و کامپوننت
عبور می‌دهند. این فایل، fixture را تولید و تازگی‌اش را تضمین می‌کند.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# fixture در کنارِ تست‌های فرانت می‌نشیند تا vitest بی‌واسطه بخواندش
_FIXTURE = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "lib"
    / "__fixtures__"
    / "lyrics_sources.json"
)

# همان پارامترهایی که `src/lib/lyricsSources.ts:_trackParams` می‌سازد
_TRACK_PARAMS = {
    "track_id": "spotify:track:4uLU6hMCjMI75M1A2tKUQC",
    "title": "Blinding Lights",
    "artist": "The Weeknd",
    "album": "After Hours",
    "duration_ms": 200040,
}


@pytest.fixture
def client(tmp_path, monkeypatch, fresh_db):
    from app import main

    return TestClient(main.app)


class TestSourcesResponseShape:
    """شکلِ پاسخ — همان چیزی که کلاینتِ فرانت به آن تکیه می‌کند."""

    def test_it_answers_200_json(self, client):
        response = client.get("/api/lyrics/sources", params=_TRACK_PARAMS)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

    def test_the_top_level_keys_are_what_the_client_reads(self, client):
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()

        # `lyricsSources.ts` دقیقاً این سه را می‌خواند
        assert set(body) >= {"trackId", "preferred", "sources"}
        assert body["trackId"] == _TRACK_PARAMS["track_id"]
        assert body["preferred"] is None

    def test_every_source_row_has_the_keys_the_client_types(self, client):
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()

        # همان فیلدهای `LyricsSource` در `src/lib/lyricsSources.ts`
        required = {
            "id",
            "label",
            "capabilities",
            "in_auto_chain",
            "selectable",
            "status",
            "experimental",
        }
        for row in body["sources"]:
            missing = required - set(row)
            assert not missing, f"{row.get('id')} missing {missing}"

    def test_the_names_are_snake_case_as_the_client_expects(self, client):
        """اگر بک‌اند camelCase بدهد، `selectable` و `in_auto_chain` می‌شکنند."""
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()
        row = body["sources"][0]

        assert "selectable" in row
        assert "in_auto_chain" in row
        assert "unavailable_reason" in row
        # camelCase نباید باشد
        assert "inAutoChain" not in row

    def test_capabilities_is_a_list_of_strings(self, client):
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()

        for row in body["sources"]:
            assert isinstance(row["capabilities"], list)
            assert all(isinstance(c, str) for c in row["capabilities"])

    def test_selectable_and_experimental_are_booleans(self, client):
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()

        for row in body["sources"]:
            assert isinstance(row["selectable"], bool)
            assert isinstance(row["experimental"], bool)
            assert isinstance(row["in_auto_chain"], bool)

    def test_the_status_values_are_ones_the_menu_maps(self, client):
        """`STATUS_KEY` در `LyricsSourceMenu.tsx` این مقادیر را می‌شناسد."""
        known = {
            "available",
            "cached",
            "empty",
            "error",
            "needs_setup",
            "disabled",
            "blocked",
        }
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()

        for row in body["sources"]:
            assert row["status"] in known, f"unmapped status: {row['status']}"

    def test_twelve_sources_with_eight_selectable(self, client):
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()

        assert len(body["sources"]) == 12
        assert sum(1 for r in body["sources"] if r["selectable"]) == 8

    def test_the_prohibited_sources_come_with_a_reason(self, client):
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()
        blocked = [r for r in body["sources"] if r["status"] == "blocked"]

        assert {r["id"] for r in blocked} == {"kugou", "megalobiz"}
        for row in blocked:
            assert row["unavailable_reason"]

    def test_no_row_leaks_a_secret_value(self, client):
        """
        نامِ *متغیرِ* محیطی در `setup_hint` عمدی و بی‌خطر است (راهنمای
        راه‌اندازی است، نه مقدار). چیزی که نباید بیاید، **مقدارِ** کلید است.
        """
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()

        import os

        for name, value in os.environ.items():
            if not value or len(value) < 12:
                continue
            if not any(m in name.upper() for m in ("TOKEN", "KEY", "SECRET", "PASSWORD")):
                continue
            assert value not in json.dumps(body), f"env {name} leaked into the response"

        # هیچ فیلدِ پاسخی نباید مقدارِ کلید داشته باشد
        for row in body["sources"]:
            assert "apikey" not in json.dumps(row).lower()


class TestFixtureIsGeneratedFromTheRealResponse:
    """
    fixture را از پاسخِ واقعی می‌سازد تا تستِ فرانت با قراردادِ دیروز تست نشود.

    این تست اگر fixture با بک‌اند نخواند، **قرمز** می‌شود — یعنی fixtureِ
    کهنه نمی‌تواند بی‌صدا بماند.
    """

    def test_the_fixture_matches_the_current_response(self, client):
        _FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        _FIXTURE.write_text(
            json.dumps(
                client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        written = json.loads(_FIXTURE.read_text(encoding="utf-8"))

        assert written["trackId"] == _TRACK_PARAMS["track_id"]
        assert len(written["sources"]) == 12
        assert written["sources"][0]["id"] == "lrclib"

    def test_the_fixture_contains_no_lyric_text(self, client):
        """fixture فقط متادیتای منبع است — هیچ متنِ آهنگی در آن نیست."""
        body = client.get("/api/lyrics/sources", params=_TRACK_PARAMS).json()
        text = json.dumps(body, ensure_ascii=False)

        # فیلدهای *متنِ آهنگ* نباید باشند. توجه: `"plain"` یک مقدارِ مجازِ
        # capability است، پس فقط به‌عنوان کلید بررسی می‌شود.
        for key in ("synced", "lines", "words", "plainLyrics", "syncedLyrics"):
            assert f'"{key}":' not in text, f"lyric field present: {key}"
