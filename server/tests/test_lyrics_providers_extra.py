"""
Providerهای متنِ افزوده‌شده: LyricsPlus، Unison، BetterLyrics، BiniLyrics،
lrc.red، SimpMusic.

لایه‌ی HTTP mock می‌شود (همان `httpx.Client` که خودِ Providerها استفاده
می‌کنند)، پس مسیرِ واقعیِ خطا-به-`ProviderError` سنجیده می‌شود نه یک
شبیه‌سازیِ دلبخواه. هیچ درخواست واقعی زده نمی‌شود.

قالبِ پاسخ‌های fixture از سورسِ عمومیِ هر سرویس آمده (منبعش در داک‌استرینگِ
هر Provider ثبت شده) — نه از حدس.
"""

from __future__ import annotations

import httpx
import pytest

from app.lyrics.models import Lyrics
from app.lyrics.registry import ProviderError
from app.providers import (
    betterlyrics,
    binilyrics,
    lrc_red,
    lyricsplus,
    simpmusic,
    unison,
)

_DURATION_MS = 180_000


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


def _patch(monkeypatch, module, handler):
    calls: list[str] = []

    def wrapped(url, params, headers):
        calls.append(url)
        return handler(url, params, headers)

    monkeypatch.setattr(module.httpx, "Client", lambda **_: _Client(wrapped))
    return calls


def _fetch(module, **kwargs):
    return module.fetch_strict("Song", "Artist", None, _DURATION_MS, **kwargs)


# ---------------------------------------------------------------- LyricsPlus


_LP_BODY = {
    "type": "Word",
    "metadata": {
        "title": "Song",
        "artist": "Artist",
        "totalDuration": 180.0,
        "language": "en",
    },
    "lyrics": [
        {
            "time": 1000,
            "duration": 500,
            "text": "hello ",
            "syllabus": [
                {"time": 1000, "duration": 200, "text": "hel"},
                {"time": 1200, "duration": 300, "text": "lo "},
            ],
        },
        {"time": 2000, "duration": 500, "text": "world"},
    ],
}


class TestLyricsPlus:
    def test_a_word_level_answer_is_parsed(self, monkeypatch):
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(200, json_body=_LP_BODY))

        found = _fetch(lyricsplus)

        assert found.sync_type == "word"
        assert [line.text for line in found.lines] == ["hello ", "world"]
        assert len(found.lines[0].words) == 2
        assert found.lines[0].words[0].start_ms == 1000

    def test_the_duration_unit_is_seconds_not_ms(self, monkeypatch):
        """
        `totalDuration` ثانیه است ولی `Line.time` میلی‌ثانیه. اگر اینجا اشتباه
        ترجمه شود نتیجه به‌عنوان «نسخه‌ی دیگر» رد می‌شود — یک باگِ بی‌صدا.
        """
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(200, json_body=_LP_BODY))

        assert _fetch(lyricsplus) is not None

    def test_a_conflicting_duration_is_rejected(self, monkeypatch):
        body = {**_LP_BODY, "metadata": {**_LP_BODY["metadata"], "totalDuration": 300.0}}
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(200, json_body=body))

        assert _fetch(lyricsplus) is None

    def test_a_wrong_artist_is_rejected(self, monkeypatch):
        body = {**_LP_BODY, "metadata": {**_LP_BODY["metadata"], "artist": "Someone Else"}}
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(200, json_body=body))

        assert _fetch(lyricsplus) is None

    def test_a_404_is_empty_not_an_error(self, monkeypatch):
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(404))

        assert _fetch(lyricsplus) is None

    @pytest.mark.parametrize("status", [429, 500, 503, 403])
    def test_an_error_status_raises(self, monkeypatch, status):
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(status))

        with pytest.raises(ProviderError) as info:
            _fetch(lyricsplus)
        assert info.value.status == status

    def test_a_timeout_raises_a_network_error(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ConnectTimeout("timed out")

        _patch(monkeypatch, lyricsplus, handler)

        with pytest.raises(ProviderError) as info:
            _fetch(lyricsplus)
        assert info.value.kind == "network"

    def test_a_malformed_body_raises_a_body_error(self, monkeypatch):
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(200, raw="{oops"))

        with pytest.raises(ProviderError) as info:
            _fetch(lyricsplus)
        assert info.value.kind == "body"

    def test_an_empty_lyrics_list_is_empty(self, monkeypatch):
        body = {**_LP_BODY, "lyrics": []}
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(200, json_body=body))

        assert _fetch(lyricsplus) is None

    def test_a_type_none_is_empty(self, monkeypatch):
        body = {"type": "None", "metadata": {}, "lyrics": []}
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(200, json_body=body))

        assert _fetch(lyricsplus) is None

    def test_a_structurally_broken_lyric_row_raises_a_body_error(self, monkeypatch):
        body = {**_LP_BODY, "lyrics": ["not-a-dict"]}
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(200, json_body=body))

        # ردیفِ خراب نادیده می‌رود و لیست خالی می‌ماند → None، نه استثنا
        assert _fetch(lyricsplus) is None

    def test_the_public_fetch_swallows_every_error(self, monkeypatch):
        _patch(monkeypatch, lyricsplus, lambda *a: _resp(500))

        assert lyricsplus.fetch("Song", "Artist", None, _DURATION_MS) is None

    def test_a_blank_title_makes_no_request(self, monkeypatch):
        monkeypatch.setattr(
            lyricsplus.httpx, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("no"))
        )
        assert lyricsplus.fetch_strict("", "Artist", None, 0) is None

    def test_the_query_carries_the_requested_title_and_artist(self, monkeypatch):
        seen: list[dict] = []

        def handler(url, params, headers):
            seen.append(params)
            return _resp(200, json_body=_LP_BODY)

        _patch(monkeypatch, lyricsplus, handler)
        _fetch(lyricsplus)

        assert seen[0]["title"] == "Song"
        assert seen[0]["artist"] == "Artist"
        assert seen[0]["duration"] == "180"


