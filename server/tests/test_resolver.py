"""
امتیازدهی resolver — قلب پروژه و ظریف‌ترین بخشش.

هر عددی که اینجا تست می‌شود یک تصمیم است، نه یک ثابت دلخواه: اگر آستانه‌ها را
جابه‌جا کنی یا نرمال‌سازی فارسی را خراب کنی، خروجی «فایل اشتباه با تگ درست»
می‌شود — بدترین حالت ممکن، چون کاربر متوجه نمی‌شود.
"""

from __future__ import annotations

import pytest

from app.resolver import GOOD_ENOUGH, MIN_SCORE, _normalize, _overlap, _tokens, score_candidate


def score(track, title, uploader="", duration_ms=None):
    return score_candidate(
        track, title, uploader, track.durationMs if duration_ms is None else duration_ms
    )


class TestNormalize:
    def test_arabic_letters_become_persian(self):
        assert _normalize("مهدي كريمي") == _normalize("مهدی کریمی")

    def test_diacritics_are_dropped(self):
        assert _normalize("مُحَمَّد") == "محمد"

    def test_bracketed_parts_are_removed(self):
        assert _normalize("Shabaneh (Live at Vienna)") == "shabaneh"
        assert _normalize("Barf [Remastered]") == "barf"

    def test_punctuation_collapses_to_space(self):
        assert _normalize("Mard-e   Tanha!!") == "mard e tanha"

    def test_tokens_drop_single_characters(self):
        # «e» در «Mard-e Tanha» نویز است و نباید در تطابق وزن بگیرد
        assert _tokens("Mard-e Tanha") == {"mard", "tanha"}


class TestOverlap:
    def test_empty_wanted_is_zero(self):
        assert _overlap(set(), {"a"}) == 0.0

    def test_full_containment_is_one(self):
        assert _overlap({"a", "b"}, {"a", "b", "c"}) == 1.0

    def test_partial(self):
        assert _overlap({"a", "b"}, {"a"}) == 0.5


class TestScoring:
    def test_exact_match_is_confident(self, track):
        result = score(track, "Farhad Mehrad - Mard-e Tanha")
        assert result >= GOOD_ENOUGH

    def test_unrelated_title_falls_below_threshold(self, track):
        assert score(track, "Cooking pasta in 10 minutes", "FoodChannel") < MIN_SCORE

    def test_candidate_with_different_title_and_same_artist_is_rejected(self, track):
        """
        اگر کاندیدا از همان هنرمند و با طول یکسان باشد اما عنوانش هیچ ربطی
        به ترک نداشته باشد (مثلاً آهنگی دیگر از همان خواننده یا لایک‌ها)،
        نباید تایید شود.
        """
        unrelated_song = score(track, "Farhad Mehrad - Shabaneh", "Farhad Mehrad", duration_ms=185_000)
        assert unrelated_song == 0.0

    def test_duration_is_the_strongest_signal(self, track):
        """عنوانِ یکسان ولی طولِ خیلی متفاوت، رد صلاحیت می‌شود — حتی وقتی متن کامل match است."""
        same = score(track, "Farhad Mehrad - Mard-e Tanha")
        off = score(track, "Farhad Mehrad - Mard-e Tanha", duration_ms=track.durationMs + 90_000)
        assert same >= GOOD_ENOUGH
        assert off == 0.0

    def test_close_duration_still_scores_well(self, track):
        near = score(track, "Farhad Mehrad - Mard-e Tanha", duration_ms=track.durationMs + 1500)
        assert near >= GOOD_ENOUGH

    def test_large_duration_gap_is_disqualified(self, track):
        """
        گیت سخت‌گیرانه متادیتا: اگر طول کاندیدا بیش از ۵ ثانیه و ۳.۵٪ با مدت زمان آهنگ تفاوت داشته باشد
        (مانند نسخه slowed ۳:۴۹ در برابر ۳:۱۹، یا اختلاف ۴۹ ثانیه‌ای)، نسخه دستکاری‌شده تلقی شده
        و فوراً نمره ۰ می‌گیرد تا مانع انتخاب نسخه اصلی نشود.
        """
        result = score(track, "Farhad Mehrad - Mard-e Tanha", duration_ms=track.durationMs + 49_000)
        assert result == 0.0

    def test_big_duration_gap_with_weak_text_match_is_still_rejected(self, track):
        """بدون تطابق متنیِ قوی، جریمه‌ی کامل باقی می‌ماند — نرم‌تر شدن فقط برای متنِ تقریباً کامل است."""
        assert score(track, "Cooking pasta", "FoodChannel", duration_ms=track.durationMs + 90_000) < MIN_SCORE

    def test_missing_duration_is_only_mildly_penalized(self, track):
        assert score(track, "Farhad Mehrad - Mard-e Tanha", duration_ms=0) > MIN_SCORE

    @pytest.mark.parametrize("word", ["live", "cover", "karaoke", "کاور", "ریمیکس"])
    def test_negative_words_are_penalized(self, track, word):
        clean = score(track, "Farhad Mehrad - Mard-e Tanha")
        dirty = score(track, f"Farhad Mehrad - Mard-e Tanha {word}")
        assert dirty < clean

    def test_negative_word_inside_the_real_title_is_not_penalized(self, track):
        """اگر خودِ ترک «Live» نام دارد، جریمه کردنش یعنی هیچ‌وقت پیدایش نکنیم."""
        track.title = "Live and Let Die"
        titled = score(track, f"{track.artist} - Live and Let Die")

        track.title = "Let Die"
        # همان کاندید، ولی حالا «live» کلمه‌ی اضافه‌ای است که در عنوان ترک نیست
        extra = score(track, f"{track.artist} - Live and Let Die")

        assert titled >= GOOD_ENOUGH
        assert titled - extra == pytest.approx(18, abs=0.01)

    def test_official_upload_gets_a_nudge(self, track):
        plain = score(track, "Farhad Mehrad - Mard-e Tanha", "Some Channel")
        official = score(track, "Farhad Mehrad - Mard-e Tanha (Official Audio)", "Some Channel")
        assert official > plain

    def test_persian_query_matches_persian_upload(self):
        from app.models import Track

        fa = Track(
            id="deezer:track:9",
            title="مرد تنها",
            artist="فرهاد مهراد",
            durationMs=185_000,
            source="deezer",
            sourceUrl="x",
        )
        # آپلود با «ي» و «ك» عربی — همان چیزی که در یوتیوب فراوان است
        assert score_candidate(fa, "فرهاد مهراد - مرد تنهاي", "", 185_000) > MIN_SCORE

    def test_artist_in_channel_name_counts(self, track):
        """کانال‌های Topic عنوانِ خالی دارند و نام هنرمند فقط در uploader است."""
        with_channel = score(track, "Mard-e Tanha", "Farhad Mehrad - Topic")
        without = score(track, "Mard-e Tanha", "Random Uploads")
        assert with_channel > without


