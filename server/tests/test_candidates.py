"""
انتخاب دستی نسخه.

`resolve` برای ماشین است و آستانه دارد؛ `browse` برای آدمی است که آن آستانه
اشتباه تصمیم گرفته. فرقشان عمدی است و همین‌جا قفل می‌شود.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import HTTPException

from app import jobs, main, resolver
from app.models import CandidateRequest


@pytest.fixture
def fake_search(monkeypatch):
    """
    جستجوی تقلبی. `queries` نشان می‌دهد کدام منابع واقعاً زده شده‌اند —
    ساندکلاد نباید بی‌درخواست زده شود.
    """
    queries: list[str] = []

    def factory(entries: list[dict]):
        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def extract_info(self, query, download=False):
                queries.append(query)
                return {"entries": entries}

        monkeypatch.setattr(resolver, "YoutubeDL", FakeYDL)
        monkeypatch.setattr(resolver, "_search_youtube_music", lambda *a, **kw: [])
        return queries

    return factory


@pytest.fixture
def fake_search_by_query(monkeypatch):
    """
    جستجوی تقلبی که هر کوئری نتیجه‌ی خودش را دارد.

    `fake_search` برای هر کوئری یک چیز برمی‌گرداند و برای تستِ *امتیازدهی* بس
    است؛ اینجا خودِ کوئری موضوع تست است، پس باید فرق کوئری‌ها دیده شود.
    """
    queries: list[str] = []

    def factory(results: dict[str, list[dict]]):
        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def extract_info(self, query, download=False):
                queries.append(query)
                return {"entries": results.get(query.split(":", 1)[1], [])}

        monkeypatch.setattr(resolver, "YoutubeDL", FakeYDL)
        monkeypatch.setattr(resolver, "_search_youtube_music", lambda *a, **kw: [])
        return queries

    return factory


def _entry(title: str, uploader: str = "Some Channel", seconds: int = 185) -> dict:
    return {
        "title": title,
        "uploader": uploader,
        "duration": seconds,
        "webpage_url": f"https://youtu.be/{abs(hash(title)) % 10**8}",
    }


class TestBrowse:
    def test_low_scores_survive(self, track, fake_search):
        """
        resolver زیر آستانه ترجیح می‌دهد شکست بخورد تا فایل اشتباه بدهد. ولی
        وقتی کاربر به این لیست می‌آید یعنی همان شکست اتفاق افتاده — پس اینجا
        همه‌چیز نشان داده می‌شود و تصمیم با اوست.
        """
        fake_search([_entry("چیزی کاملاً بی‌ربط", "Random", 20)])

        assert resolver.resolve(track) == []
        assert len(resolver.browse(track)) == 1

    def test_a_direct_link_does_not_shortcut_the_search(self, track, fake_search):
        """
        `resolve` برای ترکِ یوتیوبی همان لینک خودش را برمی‌گرداند. اگر `browse`
        هم این کار را می‌کرد، دیالوگ همیشه یک گزینه — همان اشتباهِ فعلی — داشت.
        """
        fake_search([_entry("Mard-e Tanha"), _entry("Mard-e Tanha (Live)")])
        from_youtube = track.model_copy(
            update={"source": "youtube", "sourceUrl": "https://youtu.be/abc"}
        )

        assert len(resolver.resolve(from_youtube)) == 1
        assert len(resolver.browse(from_youtube)) == 2

    def test_only_the_first_configured_source_is_searched_unless_asked(
        self, track, fake_search, monkeypatch
    ):
        """
        منبع دومِ لیست (هرچه باشد) بدون درخواستِ صریح زده نمی‌شود — پیش‌فرض
        همیشه محدود به اولین منبعِ AUDIO_SOURCES است.
        """
        monkeypatch.setattr(resolver, "AUDIO_SOURCES", ("youtube", "soundcloud"))
        queries = fake_search([_entry("Mard-e Tanha")])

        resolver.browse(track)

        assert all(q.startswith("ytsearch") for q in queries)

    def test_an_explicit_source_is_honored(self, track, fake_search):
        queries = fake_search([_entry("Mard-e Tanha")])

        resolver.browse(track, "soundcloud")

        assert all(q.startswith("scsearch") for q in queries)

    def test_results_come_back_best_first(self, track, fake_search):
        fake_search(
            [
                _entry("چیزی بی‌ربط", "Random", 20),
                _entry("Farhad Mehrad - Mard-e Tanha", "Farhad Mehrad", 185),
            ]
        )

        found = resolver.browse(track)

        assert found[0].title.startswith("Farhad Mehrad")


class TestResolveFallback:
    """
    `resolve` برای ترکِ یوتیوب/ساندکلاد فقط همان لینکِ مستقیم را می‌دهد (جستجوی
    معمولی مفت تلف نمی‌شود)، و برای ترک‌های اپل/دیزر/اسپاتیفای ممکن است به‌خاطر
    امتیازِ زودهنگامِ «قانع‌کننده»ی یک منبع اصلاً منبعِ دیگری را نپرسیده باشد.
    اگر آن کاندیدها بعداً در jobs._run دانلود نشدند (DRM، گیت ضدربات، حذف‌شده)،
    `resolve_fallback` فقط منبع‌های امتحان‌نشده را جستجو می‌کند.
    """

    def test_it_searches_even_for_a_youtube_sourced_track(self, track, fake_search):
        fake_search([_entry("Farhad Mehrad - Mard-e Tanha", "Farhad Mehrad", 185)])
        from_youtube = track.model_copy(
            update={"source": "youtube", "sourceUrl": "https://youtu.be/abc"}
        )

        # resolve خودش هیچ جستجویی نمی‌زند — همان یک کاندیدِ لینکِ مستقیم
        assert [c.url for c in resolver.resolve(from_youtube)] == ["https://youtu.be/abc"]

        found = resolver.resolve_fallback(from_youtube)

        assert len(found) == 1
        assert found[0].url != "https://youtu.be/abc"

    def test_low_scores_do_not_survive_unlike_browse(self, track, fake_search):
        """برخلاف `browse`، اینجا هنوز یک نتیجه‌ی خودکار است — آستانه‌ی امتیاز سرِ جایش می‌ماند."""
        fake_search([_entry("چیزی کاملاً بی‌ربط", "Random", 20)])
        from_youtube = track.model_copy(
            update={"source": "youtube", "sourceUrl": "https://youtu.be/abc"}
        )

        assert resolver.resolve_fallback(from_youtube) == []

    def test_already_tried_sources_are_skipped(self, track, fake_search, monkeypatch):
        """
        اگر resolve() به‌خاطر امتیازِ بالای ساندکلاد اصلاً یوتیوب را نپرسیده بود
        و همان کاندیدهای ساندکلاد دانلود نشدند (سناریوی واقعیِ DRM)، جستجوی
        دوباره‌ی ساندکلاد فقط وقت تلف می‌کند — باید مستقیم برود سراغِ یوتیوب.
        """
        monkeypatch.setattr(resolver, "AUDIO_SOURCES", ("soundcloud", "youtube"))
        queries = fake_search([_entry("Farhad Mehrad - Mard-e Tanha", "Farhad Mehrad", 185)])

        found = resolver.resolve_fallback(track, tried_sources=frozenset({"soundcloud"}))

        assert len(found) == 1
        assert found[0].source == "youtube"
        assert all(q.startswith("ytsearch") for q in queries)

    def test_nothing_left_to_try_skips_the_search_entirely(self, track, fake_search, monkeypatch):
        """همه‌ی منبع‌ها از قبل امتحان شده بودند — یک جستجوی گران‌قیمتِ بی‌فایده نباید اجرا شود."""
        monkeypatch.setattr(resolver, "AUDIO_SOURCES", ("soundcloud", "youtube"))
        queries = fake_search([_entry("Farhad Mehrad - Mard-e Tanha", "Farhad Mehrad", 185)])

        found = resolver.resolve_fallback(track, tried_sources=frozenset({"soundcloud", "youtube"}))

        assert found == []
        assert queries == []


class TestEndpoint:
    def test_unknown_source_is_rejected(self, track):
        """`source` مستقیم به yt-dlp می‌رود؛ هرچیزی را نباید قبول کرد."""
        req = CandidateRequest(
            trackId=track.id, sourceUrl=track.sourceUrl, source="spotify"
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(main.candidates(req, None))

        assert exc.value.status_code == 400

    def test_metadata_from_the_request_avoids_a_lookup(self, track, fake_search):
        """بدون این، هر بار باز کردن دیالوگ یک فراخوانی کاتالوگ اضافه می‌کرد."""
        fake_search([_entry("Mard-e Tanha")])
        req = CandidateRequest(
            trackId=track.id,
            sourceUrl=track.sourceUrl,
            title=track.title,
            artist=track.artist,
        )

        # `request` هیچ‌وقت لمس نمی‌شود چون متادیتا کامل است — None بودنش عمدی است
        found = asyncio.run(main.candidates(req, None))

        assert len(found) == 1


class TestManualPick:
    @pytest.fixture
    def picked_db(self, tmp_path, monkeypatch, fresh_db):
        monkeypatch.setattr(jobs, "DOWNLOAD_DIR", tmp_path)
        jobs.manager._jobs.clear()
        return fresh_db

    def test_a_manual_pick_never_reuses_the_old_file(self, picked_db, tmp_path, track):
        """
        بازاستفاده دقیقاً همان فایلی را برمی‌گرداند که کاربر رفته آن را عوض کند —
        و از بیرون شبیه «دکمه کار نکرد» به نظر می‌رسد.
        """
        audio = tmp_path / "old.mp3"
        audio.write_bytes(b"x")
        picked_db.insert_job("old", track, "320", "ready", time.time())
        picked_db.update_job("old", status="ready", path=str(audio), bytes=1)

        async def create(candidate_url):
            job, reused = jobs.manager.create(track, "320", candidate_url)
            if job.task:
                job.task.cancel()
            return job, reused

        _, automatic = asyncio.run(create(None))
        job, manual = asyncio.run(create("https://youtu.be/other"))

        assert automatic is True
        assert manual is False
        assert job.candidate_url == "https://youtu.be/other"


class TestSearchQueries:
    """
    کوئری تصمیم می‌گیرد اصلاً کاندیدی وجود داشته باشد یا نه — و برخلاف
    امتیازدهی، شکستش بی‌صداست: نتیجه‌ی خالی از «آن ترک اصلاً نیست» قابل تشخیص
    نیست. جستجوی ساندکلاد همه‌ی واژه‌های کوئری را با AND می‌خواهد، پس یک واژه‌ی
    اضافه یعنی صفر نتیجه، نه نتیجه‌ی ضعیف‌تر.
    """

    @pytest.fixture
    def featured(self, track, monkeypatch):
        """همان ترک، با هنرمندِ دومی که اسپاتیفای با کاما به اولی چسبانده."""
        monkeypatch.setattr(resolver, "AUDIO_SOURCES", ("soundcloud",))
        return track.model_copy(update={"artist": "Farhad Mehrad, Esfandiar Monfaredzadeh"})

    def test_extra_artists_do_not_narrow_the_query(self, featured, fake_search_by_query):
        """
        باگِ واقعی: ترکِ تازه‌منتشرشده‌ی چندهنرمندی که عیناً روی ساندکلاد بود
        «نسخه‌ی قابل دانلودی پیدا نشد» می‌گرفت، چون نامِ هنرمندِ دوم در آن نسخه
        نمی‌آمد و جستجو را صفر می‌کرد.
        """
        entry = _entry("Mard-e Tanha", "Farhad Mehrad")
        queries = fake_search_by_query({"Farhad Mehrad - Mard-e Tanha": [entry]})

        found = resolver.resolve(featured)

        assert [c.url for c in found] == [entry["webpage_url"]]
        assert queries == ["scsearch6:Farhad Mehrad - Mard-e Tanha"]

    def test_bracketed_extras_are_dropped_too(self, featured, fake_search_by_query):
        """«(feat. X)» و «[Remastered]» هم همان واژه‌های اضافه‌اند."""
        queries = fake_search_by_query({})

        resolver.resolve(featured.model_copy(update={"title": "Mard-e Tanha (feat. X) [2024]"}))

        assert queries[0] == "scsearch6:Farhad Mehrad - Mard-e Tanha"

    def test_the_title_alone_is_the_last_resort(self, featured, fake_search_by_query):
        """
        وقتی نامِ هنرمند اصلاً در آن نسخه نیست (آپلود روی حسابِ فیچرینگ، املای
        متفاوت، فارسی در برابر فینگلیش) تنها چیزِ مشترک عنوان است.
        """
        entry = _entry("Mard-e Tanha", "Some Other Account")
        queries = fake_search_by_query({"Mard-e Tanha": [entry]})

        found = resolver.resolve(featured)

        assert [c.url for c in found] == [entry["webpage_url"]]
        assert queries == ["scsearch6:Farhad Mehrad - Mard-e Tanha", "scsearch6:Mard-e Tanha"]

    def test_a_title_only_match_needs_the_duration_too(self, featured, fake_search_by_query):
        """
        کوئریِ «فقط عنوان» هنرمند را ندارد، پس هم‌نامیِ خالی کافی نیست — وگرنه
        ترکِ دیگری با همان نام به‌جای اصل دانلود می‌شد. این امتیاز از آستانه‌ی
        معمولی رد می‌شود ولی از آستانه‌ی سخت‌گیرترِ این کوئری نه.
        """
        loose = _entry("Mard-e Tanha", "Some Other Account", seconds=193)
        fake_search_by_query({"Mard-e Tanha": [loose]})

        assert resolver.MIN_SCORE <= resolver.score_candidate(
            featured, loose["title"], loose["uploader"], 193_000
        ) < resolver.TITLE_ONLY_MIN_SCORE
        assert resolver.resolve(featured) == []


class TestSilentSubstitution:
    """
    ترکی که لینکِ خودش را دارد و فایل از جای دیگری آمده.

    این همان اتفاقی است که برای «KIR TO RAPFARSI»ی ساندکلاد افتاد: لینکِ خودِ
    ترک دانلود نشد، fallback نشست، و فایلی که تحویل داده شد بازنشرِ
    «[Distort Version]»ِ یک کاربر دیگر بود — با تگ و کاور و اسمِ درست، پس هیچ
    جای برنامه این جابه‌جایی دیده نمی‌شد.
    """

    def _candidate(self, url: str) -> resolver.Candidate:
        return resolver.Candidate(
            url=url,
            title="Kir To Rapfarsi[Distort Version]",
            uploader="skill issue",
            duration_ms=111_000,
            score=75.0,
            source="soundcloud",
        )

    def test_a_different_upload_warns(self, track):
        from_soundcloud = track.model_copy(
            update={"source": "soundcloud", "sourceUrl": "https://soundcloud.com/a/real"},
        )

        warning = jobs._substitution(from_soundcloud, self._candidate("https://soundcloud.com/b/fake"))

        assert warning and "skill issue" in warning

    def test_the_track_own_link_is_silent(self, track):
        url = "https://soundcloud.com/a/real"
        from_soundcloud = track.model_copy(update={"source": "soundcloud", "sourceUrl": url})

        assert jobs._substitution(from_soundcloud, self._candidate(url)) is None

    def test_catalog_tracks_never_warn(self, track):
        """
        اپل/دیزر/اسپاتیفای اصلاً فایل صوتی ندارند و `sourceUrl` شان صفحه‌ی
        کاتالوگ است — آنجا «جایگزین» حالتِ عادی است، نه استثنا.
        """
        assert jobs._substitution(track, self._candidate("https://youtu.be/x")) is None


class TestDrmFallback:
    def test_multi_artist_queries_in_fallback(self, track):
        featured = track.model_copy(update={"artist": "DORCCI LEAKS, Dorcci"})
        queries_normal = resolver._queries(featured, include_all_artists=False)
        queries_fallback = resolver._queries(featured, include_all_artists=True)

        assert len(queries_normal) == 2
        assert "DORCCI LEAKS - Mard-e Tanha" in queries_normal
        assert "Dorcci - Mard-e Tanha" not in queries_normal

        assert "Dorcci - Mard-e Tanha" in queries_fallback
        assert "DORCCI LEAKS - Mard-e Tanha" in queries_fallback

    def test_youtube_music_search_source(self, track, monkeypatch):
        class FakeTrack:
            id = "ytm:track:abc12345678"
            title = "Mard-e Tanha"
            artist = "Farhad Mehrad"
            durationMs = 185_000
            sourceUrl = "https://music.youtube.com/watch?v=abc12345678"

        class FakeSearchResults:
            tracks = [FakeTrack()]

        class FakeYTM:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def search(query, limit=6):
                return FakeSearchResults()

        monkeypatch.setattr("app.providers.youtube_music.enabled", FakeYTM.enabled)
        monkeypatch.setattr("app.providers.youtube_music.search", FakeYTM.search)

        found = resolver._search_source(track, "youtube_music")
        assert len(found) == 1
        assert found[0].source == "youtube_music"
        assert found[0].url == "https://music.youtube.com/watch?v=abc12345678"

    def test_downloader_recovers_via_innertubex_on_drm_error(self, track, monkeypatch, tmp_path):
        from app import downloader

        mock_out = tmp_path / "mock.mp3"
        mock_out.write_bytes(b"dummy audio")

        def fake_extract_info(url, download=True):
            raise RuntimeError("ERROR: This video contains DRM protection and cannot be downloaded")

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def extract_info(self, url, download=True):
                return fake_extract_info(url, download=download)

        monkeypatch.setattr("yt_dlp.YoutubeDL", FakeYDL)
        monkeypatch.setattr(
            downloader,
            "_try_innertubex_download",
            lambda t, vid, q, prog, out_dir, abort: mock_out,
        )

        res = downloader.download(
            track=track,
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            quality="320",
            on_progress=lambda p: None,
            out_dir=tmp_path,
        )
        assert res == mock_out