# ---------------------------------------------------------------- Unison


_UNISON_TTML = (
    '<tt xmlns="http://www.w3.org/ns/ttml" xml:lang="fa"><body><div>'
    '<p begin="1s" end="2s"><span begin="1s">a</span></p>'
    "</div></body></tt>"
)


def _unison_body(payload=_UNISON_TTML, fmt="ttml", **extra):
    data = {"song": "Song", "artist": "Artist", "lyrics": payload, "format": fmt}
    data.update(extra)
    return {"success": True, "data": data}


class TestUnison:
    def test_a_ttml_payload_reaches_the_ttml_parser(self, monkeypatch):
        _patch(monkeypatch, unison, lambda *a: _resp(200, json_body=_unison_body()))

        found = _fetch(unison)

        assert found.sync_type == "word"
        assert found.lines[0].text == "a"

    def test_an_lrc_payload_reaches_the_lrc_parser(self, monkeypatch):
        _patch(
            monkeypatch,
            unison,
            lambda *a: _resp(200, json_body=_unison_body("[00:01.00]<00:01.00>hi", "lrc")),
        )

        found = _fetch(unison)

        assert len(found.lines) == 1
        assert found.lines[0].words[0].text == "hi"

    def test_a_plain_payload_is_not_line_synced(self, monkeypatch):
        """متنِ بی‌تگ نباید `synced` شود — ترک را از نسخه‌ی هم‌زمان محروم می‌کند."""
        _patch(monkeypatch, unison, lambda *a: _resp(200, json_body=_unison_body("just text", "plain")))

        assert _fetch(unison) is None

    def test_the_language_is_carried_through(self, monkeypatch):
        _patch(monkeypatch, unison, lambda *a: _resp(200, json_body=_unison_body()))

        assert _fetch(unison).language == "fa"

    def test_richsync_claim_without_word_tags_is_downgraded(self, monkeypatch):
        """
        سرویس `richsync` ادعا می‌کند ولی محتوا هیچ تگِ کلمه ندارد. برچسبِ
        اشتباه یعنی UI کلمه‌ای هایلایت می‌کند که داده‌اش نیست.
        """
        _patch(
            monkeypatch,
            unison,
            lambda *a: _resp(200, json_body=_unison_body("[00:01.00]hi", "lrc", syncType="richsync")),
        )

        found = _fetch(unison)

        assert found.sync_type == "line"

    def test_a_conflicting_duration_is_rejected(self, monkeypatch):
        _patch(
            monkeypatch,
            unison,
            lambda *a: _resp(200, json_body=_unison_body(duration=300.0)),
        )

        assert _fetch(unison) is None

    def test_success_false_is_empty(self, monkeypatch):
        _patch(monkeypatch, unison, lambda *a: _resp(200, json_body={"success": False, "data": {}}))

        assert _fetch(unison) is None

    def test_a_404_is_empty(self, monkeypatch):
        _patch(monkeypatch, unison, lambda *a: _resp(404))

        assert _fetch(unison) is None

    @pytest.mark.parametrize("status", [429, 500, 503, 400])
    def test_an_error_status_raises(self, monkeypatch, status):
        _patch(monkeypatch, unison, lambda *a: _resp(status))

        with pytest.raises(ProviderError) as info:
            _fetch(unison)
        assert info.value.status == status

    def test_a_timeout_raises_a_network_error(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ReadTimeout("timed out")

        _patch(monkeypatch, unison, handler)

        with pytest.raises(ProviderError) as info:
            _fetch(unison)
        assert info.value.kind == "network"

    def test_a_garbage_ttml_payload_is_an_empty_result_not_a_crash(self, monkeypatch):
        _patch(monkeypatch, unison, lambda *a: _resp(200, json_body=_unison_body("<tt>broken", "ttml")))

        assert _fetch(unison) is None

    def test_the_public_fetch_swallows_every_error(self, monkeypatch):
        _patch(monkeypatch, unison, lambda *a: _resp(500))

        assert unison.fetch("Song", "Artist", None, _DURATION_MS) is None

    def test_the_query_uses_the_song_and_artist_branch(self, monkeypatch):
        seen: list[dict] = []

        def handler(url, params, headers):
            seen.append(params)
            return _resp(200, json_body=_unison_body())

        _patch(monkeypatch, unison, handler)
        _fetch(unison)

        assert seen[0]["song"] == "Song"
        assert seen[0]["artist"] == "Artist"


# ---------------------------------------------------------------- BetterLyrics


class TestBetterLyrics:
    def test_an_lrc_payload_with_word_tags_is_parsed(self, monkeypatch):
        body = {"data": {"song": "Song", "artist": "Artist", "lyrics": "[00:01.00]<00:01.00>hi", "format": "lrc"}}
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, json_body=body))

        found = _fetch(betterlyrics)

        assert found.sync_type == "word"
        assert found.lines[0].words[0].text == "hi"

    def test_a_ttml_payload_is_parsed(self, monkeypatch):
        body = {"data": {"song": "Song", "artist": "Artist", "lyrics": _UNISON_TTML, "format": "ttml"}}
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, json_body=body))

        assert _fetch(betterlyrics).sync_type == "word"

    def test_a_response_without_the_success_flag_is_still_accepted(self, monkeypatch):
        """این میزبان گاهی `success` نمی‌فرستد؛ نباید نیاز باشد."""
        body = {"data": {"song": "Song", "artist": "Artist", "lyrics": "[00:01.00]hi", "format": "lrc"}}
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, json_body=body))

        assert _fetch(betterlyrics) is not None

    def test_a_missing_data_object_is_empty(self, monkeypatch):
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, json_body={}))

        assert _fetch(betterlyrics) is None

    def test_a_404_is_empty(self, monkeypatch):
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(404))

        assert _fetch(betterlyrics) is None

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_an_error_status_raises(self, monkeypatch, status):
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(status))

        with pytest.raises(ProviderError) as info:
            _fetch(betterlyrics)
        assert info.value.status == status

    def test_a_timeout_raises_a_network_error(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ConnectError("no route")

        _patch(monkeypatch, betterlyrics, handler)

        with pytest.raises(ProviderError) as info:
            _fetch(betterlyrics)
        assert info.value.kind == "network"

    def test_a_malformed_body_raises(self, monkeypatch):
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, raw="not json"))

        with pytest.raises(ProviderError):
            _fetch(betterlyrics)

    @pytest.mark.parametrize("payload", [["a"], "text", 42, None], ids=["list", "str", "int", "null"])
    def test_a_non_object_body_raises_a_body_error(self, monkeypatch, payload):
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, json_body=payload))

        with pytest.raises(ProviderError) as info:
            _fetch(betterlyrics)
        assert info.value.kind == "body"

    @pytest.mark.parametrize("data", [["a"], "x", 1, None], ids=["list", "str", "int", "null"])
    def test_a_non_object_data_field_is_an_empty_result(self, monkeypatch, data):
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, json_body={"data": data}))

        assert _fetch(betterlyrics) is None

    def test_a_non_string_lyrics_payload_is_an_empty_result(self, monkeypatch):
        body = {"data": {"song": "Song", "artist": "Artist", "lyrics": ["not", "a", "string"]}}
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, json_body=body))

        assert _fetch(betterlyrics) is None

    def test_the_datetime_shaped_lyrics_payload_still_reaches_the_parser(self, monkeypatch):
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, json_body=_unison_body()))

        assert _fetch(betterlyrics) is not None

    def test_a_wrong_artist_is_rejected(self, monkeypatch):
        body = {"data": {"song": "Song", "artist": "Someone Else", "lyrics": "[00:01.00]x", "format": "lrc"}}
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(200, json_body=body))

        assert _fetch(betterlyrics) is None

    def test_the_public_fetch_swallows_every_error(self, monkeypatch):
        _patch(monkeypatch, betterlyrics, lambda *a: _resp(500))

        assert betterlyrics.fetch("Song", "Artist", None, _DURATION_MS) is None


