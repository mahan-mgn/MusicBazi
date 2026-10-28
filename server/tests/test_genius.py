"""
متن آهنگ از Genius.

API عمومی‌اش متن را نمی‌دهد، فقط جستجو و لینک صفحه — و صفحه پر از div ست که
باید فقط داخل `data-lyrics-container` را جمع کرد، نه هر چیزی. سه چیز اینجا
قفل می‌شود: انتخاب بهترین نتیجه‌ی جستجو، استخراج درست از HTML تودرتو، و اینکه
بدون کلید (یا هر خطای شبکه‌ای) چیزی جز None برنمی‌گردد.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers import genius
from app import config


class TestBestUrl:
    def test_exact_match_wins(self):
        hits = [
            {
                "result": {
                    "url": "https://genius.com/other-song",
                    "lyrics_state": "complete",
                    "title": "Some Other Song",
                    "primary_artist": {"name": "Someone Else"},
                }
            },
            {
                "result": {
                    "url": "https://genius.com/farhad-barf",
                    "lyrics_state": "complete",
                    "title": "Barf (Remastered)",
                    "primary_artist": {"name": "Farhad Mehrad"},
                }
            },
        ]

        assert genius._best_url(hits, "Barf", "Farhad") == "https://genius.com/farhad-barf"

    def test_incomplete_lyrics_state_is_skipped(self):
        """instrumental یا هنوز رونویسی‌نشده — لینک هست ولی متنش نه."""
        hits = [
            {
                "result": {
                    "url": "https://genius.com/instrumental",
                    "lyrics_state": "unreleased",
                    "title": "Barf",
                    "primary_artist": {"name": "Farhad"},
                }
            }
        ]

        assert genius._best_url(hits, "Barf", "Farhad") is None

    def test_no_hits_returns_none(self):
        assert genius._best_url([], "Barf", "Farhad") is None

    def test_an_unrelated_hit_is_never_accepted(self):
        """
        جستجوی Genius دست‌خالی برنمی‌گردد: برای ترکی که ندارد هم ده نتیجه‌ی
        بی‌ربط می‌دهد. باگِ واقعی همین بود — «Telesm» از «Amiryal» در Genius
        نیست و اولین نتیجه‌ی بی‌ربط قبول می‌شد، پس فایل .lrc متنِ صفحه‌ی دیگری
        می‌گرفت و کارتِ اطلاعات کاور و تاریخِ آهنگِ دیگری را نشان می‌داد.
        """
        hits = [
            {
                "result": {
                    "url": "https://genius.com/unrelated",
                    "lyrics_state": "complete",
                    "title": "Totally Different",
                    "primary_artist": {"name": "Nobody"},
                }
            }
        ]

        assert genius._best_url(hits, "Barf", "Farhad") is None

    def test_the_title_alone_is_not_enough(self):
        """هم‌نامی فراوان است؛ بدونِ خوردنِ هنرمند، آهنگِ کسِ دیگری است."""
        hits = [
            {
                "result": {
                    "url": "https://genius.com/someone-else-barf",
                    "lyrics_state": "complete",
                    "title": "Barf",
                    "primary_artist": {"name": "Someone Else"},
                }
            }
        ]

        assert genius._best_url(hits, "Barf", "Farhad") is None


def _hit(title: str, artist: str, url: str = "https://genius.com/x") -> dict:
    return {
        "result": {
            "url": url,
            "lyrics_state": "complete",
            "title": title,
            "primary_artist": {"name": artist},
        }
    }


class TestSpellingDrift:
    """
    رومانیزه‌ی فارسی استاندارد ندارد و اسپاتیفای/اپل با Genius یکی نمی‌نویسند.
    باگِ واقعی همین بود: «Mordi» از «Tlkhoon» در Genius «Moordi» است، هیچ
    کلمه‌ی مشترکی ندارند و متنِ موجود دور ریخته می‌شد.
    """

    def test_a_near_miss_title_is_accepted_when_the_artist_matches(self):
        hits = [_hit("Moordi", "Tlkhoon", "https://genius.com/tlkhoon-moordi-lyrics")]

        assert (
            genius._best_url(hits, "Mordi", "Tlkhoon")
            == "https://genius.com/tlkhoon-moordi-lyrics"
        )

    def test_a_near_miss_title_alone_is_still_not_enough(self):
        """تحملِ املا فقط کنارِ هنرمندِ درست؛ وگرنه همان قبولِ کورِ قبلی است."""
        hits = [_hit("Moordi", "Someone Else")]

        assert genius._best_url(hits, "Mordi", "Tlkhoon") is None

    def test_a_merely_similar_title_is_rejected(self):
        """«Mahdi» هم چند حرف مشترک دارد — آستانه باید جلویش را بگیرد."""
        hits = [_hit("Mahdi", "Tlkhoon")]

        assert genius._best_url(hits, "Mordi", "Tlkhoon") is None

    def test_an_exact_match_wins_over_a_near_miss(self):
        hits = [
            _hit("Moordi", "Tlkhoon", "https://genius.com/near"),
            _hit("Mordi", "Tlkhoon", "https://genius.com/exact"),
        ]

        assert genius._best_url(hits, "Mordi", "Tlkhoon") == "https://genius.com/exact"


class TestPrimary:
    @pytest.mark.parametrize(
        "artist",
        ["Tlkhoon, NoTsH", "Tlkhoon & NoTsH", "Tlkhoon x NoTsH", "Tlkhoon feat. NoTsH"],
    )
    def test_only_the_first_artist_survives(self, artist):
        assert genius._primary(artist) == "Tlkhoon"

    def test_a_single_artist_is_untouched(self):
        assert genius._primary("Farhad Mehrad") == "Farhad Mehrad"


class TestExtract:
    def test_line_breaks_become_newlines(self):
        html = '<div data-lyrics-container="true">Line one<br>Line two</div>'

        assert genius._extract(html) == "Line one\nLine two"

    def test_nested_divs_do_not_truncate_the_text(self):
        """
        یک annotation یا دکمه‌ی توضیح می‌تواند div تودرتو باشد — قطع زودهنگام
        روی اولین `</div>` دقیقاً همین را می‌شکست.
        """
        html = (
            '<div data-lyrics-container="true">'
            "Verse one<br>"
            '<div class="ReferentFragment">annotated bit</div>'
            "<br>Verse two"
            "</div>"
        )

        text = genius._extract(html)

        assert "Verse one" in text
        assert "annotated bit" in text
        assert "Verse two" in text

    def test_multiple_containers_are_joined(self):
        """Genius گاهی متن را دور یک تبلیغ/امبد به چند div می‌شکند."""
        html = (
            '<div data-lyrics-container="true">Part one</div>'
            '<div class="ad">skip me</div>'
            '<div data-lyrics-container="true">Part two</div>'
        )

        text = genius._extract(html)

        assert "Part one" in text
        assert "Part two" in text
        assert "skip me" not in text

    def test_the_contributors_header_inside_the_container_is_excluded(self):
        """
        Genius خودش داخل همان div یک بلوکِ «۴ Contributors» + عنوان می‌گذارد و
        با data-exclude-from-selection علامتش می‌زند — دقیقاً مثل چیزی که وقتی
        کاربر متن را از خودِ سایت کپی می‌کند نادیده گرفته می‌شود.
        """
        html = (
            '<div data-lyrics-container="true">'
            '<div data-exclude-from-selection="true">'
            "<span>4 Contributors</span><h2>Barf Lyrics</h2>"
            "</div>"
            "واقعی متن آهنگ"
            "</div>"
        )

        assert genius._extract(html) == "واقعی متن آهنگ"

    def test_no_container_returns_none(self):
        assert genius._extract("<div>nothing here</div>") is None

    def test_excess_blank_lines_are_collapsed(self):
        html = '<div data-lyrics-container="true">A<br><br><br><br>B</div>'

        assert genius._extract(html) == "A\n\nB"


class _FakeClient:
    def __init__(self, handler):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, params=None, headers=None):
        return self._handler(url, params or {}, headers or {})


def _response(status: int, *, json_body=None, text: str = "") -> httpx.Response:
    request = httpx.Request("GET", "https://x.test")
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=request)
    return httpx.Response(status, text=text, request=request)


class TestFetch:
    @pytest.fixture(autouse=True)
    def token(self, monkeypatch):
        monkeypatch.setattr(config, "GENIUS_ACCESS_TOKEN", "test-token")

    def test_no_token_short_circuits_without_a_request(self, monkeypatch):
        monkeypatch.setattr(config, "GENIUS_ACCESS_TOKEN", None)
        monkeypatch.setattr(genius.httpx, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("should not connect")))

        assert genius.fetch("Barf", "Farhad", None, 0) is None

    def test_full_round_trip_returns_plain_lyrics(self, monkeypatch):
        search_body = {
            "response": {
                "hits": [
                    {
                        "result": {
                            "url": "https://genius.com/farhad-barf",
                            "lyrics_state": "complete",
                            "title": "Barf",
                            "primary_artist": {"name": "Farhad"},
                        }
                    }
                ]
            }
        }
        page_html = '<div data-lyrics-container="true">بارون که می‌باره<br>یاد تو می‌افتم</div>'

        def handler(url, params, headers):
            if url.endswith("/search"):
                assert headers.get("Authorization") == "Bearer test-token"
                return _response(200, json_body=search_body)
            assert url == "https://genius.com/farhad-barf"
            return _response(200, text=page_html)

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        found = genius.fetch("Barf", "Farhad", None, 0)

        assert found.plain == "بارون که می‌باره\nیاد تو می‌افتم"
        assert found.synced is None

    def test_a_multi_artist_name_falls_back_to_the_first_artist(self, monkeypatch):
        """
        Genius دنبالِ عینِ رشته می‌گردد: `q=«Akharin Nafas Tlkhoon, NoTsH»`
        صفر نتیجه می‌دهد و همان ترک با `q=«Akharin Nafas Tlkhoon»` پیدا می‌شود.
        بدون این تلاشِ دوم، هر ترکِ دونفره‌ای بی‌متن می‌ماند.
        """
        queries = []

        def handler(url, params, headers):
            if url.endswith("/search"):
                queries.append(params["q"])
                if "NoTsH" in params["q"]:
                    return _response(200, json_body={"response": {"hits": []}})
                return _response(
                    200,
                    json_body={
                        "response": {
                            "hits": [
                                {
                                    "result": {
                                        "url": "https://genius.com/tlkhoon-akharin-nafas",
                                        "lyrics_state": "complete",
                                        "title": "Akharin Nafas",
                                        "primary_artist": {"name": "Tlkhoon"},
                                    }
                                }
                            ]
                        }
                    },
                )
            return _response(200, text='<div data-lyrics-container="true">Akhen man boridam</div>')

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        found = genius.fetch("Akharin Nafas", "Tlkhoon, NoTsH", None, 0)

        assert found.plain == "Akhen man boridam"
        assert queries == ["Akharin Nafas Tlkhoon, NoTsH", "Akharin Nafas Tlkhoon"]

    def test_a_failed_search_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            genius.httpx, "Client", lambda **_: _FakeClient(lambda *a: _response(500))
        )

        assert genius.fetch("Barf", "Farhad", None, 0) is None

    def test_no_matching_hit_returns_none_without_fetching_a_page(self, monkeypatch):
        calls = []

        def handler(url, params, headers):
            calls.append(url)
            return _response(200, json_body={"response": {"hits": []}})

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        assert genius.fetch("Barf", "Farhad", None, 0) is None
        assert len(calls) == 1

    def test_network_error_is_swallowed(self, monkeypatch):
        def boom(**_):
            raise httpx.HTTPError("down")

        monkeypatch.setattr(genius.httpx, "Client", boom)

        assert genius.fetch("Barf", "Farhad", None, 0) is None

    def test_empty_title_returns_none(self):
        assert genius.fetch("", "Farhad", None, 0) is None


class TestSongInfo:
    @pytest.fixture(autouse=True)
    def token(self, monkeypatch):
        monkeypatch.setattr(config, "GENIUS_ACCESS_TOKEN", "test-token")

    def test_no_token_short_circuits_without_a_request(self, monkeypatch):
        monkeypatch.setattr(config, "GENIUS_ACCESS_TOKEN", None)
        monkeypatch.setattr(
            genius.httpx, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("should not connect"))
        )

        assert genius.song_info("Barf", "Farhad") is None

    def test_full_round_trip_returns_credits(self, monkeypatch):
        search_body = {
            "response": {
                "hits": [
                    {
                        "result": {
                            "id": 42,
                            "url": "https://genius.com/farhad-barf",
                            "lyrics_state": "complete",
                            "title": "Barf",
                            "primary_artist": {"name": "Farhad"},
                            "song_art_image_url": "https://images.genius.com/small.jpg",
                        }
                    }
                ]
            }
        }
        song_body = {
            "response": {
                "song": {
                    "writer_artists": [{"name": "Farhad Mehrad"}, {"name": "Someone Else"}],
                    "producer_artists": [{"name": "A Producer"}],
                    "album": {"name": "Barf"},
                    "release_date_for_display": "December 1, 1988",
                    "song_art_image_url": "https://images.genius.com/big.jpg",
                }
            }
        }

        def handler(url, params, headers):
            if url.endswith("/search"):
                assert headers.get("Authorization") == "Bearer test-token"
                return _response(200, json_body=search_body)
            assert url == "https://api.genius.com/songs/42"
            assert params.get("text_format") == "plain"
            return _response(200, json_body=song_body)

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        info = genius.song_info("Barf", "Farhad")

        assert info.writers == ["Farhad Mehrad", "Someone Else"]
        assert info.producers == ["A Producer"]
        assert info.album == "Barf"
        assert info.releaseDate == "December 1, 1988"
        assert info.artworkUrl == "https://images.genius.com/big.jpg"
        assert info.url == "https://genius.com/farhad-barf"

    def test_no_matching_hit_returns_none_without_fetching_details(self, monkeypatch):
        calls = []

        def handler(url, params, headers):
            calls.append(url)
            return _response(200, json_body={"response": {"hits": []}})

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        assert genius.song_info("Barf", "Farhad") is None
        assert len(calls) == 1

    def test_song_detail_failure_returns_none(self, monkeypatch):
        search_body = {
            "response": {
                "hits": [
                    {
                        "result": {
                            "id": 42,
                            "url": "https://genius.com/farhad-barf",
                            "lyrics_state": "complete",
                            "title": "Barf",
                            "primary_artist": {"name": "Farhad"},
                        }
                    }
                ]
            }
        }

        def handler(url, params, headers):
            if url.endswith("/search"):
                return _response(200, json_body=search_body)
            return _response(500)

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        assert genius.song_info("Barf", "Farhad") is None

    def test_network_error_is_swallowed(self, monkeypatch):
        def boom(**_):
            raise httpx.HTTPError("down")

        monkeypatch.setattr(genius.httpx, "Client", boom)

        assert genius.song_info("Barf", "Farhad") is None

    @pytest.mark.parametrize("status", [404, 429, 500, 503])
    def test_an_error_status_on_search_returns_none(self, monkeypatch, status):
        """
        `_search` از ۲B.0.1 به بعد به‌جای `[]` یک `ProviderError` می‌دهد. این
        مصرف‌کننده (`main.py:554` → `GET /api/songinfo`) قرارداد *قدیمیِ*
        خودش را دارد: هر خطایی `None` می‌شود، چون endpoint با ۴۰۴ جواب می‌دهد
        نه ۵۰۰. اگر ProviderError از اینجا درز کند، endpoint ۵۰۰ می‌دهد و
        کارتِ اطلاعاتِ بات به‌جای «چیزی پیدا نشد» می‌شکند.
        """

        def handler(url, params, headers):
            return _response(status)

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        assert genius.song_info("Barf", "Farhad") is None

    def test_a_timeout_on_search_returns_none(self, monkeypatch):
        def handler(url, params, headers):
            raise httpx.ConnectTimeout("timed out")

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        assert genius.song_info("Barf", "Farhad") is None

    def test_a_malformed_search_body_returns_none(self, monkeypatch):
        def handler(url, params, headers):
            return _response(200, text="{not json")

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        assert genius.song_info("Barf", "Farhad") is None

    def test_missing_credits_become_empty_lists(self, monkeypatch):
        search_body = {
            "response": {
                "hits": [
                    {
                        "result": {
                            "id": 7,
                            "url": "https://genius.com/x",
                            "lyrics_state": "complete",
                            "title": "Barf",
                            "primary_artist": {"name": "Farhad"},
                        }
                    }
                ]
            }
        }
        song_body = {"response": {"song": {}}}

        def handler(url, params, headers):
            if url.endswith("/search"):
                return _response(200, json_body=search_body)
            return _response(200, json_body=song_body)

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        info = genius.song_info("Barf", "Farhad")

        assert info.writers == []
        assert info.producers == []
        assert info.album is None


class TestEnabled:
    def test_true_when_token_is_set(self, monkeypatch):
        monkeypatch.setattr(config, "GENIUS_ACCESS_TOKEN", "x")
        assert genius.enabled() is True

    def test_false_without_a_token(self, monkeypatch):
        monkeypatch.setattr(config, "GENIUS_ACCESS_TOKEN", None)
        assert genius.enabled() is False


class TestVersionWordPenalty:
    """
    Genius از یک عنوان چند نسخه دارد: استودیو، لایو، ریمیکس، آکوستیک. قبلاً
    همپوشانیِ کلمات کافی بود، پس ترکِ «Barf» می‌توانست با «Barf (Live)» بخورد
    — دو خط اول یکی‌اند ولی بقیه‌ی متن نه.

    فیلدِ مدت در پاسخ‌های `/search` گینس وجود ندارد، پس تنها سیگنالِ «این نسخه‌ی
    دیگری‌ست» خودِ کلمه‌ی نسخه در عنوان است.
    """

    # «(Remastered)» عمداً اینجا نیست: ریمستر همان ضبط است و متنش هم همان است
    _HARD_VERSION_WORDS = ("live", "remix", "acoustic", "unplugged", "instrumental")

    @pytest.mark.parametrize("marker", _HARD_VERSION_WORDS)
    def test_a_marked_version_is_rejected_when_a_plain_title_exists(self, marker):
        hits = [
            _hit(f"Barf ({marker})", "Farhad", "https://genius.com/version"),
            _hit("Barf", "Farhad", "https://genius.com/studio"),
        ]

        assert genius._best_url(hits, "Barf", "Farhad") == "https://genius.com/studio"

    @pytest.mark.parametrize("marker", _HARD_VERSION_WORDS)
    def test_a_marked_version_is_still_used_when_it_is_all_genius_has(self, marker):
        """رد کردنِ نسخه‌ی تنها یعنی هیچ متنی — و متنی با برچسبِ نسخه بهتر از
        هیچ است، چون کاربر دست‌کم متن را می‌بیند و خودش می‌فهمد کدام نسخه است."""
        hits = [_hit(f"Barf ({marker})", "Farhad", "https://genius.com/only")]

        assert genius._best_url(hits, "Barf", "Farhad") == "https://genius.com/only"

    def test_a_remastered_version_is_not_penalised(self):
        """ریمستر همان ضبط است؛ متنش عوض نشده. جریمه‌کردنش یعنی از دست دادنِ
        نسخه‌ی درست در کاتالوگی که فقط همین را دارد."""
        hits = [
            _hit("Barf (Remastered)", "Farhad", "https://genius.com/remaster"),
            _hit("Barf", "Farhad", "https://genius.com/plain"),
        ]

        # هر دو پذیرفتنی‌اند؛ مهم این است که ریمستر حذف نمی‌شود
        assert genius._best_url(hits, "Barf", "Farhad") in (
            "https://genius.com/remaster",
            "https://genius.com/plain",
        )

    def test_a_version_marker_in_the_wanted_title_is_not_a_penalty(self):
        """وقتی کاربر خودش نسخه‌ی لایو را می‌خواهد، نسخه‌ی لایو درست است نه
        نسخه‌ی استودیو. قاعده باید نسبت به عنوانِ درخواستی بسنجد، نه مطلق."""
        hits = [
            _hit("Barf (Live)", "Farhad", "https://genius.com/live"),
            _hit("Barf", "Farhad", "https://genius.com/studio"),
        ]

        assert genius._best_url(hits, "Barf (Live)", "Farhad") == "https://genius.com/live"


class TestDurationIsNotASignal:
    """
    `/search` گینس مدت نمی‌دهد و `/songs/{id}` هم فقط متن و اعتبار می‌دهد.
    این تست‌ها قفل می‌کنند که امضای `duration_ms` بدونِ اینکه بی‌دلیل بشکند
    باقی بماند و نبود/خرابیِ مدت باعث شکستِ تطبیق نشود.
    """

    def test_a_zero_duration_still_matches(self, monkeypatch):
        monkeypatch.setattr(config, "GENIUS_ACCESS_TOKEN", "test-token")

        def handler(url, params, headers):
            if url.endswith("/search"):
                return _response(200, json_body={"response": {"hits": [_hit("Barf", "Farhad", "https://genius.com/barf")]}})
            return _response(200, text='<div data-lyrics-container="true">line</div>')

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        assert genius.fetch("Barf", "Farhad", None, 0) is not None

    def test_a_garbage_duration_does_not_break_matching(self, monkeypatch):
        monkeypatch.setattr(config, "GENIUS_ACCESS_TOKEN", "test-token")

        def handler(url, params, headers):
            if url.endswith("/search"):
                return _response(200, json_body={"response": {"hits": [_hit("Barf", "Farhad", "https://genius.com/barf")]}})
            return _response(200, text='<div data-lyrics-container="true">line</div>')

        monkeypatch.setattr(genius.httpx, "Client", lambda **_: _FakeClient(handler))

        assert genius.fetch("Barf", "Farhad", None, -1) is not None

    def test_the_search_hit_body_is_used_verbatim(self):
        """هر فیلدِ اضافه‌ای که فرض کرده بودیم در hit هست، نباید لازم باشد."""
        hit = _hit("Barf", "Farhad", "https://genius.com/barf")
        assert "duration" not in hit["result"]

        assert genius._best_url([hit], "Barf", "Farhad") == "https://genius.com/barf"