class TestModifiedReuploads:
    """
    بازنشرهای دستکاری‌شده (8D، slowed، nightcore، bass boosted).

    این‌ها بدترین نوع نتیجه‌ی اشتباه‌اند چون *بی‌سروصدا* اشتباه‌اند: عنوان و
    هنرمند کاملاً مچ‌اند و مدتشان هم تقریباً همان است، پس امتیازدهی بالاترین
    نمره را به آن‌ها می‌داد — بالاتر از خودِ ترک. کاربر فایل را می‌گرفت، تگش
    درست بود، و تازه موقع پخش می‌فهمید صدا عوض شده.

    بدتر اینکه «audio»ی تنها در POSITIVE بود و «8D AUDIO» بابتش جایزه هم
    می‌گرفت؛ با `GOOD_ENOUGH` که جستجو را همان‌جا متوقف می‌کند، یوتیوب اصلاً
    پرسیده نمی‌شد.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "The Neighbourhood - Sweater Weather (8D AUDIO)",
            "Sweater Weather - The Neighbourhood (Slowed + Reverb)",
            "Sweater Weather (sped up)",
            "Sweater Weather - Nightcore",
            "Sweater Weather (Bass Boosted)",
            # همان چیزی که به‌جای ترکِ ساندکلادِ «KIR TO RAPFARSI» دانلود شد:
            # بازنشرِ کلیپ‌شده، با همان عنوان و همان طول
            "Sweater Weather[Distort Version]",
            "Sweater Weather (New) M&M",
            "Sweater Weather (Mix & Master)",
            "Sweater Weather Type Beat",
        ],
    )
    def test_scores_below_the_plain_version(self, track, title):
        plain = score(track, f"{track.artist} - {track.title}", track.artist)
        assert score(track, title, "someuser") < plain

    def test_official_upload_still_wins(self, track):
        official = score(track, f"{track.artist} - {track.title} (Official Audio)", track.artist)
        plain = score(track, f"{track.artist} - {track.title}", track.artist)
        assert official > plain

    def test_multi_artist_official_upload_beats_unofficial_keyword_stuffed_reupload(self):
        from app.models import Track

        collab = Track(
            id="sp:track:1ms0yxJHPwKPvWNmJYBdFG",
            title="Later",
            artist="Therichpia, Tlkhoon, Matin Fattahi",
            durationMs=168_947,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/1ms0yxJHPwKPvWNmJYBdFG",
        )
        official = score_candidate(
            collab,
            title="Later",
            uploader="TheRichPia",
            duration_ms=168_993,
        )
        unofficial = score_candidate(
            collab,
            title="Matin Fattahi x Tlkhoon x Therichpia - Later (New) M&M",
            uploader="Hustler Beatz",
            duration_ms=170_234,
        )
        unofficial_clean = score_candidate(
            collab,
            title="Matin Fattahi x Tlkhoon x Therichpia - Later",
            uploader="Hustler Beatz",
            duration_ms=170_234,
        )
        assert official >= GOOD_ENOUGH
        assert official > unofficial
        assert official > unofficial_clean


class TestNegativeWordBoundaries:
    """
    عبارت‌های منفی باید *واژه* باشند، نه زیررشته.

    «live» داخلِ «deliverance» و «alive» هم هست و «cover» داخلِ «discover» —
    بدون مرزِ واژه، نسخه‌ی کاملاً درست بابتِ چیزی که اصلاً در عنوانش نیست
    جریمه می‌شد.
    """

    def test_substring_inside_another_word_is_not_a_penalty(self, track):
        clean = score(track, f"{track.artist} - {track.title}", track.artist)
        # «Deliverance» و «Discovery» هیچ‌کدام نسخه‌ی زنده یا کاور نیستند
        assert score(track, f"{track.artist} - {track.title} (Deliverance Mix)", track.artist) == clean
        # آپلودکننده‌ی بی‌ربط همان امتیازِ یک برچسبِ دیگر را می‌گیرد؛ اگر «Discovery»
        # به‌اشتباه «cover» شمرده شود، از این پایین‌تر می‌افتد.
        assert score(track, f"{track.artist} - {track.title}", "Discovery Records") == score(
            track, f"{track.artist} - {track.title}", "Neutral Records"
        )

    def test_real_mentions_are_still_penalised(self, track):
        clean = score(track, f"{track.artist} - {track.title}", track.artist)
        assert score(track, f"{track.artist} - {track.title} (Live)", track.artist) < clean
        assert score(track, f"{track.title} - covers band", "someone") < clean

    def test_inflected_forms_count(self, track):
        clean = score(track, f"{track.artist} - {track.title}", track.artist)
        # «remixed»/«remixes» همان «remix»‌اند و باید همان جریمه را بگیرند
        assert score(track, f"{track.title} (remixed)", "dj") < clean
        assert score(track, f"{track.title} (remixes)", "dj") < clean


class TestSourceRetry:
    """
    اولویتِ ساندکلاد باید حتی زیرِ خطای گذرا هم حفظ شود.

    قبلاً یک استثنایِ تصادفی در جستجوی ساندکلاد بی‌صدا به یوتیوب می‌رفت — حتی
    وقتی ترک همان‌جا بود. حالا یک تلاشِ دوباره هست و فقط شکستِ واقعی، منبع را
    کنار می‌گذارد. «ترک در این منبع نبود» خطا نیست و نباید دوباره‌خواهی بگیرد.
    """

    @pytest.fixture(autouse=True)
    def _no_delay(self, monkeypatch):
        from app import resolver

        monkeypatch.setattr(resolver, "SOURCE_RETRY_DELAY", 0.0)

    def test_transient_error_is_retried_and_succeeds(self, track, monkeypatch):
        from app import resolver
        from app.resolver import Candidate

        good = Candidate(
            url="https://soundcloud.com/x/ajibe",
            title=track.title,
            uploader=track.artist,
            duration_ms=track.durationMs,
            score=100.0,
            source="soundcloud",
        )

        calls = {"n": 0}

        def flaky(tr, source, min_score=resolver.MIN_SCORE, **_kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("network hiccup")
            return [good]

        monkeypatch.setattr(resolver, "_search_source", flaky)
        result = resolver._search_source_retrying(track, "soundcloud")
        assert result == [good]
        assert calls["n"] == 2  # یک شکست + یک موفقیت

    def test_persistent_error_returns_empty(self, track, monkeypatch):
        from app import resolver

        def always_fail(tr, source, min_score=resolver.MIN_SCORE, **_kw):
            raise OSError("down for good")

        monkeypatch.setattr(resolver, "_search_source", always_fail)
        # نباید استثنا بالا بیاید؛ منبعِ بعدی باید فرصت داشته باشد
        assert resolver._search_source_retrying(track, "soundcloud") == []

    def test_soundcloud_is_tried_first(self, track, monkeypatch):
        from app import resolver
        from app.resolver import Candidate

        order: list[str] = []

        def by_source(tr, source, min_score=resolver.MIN_SCORE, **_kw):
            order.append(source)
            if source == "soundcloud":
                return [
                    Candidate(
                        url="https://soundcloud.com/x/y",
                        title=tr.title,
                        uploader=tr.artist,
                        duration_ms=tr.durationMs,
                        score=resolver.GOOD_ENOUGH + 1,
                        source="soundcloud",
                    )
                ]
            return []

        monkeypatch.setattr(resolver, "_search_source", by_source)
        found = resolver._search_all_sources(track)
        # ساندکلاد جوابِ قانع‌کننده داد — یوتیوب نباید اصلاً پرسیده شود
        assert order == ["soundcloud"]
        assert found and found[0].source == "soundcloud"

    def test_falls_back_to_youtube_when_soundcloud_empty(self, track, monkeypatch):
        from app import resolver
        from app.resolver import Candidate

        order: list[str] = []

        def by_source(tr, source, min_score=resolver.MIN_SCORE, **_kw):
            order.append(source)
            if source == "youtube":
                return [
                    Candidate(
                        url="https://youtube.com/watch?v=z",
                        title=tr.title,
                        uploader=tr.artist,
                        duration_ms=tr.durationMs,
                        score=resolver.GOOD_ENOUGH + 1,
                        source="youtube",
                    )
                ]
            return []

        monkeypatch.setattr(resolver, "_search_source", by_source)
        found = resolver._search_all_sources(track)
        # ساندکلاد خالی بود — نوبت به یوتیوب رسید. یوتیوب‌موزیک هم اکنون
        # بین این دو جستجو می‌شود، پس فقط ترتیب نسبی مهم است.
        assert order[0] == "soundcloud"
        assert order[-1] == "youtube"
        assert found and found[0].source == "youtube"

    def test_falls_back_to_youtube_when_soundcloud_errors(self, track, monkeypatch):
        from app import resolver
        from app.resolver import Candidate

        def by_source(tr, source, min_score=resolver.MIN_SCORE, **_kw):
            if source == "soundcloud":
                raise OSError("soundcloud down")
            return [
                Candidate(
                    url="https://youtube.com/watch?v=z",
                    title=tr.title,
                    uploader=tr.artist,
                    duration_ms=tr.durationMs,
                    score=resolver.GOOD_ENOUGH + 1,
                    source="youtube",
                )
            ]

        monkeypatch.setattr(resolver, "_search_source", by_source)
        # شکستِ دائمیِ ساندکلاد نباید کلِ دانلود را ببندد — یوتیوب جواب می‌دهد
        found = resolver._search_all_sources(track)
        assert found and found[0].source == "youtube"


class TestCanonicalOverrides:
    """تست‌های نگاشت ترک‌های خاص به آدرس قطعی/اصلی."""

    def test_sinazza_sex_drug_canonical_override(self):
        from app import resolver
        from app.models import Track

        tr = Track(
            id="sp:track:test123",
            title="sex drug",
            artist="Sinazza",
            album="Vision",
            durationMs=150_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/test123",
        )

        candidates = resolver.resolve(tr)
        assert len(candidates) == 1
        assert candidates[0].url == "https://soundcloud.com/sinazza/sex-drug-6"
        assert candidates[0].source == "soundcloud"

    def test_dorcci_b_hessi_canonical_override(self):
        from app import resolver
        from app.models import Track

        tr = Track(
            id="deezer:track:2750780811",
            title="B HESSI",
            artist="Dorcci",
            album="B HESSI",
            durationMs=123_000,
            source="deezer",
            sourceUrl="https://www.deezer.com/track/2750780811",
        )

        candidates = resolver.resolve(tr)
        assert len(candidates) == 1
        assert candidates[0].url == "https://www.youtube.com/watch?v=P8Y8KwliBKo"
        assert candidates[0].source == "youtube"

    def test_dorcci_addi_canonical_override_from_all_platforms(self):
        from app import resolver
        from app.models import Track

        # ترک اسپاتیفای ADDI با شناسه مشخص‌شده
        tr_spotify = Track(
            id="sp:track:1YFAi3Mxuofp5tOUao2oaJ",
            title="ADDI",
            artist="Dorcci",
            album="YOUNG MORVARID",
            durationMs=388_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/1YFAi3Mxuofp5tOUao2oaJ",
        )
        candidates = resolver.resolve(tr_spotify)
        assert len(candidates) == 1
        assert candidates[0].url == "https://www.youtube.com/watch?v=tw9ZOCCkgvw"
        assert candidates[0].source == "youtube"

        # ترک دیزر ADDI
        tr_deezer = Track(
            id="deezer:track:3278339721",
            title="ADDI",
            artist="Dorcci",
            album="YOUNG MORVARID",
            durationMs=388_000,
            source="deezer",
            sourceUrl="https://www.deezer.com/track/3278339721",
        )
        assert resolver._is_dorcci_addi(tr_deezer)
        cand_deezer = resolver.resolve(tr_deezer)
        assert cand_deezer[0].url == "https://www.youtube.com/watch?v=tw9ZOCCkgvw"

    def test_dorcci_young_morvarid_canonical_override_from_all_platforms(self):
        from app import resolver
        from app.models import Track

        # ترک اسپاتیفای YOUNG MORVARID
        tr_spotify = Track(
            id="sp:track:0Gy6zmPCoE9m9gdjIm06Uo",
            title="YOUNG MORVARID",
            artist="Dorcci",
            album="YOUNG MORVARID",
            durationMs=130_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/0Gy6zmPCoE9m9gdjIm06Uo",
        )
        candidates = resolver.resolve(tr_spotify)
        assert len(candidates) == 1
        assert candidates[0].url == "https://www.youtube.com/watch?v=61Cz3eOdWKA"
        assert candidates[0].source == "youtube"

        # ترک دیزر YOUNG MORVARID
        tr_deezer = Track(
            id="deezer:track:3278339731",
            title="YOUNG MORVARID",
            artist="Dorcci",
            album="YOUNG MORVARID",
            durationMs=130_000,
            source="deezer",
            sourceUrl="https://www.deezer.com/track/3278339731",
        )
        assert resolver._is_dorcci_young_morvarid(tr_deezer)
        cand_deezer = resolver.resolve(tr_deezer)
        assert cand_deezer[0].url == "https://www.youtube.com/watch?v=61Cz3eOdWKA"

    def test_lithe_lychee_martini_canonical_override(self):
        from app import resolver
        from app.models import Track

        tr = Track(
            id="sp:track:7oqDFVu8MUwZsRBpMXS1Hs",
            title="Lychee Martini",
            artist="Lithe",
            album="Euphoria",
            durationMs=116_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/7oqDFVu8MUwZsRBpMXS1Hs",
        )

        candidates = resolver.resolve(tr)
        assert len(candidates) == 1
        assert candidates[0].url == "https://soundcloud.com/lithe9/lychee-martini"
        assert candidates[0].source == "soundcloud"

    def test_tlkhoon_havasam_canonical_override_from_all_platforms(self):
        from app import resolver
        from app.models import Track

        # ۱. ترک اسپاتیفای به نسخه اصلی ۳:۱۹ رسمی یوتیوب موزیک تلخون متصل می‌شود
        tr_spotify = Track(
            id="sp:track:32xQkDh3INkWDqFYOdpZdP",
            title="Havasam",
            artist="Tlkhoon, Matin Fattahi",
            durationMs=199_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/32xQkDh3INkWDqFYOdpZdP",
        )
        cand_sp = resolver.resolve(tr_spotify)
        assert len(cand_sp) == 1
        assert cand_sp[0].url == "https://music.youtube.com/watch?v=AK3KLv7MWno"
        assert cand_sp[0].source == "youtube_music"
        assert cand_sp[0].duration_ms == 199_000

        # ۲. ترک دیزر به نسخه اصلی ۳:۱۹ رسمی یوتیوب موزیک تلخون متصل می‌شود
        tr_deezer = Track(
            id="deezer:track:3279339531",
            title="Havasam",
            artist="Tlkhoon, Matin Fattahi",
            durationMs=199_000,
            source="deezer",
            sourceUrl="https://www.deezer.com/track/3279339531",
        )
        cand_dz = resolver.resolve(tr_deezer)
        assert len(cand_dz) == 1
        assert cand_dz[0].url == "https://music.youtube.com/watch?v=AK3KLv7MWno"
        assert cand_dz[0].source == "youtube_music"

        # ۳. ترک یوتیوب موزیک مستقیماً به نسخه اصلی ۳:۱۹ رسمی یوتیوب موزیک متصل می‌شود
        tr_ytm = Track(
            id="ytm:track:AK3KLv7MWno",
            title="Havasam",
            artist="Tlkhoon",
            durationMs=199_000,
            source="youtube_music",
            sourceUrl="https://music.youtube.com/watch?v=AK3KLv7MWno",
        )
        cand_ytm = resolver.resolve(tr_ytm)
        assert len(cand_ytm) == 1
        assert cand_ytm[0].url == "https://music.youtube.com/watch?v=AK3KLv7MWno"
        assert cand_ytm[0].source == "youtube_music"

        # ۴. ترک ساندکلاد به نسخه اصلی رسمی ساندکلاد متصل می‌شود
        tr_sc = Track(
            id="sc:track:999999",
            title="Havasam",
            artist="Tlkhoon",
            durationMs=199_000,
            source="soundcloud",
            sourceUrl="https://soundcloud.com/tlkhoon/havasam",
        )
        cand_sc = resolver.resolve(tr_sc)
        assert len(cand_sc) == 1
        assert cand_sc[0].url == "https://soundcloud.com/tlkhoon/havasam"
        assert cand_sc[0].source == "soundcloud"

        # ۵. متن فارسی
        tr_fa = Track(
            id="sp:track:other_id",
            title="حواسم",
            artist="تلخون، متین فتاحی",
            durationMs=199_000,
            source="spotify",
            sourceUrl="https://musicbazi.local/track/other_id",
        )
        cand_fa = resolver.resolve(tr_fa)
        assert len(cand_fa) == 1
        assert cand_fa[0].url == "https://music.youtube.com/watch?v=AK3KLv7MWno"
        assert cand_fa[0].source == "youtube_music"

        # ۶. موزیک ویدیوی یوتیوب در بخش Videos نباید دستکاری شود و دقیقاً همان ویدیو را پخش می‌کند
        tr_yt_video = Track(
            id="yt:track:music_video_123",
            title="Havasam (Official Music Video)",
            artist="Tlkhoon",
            durationMs=199_000,
            source="youtube",
            sourceUrl="https://www.youtube.com/watch?v=music_video_123",
        )
        assert resolver.is_youtube_video(tr_yt_video)
        cand_yt_video = resolver.resolve(tr_yt_video)
        assert len(cand_yt_video) == 1
        assert cand_yt_video[0].url == "https://www.youtube.com/watch?v=music_video_123"
        assert cand_yt_video[0].source == "youtube"

        # ۷. انتشار رسمی یوتیوب در بخش Releases به نسخه اصلی رسمی متصل می‌شود
        tr_yt_release = Track(
            id="yt:track:release_track_id",
            title="Havasam",
            artist="Tlkhoon",
            album="Havasam",
            albumId="yt:playlist:OLAK5uy_havasam",
            durationMs=199_000,
            source="youtube",
            sourceUrl="https://www.youtube.com/watch?v=release_track_id&list=OLAK5uy_havasam",
        )
        assert not resolver.is_youtube_video(tr_yt_release)
        cand_yt_release = resolver.resolve(tr_yt_release)
        assert len(cand_yt_release) == 1
        assert cand_yt_release[0].url == "https://music.youtube.com/watch?v=AK3KLv7MWno"
        assert cand_yt_release[0].source == "youtube_music"

        # ۸. کنترل‌های منفی (Negative Controls)
        tr_other_tlkhoon = Track(
            id="sp:track:tlkhoon_moordi",
            title="Moordi",
            artist="Tlkhoon",
            durationMs=180_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/moordi",
        )
        assert not resolver._is_tlkhoon_havasam(tr_other_tlkhoon)

        tr_other_havasam = Track(
            id="sp:track:other_havasam",
            title="Havasam",
            artist="Other Singer",
            durationMs=200_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/other",
        )
        assert not resolver._is_tlkhoon_havasam(tr_other_havasam)

        # ۸. کنترل‌های منفی (Negative Controls)
        tr_other_tlkhoon = Track(
            id="sp:track:tlkhoon_moordi",
            title="Moordi",
            artist="Tlkhoon",
            durationMs=180_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/moordi",
        )
        assert not resolver._is_tlkhoon_havasam(tr_other_tlkhoon)

        tr_other_havasam = Track(
            id="sp:track:other_havasam",
            title="Havasam",
            artist="Other Singer",
            durationMs=200_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/other",
        )
        assert not resolver._is_tlkhoon_havasam(tr_other_havasam)

    def test_dorcci_b_hessi_magical_slowed_version_is_rejected(self):
        from app.models import Track
        from app.resolver import GOOD_ENOUGH, score_candidate

        tr = Track(
            id="deezer:track:2750780811",
            title="B HESSI",
            artist="Dorcci",
            album="B HESSI",
            durationMs=123_000,
            source="deezer",
            sourceUrl="https://www.deezer.com/track/2750780811",
        )

        # نسخه دستکاری‌شده ۱۳۶ ثانیه‌ای ساندکلاد با عنوان Magical Version
        slowed_score = score_candidate(
            tr,
            title="DORCCI - B HESSI [ Magical Version ]",
            uploader="DORCCI",
            duration_ms=136_088,
        )
        # به دلیل اختلاف مدت زمان و کلمه منفی نباید به آستانه قطعیت (۸۰) برسد
        assert slowed_score < GOOD_ENOUGH

        # نسخه اصلی ۱۲۴ ثانیه‌ای یوتیوب
        official_score = score_candidate(
            tr,
            title="B HESSI",
            uploader="Dorcci",
            duration_ms=124_000,
        )
        assert official_score >= GOOD_ENOUGH
        assert official_score > slowed_score

    def test_relative_duration_penalty_blocks_sped_up_and_slowed_versions(self):
        """
        تست سیستمی: آهنگ ۱۲۲ ثانیه‌ای (مثل Lithe - Lychee Martini) که نسخه‌ی ۱۱۶ ثانیه‌ای
        (۵٪ اختلاف سرعت / sped up) دارد، به دلیل انحراف نسبی بالای ۴٪ نباید هرگز به
        آستانه قبولی خودکار (GOOD_ENOUGH=80) برسد.
        """
        from app.models import Track
        from app.resolver import GOOD_ENOUGH, score_candidate

        tr = Track(
            id="sp:track:7oqDFVu8MUwZsRBpMXS1Hs",
            title="Lychee Martini",
            artist="Lithe",
            album="Lychee Martini",
            durationMs=122_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/7oqDFVu8MUwZsRBpMXS1Hs",
        )

        # نسخه با اختلاف ۶ ثانیه (۵٪ سریع‌تر یا ادیت غیراستودیویی ۱:۵۶)
        off_version = score_candidate(
            tr,
            title="Lithe - Lychee Martini",
            uploader="Lithe",
            duration_ms=116_000,
        )
        assert off_version < GOOD_ENOUGH

        # نسخه با کلمه sped up حتی با طول مشابه
        sped_up = score_candidate(
            tr,
            title="Lithe - Lychee Martini (Sped Up)",
            uploader="Lithe",
            duration_ms=120_000,
        )
        assert sped_up < GOOD_ENOUGH

        # نسخه استودیویی رسمی با طول دقیق یا بسیار نزدیک (۱۲۲ ثانیه)
        exact_official = score_candidate(
            tr,
            title="Lychee Martini",
            uploader="Lithe - Topic",
            duration_ms=122_000,
        )
        assert exact_official >= GOOD_ENOUGH
        assert exact_official > off_version

    def test_off_duration_soundcloud_does_not_prevent_youtube_search(self, monkeypatch):
        """
        اگر ساندکلاد فقط نسخه‌ی با اختلاف تمپو (مثلاً ۱:۵۶ به‌جای ۲:۰۲) داشته باشد،
        امتیازش به ۸۰ نمی‌رسد و مانع جستجوی نسخه‌ی رسمی در یوتیوب نمی‌شود.
        """
        from app import resolver
        from app.models import Track
        from app.resolver import Candidate

        tr = Track(
            id="sp:track:7oqDFVu8MUwZsRBpMXS1Hs",
            title="Lychee Martini",
            artist="Lithe",
            album="Lychee Martini",
            durationMs=122_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/7oqDFVu8MUwZsRBpMXS1Hs",
        )

        order: list[str] = []

        def mock_search(track, source, min_score=None, **kw):
            order.append(source)
            if source == "soundcloud":
                # ساندکلاد فقط نسخه ۱۱۶ ثانیه‌ای sped up را دارد
                sc_score = resolver.score_candidate(
                    track, "Lithe - Lychee Martini", "Lithe", 116_000
                )
                return [
                    Candidate(
                        url="https://soundcloud.com/user/lychee",
                        title="Lithe - Lychee Martini",
                        uploader="Lithe",
                        duration_ms=116_000,
                        score=sc_score,
                        source="soundcloud",
                    )
                ]
            if source == "youtube":
                # یوتیوب نسخه رسمی ۱۲۲ ثانیه‌ای Topic را دارد
                yt_score = resolver.score_candidate(
                    track, "Lychee Martini", "Lithe - Topic", 122_000
                )
                return [
                    Candidate(
                        url="https://youtube.com/watch?v=official",
                        title="Lychee Martini",
                        uploader="Lithe - Topic",
                        duration_ms=122_000,
                        score=yt_score,
                        source="youtube",
                    )
                ]
            return []

        monkeypatch.setattr(resolver, "_search_source", mock_search)
        results = resolver._search_all_sources(tr)

        # باید هر دو منبع جستجو شوند چون ساندکلاد به آستانه قطعیت (۸۰) نرسید
        assert "youtube" in order
        # و نسخه رسمی یوتیوب باید برنده شود
        assert results[0].source == "youtube"
        assert results[0].duration_ms == 122_000

    def test_strict_duration_gate_rejects_slowed_version_completely(self):
        """
        تست گیت سخت‌گیرانه متادیتا:
        آهنگ ۱۹۹ ثانیه‌ای (۳:۱۹) در برابر نسخه ۲۲۹ ثانیه‌ای (۳:۴۹) که ۱۵٪ کاهش سرعت (slowed) دارد،
        باید نمره ۰ بگیرد و کلاً رد صلاحیت شود تا منبع بعدی را باز بگذارد.
        """
        from app.models import Track
        from app.resolver import MIN_SCORE, score_candidate

        tr = Track(
            id="sp:track:havasam_test",
            title="Havasam",
            artist="Tlkhoon",
            durationMs=199_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/havasam_test",
        )
        # نسخه ۳:۴۹ slowed
        slowed_score = score_candidate(
            tr,
            title="Tlkhoon - Havasam",
            uploader="Tlkhoon",
            duration_ms=229_000,
        )
        assert slowed_score == 0.0
        assert slowed_score < MIN_SCORE

        # نسخه ۳:۱۹ اصلی
        exact_score = score_candidate(
            tr,
            title="Tlkhoon - Havasam",
            uploader="Tlkhoon",
            duration_ms=199_000,
        )
        assert exact_score >= 80.0

    def test_candidate_cache_invalidated_when_duration_mismatches(self, monkeypatch):
        """
        اگر در کش دیتابیس کاندیدایی با طول نامنطبق (مثلاً ۳:۴۹) ذخیره شده باشد،
        سیستم باید آن را نامعتبر تشخیص داده، کش را باطل کند و مجدداً جستجو کند.
        """
        from app import db, resolver
        from app.models import Track
        from app.resolver import Candidate

        tr = Track(
            id="sp:track:test_dur_cache",
            title="Test Song",
            artist="Test Artist",
            durationMs=199_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/test_dur_cache",
        )

        stale_candidate = {
            "url": "https://soundcloud.com/stale/slowed",
            "title": "Test Song",
            "uploader": "Test Artist",
            "duration_ms": 229_000,  # ۳:۴۹ (نامنطبق)
            "score": 70.0,
            "source": "soundcloud",
        }
        monkeypatch.setattr(db, "get_resolved_candidates", lambda tid: [stale_candidate])

        fresh_candidate = Candidate(
            url="https://youtube.com/watch?v=exact_match",
            title="Test Song",
            uploader="Test Artist",
            duration_ms=199_000,  # ۳:۱۹ (منطبق)
            score=95.0,
            source="youtube",
        )
        monkeypatch.setattr(resolver, "_search_all_sources", lambda tr, **kw: [fresh_candidate])

        resolved = resolver.resolve(tr, use_cache=True)
        assert len(resolved) == 1
        assert resolved[0].url == "https://youtube.com/watch?v=exact_match"
        assert resolved[0].duration_ms == 199_000

    def test_canonical_override_survives_direct_soundcloud_source(self):
        """حتی اگر منبع ساندکلاد باشد، نگاشت قطعی اعمال می‌شود."""
        from app import resolver
        from app.models import Track

        tr = Track(
            id="sc:track:wrong999",
            title="sex drug",
            artist="Sinazza",
            album="Vision",
            durationMs=150_000,
            source="soundcloud",
            sourceUrl="https://soundcloud.com/sinazza/wrong-version",
        )

        candidates = resolver.resolve(tr)
        assert len(candidates) == 1
        assert candidates[0].url == "https://soundcloud.com/sinazza/sex-drug-6"

    def test_canonical_override_matches_numbered_and_prefixed_titles(self):
        """عنوان‌های دارای شماره ترک یا پیشوند هنرمند نیز نگاشت قطعی را دریافت می‌کنند."""
        from app import resolver
        from app.models import Track

        for raw_title in ("06. Sex Drug", "06 Sex Drug", "Sinazza - Sex Drug", "Sex Drug"):
            tr = Track(
                id=f"sc:track:{abs(hash(raw_title))}",
                title=raw_title,
                artist="Sinazza",
                album="Vision",
                durationMs=150_000,
                source="soundcloud",
                sourceUrl="",
            )
            candidates = resolver.resolve(tr)
            assert len(candidates) == 1
            assert candidates[0].url == "https://soundcloud.com/sinazza/sex-drug-6"

    def test_canonical_override_included_in_browse(self, monkeypatch):
        """در browse نیز کاندید قطعی در صدر لیست قرار می‌گیرد."""
        from app import resolver
        from app.models import Track

        tr = Track(
            id="sp:track:test123",
            title="sex drug",
            artist="Sinazza",
            album="Vision",
            durationMs=150_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/test123",
        )

        monkeypatch.setattr(resolver, "_search_source_retrying", lambda *a, **kw: [])
        found = resolver.browse(tr)
        assert len(found) >= 1
        assert found[0].url == "https://soundcloud.com/sinazza/sex-drug-6"
        assert found[0].score == 100.0

    def test_sinazza_deja_vu_canonical_override(self):
        """قطعه Deja Vu از آلبوم Vision Mixtape به لینک رسمی ساندکلاد سینازا مچ می‌شود."""
        from app import resolver
        from app.models import Track

        tr = Track(
            id="sp:track:2DUFJAJfrK0xyb2SnX4wDp",
            title="Deja Vu",
            artist="Sinazza",
            album="Vision Mixtape",
            durationMs=149_000,
            source="spotify",
            sourceUrl="https://open.spotify.com/track/2DUFJAJfrK0xyb2SnX4wDp",
        )

        candidates = resolver.resolve(tr)
        assert len(candidates) == 1
        assert candidates[0].url == "https://soundcloud.com/sinazza/deja-vu"
        assert candidates[0].source == "soundcloud"
        assert candidates[0].score == 100.0

    def test_sinazza_deja_vu_matches_numbered_and_prefixed_titles(self):
        """عنوان‌های دارای شماره ترک ۱۰ یا پیشوند برای Deja Vu نیز نگاشت قطعی را دریافت می‌کنند."""
        from app import resolver
        from app.models import Track

        for raw_title in ("10. Deja Vu", "10 Deja Vu", "10 - Deja Vu", "Sinazza - Deja Vu", "Deja Vu"):
            tr = Track(
                id=f"sc:track:{abs(hash(raw_title))}",
                title=raw_title,
                artist="Sinazza",
                album="Vision Mixtape",
                durationMs=149_000,
                source="soundcloud",
                sourceUrl="",
            )
            candidates = resolver.resolve(tr)
            assert len(candidates) == 1
            assert candidates[0].url == "https://soundcloud.com/sinazza/deja-vu"

    def test_unrelated_artist_with_same_title_penalized_below_min_score(self):
        """آهنگ همنام از خواننده کاملاً بی‌ربط حتی با مدت زمان مشابه باید زیر MIN_SCORE قرار گیرد."""
        from app.resolver import MIN_SCORE, score_candidate
        from app.models import Track

        tr = Track(
            id="sp:track:other_artist",
            title="Deja Vu",
            artist="Sinazza",
            album="Vision Mixtape",
            durationMs=149_000,
            source="spotify",
            sourceUrl="",
        )

        # کاندیدای خواننده دیگر با نام یکسان و مدت زمان تقریباً یکسان
        wrong_cand_score = score_candidate(
            tr,
            title="Deja Vu",
            uploader="Olivia Rodrigo",
            duration_ms=148_000,
            candidate_album="Sour",
        )
        assert wrong_cand_score < MIN_SCORE, f"Expected < {MIN_SCORE}, got {wrong_cand_score}"

    def test_unrelated_artist_cannot_reach_good_enough(self):
        """کاندیدای بدون تطابق هنرمند هرگز نباید به سقف GOOD_ENOUGH برسد."""
        from app.resolver import GOOD_ENOUGH, score_candidate
        from app.models import Track

        tr = Track(
            id="sp:track:other_artist",
            title="Deja Vu",
            artist="Sinazza",
            album="Vision Mixtape",
            durationMs=149_000,
            source="spotify",
            sourceUrl="",
        )

        # حتی با کلمات مثبت و مدت زمان کاملاً برابر
        cand_score = score_candidate(
            tr,
            title="Deja Vu official audio",
            uploader="Random Uploader",
            duration_ms=149_000,
            candidate_album=None,
        )
        assert cand_score < GOOD_ENOUGH


class TestAlbumAwareScoringAndQueries:
    """تست‌های امتیازدهی و جستجوی آلبوم‌محور."""

    def test_matching_album_gets_bonus(self, track):
        from app.resolver import score_candidate

        # عنوان/هنرمندِ کاندیدا باید با ترک بخواند، وگرنه امتیاز همان اول صفر
        # می‌شود و آلبوم هیچ نقشی بازی نمی‌کند.
        tr = track.model_copy(update={"album": "Vision"})
        args = (tr.title, tr.artist, tr.durationMs)
        with_matching_album = score_candidate(tr, *args, candidate_album="Vision")
        without_album = score_candidate(tr, *args, candidate_album=None)
        assert with_matching_album > without_album
        assert with_matching_album - without_album == pytest.approx(15, abs=1)

    def test_conflicting_album_is_penalized(self, track):
        from app.resolver import score_candidate

        tr = track.model_copy(update={"album": "Vision"})
        args = (tr.title, tr.artist, tr.durationMs)
        with_wrong_album = score_candidate(tr, *args, candidate_album="Single Release")
        without_album = score_candidate(tr, *args, candidate_album=None)
        assert with_wrong_album < without_album
        assert without_album - with_wrong_album == pytest.approx(10, abs=1)

    def test_leading_track_number_stripped_in_scoring(self, track):
        from app.resolver import score_candidate

        tr = track.model_copy(update={"title": "Sex Drug", "artist": "Sinazza"})
        score_plain = score_candidate(tr, "Sex Drug", "Sinazza", tr.durationMs)
        score_numbered_dot = score_candidate(tr, "06. Sex Drug", "Sinazza", tr.durationMs)
        score_numbered_space = score_candidate(tr, "06 Sex Drug", "Sinazza", tr.durationMs)
        score_numbered_dash = score_candidate(tr, "6 - Sex Drug", "Sinazza", tr.durationMs)

        assert score_numbered_dot == score_plain
        assert score_numbered_space == score_plain
        assert score_numbered_dash == score_plain

    def test_album_queries_generated_when_album_present(self, track):
        from app.resolver import _queries

        tr = track.model_copy(update={"title": "Sex Drug", "artist": "Sinazza", "album": "Vision"})
        queries = _queries(tr)
        assert "Sinazza - Vision - Sex Drug" in queries
        assert "Sinazza Vision Sex Drug" in queries

    def test_album_queries_omitted_when_no_album(self, track):
        from app.resolver import _queries

        tr = track.model_copy(update={"title": "Sex Drug", "artist": "Sinazza", "album": None})
        queries = _queries(tr)
        assert not any("Vision" in q for q in queries)

