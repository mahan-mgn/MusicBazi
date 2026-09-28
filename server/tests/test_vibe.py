"""
چت‌بات پیشنهاد پلی‌لیست: تشخیصِ کلیدواژه‌ای، فراخوانیِ Gemini (مانک‌شده، بدون
شبکه‌ی واقعی)، و resolve_tracks که پیشنهادها را در کاتالوگ پیدا می‌کند.

نکته‌ی قفل‌شده: هیچ مسیری — نبودِ کلید، خطای شبکه، JSON خراب، وایبِ ناشناخته،
شکستِ یک جستجوی تکی — نباید استثنا پرت کند یا چت را دست‌خالی بگذارد.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import catalog, vibe
from app.models import AlbumDetail, Playlist, SearchResults, Track, VibeRequest


def _track(title: str, artist: str, source: str = "apple") -> Track:
    return Track(
        id=f"{source}:{title}", title=title, artist=artist, durationMs=1, source=source, sourceUrl="x"
    )


def _playlist(id_suffix: str, source: str = "deezer", track_count: int = 20) -> Playlist:
    return Playlist(
        id=f"{source}:playlist:{id_suffix}",
        title=f"Playlist {id_suffix}",
        owner="someone",
        trackCount=track_count,
        source=source,
        sourceUrl=f"https://example.com/{source}/{id_suffix}",
    )


def _detail(playlist_id: str, titles: list[str]) -> AlbumDetail:
    tracks = [_track(t, "Artist", source="deezer") for t in titles]
    return AlbumDetail(
        id=playlist_id,
        title="P",
        artist="owner",
        year=0,
        trackCount=len(tracks),
        source="deezer",
        sourceUrl="https://example.com/p",
        durationMs=0,
        tracks=tracks,
    )


class TestKeywordDetection:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("خیلی ناراحتم", "sad"),
            ("حالم بده", "sad"),
            ("امروز خیلی خوشحالم", "happy"),
            ("میخوام برم باشگاه یه چی پرانرژی بزار", "energetic"),
            ("دلم آرامش میخواد", "calm"),
            ("عاشقشم", "romantic"),
            ("خیلی عصبانیم", "angry"),
            ("یاد قدیما افتادم", "nostalgic"),
            ("باید درس بخونم، تمرکز میخوام", "focus"),
            ("دلم شکست", "heartbreak"),
        ],
    )
    def test_matches(self, text, expected):
        assert vibe.detect_from_keywords(text) == expected

    def test_no_match_returns_none(self):
        assert vibe.detect_from_keywords("امروز هوا خوبه") is None

    def test_empty_text_returns_none(self):
        assert vibe.detect_from_keywords("   ") is None


class TestQualifiers:
    """
    قیدهای «قدیمی» و «ایرانی/فارسی» یک محورِ مستقل از خودِ وایب‌اند — درخواستِ
    ترکیبیِ «غمگینِ قدیمیِ ایرانی» باید هم وایبِ درست را بگیرد هم استخر را به
    همان محدود کند، بدون اینکه هیچ‌وقت پلی‌لیست را خالی بگذارد.
    """

    @pytest.mark.parametrize(
        "text,old,persian_only",
        [
            ("یک پلی لیست غمگین از آهنگ های قدیمی ایرانی میخوام", True, True),
            ("یه چیز قدیمی بزار", True, False),
            ("فقط آهنگ ایرانی می‌خوام", False, True),
            ("امروز خیلی خوشحالم", False, False),
        ],
    )
    def test_detects_qualifiers_from_text(self, text, old, persian_only):
        q = vibe.detect_qualifiers(text)
        assert q.old == old
        assert q.persian_only == persian_only

    def test_qualifiers_persist_across_history(self):
        # «قدیمی ایرانی» در نوبتِ اول، پیامِ دوم فقط «آروم‌تر» — قید باید بماند
        from app.models import VibeTurn

        history = [VibeTurn(role="user", text="غمگین ایرانی قدیمی"), VibeTurn(role="model", text="بفرما")]
        q = vibe.detect_qualifiers("نه آروم‌تر", history)
        assert q.old and q.persian_only

    def test_qualifiers_ignore_model_turns_in_history(self):
        # مدل ممکن است اسمِ یک آهنگِ قدیمی را بگوید؛ این قیدِ کاربر نیست
        from app.models import VibeTurn

        history = [VibeTurn(role="model", text="مثلاً فرهاد مهراد قدیمی")]
        q = vibe.detect_qualifiers("یه چیز شاد", history)
        assert not q.old

    def test_old_filters_to_classic_persian_artists(self):
        picks = list(vibe.VIBES["sad"].picks)
        filtered = vibe._filter_picks(picks, vibe.Qualifiers(old=True))
        assert filtered
        assert all(artist in vibe.OLD_PERSIAN_ARTISTS for _, artist in filtered)

    def test_persian_only_filters_out_latin_script_artists(self):
        picks = list(vibe.VIBES["sad"].picks)
        filtered = vibe._filter_picks(picks, vibe.Qualifiers(persian_only=True))
        assert filtered
        assert all(vibe._is_persian(artist) for _, artist in filtered)
        assert ("Someone Like You", "Adele") not in filtered

    def test_no_qualifiers_returns_picks_unchanged(self):
        picks = list(vibe.VIBES["sad"].picks)
        assert vibe._filter_picks(picks, vibe.Qualifiers()) == picks

    def test_an_impossible_constraint_degrades_gracefully_instead_of_emptying(self):
        """هیچ آهنگِ «قدیمی» در استخرِ energetic نیست — نباید پلی‌لیست را خالی کند."""
        picks = list(vibe.VIBES["energetic"].picks)
        assert vibe._filter_picks(picks, vibe.Qualifiers(old=True)) == picks


class TestSuggestWithoutLlm:
    @pytest.fixture(autouse=True)
    def no_key(self, monkeypatch):
        monkeypatch.setattr(vibe, "GEMINI_API_KEY", None)

    def test_chip_click_uses_canned_vibe_without_touching_client(self):
        # client=None: اگر مسیر چیپ سراغ شبکه می‌رفت، همین‌جا با AttributeError می‌شکست
        result = asyncio.run(vibe.suggest(None, VibeRequest(vibe="happy")))
        assert result.vibe == "happy"
        assert result.label == vibe.VIBES["happy"].label
        assert set(result.picks) <= set(vibe.VIBES["happy"].picks)
        assert len(result.picks) == min(vibe.PICKS_PER_SUGGESTION, len(vibe.VIBES["happy"].picks))

    def test_unknown_vibe_key_falls_through_to_message(self):
        result = asyncio.run(vibe.suggest(None, VibeRequest(vibe="nonexistent", message="خیلی ناراحتم")))
        assert result.vibe == "sad"

    def test_message_falls_back_to_keywords_without_a_key(self):
        result = asyncio.run(vibe.suggest(None, VibeRequest(message="خیلی عصبانیم")))
        assert result.vibe == "angry"

    def test_unrecognized_message_falls_back_to_discover(self):
        result = asyncio.run(vibe.suggest(None, VibeRequest(message="امروز هوا خوبه")))
        assert result.vibe == "discover"
        assert result.picks == list(vibe.DISCOVER.picks)

    def test_empty_request_falls_back_to_discover(self):
        result = asyncio.run(vibe.suggest(None, VibeRequest()))
        assert result.vibe == "discover"


class _FakeClient:
    """جایگزینِ httpx.AsyncClient — فقط .post را دارد، دقیقاً همان چیزی که _call_llm صدا می‌زند."""

    def __init__(self, handler):
        self._handler = handler

    async def post(self, url, *, json, headers, timeout):
        return self._handler(url, json, headers, timeout)


def _response(status: int, *, json_body: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent")
    return httpx.Response(status, json=json_body, request=request)


def _gemini_text(text: str) -> dict:
    """بدنه‌ی پاسخِ generateContent — فقط یک partِ متنی."""
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}


def _req(**kw) -> VibeRequest:
    """VibeRequestِ خالیِ مناسبِ _call_llm (که تاریخچه را از req می‌خواند)."""
    return VibeRequest(**kw)


class TestCallLlm:
    @pytest.fixture(autouse=True)
    def key(self, monkeypatch):
        monkeypatch.setattr(vibe, "GEMINI_API_KEY", "test-key")

    def test_no_key_short_circuits_without_a_request(self, monkeypatch):
        monkeypatch.setattr(vibe, "GEMINI_API_KEY", None)
        client = _FakeClient(lambda *a: (_ for _ in ()).throw(AssertionError("should not connect")))

        assert asyncio.run(vibe._call_llm(client, _req(), "ناراحتم")) is None

    def test_successful_response_is_parsed(self):
        body = _gemini_text(
            '{"vibe": "sad", "reply": "حالت رو درک می‌کنم.", '
            '"picks": [{"title": "Someone Like You", "artist": "Adele"},'
            '{"title": "گریه نکن", "artist": "شادمهر عقیلی"}]}'
        )
        client = _FakeClient(lambda *a: _response(200, json_body=body))

        result = asyncio.run(vibe._call_llm(client, _req(), "خیلی ناراحتم"))

        assert result is not None
        assert result.vibe == "sad"
        assert result.label == vibe.VIBES["sad"].label
        assert result.reply == "حالت رو درک می‌کنم."
        assert result.picks == [("Someone Like You", "Adele"), ("گریه نکن", "شادمهر عقیلی")]

    def test_response_wrapped_in_markdown_fence_still_parses(self):
        """مدل بعضی‌وقت‌ها با تأکید هم ```json می‌گذارد — نباید کل پاسخ را باطل کند."""
        body = _gemini_text(
            '```json\n{"vibe": "happy", "reply": "چه خوب!", '
            '"picks": [{"title": "Happy", "artist": "Pharrell Williams"}]}\n``'
        )
        client = _FakeClient(lambda *a: _response(200, json_body=body))

        result = asyncio.run(vibe._call_llm(client, _req(), "خوشحالم"))

        assert result is not None
        assert result.vibe == "happy"

    def test_http_error_returns_none(self):
        client = _FakeClient(lambda *a: _response(500))
        assert asyncio.run(vibe._call_llm(client, _req(), "متن")) is None

    def test_malformed_json_returns_none(self):
        body = _gemini_text("not json at all")
        client = _FakeClient(lambda *a: _response(200, json_body=body))
        assert asyncio.run(vibe._call_llm(client, _req(), "متن")) is None

    def test_unknown_vibe_in_response_is_rejected(self):
        body = _gemini_text('{"vibe": "mysterious", "reply": "x", "picks": [{"title": "A", "artist": "B"}]}')
        client = _FakeClient(lambda *a: _response(200, json_body=body))
        assert asyncio.run(vibe._call_llm(client, _req(), "متن")) is None

    def test_empty_picks_is_rejected(self):
        body = _gemini_text('{"vibe": "sad", "reply": "x", "picks": []}')
        client = _FakeClient(lambda *a: _response(200, json_body=body))
        assert asyncio.run(vibe._call_llm(client, _req(), "متن")) is None

    def test_network_exception_returns_none(self):
        class Boom:
            async def post(self, *a, **kw):
                raise httpx.ConnectError("down")

        assert asyncio.run(vibe._call_llm(Boom(), _req(), "متن")) is None

    def test_blocked_prompt_falls_back_instead_of_crashing(self):
        """۲۰۰ با promptFeedback.blockReason — متن‌های خشم/غم گاهی سانسور می‌شوند."""
        body = {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
        client = _FakeClient(lambda *a: _response(200, json_body=body))
        assert asyncio.run(vibe._call_llm(client, _req(), "خیلی عصبانیم")) is None

    def test_empty_candidates_returns_none(self):
        """۲۰۰ ولی بی‌candidate (مثلاً MAX_TOKENS) — نباید KeyError بدهد."""
        client = _FakeClient(lambda *a: _response(200, json_body={"candidates": []}))
        assert asyncio.run(vibe._call_llm(client, _req(), "متن")) is None

    def test_request_carries_schema_and_key_in_header(self):
        """
        قراردادِ Gemini: کلید در هدر (نه query)، قالب در responseSchema. اگر
        روزی کسی این را به سبکِ Anthropic برگرداند، پاسخِ مدل بی‌قالب می‌شود و
        چت بی‌صدا روی حالتِ کلیدواژه می‌افتد — این تست جلوی آن را می‌گیرد.
        """
        captured: dict = {}

        def handler(url, body, headers, timeout):
            captured["url"], captured["headers"], captured["body"] = url, headers, body
            return _response(200, json_body=_gemini_text(
                '{"vibe": "calm", "reply": "باشه.", "picks": [{"title": "A", "artist": "B"}]}'
            ))

        asyncio.run(vibe._call_llm(_FakeClient(handler), _req(), "دلم آرامش میخواد"))

        assert vibe.GEMINI_MODEL in captured["url"]
        assert captured["headers"]["x-goog-api-key"] == "test-key"
        assert "anthropic-version" not in captured["headers"]
        config = captured["body"]["generationConfig"]
        assert config["responseMimeType"] == "application/json"
        assert set(config["responseSchema"]["properties"]["picks"]["items"]["properties"]) == {
            "title",
            "artist",
        }
        assert config["responseSchema"]["properties"]["vibe"]["enum"] == list(vibe.VIBES)
        assert "reason" in config["responseSchema"]["properties"]
        # systemInstruction/contents به سبکِ generateContent، نه messages/system
        assert "systemInstruction" in captured["body"]
        assert captured["body"]["contents"][0]["parts"][0]["text"] == "دلم آرامش میخواد"

    def test_history_is_sent_as_prior_turns(self):
        """
        حافظه‌ی چندتوره: «نه آروم‌تر» فقط وقتی معنا دارد که پیامِ قبلی هم به
        مدل رسیده باشد. ترتیب و roleها همان قراردادِ generateContent است.
        """
        captured: dict = {}

        def handler(url, body, headers, timeout):
            captured["body"] = body
            return _response(200, json_body=_gemini_text(
                '{"vibe": "calm", "reply": "باشه.", "reason": "r", "picks": [{"title": "A", "artist": "B"}]}'
            ))

        req = _req(
            history=[
                {"role": "user", "text": "غمگینم"},
                {"role": "model", "text": "این‌ها رو گذاشتم"},
            ]
        )
        asyncio.run(vibe._call_llm(_FakeClient(handler), req, "نه آروم‌تر"))

        turns = captured["body"]["contents"]
        assert [(t["role"], t["parts"][0]["text"]) for t in turns] == [
            ("user", "غمگینم"),
            ("model", "این‌ها رو گذاشتم"),
            ("user", "نه آروم‌تر"),
        ]

    def test_history_is_truncated_to_the_latest_turns(self):
        """سقفِ توکن: فقط HISTORY_TURNSِ آخر می‌روند، و همیشه پیامِ جاری ته‌اش."""
        captured: dict = {}

        def handler(url, body, headers, timeout):
            captured["body"] = body
            return _response(200, json_body=_gemini_text(
                '{"vibe": "calm", "reply": "x", "reason": "r", "picks": [{"title": "A", "artist": "B"}]}'
            ))

        req = _req(history=[{"role": "user", "text": f"m{i}"} for i in range(20)])
        asyncio.run(vibe._call_llm(_FakeClient(handler), req, "آخری"))

        texts = [t["parts"][0]["text"] for t in captured["body"]["contents"]]
        assert len(texts) == vibe.HISTORY_TURNS + 1
        assert texts[-1] == "آخری"
        assert texts[0] == "m14"  # ۲۰ تا بود، ۶ تای آخر مانده

    def test_blank_and_unknown_roles_are_dropped_from_history(self):
        """
        تاریخچه‌ی خراب نباید چت را ۴۰۰/۴۲۲ کند: نوبتِ خالی و role ناشناس
        حذف می‌شوند و پیامِ جاری همیشه می‌ماند.
        """
        req = _req(history=[{"role": "system", "text": "hacker"}, {"role": "user", "text": "   "}])
        assert vibe._contents(req, "سلام") == [{"role": "user", "parts": [{"text": "سلام"}]}]

    def test_taste_profile_reaches_the_system_prompt(self, monkeypatch):
        """چت باید سلیقه‌ی خودِ کاربر را بداند — وگرنه «خاص» بودنش حرفی است."""
        captured: dict = {}

        def handler(url, body, headers, timeout):
            captured["body"] = body
            return _response(200, json_body=_gemini_text(
                '{"vibe": "sad", "reply": "x", "reason": "r", "picks": [{"title": "A", "artist": "B"}]}'
            ))

        monkeypatch.setattr(vibe, "library_digest", lambda: "User's liked artists: شادمهر عقیلی")
        asyncio.run(vibe._call_llm(_FakeClient(handler), _req(), "ناراحتم"))

        assert "User's liked artists: شادمهر عقیلی" in captured["body"]["systemInstruction"]["parts"][0]["text"]

    def test_no_taste_profile_leaves_system_prompt_clean(self, monkeypatch):
        captured: dict = {}

        def handler(url, body, headers, timeout):
            captured["body"] = body
            return _response(200, json_body=_gemini_text(
                '{"vibe": "sad", "reply": "x", "reason": "r", "picks": [{"title": "A", "artist": "B"}]}'
            ))

        monkeypatch.setattr(vibe, "library_digest", lambda: None)
        asyncio.run(vibe._call_llm(_FakeClient(handler), _req(), "ناراحتم"))

        assert "Taste profile" not in captured["body"]["systemInstruction"]["parts"][0]["text"]

    def test_reason_is_parsed(self):
        body = _gemini_text(
            '{"vibe": "sad", "reply": "x", "reason": "چون لایک‌هات سمتِ پاپِ آرامه",'
            ' "picks": [{"title": "A", "artist": "B"}]}'
        )
        client = _FakeClient(lambda *a: _response(200, json_body=body))
        result = asyncio.run(vibe._call_llm(client, _req(), "ناراحتم"))
        assert result is not None and result.reason == "چون لایک‌هات سمتِ پاپِ آرامه"

    def test_missing_reason_does_not_void_an_otherwise_good_answer(self):
        """schema آن را required می‌کند ولی مدلِ قدیمی ممکن است حذفش کند."""
        body = _gemini_text('{"vibe": "sad", "reply": "x", "picks": [{"title": "A", "artist": "B"}]}')
        client = _FakeClient(lambda *a: _response(200, json_body=body))
        result = asyncio.run(vibe._call_llm(client, _req(), "ناراحتم"))
        assert result is not None and result.reason is None


class TestSuggestWithLlm:
    @pytest.fixture(autouse=True)
    def key(self, monkeypatch):
        monkeypatch.setattr(vibe, "GEMINI_API_KEY", "test-key")

    def test_llm_result_is_used_when_available(self, monkeypatch):
        fake_result = vibe.VibeResult(
            vibe="calm", label=vibe.VIBES["calm"].label, reply="آروم باش.", picks=[("A", "B")]
        )

        async def fake_llm(client, req, text):
            return fake_result

        monkeypatch.setattr(vibe, "_call_llm", fake_llm)

        result = asyncio.run(vibe.suggest(None, VibeRequest(message="نمی‌دونم چی می‌خوام")))
        assert result is fake_result

    def test_llm_failure_falls_back_to_keywords(self, monkeypatch):
        async def fake_llm(client, req, text):
            return None

        monkeypatch.setattr(vibe, "_call_llm", fake_llm)

        result = asyncio.run(vibe.suggest(None, VibeRequest(message="خیلی عصبانیم")))
        assert result.vibe == "angry"

    def test_chip_click_goes_through_the_llm(self, monkeypatch):
        """
        چیپ دیگر LLM را دور نمی‌زند: برچسبش به‌عنوانِ پیام می‌رود تا انتخاب‌ها
        با سلیقه و تاریخچه قاطی شوند. (قبلاً همیشه همان ریپلایِ ثابت بود.)
        """
        captured: dict = {}
        fake_result = vibe.VibeResult(
            vibe="romantic", label=vibe.VIBES["romantic"].label, reply="عشق!", picks=[("A", "B")], reason="r"
        )

        async def fake_llm(client, req, text):
            captured["text"] = text
            return fake_result

        monkeypatch.setattr(vibe, "_call_llm", fake_llm)

        result = asyncio.run(vibe.suggest(None, VibeRequest(vibe="romantic")))
        assert result is fake_result
        assert captured["text"] == vibe.VIBES["romantic"].label

    def test_chip_falls_back_to_its_own_vibe_when_llm_is_silent(self, monkeypatch):
        """بدونِ کلید/با خطای Gemini، چیپ باید همان وایبِ خودش را بدهد نه حدسِ متن."""

        async def fake_llm(client, req, text):
            return None

        monkeypatch.setattr(vibe, "_call_llm", fake_llm)

        result = asyncio.run(vibe.suggest(None, VibeRequest(vibe="romantic")))
        assert result.vibe == "romantic"
        assert result.reply == vibe.VIBES["romantic"].reply


class TestResolveTracks:
    def test_dedupes_and_caps_at_max(self, monkeypatch):
        async def fake_search(client, query):
            if "dup" in query:
                return SearchResults(query=query, tracks=[_track("Same Song", "Artist")])
            return SearchResults(query=query, tracks=[_track(query.strip(), "X")])

        monkeypatch.setattr(catalog, "search", fake_search)

        picks = [("dup1", "a"), ("dup2", "a")] + [(f"t{i}", "") for i in range(12)]
        tracks = asyncio.run(vibe.resolve_tracks(None, picks))

        assert len(tracks) == vibe.MAX_TRACKS
        assert [t.title for t in tracks].count("Same Song") == 1

    def test_a_failed_search_does_not_break_the_rest(self, monkeypatch):
        async def fake_search(client, query):
            if "boom" in query:
                raise RuntimeError("provider down")
            return SearchResults(query=query, tracks=[_track(query.strip(), "X")])

        monkeypatch.setattr(catalog, "search", fake_search)

        tracks = asyncio.run(vibe.resolve_tracks(None, [("boom", "x"), ("ok", "y")]))
        assert [t.title for t in tracks] == ["ok y"]

    def test_empty_search_results_are_skipped(self, monkeypatch):
        async def fake_search(client, query):
            return SearchResults(query=query, tracks=[])

        monkeypatch.setattr(catalog, "search", fake_search)

        assert asyncio.run(vibe.resolve_tracks(None, [("nothing", "here")])) == []

    def test_no_picks_returns_empty_list(self):
        assert asyncio.run(vibe.resolve_tracks(None, [])) == []

    def test_excluded_track_ids_are_dropped(self, monkeypatch):
        async def fake_search(client, query):
            return SearchResults(query=query, tracks=[_track(query.strip(), "X", source="deezer")])

        monkeypatch.setattr(catalog, "search", fake_search)

        tracks = asyncio.run(
            vibe.resolve_tracks(None, [("keep", "a"), ("drop", "b")], exclude={"deezer:drop b"})
        )

        assert [t.title for t in tracks] == ["keep a"]


class TestPickPlaylists:
    def test_dedupes_by_id(self):
        a = _playlist("1")
        assert len(vibe._pick_playlists([a, a, a])) == 1

    def test_filters_out_very_short_playlists(self):
        short = _playlist("1", track_count=1)
        long_ = _playlist("2", track_count=20)

        picked = vibe._pick_playlists([short, long_])

        assert [p.id for p in picked] == [long_.id]

    def test_alternates_between_sources(self):
        deezer_playlists = [_playlist(str(i), source="deezer") for i in range(5)]
        spotify_playlists = [_playlist(str(i), source="spotify") for i in range(5)]

        picked = vibe._pick_playlists(deezer_playlists + spotify_playlists)

        assert len(picked) == vibe.PLAYLIST_COUNT
        assert {p.source for p in picked} == {"deezer", "spotify"}

    def test_caps_at_playlist_count(self):
        pool = [_playlist(str(i)) for i in range(10)]
        assert len(vibe._pick_playlists(pool)) == vibe.PLAYLIST_COUNT

    def test_empty_candidates_returns_empty(self):
        assert vibe._pick_playlists([]) == []


class TestTracksFromPlaylists:
    def test_samples_from_each_playlist_and_dedupes(self, monkeypatch):
        p1, p2 = _playlist("1"), _playlist("2")
        overlapping_titles = [f"t{i}" for i in range(10)]

        async def fake_resolve(client, ref):
            # هر دو پلی‌لیست همان ده عنوان را دارند — نتیجه باید یکتا بماند
            return _detail(ref, overlapping_titles)

        monkeypatch.setattr(catalog, "resolve_ref", fake_resolve)

        tracks = asyncio.run(vibe._tracks_from_playlists(None, [p1, p2], exclude=set()))

        titles = [t.title for t in tracks]
        assert len(titles) == len(set(titles))
        assert len(tracks) <= vibe.MAX_TRACKS

    def test_excluded_ids_are_skipped(self, monkeypatch):
        p1 = _playlist("1")
        detail = _detail("a", ["Keep", "Drop"])
        drop_id = next(t.id for t in detail.tracks if t.title == "Drop")

        async def fake_resolve(client, ref):
            return detail

        monkeypatch.setattr(catalog, "resolve_ref", fake_resolve)

        tracks = asyncio.run(vibe._tracks_from_playlists(None, [p1], exclude={drop_id}))

        assert all(t.id != drop_id for t in tracks)

    def test_a_failed_resolve_does_not_break_the_rest(self, monkeypatch):
        p1, p2 = _playlist("1"), _playlist("2")

        async def fake_resolve(client, ref):
            if ref == p1.sourceUrl:
                raise RuntimeError("down")
            return _detail("b", ["Ok Song"])

        monkeypatch.setattr(catalog, "resolve_ref", fake_resolve)

        tracks = asyncio.run(vibe._tracks_from_playlists(None, [p1, p2], exclude=set()))

        assert [t.title for t in tracks] == ["Ok Song"]

    def test_no_playlists_returns_empty(self):
        assert asyncio.run(vibe._tracks_from_playlists(None, [], exclude=set())) == []


class TestBuildPlaylist:
    """
    نقطه‌ی ورودیِ کامل: اول پلی‌لیستِ واقعی، فقط اگر چیزی پیدا نشد برگشت به
    روشِ قدیمیِ تک‌ترکی — همان قولی که به کاربر داده شد و نباید رگرسیون بخورد.
    """

    def test_uses_platform_playlists_when_found(self, monkeypatch):
        pl = _playlist("1")

        async def fake_search_playlists(client, key, qualifiers=vibe.Qualifiers()):
            return [pl]

        async def fake_tracks_from_playlists(client, playlists, exclude):
            return [_track("Real Song", "Artist", source="deezer")]

        async def fail_resolve_tracks(client, picks, exclude=frozenset()):
            raise AssertionError("نباید به روشِ قدیمی بیفتد — پلی‌لیستِ واقعی جواب داده بود")

        monkeypatch.setattr(vibe, "_search_playlists", fake_search_playlists)
        monkeypatch.setattr(vibe, "_pick_playlists", lambda candidates: [pl])
        monkeypatch.setattr(vibe, "_tracks_from_playlists", fake_tracks_from_playlists)
        monkeypatch.setattr(vibe, "resolve_tracks", fail_resolve_tracks)

        result = asyncio.run(vibe.build_playlist(None, VibeRequest(vibe="happy")))

        assert [t.title for t in result.tracks] == ["Real Song"]
        assert "Playlist 1" in result.reply

    def test_falls_back_to_the_old_method_when_no_playlists_found(self, monkeypatch):
        async def fake_search_playlists(client, key, qualifiers=vibe.Qualifiers()):
            return []

        async def fake_resolve_tracks(client, picks, exclude=frozenset()):
            return [_track("Fallback Song", "Artist")]

        monkeypatch.setattr(vibe, "_search_playlists", fake_search_playlists)
        monkeypatch.setattr(vibe, "resolve_tracks", fake_resolve_tracks)

        result = asyncio.run(vibe.build_playlist(None, VibeRequest(vibe="happy")))

        assert [t.title for t in result.tracks] == ["Fallback Song"]
        # ریپلای دست‌نخورده می‌ماند — چیزی درباره‌ی پلی‌لیستِ واقعی اضافه نشده
        assert result.reply == vibe.VIBES["happy"].reply

    def test_qualifiers_reach_the_playlist_search_and_the_picks_fallback(self, monkeypatch):
        """
        سناریوی «یک پلی لیست غمگین از آهنگ های قدیمی ایرانی میخوام»: هم
        جستجوی پلی‌لیستِ واقعی هم استخرِ برگشتی باید همان قیدها را ببینند.
        """
        monkeypatch.setattr(vibe, "GEMINI_API_KEY", None)
        captured: dict = {}

        async def fake_search_playlists(client, key, qualifiers=vibe.Qualifiers()):
            captured["qualifiers"] = qualifiers
            return []  # پلتفرم چیزی نداد — باید به استخرِ فیلترشده بیفتد

        async def fake_resolve_tracks(client, picks, exclude=frozenset()):
            captured["picks"] = picks
            return [_track("بزن بارون", "فریدون فروغی", source="deezer")]

        monkeypatch.setattr(vibe, "_search_playlists", fake_search_playlists)
        monkeypatch.setattr(vibe, "resolve_tracks", fake_resolve_tracks)

        req = VibeRequest(message="یک پلی لیست غمگین از آهنگ های قدیمی ایرانی میخوام")
        result = asyncio.run(vibe.build_playlist(None, req))

        assert captured["qualifiers"] == vibe.Qualifiers(old=True, persian_only=True)
        assert captured["picks"]
        assert all(artist in vibe.OLD_PERSIAN_ARTISTS for _, artist in captured["picks"])
        assert "ایرونی" in result.reply

    def test_falls_back_when_playlists_found_but_yield_no_tracks(self, monkeypatch):
        """پلی‌لیست پیدا شد ولی resolve_ref همه را None داد (پلتفرم موقتاً قطع) — نباید دست‌خالی بماند."""
        pl = _playlist("1")

        async def fake_search_playlists(client, key, qualifiers=vibe.Qualifiers()):
            return [pl]

        async def empty_tracks_from_playlists(client, playlists, exclude):
            return []

        async def fake_resolve_tracks(client, picks, exclude=frozenset()):
            return [_track("Fallback Song", "Artist")]

        monkeypatch.setattr(vibe, "_search_playlists", fake_search_playlists)
        monkeypatch.setattr(vibe, "_pick_playlists", lambda candidates: [pl])
        monkeypatch.setattr(vibe, "_tracks_from_playlists", empty_tracks_from_playlists)
        monkeypatch.setattr(vibe, "resolve_tracks", fake_resolve_tracks)

        result = asyncio.run(vibe.build_playlist(None, VibeRequest(vibe="happy")))

        assert [t.title for t in result.tracks] == ["Fallback Song"]


class TestLibraryAwareness:
    """
    چت باید سلیقه‌ی خودِ کاربر را بداند و بداند کدام پیشنهاد را از قبل دارد.
    بدون این دو، «وایب چت» فقط یک جستجوی قشنگ است.
    """

    def test_digest_names_liked_artists_and_their_center(self, fresh_db, track):
        import time

        fresh_db.insert_job("j1", track, "320", "ready", time.time())
        fresh_db.update_job("j1", status="ready", path="x", bytes=10, valence=0.2, energy=0.3)
        fresh_db.set_favorite("j1", True)

        digest = vibe.library_digest()

        assert digest is not None and track.artist in digest
        assert "valence 0.20" in digest and "energy 0.30" in digest

    def test_digest_is_none_for_an_empty_library(self, fresh_db):
        assert vibe.library_digest() is None

    def test_owned_tracks_come_back_ready_without_a_download(self, fresh_db, track):
        import time

        fresh_db.insert_job("j1", track, "320", "ready", time.time())
        fresh_db.update_job("j1", status="ready", path="x", bytes=10)

        owned = vibe._owned_files([track])

        assert owned[track.id].jobId == "j1"
        assert owned[track.id].streamUrl.endswith(f"/api/downloads/j1/stream")

    def test_tracks_not_in_the_library_are_not_marked_ready(self, fresh_db, track):
        assert vibe._owned_files([track]) == {}

    def test_two_qualities_pick_the_bigger_file(self, fresh_db, track):
        import time

        fresh_db.insert_job("j-low", track, "128", "ready", time.time())
        fresh_db.update_job("j-low", status="ready", path="x", bytes=100)
        fresh_db.insert_job("j-high", track, "320", "ready", time.time())
        fresh_db.update_job("j-high", status="ready", path="x", bytes=900)

        assert vibe._owned_files([track])[track.id].jobId == "j-high"

    def test_build_playlist_reports_reason_and_ready(self, monkeypatch, fresh_db, track):
        async def fake_suggest(client, req):
            return vibe.VibeResult(
                vibe="sad", label=vibe.VIBES["sad"].label, reply="r", picks=[("x", "y")], reason="چون دلتنگی"
            )

        async def fake_search_playlists(client, key, qualifiers=vibe.Qualifiers()):
            return []

        async def fake_resolve(client, picks, exclude=frozenset()):
            return [track]

        monkeypatch.setattr(vibe, "_search_playlists", fake_search_playlists)
        monkeypatch.setattr(vibe, "resolve_tracks", fake_resolve)
        monkeypatch.setattr(vibe, "suggest", fake_suggest)

        import time

        fresh_db.insert_job("j1", track, "320", "ready", time.time())
        fresh_db.update_job("j1", status="ready", path="x", bytes=10)

        result = asyncio.run(vibe.build_playlist(None, VibeRequest(message="غمگینم")))

        assert result.reason == "چون دلتنگی"
        assert result.ready[track.id].jobId == "j1"

    def test_keyword_path_has_no_reason(self, monkeypatch):
        """مسیرِ کلیدواژه توضیحی نمی‌سازد — «چرا اینا؟» فقط با مدل."""
        monkeypatch.setattr(vibe, "GEMINI_API_KEY", None)

        async def fake_search_playlists(client, key, qualifiers=vibe.Qualifiers()):
            return []

        async def fake_resolve(client, picks, exclude=frozenset()):
            return [_track("x", "y")]

        monkeypatch.setattr(vibe, "_search_playlists", fake_search_playlists)
        monkeypatch.setattr(vibe, "resolve_tracks", fake_resolve)

        result = asyncio.run(vibe.build_playlist(None, VibeRequest(message="خیلی ناراحتم")))
        assert result.reason is None and result.ready == {}


class TestSamplePicks:
    """
    استخرِ هر وایب باید هر بار زیرمجموعه‌ی متفاوتی بدهد — کلیک‌های پیاپی روی
    یک چیپ نباید همان پلی‌لیست را برگردانند.
    """

    def test_returns_the_configured_count_when_pool_is_larger(self):
        pool = tuple((f"t{i}", "a") for i in range(20))
        assert len(vibe._sample_picks(pool)) == vibe.PICKS_PER_SUGGESTION

    def test_returns_the_whole_pool_when_it_is_not_larger(self):
        pool = (("t1", "a"), ("t2", "b"))
        assert vibe._sample_picks(pool) == list(pool)

    def test_repeated_calls_vary(self):
        pool = tuple((f"t{i}", "a") for i in range(30))
        samples = {tuple(vibe._sample_picks(pool)) for _ in range(10)}
        assert len(samples) > 1