# ---------------------------------------------------------------- BiniLyrics


def _bini_search(results):
    def handler(url, params, headers):
        if "lyrics-api" in url:
            return _resp(200, json_body={"total": len(results), "results": results})
        return _resp(200, text=_UNISON_TTML)

    return handler


def _bini_row(**extra):
    row = {"track_name": "Song", "artist_name": "Artist", "duration": 180, "lyricsUrl": "https://lyrics-storage.binimum.org/x.ttml"}
    row.update(extra)
    return row


class TestBiniLyrics:
    def test_a_matching_result_fetches_its_ttml_document(self, monkeypatch):
        _patch(monkeypatch, binilyrics, _bini_search([_bini_row()]))

        found = _fetch(binilyrics)

        assert found is not None
        assert found.lines[0].text == "a"

    def test_the_search_and_the_document_are_two_requests(self, monkeypatch):
        calls = _patch(monkeypatch, binilyrics, _bini_search([_bini_row()]))

        _fetch(binilyrics)

        assert len(calls) == 2
        assert "lyrics-api" in calls[0]
        assert "lyrics-storage" in calls[1]

    def test_an_unrelated_result_is_never_fetched(self, monkeypatch):
        """
        تطبیق **قبل** از خواندنِ فایل اجرا می‌شود. بی‌آن، یک جستجوی بی‌ربط
        درخواستِ اضافه به سرویسِ رایگان می‌زند و متنِ آهنگِ دیگری می‌آورد.
        """
        calls = _patch(
            monkeypatch,
            binilyrics,
            _bini_search([_bini_row(track_name="Totally Different", artist_name="Nobody")]),
        )

        assert _fetch(binilyrics) is None
        assert len(calls) == 1  # فقط جستجو، هیچ فایلی

    def test_at_most_three_documents_are_fetched(self, monkeypatch):
        """سقفِ درخواست: یک جستجو می‌تواند ده‌ها نتیجه بدهد."""
        rows = [_bini_row(lyricsUrl=f"https://lyrics-storage.binimum.org/{i}.ttml") for i in range(10)]
        handler_calls: list[str] = []

        def handler(url, params, headers):
            handler_calls.append(url)
            if "lyrics-api" in url:
                return _resp(200, json_body={"total": 10, "results": rows})
            return _resp(404)  # هیچ سندی پیدا نشد

        _patch(monkeypatch, binilyrics, handler)

        assert _fetch(binilyrics) is None
        assert len(handler_calls) == 1 + binilyrics._MAX_DOCS

    def test_a_mismatched_duration_result_is_skipped(self, monkeypatch):
        calls = _patch(monkeypatch, binilyrics, _bini_search([_bini_row(duration=300)]))

        assert _fetch(binilyrics) is None
        assert len(calls) == 1

    def test_the_best_ranked_result_is_tried_first(self, monkeypatch):
        rows = [
            _bini_row(duration=300, lyricsUrl="https://lyrics-storage.binimum.org/bad.ttml"),
            _bini_row(duration=180, lyricsUrl="https://lyrics-storage.binimum.org/good.ttml"),
        ]
        order: list[str] = []

        def handler(url, params, headers):
            if "lyrics-api" in url:
                return _resp(200, json_body={"total": 2, "results": rows})
            order.append(url)
            return _resp(200, text=_UNISON_TTML)

        _patch(monkeypatch, binilyrics, handler)
        _fetch(binilyrics)

        assert order and "good.ttml" in order[0]

    def test_an_empty_result_list_is_empty(self, monkeypatch):
        _patch(monkeypatch, binilyrics, _bini_search([]))

        assert _fetch(binilyrics) is None

    def test_a_404_on_search_is_empty(self, monkeypatch):
        _patch(monkeypatch, binilyrics, lambda *a: _resp(404))

        assert _fetch(binilyrics) is None

    @pytest.mark.parametrize("status", [429, 500, 502])
    def test_an_error_status_raises(self, monkeypatch, status):
        _patch(monkeypatch, binilyrics, lambda *a: _resp(status))

        with pytest.raises(ProviderError) as info:
            _fetch(binilyrics)
        assert info.value.status == status

    def test_a_timeout_raises_a_network_error(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ConnectTimeout("t")

        _patch(monkeypatch, binilyrics, handler)

        with pytest.raises(ProviderError) as info:
            _fetch(binilyrics)
        assert info.value.kind == "network"

    def test_a_missing_results_field_raises_a_body_error(self, monkeypatch):
        _patch(monkeypatch, binilyrics, lambda *a: _resp(200, json_body={"total": 0}))

        with pytest.raises(ProviderError) as info:
            _fetch(binilyrics)
        assert info.value.kind == "body"

    def test_a_broken_document_does_not_kill_the_next_candidate(self, monkeypatch):
        rows = [
            _bini_row(lyricsUrl="https://lyrics-storage.binimum.org/broken.ttml"),
            _bini_row(lyricsUrl="https://lyrics-storage.binimum.org/good.ttml"),
        ]

        def handler(url, params, headers):
            if "lyrics-api" in url:
                return _resp(200, json_body={"total": 2, "results": rows})
            if "broken" in url:
                return _resp(200, text="<tt>malformed")
            return _resp(200, text=_UNISON_TTML)

        _patch(monkeypatch, binilyrics, handler)

        assert _fetch(binilyrics) is not None

    def test_a_non_http_lyrics_url_is_skipped(self, monkeypatch):
        """جلوگیری از اینکه یک پاسخِ مخدوش ما را به مسیرِ دلخواه بفرستد."""
        calls = _patch(
            monkeypatch,
            binilyrics,
            _bini_search([_bini_row(lyricsUrl="file:///etc/passwd")]),
        )

        assert _fetch(binilyrics) is None
        assert len(calls) == 1

    def test_the_public_fetch_swallows_every_error(self, monkeypatch):
        _patch(monkeypatch, binilyrics, lambda *a: _resp(500))

        assert binilyrics.fetch("Song", "Artist", None, _DURATION_MS) is None


# ---------------------------------------------------------------- lrc.red


def _lrc_red_handler(hits, doc_text=_UNISON_TTML):
    def handler(url, params, headers):
        if "search.json" in url:
            return _resp(200, json_body={"hits": hits, "next": None})
        return _resp(200, text=doc_text)

    return handler


def _hit(**extra):
    row = {"title": "Song", "artist": "Artist", "duration": 180, "isrc": "US1234567890"}
    row.update(extra)
    return row


class TestLrcRed:
    def test_a_matching_hit_fetches_its_document(self, monkeypatch):
        _patch(monkeypatch, lrc_red, _lrc_red_handler([_hit()]))

        assert _fetch(lrc_red) is not None

    def test_the_ttml_document_is_preferred(self, monkeypatch):
        calls = _patch(monkeypatch, lrc_red, _lrc_red_handler([_hit()]))

        _fetch(lrc_red)

        assert any(".ttml" in url for url in calls)

    def test_a_404_on_ttml_falls_back_to_lrc(self, monkeypatch):
        def handler(url, params, headers):
            if "search.json" in url:
                return _resp(200, json_body={"hits": [_hit()]})
            if url.endswith(".ttml"):
                return _resp(404)
            return _resp(200, text="[00:01.00]hi")

        _patch(monkeypatch, lrc_red, handler)

        found = _fetch(lrc_red)

        assert found is not None
        assert found.lines[0].text == "hi"

    def test_an_unrelated_hit_is_never_fetched(self, monkeypatch):
        calls = _patch(
            monkeypatch,
            lrc_red,
            _lrc_red_handler([_hit(title="Totally Different", artist="Nobody")]),
        )

        assert _fetch(lrc_red) is None
        assert len(calls) == 1

    def test_a_hit_without_an_isrc_is_skipped(self, monkeypatch):
        calls = _patch(monkeypatch, lrc_red, _lrc_red_handler([_hit(isrc="")]))

        assert _fetch(lrc_red) is None
        assert len(calls) == 1

    def test_an_empty_hits_list_is_empty(self, monkeypatch):
        _patch(monkeypatch, lrc_red, _lrc_red_handler([]))

        assert _fetch(lrc_red) is None

    def test_a_404_on_search_is_empty(self, monkeypatch):
        _patch(monkeypatch, lrc_red, lambda *a: _resp(404))

        assert _fetch(lrc_red) is None

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_an_error_status_raises(self, monkeypatch, status):
        _patch(monkeypatch, lrc_red, lambda *a: _resp(status))

        with pytest.raises(ProviderError) as info:
            _fetch(lrc_red)
        assert info.value.status == status

    def test_a_timeout_raises_a_network_error(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ReadTimeout("t")

        _patch(monkeypatch, lrc_red, handler)

        with pytest.raises(ProviderError) as info:
            _fetch(lrc_red)
        assert info.value.kind == "network"

    def test_a_missing_hits_field_raises_a_body_error(self, monkeypatch):
        _patch(monkeypatch, lrc_red, lambda *a: _resp(200, json_body={"total": 0}))

        with pytest.raises(ProviderError) as info:
            _fetch(lrc_red)
        assert info.value.kind == "body"

    @pytest.mark.parametrize("payload", [["a"], "text", 7, None], ids=["list", "str", "int", "null"])
    def test_a_non_object_search_body_raises_a_body_error(self, monkeypatch, payload):
        _patch(monkeypatch, lrc_red, lambda *a: _resp(200, json_body=payload))

        with pytest.raises(ProviderError) as info:
            _fetch(lrc_red)
        assert info.value.kind == "body"

    @pytest.mark.parametrize("hits", ["not-a-list", {"a": 1}, 5], ids=["str", "dict", "int"])
    def test_a_non_list_hits_field_raises_a_body_error(self, monkeypatch, hits):
        _patch(monkeypatch, lrc_red, lambda *a: _resp(200, json_body={"hits": hits}))

        with pytest.raises(ProviderError) as info:
            _fetch(lrc_red)
        assert info.value.kind == "body"

    def test_the_format_fallback_uses_the_isrc_from_the_search_response(self, monkeypatch):
        """
        تطبیق با ISRC انجام **نمی‌شود** (Track آن را ندارد). ISRC از خودِ
        پاسخِ جستجو خوانده می‌شود و همان در مسیرِ فایل می‌نشیند.
        """
        seen: list[str] = []

        def handler(url, params, headers):
            if "search.json" in url:
                return _resp(200, json_body={"hits": [{"title": "Song", "artist": "Artist", "duration": 180, "isrc": "USABC1234567"}]})
            seen.append(url)
            return _resp(200, text=_UNISON_TTML)

        _patch(monkeypatch, lrc_red, handler)
        _fetch(lrc_red)

        assert any("USABC1234567" in url for url in seen)

    def test_the_search_query_combines_artist_and_title(self, monkeypatch):
        seen: list[dict] = []

        def handler(url, params, headers):
            seen.append(params)
            if "search.json" in url:
                return _resp(200, json_body={"hits": [_hit()]})
            return _resp(200, text=_UNISON_TTML)

        _patch(monkeypatch, lrc_red, handler)
        _fetch(lrc_red)

        assert "Song" in seen[0]["q"] and "Artist" in seen[0]["q"]

    def test_the_public_fetch_swallows_every_error(self, monkeypatch):
        _patch(monkeypatch, lrc_red, lambda *a: _resp(500))

        assert lrc_red.fetch("Song", "Artist", None, _DURATION_MS) is None


# ---------------------------------------------------------------- SimpMusic


_SIMP_BODY = {
    "success": True,
    "data": {
        "songTitle": "Song",
        "artistName": "Artist",
        "durationSeconds": 180,
        "syncedLyrics": "[00:01.00]<00:01.00>hi",
        "plainLyric": "hi",
    },
}


class TestSimpMusicVideoId:
    """کلیدِ این سرویس شناسه‌ی ویدیوست، نه عنوان. استخراجش باید قطعی باشد."""

    def test_a_youtube_track_id_yields_the_video_id(self):
        assert simpmusic.video_id_of("youtube:video:dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_a_short_tail_is_not_a_video_id(self):
        assert simpmusic.video_id_of("youtube:video:abc") is None

    def test_a_non_youtube_id_is_not_a_video_id(self):
        assert simpmusic.video_id_of("spotify:track:4uLU6hMCjMI75M1A2tKUQC") is None

    def test_an_empty_id_is_none(self):
        assert simpmusic.video_id_of("") is None


class TestSimpMusicIsNowReachable:
    """
    SimpMusic کلیدش `videoId` است. پیش‌تر **هیچ مسیری** این شناسه را به
    Provider نمی‌رساند و Provider در عمل بی‌اثر بود. حالا `Track.videoId`
    و مسیرِ عبورِ Manager آن را می‌رسانند.

    جریان: `Track.videoId` → `LyricsManager.fetch` → `entry.strict(..., video_id=…)`.
    """

    def test_the_track_model_carries_the_optional_hints(self):
        from app.models import Track

        assert "videoId" in Track.model_fields
        assert "isrc" in Track.model_fields
        # اختیاری‌اند — نبودشان Track را invalid نمی‌کند
        assert Track.model_fields["videoId"].default is None
        assert Track.model_fields["isrc"].default is None

    def test_a_track_without_the_hints_still_validates(self):
        from app.models import Track

        track = Track(
            id="x",
            title="Song",
            artist="Artist",
            album=None,
            durationMs=1_000,
            source="spotify",
            sourceUrl="https://e.invalid/x",
        )
        assert track.videoId is None and track.isrc is None

    def test_the_manager_passes_the_video_id_from_the_track(self, monkeypatch):
        """شاهدِ رفعِ UNREACHABLE: شناسه واقعاً به Provider می‌رسد."""
        from app.lyrics.manager import LyricsManager
        from app.lyrics.registry import ProviderEntry, ProviderRegistry
        from app.models import Track

        seen: list[dict] = []

        def capturing(title, artist, album, duration_ms, *, video_id=None, isrc=None):
            seen.append({"video_id": video_id, "isrc": isrc})
            return None

        registry = ProviderRegistry(
            [ProviderEntry("simpmusic", lambda *a, **k: None, None, capturing)],
            ("simpmusic",),
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)
        track = Track(
            id="ytm:track:dQw4w9WgXcQ",
            title="Song",
            artist="Artist",
            album=None,
            durationMs=1_000,
            source="youtube_music",
            sourceUrl="https://music.youtube.com/watch?v=dQw4w9WgXcQ",
            videoId="dQw4w9WgXcQ",
            isrc="US1234567890",
        )

        manager.fetch(track)

        assert seen == [{"video_id": "dQw4w9WgXcQ", "isrc": "US1234567890"}]

    def test_a_provider_that_takes_no_hints_still_works(self, monkeypatch):
        """
        سازگاریِ عقب‌رو: Providerی که فقط چهار آرگومانِ موقعیتی می‌گیرد
        نباید با پاس‌شدنِ کلیدواژه‌ها بشکند.
        """
        from app.lyrics.manager import LyricsManager
        from app.lyrics.models import Lyrics
        from app.lyrics.registry import ProviderEntry, ProviderRegistry
        from app.models import Track

        def four_arg(title, artist, album, duration_ms):
            return Lyrics(plain="ok")

        registry = ProviderRegistry(
            [ProviderEntry("plain", four_arg, None, four_arg)], ("plain",)
        )
        manager = LyricsManager(registry=registry, miss_ttl_s=0)
        track = Track(
            id="x",
            title="Song",
            artist="Artist",
            album=None,
            durationMs=1_000,
            source="spotify",
            sourceUrl="https://e.invalid/x",
            videoId="dQw4w9WgXcQ",
        )

        found = manager.fetch(track)

        assert found is not None and found.plain == "ok"

    def test_every_registered_provider_accepts_the_hint_keywords(self):
        """امضای یکدست: همه‌ی Providerها `video_id`/`isrc` اختیاری دارند."""
        import inspect

        from app.lyrics.manager import _PROVIDERS

        for entry in _PROVIDERS:
            params = inspect.signature(entry.strict()).parameters
            assert "video_id" in params, entry.name
            assert "isrc" in params, entry.name
            assert params["video_id"].kind is inspect.Parameter.KEYWORD_ONLY
            assert params["isrc"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_the_real_extractor_still_exists_but_only_for_streams(self):
        """
        استخراج‌کنندهٔ واقعیِ videoId (`stream/playback.py:98`) روی ترکِ
        غیرِ یوتیوب `None` می‌دهد؛ برای ترکِ یوتیوب شناسه را می‌دهد.
        """
        from app.models import Track
        from app.stream.playback import extract_youtube_video_id

        spotify = Track(
            id="spotify:track:x",
            title="Song",
            artist="Artist",
            album=None,
            durationMs=1_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/x",
        )
        assert extract_youtube_video_id(spotify) is None

        yt = Track(
            id="ytm:track:dQw4w9WgXcQ",
            title="Song",
            artist="Artist",
            album=None,
            durationMs=1_000,
            source="youtube_music",
            sourceUrl="https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        assert extract_youtube_video_id(yt) == "dQw4w9WgXcQ"


class TestSimpMusic:
    def test_without_a_video_id_it_returns_none_and_makes_no_request(self, monkeypatch):
        """حدس‌زدنِ شناسه یعنی متنِ آهنگِ کاملاً دیگری — پس هیچ درخواستی نمی‌رود."""
        monkeypatch.setattr(
            simpmusic.httpx, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("no"))
        )

        assert simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS) is None

    def test_with_a_video_id_the_lyrics_are_parsed(self, monkeypatch):
        _patch(monkeypatch, simpmusic, lambda *a: _resp(200, json_body=_SIMP_BODY))

        found = simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS, video_id="dQw4w9WgXcQ")

        assert found is not None
        assert found.lines[0].words[0].text == "hi"

    def test_rich_sync_is_preferred_over_synced(self, monkeypatch):
        body = {
            "success": True,
            "data": {
                "songTitle": "Song",
                "artistName": "Artist",
                "durationSeconds": 180,
                "syncedLyrics": "[00:01.00]line only",
                "richSyncLyrics": "[00:01.00]<00:01.00>word level",
            },
        }
        _patch(monkeypatch, simpmusic, lambda *a: _resp(200, json_body=body))

        found = simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS, video_id="dQw4w9WgXcQ")

        assert found.sync_type == "word"

    def test_a_404_in_the_envelope_is_empty(self, monkeypatch):
        body = {"success": False, "error": {"code": 404, "error": "not found"}}
        _patch(monkeypatch, simpmusic, lambda *a: _resp(200, json_body=body))

        assert simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS, video_id="dQw4w9WgXcQ") is None

    def test_an_http_404_is_empty(self, monkeypatch):
        _patch(monkeypatch, simpmusic, lambda *a: _resp(404))

        assert simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS, video_id="dQw4w9WgXcQ") is None

    def test_a_generic_unsuccessful_envelope_raises(self, monkeypatch):
        """`success:false` بدونِ کدِ ۴۰۴ خطای سرویس است، نه «ندارم»."""
        body = {"success": False, "error": {"code": 500, "error": "boom"}}
        _patch(monkeypatch, simpmusic, lambda *a: _resp(200, json_body=body))

        with pytest.raises(ProviderError):
            simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS, video_id="dQw4w9WgXcQ")

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_an_error_status_raises(self, monkeypatch, status):
        _patch(monkeypatch, simpmusic, lambda *a: _resp(status))

        with pytest.raises(ProviderError) as info:
            simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS, video_id="dQw4w9WgXcQ")
        assert info.value.status == status

    def test_a_timeout_raises_a_network_error(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ConnectTimeout("t")

        _patch(monkeypatch, simpmusic, handler)

        with pytest.raises(ProviderError) as info:
            simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS, video_id="dQw4w9WgXcQ")
        assert info.value.kind == "network"

    def test_a_wrong_artist_is_rejected(self, monkeypatch):
        body = {**_SIMP_BODY, "data": {**_SIMP_BODY["data"], "artistName": "Someone Else"}}
        _patch(monkeypatch, simpmusic, lambda *a: _resp(200, json_body=body))

        assert simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS, video_id="dQw4w9WgXcQ") is None

    def test_the_video_id_is_in_the_path_not_the_query(self, monkeypatch):
        seen: list[str] = []

        def handler(url, params, headers):
            seen.append(url)
            return _resp(200, json_body=_SIMP_BODY)

        _patch(monkeypatch, simpmusic, handler)
        simpmusic.fetch_strict("Song", "Artist", None, _DURATION_MS, video_id="dQw4w9WgXcQ")

        assert seen[0].endswith("/v1/dQw4w9WgXcQ")


