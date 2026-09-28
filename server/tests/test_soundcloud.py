"""
آلبومِ ساندکلاد بدون «ناشناس».

استخراج تختِ yt-dlp روی یک «ست» ساندکلاد فقط شناسه و لینک ترک‌ها را می‌دهد —
نه عنوان، نه مدت، نه کاور. اینجا قفل می‌کنیم که آن سوراخ با api-v2 پر شود و اگر
حتی api هم نبود، باز هم چیزی جز عنوانِ خالی به فرانت نرسد.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers import soundcloud, ytdlp


def _row(track_id: int, title: str, **extra) -> dict:
    return {
        "id": track_id,
        "title": title,
        "duration": 200_000,
        "permalink_url": f"https://soundcloud.com/dorcci/{title.lower()}",
        "artwork_url": "https://i1.sndcdn.com/artworks-abc-large.jpg",
        "user": {"username": "Dorcci"},
        **extra,
    }


def _flat_entry(track_id: int, slug: str) -> dict:
    """همان چیزی که extract_flat برای یک ست ساندکلاد می‌دهد — تقریباً هیچ."""
    return {
        "_type": "url_transparent",
        "ie_key": "Soundcloud",
        "id": str(track_id),
        "url": f"https://soundcloud.com/dorcci/{slug}",
        "album": "YOUNG MORVARID",
    }


@pytest.fixture(autouse=True)
def no_cached_client_id(monkeypatch):
    """client_id ماژول بین تست‌ها نشت نکند."""
    monkeypatch.setattr(soundcloud, "_cached_id", None)


class TestMapping:
    def test_api_row_becomes_a_named_track(self):
        entry = soundcloud.as_entry(_row(1, "GONAH"))
        track = ytdlp._entry_to_track(entry, "soundcloud", "YOUNG MORVARID")

        assert track.title == "GONAH"
        assert track.artist == "Dorcci"
        assert track.durationMs == 200_000
        assert track.album == "YOUNG MORVARID"

    def test_duration_comes_in_milliseconds(self):
        """api-v2 میلی‌ثانیه می‌دهد و entryهای yt-dlp ثانیه — جای اشتباهِ هزاربرابری."""
        assert soundcloud.as_entry(_row(1, "GONAH", duration=136_767))["duration"] == 136.767

    def test_publisher_artist_wins_over_the_uploader(self):
        """آپلودکننده می‌تواند لیبل باشد؛ ناشر، خودِ هنرمند است."""
        row = _row(1, "GONAH", publisher_metadata={"artist": "Dorcci"}, user={"username": "Some Label"})

        assert soundcloud.as_entry(row)["artist"] == "Dorcci"

    def test_artwork_is_upgraded_from_the_thumbnail_size(self):
        """large یعنی ۱۰۰ پیکسل — روی کاور آلبوم لک می‌شود."""
        art = soundcloud.as_entry(_row(1, "GONAH"))["thumbnail"]

        assert art == "https://i1.sndcdn.com/artworks-abc-t500x500.jpg"

    def test_artwork_falls_back_to_the_avatar(self):
        row = _row(1, "GONAH", artwork_url=None)
        row["user"]["avatar_url"] = "https://i1.sndcdn.com/avatars-xyz-large.jpg"

        assert soundcloud.as_entry(row)["thumbnail"] == "https://i1.sndcdn.com/avatars-xyz-t500x500.jpg"


def _user_row(user_id: int, username: str, **extra) -> dict:
    return {
        "id": user_id,
        "username": username,
        "permalink_url": f"https://soundcloud.com/{username.lower()}",
        "avatar_url": "https://i1.sndcdn.com/avatars-xyz-large.jpg",
        "followers_count": 12_300,
        "track_count": 41,
        **extra,
    }


def _set_row(set_id: int, title: str, **extra) -> dict:
    return {
        "id": set_id,
        "title": title,
        "permalink_url": f"https://soundcloud.com/dorcci/sets/{title.lower()}",
        "release_date": "2025-02-01T00:00:00Z",
        "track_count": 9,
        "artwork_url": "https://i1.sndcdn.com/artworks-abc-large.jpg",
        "user": {"username": "Dorcci"},
        **extra,
    }


class TestUserSearch:
    """
    کاربر — چیزی که در ساندکلاد جای «هنرمند» را می‌گیرد. ساندکلاد بین هنرمند و
    شنونده تفکیکی ندارد، پس بعضی نتایج آپلودکننده‌ی ساده‌اند.
    """

    _user = staticmethod(_user_row)

    def _search(self, monkeypatch, rows: list[dict]):
        monkeypatch.setattr(soundcloud, "_search", lambda path, query, limit: rows)

    def test_a_user_row_becomes_an_artist(self, monkeypatch):
        self._search(monkeypatch, [self._user(9, "Dorcci")])

        artist = soundcloud.search_users("dorcci")[0]

        assert artist.id == "sc:artist:9"
        assert artist.name == "Dorcci"
        assert artist.source == "soundcloud"
        assert artist.sourceUrl == "https://soundcloud.com/dorcci"
        assert artist.subtitle == "12,300 دنبال‌کننده"
        # آواتارِ ۱۰۰ پیکسلی روی کارت لک می‌شود
        assert artist.artworkUrl == "https://i1.sndcdn.com/avatars-xyz-t500x500.jpg"

    def test_a_user_without_followers_falls_back_to_the_track_count(self, monkeypatch):
        self._search(monkeypatch, [self._user(9, "Dorcci", followers_count=0)])

        assert soundcloud.search_users("dorcci")[0].subtitle == "41 آهنگ"

    def test_the_default_avatar_is_dropped(self, monkeypatch):
        """
        آواتارِ پیش‌فرض برای همه یکسان است — با None، فرانت حرفِ اول نام را با
        رنگِ پایدارِ خودش می‌گذارد که از یک آدمکِ تکراری خواناتر است.
        """
        row = self._user(9, "Dorcci", avatar_url="https://a1.sndcdn.com/images/default_avatar_large.png")
        self._search(monkeypatch, [row])

        assert soundcloud.search_users("dorcci")[0].artworkUrl is None

    def test_a_user_without_a_page_is_skipped(self, monkeypatch):
        """بی‌لینک یعنی کارتی که هیچ جا باز نمی‌شود."""
        self._search(monkeypatch, [{"id": 9, "username": "Dorcci"}, self._user(10, "Real")])

        assert [a.name for a in soundcloud.search_users("dorcci")] == ["Real"]

    def test_a_listener_with_no_tracks_is_skipped(self, monkeypatch):
        """
        ساندکلاد بین هنرمند و شنونده تفکیک ندارد و نتیجه پر از حسابِ شنونده است.
        کارتِ یک شنونده‌ی هم‌نام فقط به صفحه‌ی خالی می‌رسید — دقیقاً همان چیزی که
        برای «farhad mehrad» می‌دیدیم.
        """
        rows = [self._user(9, "Farhad Mehrad", track_count=0), self._user(10, "Real")]
        self._search(monkeypatch, rows)

        assert [a.name for a in soundcloud.search_users("farhad mehrad")] == ["Real"]


class TestArtistPage:
    """
    صفحه‌ی هنرمندِ ساندکلاد — چون کارتِ ساندکلاد در نتایج جستجو هم به همین‌جا
    می‌رسد، نه به یک لینکِ بیرونی.
    """

    @staticmethod
    def _api(monkeypatch, bodies: dict):
        def fake(path, **params):
            body = bodies.get(path)
            if isinstance(body, BaseException):
                raise body
            return body

        monkeypatch.setattr(soundcloud, "_api", fake)

    def test_the_page_has_a_head_tracks_and_albums(self, monkeypatch):
        self._api(
            monkeypatch,
            {
                "/users/9": _user_row(9, "Dorcci"),
                "/users/9/tracks": [_row(11, "GONAH")],
                "/users/9/albums": {
                    "collection": [
                        _set_row(21, "YOUNG MORVARID", release_date="2023-01-01T00:00:00Z"),
                        _set_row(22, "GONAH"),
                    ]
                },
            },
        )

        detail = ytdlp.soundcloud_artist("9")

        assert detail.id == "sc:artist:9"
        assert detail.subtitle == "12,300 دنبال‌کننده"
        assert [t.title for t in detail.topTracks] == ["GONAH"]
        assert [t.artist for t in detail.topTracks] == ["Dorcci"]
        # تازه‌ترین اول، مثل بقیه‌ی صفحه‌های هنرمند
        assert [a.title for a in detail.albums] == ["GONAH", "YOUNG MORVARID"]
        assert [a.releaseType for a in detail.albums] == ["album", "album"]

    def test_an_empty_set_is_not_listed(self, monkeypatch):
        """ستِ ساخته‌شده و پرنشده، کارتی است که باز کردنش به صفحه‌ی خالی می‌رسد."""
        self._api(
            monkeypatch,
            {
                "/users/9": _user_row(9, "Dorcci"),
                "/users/9/tracks": [],
                "/users/9/albums": {"collection": [_set_row(21, "EMPTY", track_count=0)]},
            },
        )

        assert ytdlp.soundcloud_artist("9").albums == []

    def test_a_dead_track_list_still_opens_the_page(self, monkeypatch):
        """یک کاربرِ بی‌آلبوم هم صفحه دارد؛ نامش و آواتارش از سرِ صفحه می‌آیند."""
        self._api(
            monkeypatch,
            {
                "/users/9": _user_row(9, "Dorcci"),
                "/users/9/tracks": httpx.HTTPError("down"),
                "/users/9/albums": httpx.HTTPError("down"),
            },
        )

        detail = ytdlp.soundcloud_artist("9")

        assert detail.name == "Dorcci"
        assert detail.topTracks == [] and detail.albums == []

    def test_a_missing_user_is_none(self, monkeypatch):
        self._api(monkeypatch, {"/users/9": {}})

        assert ytdlp.soundcloud_artist("9") is None

    def test_top_tracks_request_uses_soundcloud_hotness_order(self, monkeypatch):
        seen: list[tuple[str, dict]] = []

        def fake(path, **params):
            seen.append((path, params))
            return [_row(11, "GONAH", playback_count=900)]

        monkeypatch.setattr(soundcloud, "_collection", fake)

        rows = soundcloud.user_top_tracks("9", limit=20)

        assert [row["title"] for row in rows] == ["GONAH"]
        assert seen == [("/users/9/tracks", {"limit": 20, "order": "hotness"})]

    def test_a_blocked_track_is_left_out(self, monkeypatch):
        """BLOCK یعنی از همین IP پخش نمی‌شود — همان IP ای که دانلود هم از آن می‌رود."""
        self._api(
            monkeypatch,
            {
                "/users/9": _user_row(9, "Dorcci"),
                "/users/9/tracks": [_row(11, "GONAH", policy="BLOCK"), _row(12, "EDGEBAR")],
                "/users/9/albums": {"collection": []},
            },
        )

        assert [t.title for t in ytdlp.soundcloud_artist("9").topTracks] == ["EDGEBAR"]

    def test_top_tracks_are_ordered_by_plays_not_recency(self, monkeypatch):
        """صفحه‌ی هنرمند ساندکلاد محبوب می‌چیند، نه تازه‌به‌قدیمِ تبِ Tracks."""
        self._api(
            monkeypatch,
            {
                "/users/9": _user_row(9, "Dorcci"),
                "/users/9/tracks": [
                    _row(11, "WIND", playback_count=12),
                    _row(12, "GONAH", playback_count=900),
                ],
                "/users/9/albums": {"collection": []},
            },
        )

        assert [t.title for t in ytdlp.soundcloud_artist("9").topTracks] == ["GONAH", "WIND"]

    def test_a_standalone_track_lands_in_singles(self, monkeypatch):
        """ترکِ تکی ست نیست؛ بدون این، Singles & EP خالی می‌ماند."""
        self._api(
            monkeypatch,
            {
                "/users/9": _user_row(9, "Dorcci"),
                "/users/9/tracks": [
                    _row(
                        11,
                        "WIND",
                        publisher_metadata={"album_title": "WIND - Single"},
                        release_date="2026-01-01T00:00:00Z",
                    ),
                    _row(
                        12,
                        "GONAH",
                        publisher_metadata={"album_title": "GONAH"},
                        release_date="2025-02-01T00:00:00Z",
                    ),
                    _row(
                        13,
                        "BOY",
                        publisher_metadata={"album_title": "YOUNG MORVARID"},
                        release_date="2025-01-01T00:00:00Z",
                    ),
                ],
                "/users/9/albums": {
                    "collection": [
                        _set_row(21, "YOUNG MORVARID", track_count=12, release_date="2025-01-01T00:00:00Z"),
                        _set_row(22, "GONAH", track_count=1, release_date="2025-02-01T00:00:00Z"),
                    ]
                },
            },
        )

        albums = ytdlp.soundcloud_artist("9").albums

        assert [a.title for a in albums] == ["WIND", "GONAH", "YOUNG MORVARID"]
        assert [a.releaseType for a in albums] == ["single", "single", "album"]
        # ترکِ هم‌نام با ست دوباره نمی‌آید
        assert [a.id for a in albums if a.title == "GONAH"] == ["sc:playlist:22"]

    def test_a_short_set_is_an_ep(self, monkeypatch):
        self._api(
            monkeypatch,
            {
                "/users/9": _user_row(9, "Dorcci"),
                "/users/9/tracks": [],
                "/users/9/albums": {
                    "collection": [_set_row(21, "NIGHT EP", track_count=4)]
                },
            },
        )

        assert ytdlp.soundcloud_artist("9").albums[0].releaseType == "ep"


class TestLikesAndReposts:
    """
    آهنگ‌هایی که خودِ کاربر لایک یا ریپست کرده — همان دو تبِ Likes و Reposts در
    صفحه‌ی ساندکلاد. هر دو زیرِ کلیدِ `_paged` جمع می‌شوند و ترک/پلی‌لیست را
    قاطی برمی‌گردانند، هرکدام زیرِ کلیدِ خودشان.
    """

    def _paged(self, monkeypatch, bodies: dict):
        def fake(path, limit):
            return bodies.get(path, [])

        monkeypatch.setattr(soundcloud, "_paged", fake)

    def test_the_right_endpoint_is_used_for_each_tab(self, monkeypatch):
        """ریپست زیرِ `/users/{id}/reposts` ۴۰۴ می‌دهد؛ فیدش از `/stream/...` است."""
        seen: list[str] = []
        monkeypatch.setattr(soundcloud, "_paged", lambda path, limit: seen.append(path) or [])

        soundcloud.user_likes("9")
        soundcloud.user_reposts("9")

        assert seen == ["/users/9/likes", "/stream/users/9/reposts"]

    def test_liked_tracks_are_unwrapped(self, monkeypatch):
        self._paged(monkeypatch, {"/users/9/likes": [{"kind": "like", "track": _row(11, "GONAH")}]})

        entries = soundcloud.user_likes("9")

        assert [e["title"] for e in entries] == ["GONAH"]

    def test_a_liked_playlist_is_skipped(self, monkeypatch):
        """پلی‌لیستِ لایک‌شده جای دیگری نشان داده می‌شود، نه در فهرستِ ترک‌ها."""
        self._paged(
            monkeypatch,
            {
                "/users/9/likes": [
                    {"kind": "like", "playlist": {"id": 5, "title": "A Set"}},
                    {"kind": "like", "track": _row(11, "GONAH")},
                ]
            },
        )

        assert [e["title"] for e in soundcloud.user_likes("9")] == ["GONAH"]

    def test_reposted_tracks_are_unwrapped(self, monkeypatch):
        self._paged(
            monkeypatch,
            {
                "/stream/users/9/reposts": [
                    {"type": "track-repost", "track": _row(11, "GONAH")},
                    {"type": "playlist-repost", "playlist": {"id": 5, "title": "A Set"}},
                ]
            },
        )

        assert [e["title"] for e in soundcloud.user_reposts("9")] == ["GONAH"]

    def test_a_blocked_liked_track_is_left_out(self, monkeypatch):
        self._paged(
            monkeypatch,
            {
                "/users/9/likes": [
                    {"kind": "like", "track": _row(11, "GONAH", policy="BLOCK")},
                    {"kind": "like", "track": _row(12, "EDGEBAR")},
                ]
            },
        )

        assert [e["title"] for e in soundcloud.user_likes("9")] == ["EDGEBAR"]


class TestPaged:
    """
    لایک‌ها و ریپست‌ها با `limit` قانع نمی‌شوند و باید دنبالِ `next_href` رفت —
    وگرنه یک هنرمندِ واقعی با ۱۶۰+ لایک فقط ۳۳ تای اول را نشان می‌داد.
    """

    @staticmethod
    def _fake_http(monkeypatch, handler):
        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def get(self, url, params=None):
                return handler(url, params or {})

        monkeypatch.setattr(soundcloud, "_http", FakeClient)
        monkeypatch.setattr(soundcloud, "_cached_id", "c" * 32)

    @staticmethod
    def _json(url: str, body: dict) -> httpx.Response:
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    def test_next_href_is_followed_until_the_limit_is_reached(self, monkeypatch):
        first = "https://api-v2.soundcloud.com/users/9/likes"
        second = "https://api-v2.soundcloud.com/users/9/likes?offset=abc"
        pages = {
            first: {"collection": [{"track": _row(1, "A")}, {"track": _row(2, "B")}], "next_href": second},
            second: {"collection": [{"track": _row(3, "C")}, {"track": _row(4, "D")}], "next_href": None},
        }

        self._fake_http(monkeypatch, lambda url, params: self._json(url, pages[url]))

        rows = soundcloud._paged("/users/9/likes", limit=3)

        # سه‌تا خواسته بودیم؛ صفحه‌ی دوم دو تا آورد ولی فقط اولی‌اش لازم بود
        assert [r["track"]["title"] for r in rows] == ["A", "B", "C"]

    def test_it_stops_when_a_page_comes_back_empty(self, monkeypatch):
        """`next_href` گاهی حتی روی آخرین صفحه هم پر است؛ صفحه‌ی خالی باید بس کند."""
        self._fake_http(
            monkeypatch,
            lambda url, params: self._json(
                url, {"collection": [], "next_href": "https://api-v2.soundcloud.com/x?offset=1"}
            ),
        )

        assert soundcloud._paged("/users/9/likes", limit=10) == []

    def test_a_page_that_gives_fewer_than_asked_still_continues(self, monkeypatch):
        """فیدِ ریپست همیشه پنج‌تاپنج‌تا می‌دهد، حتی وقتی `limit` خیلی بزرگ‌تر است."""
        first = "https://api-v2.soundcloud.com/stream/users/9/reposts"
        second = "https://api-v2.soundcloud.com/stream/users/9/reposts?offset=abc"
        pages = {
            first: {"collection": [{"track": _row(1, "A")}], "next_href": second},
            second: {"collection": [{"track": _row(2, "B")}], "next_href": None},
        }

        self._fake_http(monkeypatch, lambda url, params: self._json(url, pages[url]))

        rows = soundcloud._paged("/stream/users/9/reposts", limit=20)

        assert [r["track"]["title"] for r in rows] == ["A", "B"]

    def test_a_next_href_that_repeats_the_same_page_does_not_duplicate_items(self, monkeypatch):
        """
        فیدِ واقعیِ ریپست وقتی تمام می‌شود، همان صفحه‌ی آخر را دوباره و دوباره
        با `next_href` پر می‌دهد — دقیقاً همان چیزی که پنج ریپستِ یک هنرمند را
        در خروجی پنجاه‌تا نشان می‌داد.
        """
        first = "https://api-v2.soundcloud.com/stream/users/9/reposts"
        last = "https://api-v2.soundcloud.com/stream/users/9/reposts?offset=end"
        pages = {
            first: {"collection": [{"track": _row(1, "A")}], "next_href": last},
            last: {"collection": [{"track": _row(1, "A")}], "next_href": last},
        }

        self._fake_http(monkeypatch, lambda url, params: self._json(url, pages[url]))

        rows = soundcloud._paged("/stream/users/9/reposts", limit=50)

        assert [r["track"]["title"] for r in rows] == ["A"]

    def test_a_next_href_that_wraps_back_to_the_start_does_not_duplicate_items(self, monkeypatch):
        """
        لایک‌ها به‌جای تکرارِ همان صفحه، گاهی از سرِ لیست شروع می‌کنند — با یک
        `next_href` تازه ولی همان شناسه‌های قبلی. نتیجه باید فقط یک‌بار بماند.
        """
        first = "https://api-v2.soundcloud.com/users/9/likes"
        wraps_to_start = "https://api-v2.soundcloud.com/users/9/likes?offset=wrap"
        pages = {
            first: {
                "collection": [{"track": _row(1, "A")}, {"track": _row(2, "B")}],
                "next_href": wraps_to_start,
            },
            wraps_to_start: {
                "collection": [{"track": _row(1, "A")}, {"track": _row(2, "B")}],
                "next_href": first,
            },
        }

        self._fake_http(monkeypatch, lambda url, params: self._json(url, pages[url]))

        rows = soundcloud._paged("/users/9/likes", limit=50)

        assert [r["track"]["title"] for r in rows] == ["A", "B"]


class TestArtistPageLikesAndReposts:
    """`soundcloud_artist` سرِ صفحه، ترک‌ها، آلبوم‌ها، لایک‌ها و ریپست‌ها را یکی می‌کند."""

    @staticmethod
    def _api(monkeypatch, bodies: dict):
        def fake(path, **params):
            body = bodies.get(path)
            if isinstance(body, BaseException):
                raise body
            return body

        monkeypatch.setattr(soundcloud, "_api", fake)

    @staticmethod
    def _paged(monkeypatch, bodies: dict):
        """لایک‌ها و ریپست‌ها از `_paged` می‌آیند، نه از `_api` — جدا مسیر می‌روند."""

        def fake(path, limit):
            body = bodies.get(path, [])
            if isinstance(body, BaseException):
                raise body
            return body

        monkeypatch.setattr(soundcloud, "_paged", fake)

    def test_liked_and_reposted_tracks_show_up_on_the_artist_page(self, monkeypatch):
        self._api(
            monkeypatch,
            {
                "/users/9": _user_row(9, "Dorcci"),
                "/users/9/tracks": [],
                "/users/9/albums": {"collection": []},
            },
        )
        self._paged(
            monkeypatch,
            {
                "/users/9/likes": [{"kind": "like", "track": _row(11, "LIKED", user={"username": "Other"})}],
                "/stream/users/9/reposts": [
                    {"type": "track-repost", "track": _row(12, "REPOSTED", user={"username": "Someone Else"})}
                ],
            },
        )

        detail = ytdlp.soundcloud_artist("9")

        assert [t.title for t in detail.likedTracks] == ["LIKED"]
        assert [t.title for t in detail.repostedTracks] == ["REPOSTED"]

    def test_a_dead_likes_or_reposts_endpoint_still_opens_the_page(self, monkeypatch):
        self._api(
            monkeypatch,
            {
                "/users/9": _user_row(9, "Dorcci"),
                "/users/9/tracks": [],
                "/users/9/albums": {"collection": []},
            },
        )
        self._paged(
            monkeypatch,
            {
                "/users/9/likes": httpx.HTTPError("down"),
                "/stream/users/9/reposts": httpx.HTTPError("down"),
            },
        )

        detail = ytdlp.soundcloud_artist("9")

        assert detail.name == "Dorcci"
        assert detail.likedTracks == [] and detail.repostedTracks == []


class TestHydrate:
    def test_flat_entries_get_their_names(self, monkeypatch):
        monkeypatch.setattr(
            soundcloud, "tracks", lambda ids, hint=None: {"11": _row(11, "GONAH")}
        )

        entries = soundcloud.hydrate([_flat_entry(11, "gonah")])

        assert entries[0]["title"] == "GONAH"
        assert entries[0]["uploader"] == "Dorcci"

    def test_fully_populated_entries_are_left_alone(self, monkeypatch):
        """وقتی عنوان و آپلودکننده هر دو هستند، نباید بی‌خود api بزنیم."""
        called = []
        monkeypatch.setattr(soundcloud, "tracks", lambda ids, hint=None: called.append(ids) or {})

        entries = soundcloud.hydrate([{"id": "11", "title": "GONAH", "uploader": "Dorcci"}])

        assert not called
        assert entries[0]["title"] == "GONAH"

    def test_entries_with_a_title_but_no_uploader_still_get_hydrated(self, monkeypatch):
        """
        استخراج تختِ صفحه‌ی «همه‌ی ترک‌ها»ی یک کاربر عنوان می‌دهد ولی آپلودکننده
        نه — دقیقاً همان چیزی که هر ترکِ صفحه‌ی هنرمند را «ناشناس» نشان می‌داد.
        """
        monkeypatch.setattr(
            soundcloud, "tracks", lambda ids, hint=None: {"11": _row(11, "GONAH")}
        )

        entries = soundcloud.hydrate([{"id": "11", "title": "GONAH", "uploader": None}])

        assert entries[0]["uploader"] == "Dorcci"

    def test_a_dead_api_does_not_kill_the_album(self, monkeypatch):
        def boom(ids, hint=None):
            raise httpx.HTTPError("down")

        monkeypatch.setattr(soundcloud, "tracks", boom)

        entries = soundcloud.hydrate([_flat_entry(11, "gonah")])
        track = ytdlp._entry_to_track(entries[0], "soundcloud", "YOUNG MORVARID")

        # اسلاگِ لینک تنها چیزی است که مانده — از عنوانِ خالی بهتر است
        assert track.title == "gonah"
        assert track.sourceUrl == "https://soundcloud.com/dorcci/gonah"


class TestClientId:
    """client_id عمر دارد. وقتی سوخت باید تازه‌اش را بگیریم، نه اینکه آلبوم بمیرد."""

    @staticmethod
    def _fake_http(monkeypatch, handler):
        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def get(self, url, params=None):
                return handler(url, params or {})

        monkeypatch.setattr(soundcloud, "_http", FakeClient)

    def _response(self, url, status, json_body=None, text=""):
        request = httpx.Request("GET", url)
        res = httpx.Response(status, json=json_body, request=request) if json_body is not None \
            else httpx.Response(status, text=text, request=request)
        return res

    def test_an_expired_id_is_replaced_by_a_scraped_one(self, monkeypatch):
        fresh = "f" * 32
        seen: list[str] = []

        def handler(url, params):
            if url.endswith("/tracks"):
                seen.append(params["client_id"])
                if params["client_id"] == "stale":
                    return self._response(url, 401, text="")
                return self._response(url, 200, json_body=[_row(11, "GONAH")])
            if url == "https://soundcloud.com/":
                return self._response(url, 200, text='<script src="https://a.sndcdn.com/app.js">')
            return self._response(url, 200, text=f'client_id:"{fresh}"')

        self._fake_http(monkeypatch, handler)

        rows = soundcloud.tracks(["11"], hint="stale")

        assert seen == ["stale", fresh]
        assert rows["11"]["title"] == "GONAH"
        # دفعه‌ی بعد از همان تازه شروع می‌کنیم
        assert soundcloud._cached_id == fresh

    def test_ids_are_sent_in_batches(self, monkeypatch):
        batches: list[int] = []

        def handler(url, params):
            batches.append(len(params["ids"].split(",")))
            return self._response(url, 200, json_body=[])

        self._fake_http(monkeypatch, handler)

        soundcloud.tracks([str(i) for i in range(120)], hint="ok")

        assert batches == [50, 50, 20]


class TestSoundcloudSetExtract:
    def test_artist_set_with_playlist_set_type_is_recognized_as_album(self, monkeypatch):
        from types import SimpleNamespace

        class FakeYDL:
            def __init__(self, opts):
                self.cache = SimpleNamespace(load=lambda *args: None)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=False):
                return {
                    "id": "2304743880",
                    "title": "FUCK MUSIC",
                    "uploader": "Mvshreghi",
                    "uploader_id": "12345",
                    "webpage_url": "https://soundcloud.com/mvshreghi/sets/fuck-music",
                    "set_type": "playlist",
                    "entries": [
                        {
                            "id": "1",
                            "title": "Mvshreghi - Track 1",
                            "uploader": "Mvshreghi",
                            "duration": 180,
                            "webpage_url": "https://soundcloud.com/mvshreghi/track-1",
                        },
                        {
                            "id": "2",
                            "title": "Mvshreghi, Guest - Track 2",
                            "uploader": "Mvshreghi",
                            "duration": 200,
                            "webpage_url": "https://soundcloud.com/mvshreghi/track-2",
                        },
                    ],
                }

        monkeypatch.setattr(ytdlp, "YoutubeDL", FakeYDL)
        detail = ytdlp.extract("https://soundcloud.com/mvshreghi/sets/fuck-music")

        assert detail is not None
        assert detail.title == "FUCK MUSIC"
        assert detail.artist == "Mvshreghi"
        assert detail.releaseType == "ep"  # 2 tracks => ep
        # تگ‌های آلبوم روی همه‌ی ترک‌ها نشسته‌اند
        assert [t.album for t in detail.tracks] == ["FUCK MUSIC", "FUCK MUSIC"]
        assert [t.albumArtist for t in detail.tracks] == ["Mvshreghi", "Mvshreghi"]
        assert [t.trackNumber for t in detail.tracks] == [1, 2]


class TestCatalogResolveScPlaylist:
    def test_sc_playlist_id_resolves_via_permalink(self, monkeypatch):
        import asyncio
        from app import catalog

        monkeypatch.setattr(
            soundcloud, "_api",
            lambda path, **kwargs: {"permalink_url": "https://soundcloud.com/mvshreghi/sets/fuck-music"}
            if path == "/playlists/2304743880" else None
        )
        monkeypatch.setattr(ytdlp, "extract", lambda url: "resolved-detail")

        client = httpx.AsyncClient()
        res = asyncio.run(catalog.resolve_ref(client, "sc:playlist:2304743880"))
        assert res == "resolved-detail"

