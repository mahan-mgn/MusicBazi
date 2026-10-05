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

    def test_duration_is_the_strongest_signal(self, track):
        """عنوانِ یکسان ولی طولِ خیلی متفاوت، جریمه می‌خورد — حتی وقتی متن کامل match است."""
        same = score(track, "Farhad Mehrad - Mard-e Tanha")
        off = score(track, "Farhad Mehrad - Mard-e Tanha", duration_ms=track.durationMs + 90_000)
        # عنوان+هنرمند اینجا کامل match هستند، پس جریمه‌ی نرم‌تر (۱۵) می‌خورد نه ۳۵
        assert same - off == pytest.approx(45, abs=1)  # ۳۰ امتیاز مثبت + ۱۵ منفی

    def test_close_duration_still_scores_well(self, track):
        near = score(track, "Farhad Mehrad - Mard-e Tanha", duration_ms=track.durationMs + 1500)
        assert near >= GOOD_ENOUGH

    def test_exact_text_match_survives_a_big_duration_gap(self, track):
        """
        عنوان و هنرمند کاملاً match هستند ولی نسخه‌ی یوتیوب حدود ۵۰ ثانیه
        بلندتر است (مثلاً کاتِ رادیویی در برابر نسخه‌ی کامل). این معمولاً یعنی
        همان ترک با کاتِ متفاوت، نه ویدیوی اشتباه — نباید کامل رد شود.
        """
        result = score(track, "Farhad Mehrad - Mard-e Tanha", duration_ms=track.durationMs + 49_000)
        assert result >= MIN_SCORE

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
        assert score(track, f"{track.artist} - {track.title}", "Discovery Records") == clean

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

        def flaky(tr, source, min_score=resolver.MIN_SCORE):
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

        def always_fail(tr, source, min_score=resolver.MIN_SCORE):
            raise OSError("down for good")

        monkeypatch.setattr(resolver, "_search_source", always_fail)
        # نباید استثنا بالا بیاید؛ منبعِ بعدی باید فرصت داشته باشد
        assert resolver._search_source_retrying(track, "soundcloud") == []

    def test_soundcloud_is_tried_first(self, track, monkeypatch):
        from app import resolver
        from app.resolver import Candidate

        order: list[str] = []

        def by_source(tr, source, min_score=resolver.MIN_SCORE):
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

        def by_source(tr, source, min_score=resolver.MIN_SCORE):
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
        # ساندکلاد خالی بود — نوبت به یوتیوب رسید
        assert order == ["soundcloud", "youtube"]
        assert found and found[0].source == "youtube"

    def test_falls_back_to_youtube_when_soundcloud_errors(self, track, monkeypatch):
        from app import resolver
        from app.resolver import Candidate

        def by_source(tr, source, min_score=resolver.MIN_SCORE):
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