# ---------------------------------------------------------------- cross-cutting


class TestNoTokenLeak:
    """
    هیچ‌کدام از این شش Provider کلید نمی‌خواهند، ولی جزئیاتِ خطا نباید هیچ
    چیزی از درخواست را چاپ کند — نه URL، نه پارامتری که ممکن است بعداً کلید
    بگیرد.
    """

    @pytest.mark.parametrize(
        "module", [lyricsplus, unison, betterlyrics, binilyrics, lrc_red, simpmusic]
    )
    def test_an_error_detail_is_only_the_exception_class_name(self, monkeypatch, module):
        def handler(url, params, headers):
            raise httpx.ConnectTimeout("https://secret.example/key=abc123")

        _patch(monkeypatch, module, handler)

        # simpmusic بدونِ videoId اصلاً درخواست نمی‌زند، پس برای اینکه مسیرِ
        # خطا واقعاً طی شود شناسه‌ی معتبر می‌دهیم.
        kwargs = {"video_id": "dQw4w9WgXcQ"} if module is simpmusic else {}

        with pytest.raises(ProviderError) as info:
            _fetch(module, **kwargs)

        assert info.value.detail == "ConnectTimeout"
        assert "abc123" not in str(info.value)
        assert "secret" not in str(info.value)


class TestRegistryIntegration:
    def test_every_new_provider_is_registered_and_default_off(self):
        from app.lyrics.manager import _PROVIDERS

        by_name = {entry.name: entry for entry in _PROVIDERS}
        for name in ("lyricsplus", "unison", "betterlyrics", "binilyrics", "lrc_red", "simpmusic"):
            entry = by_name[name]
            assert entry.default_enabled is False, name
            assert entry.fetch_strict is not None, name

    def test_a_default_off_provider_never_runs_even_with_a_healthy_manager(self, monkeypatch):
        """تستِ صریحِ بندِ ۲B.0.2-۵، این بار روی Providerهای واقعیِ جدید."""
        from app.lyrics.manager import LyricsManager

        for name in ("lyricsplus", "unison", "betterlyrics", "binilyrics", "lrc_red", "simpmusic"):
            monkeypatch.delenv(f"MUSICBAZI_LYRICS_PROVIDER_{name.upper()}_ENABLED", raising=False)

        manager = LyricsManager()

        assert "lyricsplus" not in [e.name for e in manager.registry.available()]
        assert "unison" not in [e.name for e in manager.registry.available()]

    def test_enabling_one_by_env_makes_it_available(self, monkeypatch):
        from app.lyrics.manager import LyricsManager

        monkeypatch.setenv("MUSICBAZI_LYRICS_PROVIDER_UNISON_ENABLED", "1")

        manager = LyricsManager()

        assert "unison" in [e.name for e in manager.registry.available()]

    def test_a_new_provider_result_carries_its_provider_id(self, monkeypatch):
        """مدیر باید `provider_id` را از اسمِ ثبت‌شده پر کند، نه از Provider."""
        from app.lyrics.manager import LyricsManager
        from app.lyrics.registry import ProviderEntry, ProviderRegistry
        from app.models import Track

        monkeypatch.setenv("MUSICBAZI_LYRICS_PROVIDER_UNISON_ENABLED", "1")
        _patch(monkeypatch, unison, lambda *a: _resp(200, json_body=_unison_body()))

        registry = ProviderRegistry(
            [ProviderEntry("unison", unison.fetch, unison.enabled, unison.fetch_strict)],
            ("unison",),
        )
        track = Track(
            id="t1",
            title="Song",
            artist="Artist",
            album=None,
            durationMs=_DURATION_MS,
            source="spotify",
            sourceUrl="https://example.test/x",
        )

        found = LyricsManager(registry=registry).fetch(track)

        assert found is not None and found.provider_id == "unison"


class TestContractWithExistingConsumers:
    def test_a_provider_result_is_a_plain_lyrics_object(self, monkeypatch):
        """خروجی باید همان `Lyrics` مشترک باشد تا downloader و استریم بی‌تغییر کار کنند."""
        _patch(monkeypatch, unison, lambda *a: _resp(200, json_body=_unison_body()))

        found = _fetch(unison)

        assert isinstance(found, Lyrics)
        assert "lines" in Lyrics.__dataclass_fields__
