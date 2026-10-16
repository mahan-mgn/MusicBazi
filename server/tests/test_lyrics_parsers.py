"""
پارسرهای متن: LRC خطی، LRC تقویت‌شده، TTML.

fixtureها همه ساختگی و کوچک‌اند — هیچ متنِ کپی‌رایت‌داری اینجا نیست. تمرکز
روی سه چیز است: درستیِ تبدیلِ زمان، نریختنِ کلِ پارس روی یک خطِ خراب، و
امنیتِ XML در برابر entity expansion.
"""

from __future__ import annotations

import pytest

from app.lyrics.parsers import (
    parse_enhanced_lrc,
    parse_lrc,
    parse_ttml,
    to_enhanced_lrc,
    to_lrc,
)


# ---------------------------------------------------------------- LRC خطی


class TestParseLrc:
    def test_a_simple_line_becomes_one_timed_line(self):
        found = parse_lrc("[00:12.50]hello")

        assert found.sync_type == "line"
        assert found.format == "lrc"
        assert len(found.lines) == 1
        assert found.lines[0].start_ms == 12_500
        assert found.lines[0].text == "hello"

    def test_several_timestamps_on_one_line_repeat_the_text(self):
        """LRC معمولاً برای خطِ تکرارشده همین کار را می‌کند."""
        found = parse_lrc("[00:10.00][00:20.00]again")

        assert [line.start_ms for line in found.lines] == [10_000, 20_000]
        assert [line.text for line in found.lines] == ["again", "again"]

    def test_the_line_index_is_assigned_after_sorting(self):
        found = parse_lrc("[00:20.00]second\n[00:10.00]first")

        assert [line.text for line in found.lines] == ["first", "second"]
        assert [line.index for line in found.lines] == [0, 1]

    def test_metadata_lines_are_not_lyric_lines(self):
        text = "[ar:Someone]\n[ti:A Song]\n[al:An Album]\n[length:03:20]\n[00:01.00]real line"

        found = parse_lrc(text)

        assert [line.text for line in found.lines] == ["real line"]

    def test_an_offset_shifts_every_line(self):
        """
        `offset` اعمال می‌شود. علامتش اینجا «tag - offset» است؛ جهتِ دقیق
        محتاجِ راستی‌آزمایی با فایلِ واقعی است ولی *اعمال شدنش* قفل می‌شود.
        """
        found = parse_lrc("[offset:+500]\n[00:10.00]shifted")

        assert found.lines[0].start_ms == 9_500

    def test_a_negative_offset_shifts_the_other_way(self):
        found = parse_lrc("[offset:-500]\n[00:10.00]shifted")

        assert found.lines[0].start_ms == 10_500

    def test_a_broken_offset_is_ignored_not_fatal(self):
        found = parse_lrc("[offset:banana]\n[00:10.00]fine")

        assert found.lines[0].start_ms == 10_000

    def test_an_offset_never_produces_a_negative_time(self):
        """زمانِ منفی در UI به معنیِ خطِ همیشه‌فعال است؛ صفر می‌شود."""
        found = parse_lrc("[offset:+60000]\n[00:05.00]early")

        assert found.lines[0].start_ms == 0

    def test_an_untimed_line_is_not_a_lyric_line(self):
        found = parse_lrc("just some text\n[00:10.00]timed")

        assert [line.text for line in found.lines] == ["timed"]

    def test_no_timestamps_at_all_returns_none(self):
        assert parse_lrc("just text\nmore text") is None

    def test_empty_and_none_input_return_none(self):
        assert parse_lrc("") is None
        assert parse_lrc(None) is None

    @pytest.mark.parametrize(
        "stamp,expected_ms",
        [
            ("[00:01.5]", 1_500),      # یک رقم = دهم ثانیه
            ("[00:01.50]", 1_500),
            ("[00:01.500]", 1_500),
            ("[00:01.05]", 1_050),
            ("[00:01:50]", 1_500),     # کولون به‌جای نقطه
            ("[00:01]", 1_000),        # بدون کسر
            ("[01:00.00]", 60_000),
        ],
    )
    def test_centiseconds_are_padded_not_read_as_tenths(self, stamp, expected_ms):
        """`[00:01.5]` باید ۱۵۰۰ms باشد نه ۵۰ms — همان قاعده‌ی `lrc.ts`."""
        assert parse_lrc(f"{stamp}x").lines[0].start_ms == expected_ms

    def test_a_multi_line_body_keeps_emoji_and_persian(self):
        found = parse_lrc("[00:01.00]سلام دنیا 🎵")

        assert found.lines[0].text == "سلام دنیا 🎵"

    def test_the_plain_and_synced_fields_are_both_filled(self):
        found = parse_lrc("[00:10.00]one\n[00:20.00]two")

        assert found.plain == "one\ntwo"
        assert found.synced == "[00:10.00]one\n[00:20.00]two"

    def test_a_broken_line_does_not_kill_its_neighbours(self):
        found = parse_lrc("[00:10.00]good\n[gg:ss.xx]bad\n[00:20.00]also good")

        assert [line.text for line in found.lines] == ["good", "also good"]


# ---------------------------------------------------------------- Enhanced LRC


class TestParseEnhancedLrc:
    def test_word_tags_produce_word_timing(self):
        found = parse_enhanced_lrc("[00:12.00]<00:12.00>Hello <00:13.00>world")

        assert found.sync_type == "word"
        assert found.format == "enhanced_lrc"
        line = found.lines[0]
        assert [w.text for w in line.words] == ["Hello ", "world"]
        assert [w.start_ms for w in line.words] == [12_000, 13_000]

    def test_a_word_end_is_the_start_of_the_next_word(self):
        found = parse_enhanced_lrc("[00:12.00]<00:12.00>a<00:13.00>b")

        assert found.lines[0].words[0].end_ms == 13_000

    def test_the_last_word_ends_at_the_next_line(self):
        found = parse_enhanced_lrc("[00:12.00]<00:12.00>a\n[00:20.00]<00:20.00>b")

        assert found.lines[0].words[-1].end_ms == 20_000

    def test_the_last_word_of_the_last_line_has_no_end(self):
        """پایانِ آخرین کلمه را فقط خودِ ترک می‌داند، نه فایل."""
        found = parse_enhanced_lrc("[00:12.00]<00:12.00>a")

        assert found.lines[0].words[-1].end_ms is None

    def test_the_gap_between_words_sticks_to_the_previous_word(self):
        """
        فاصله‌ها جزوِ کلمه‌ی قبلی‌اند تا گرادیانِ رنگ از رویشان هم رد شود —
        دقیقاً قاعده‌ی `lrc.ts`.
        """
        found = parse_enhanced_lrc("[00:12.00]<00:12.00>Hello<00:13.00> world")

        assert found.lines[0].words[0].text == "Hello"

    def test_the_line_text_is_the_join_of_its_words(self):
        found = parse_enhanced_lrc("[00:12.00]<00:12.00>one <00:13.00>two")

        assert found.lines[0].text == "one two"

    def test_a_line_without_word_tags_falls_back_to_line_synced(self):
        found = parse_enhanced_lrc("[00:12.00]plain line")

        assert found.lines[0].words == ()
        assert found.sync_type == "line"
        assert found.format == "lrc"

    def test_a_mix_keeps_word_timing_only_where_it_exists(self):
        found = parse_enhanced_lrc(
            "[00:12.00]<00:12.00>timed\n[00:20.00]untimed"
        )

        assert found.lines[0].words != ()
        assert found.lines[1].words == ()
        assert found.sync_type == "word"  # یکی کافی است

    def test_an_empty_word_tag_line_is_treated_as_instrumental(self):
        """خطِ «فقطِ تگِ خالی» کلمه‌ی واقعی ندارد — مثل خطِ بی‌کلام."""
        found = parse_enhanced_lrc("[00:12.00]<00:12.00>")

        assert found.lines[0].words == ()

    def test_empty_and_none_input_return_none(self):
        assert parse_enhanced_lrc("") is None
        assert parse_enhanced_lrc(None) is None


# ---------------------------------------------------------------- TTML


_TTML_CLOCK = """<?xml version="1.0" encoding="utf-8"?>
<tt xmlns="http://www.w3.org/ns/ttml"
    xmlns:ttm="http://www.w3.org/ns/ttml#metadata"
    xml:lang="fa">
  <body><div>
    <p begin="00:00:12.500" end="00:00:15.000">خط اول</p>
    <p begin="00:00:15.000" end="00:00:18.000">خط دوم</p>
  </div></body>
</tt>
"""


class TestParseTtmlClockTime:
    def test_clock_times_are_converted_to_ms(self):
        found = parse_ttml(_TTML_CLOCK)

        assert found.format == "ttml"
        assert found.sync_type == "line"
        assert [line.start_ms for line in found.lines] == [12_500, 15_000]
        assert [line.end_ms for line in found.lines] == [15_000, 18_000]

    def test_the_language_comes_from_the_root(self):
        assert parse_ttml(_TTML_CLOCK).language == "fa"

    def test_the_line_order_is_preserved_in_index(self):
        found = parse_ttml(_TTML_CLOCK)

        assert [line.index for line in found.lines] == [0, 1]
        assert [line.text for line in found.lines] == ["خط اول", "خط دوم"]

    def test_short_clock_forms_are_accepted(self):
        """`mm:ss` و `hh:mm:ss` هر دو، با و بدون کسر."""
        text = """<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
        <p begin="00:12.5" end="00:15">fraction</p>
        <p begin="01:02.500" end="01:05">mm:ss</p>
        <p begin="01:00:00" end="01:00:05">hh:mm:ss</p>
        </div></body></tt>"""

        found = parse_ttml(text)

        assert [line.start_ms for line in found.lines] == [12_500, 62_500, 3_600_000]

    def test_a_bare_number_without_a_unit_is_not_a_time(self):
        """`12.5` بی‌واحد نه ساعت است نه ثانیه — TTML واحد را الزامی می‌داند."""
        text = """<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
        <p begin="12.5">ambiguous</p>
        <p begin="00:01.00">valid</p>
        </div></body></tt>"""

        found = parse_ttml(text)

        assert [line.text for line in found.lines] == ["valid"]

    def test_a_clock_with_frames_is_accepted(self):
        text = """<tt xmlns="http://www.w3.org/ns/ttml"
            xmlns:ttp="http://www.w3.org/ns/ttml#parameter"
            ttp:frameRate="25"><body><div>
        <p begin="00:00:01:05" end="00:00:02:00">framed</p>
        </div></body></tt>"""

        found = parse_ttml(text)

        # ۱ ثانیه و ۵ فریم با ۲۵fps = ۱۲۰۰ms
        assert found.lines[0].start_ms == 1_200

    def test_a_root_without_the_tt_namespace_is_handled(self):
        """پیشوندِ namespace در سندهای واقعی دلخواه است."""
        text = '<tt:tt xmlns:tt="http://www.w3.org/ns/ttml"><tt:body><tt:div><tt:p begin="0s">x</tt:p></tt:div></tt:body></tt:tt>'

        found = parse_ttml(text)

        assert found.lines[0].text == "x"


class TestParseTtmlOffsetTime:
    def test_offset_times_with_units_are_converted(self):
        text = """<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
        <p begin="1500ms" end="3s">a</p>
        <p begin="2m" end="2m30s">b</p>
        <p begin="1h">c</p>
        </div></body></tt>"""

        found = parse_ttml(text)

        assert found.lines[0].start_ms == 1_500
        assert found.lines[0].end_ms == 3_000
        assert found.lines[1].start_ms == 120_000
        assert found.lines[1].end_ms == 150_000
        assert found.lines[2].start_ms == 3_600_000

    def test_a_duration_instead_of_an_end_is_used(self):
        text = """<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
        <p begin="5s" dur="2s">a</p>
        </div></body></tt>"""

        found = parse_ttml(text)

        assert found.lines[0].end_ms == 7_000


class TestParseTtmlTicks:
    def test_ticks_use_the_documents_tick_rate(self):
        text = """<tt xmlns="http://www.w3.org/ns/ttml"
            xmlns:ttp="http://www.w3.org/ns/ttml#parameter"
            ttp:tickRate="1000"><body><div>
        <p begin="1250t">a</p>
        </div></body></tt>"""

        found = parse_ttml(text)

        assert found.lines[0].start_ms == 1_250


class TestParseTtmlSpansAndRoles:
    def test_spans_inside_a_paragraph_become_words(self):
        text = """<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
        <p begin="10s" end="12s"><span begin="10s">one </span><span begin="11s">two</span></p>
        </div></body></tt>"""

        found = parse_ttml(text)

        assert found.sync_type == "word"
        assert [w.text for w in found.lines[0].words] == ["one ", "two"]
        assert [w.start_ms for w in found.lines[0].words] == [10_000, 11_000]

    def test_a_role_is_carried_onto_the_line(self):
        text = """<tt xmlns="http://www.w3.org/ns/ttml"
            xmlns:ttm="http://www.w3.org/ns/ttml#metadata"><body><div>
        <p begin="10s" ttm:role="translation">ترجمه</p>
        <p begin="10s" ttm:role="background">پس‌زمینه</p>
        </div></body></tt>"""

        found = parse_ttml(text)

        assert [line.role for line in found.lines] == ["translation", "background"]

    def test_a_line_without_a_begin_is_skipped(self):
        text = """<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
        <p>no timing</p>
        <p begin="1s">timed</p>
        </div></body></tt>"""

        found = parse_ttml(text)

        assert [line.text for line in found.lines] == ["timed"]


class TestParseTtmlSafety:
    def test_a_document_with_a_doctype_is_rejected(self):
        """XXE: یک DOCTYPE می‌تواند فایلِ محلی را بکشد داخلِ سند."""
        text = """<?xml version="1.0"?>
<!DOCTYPE tt [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
<p begin="1s">&xxe;</p>
</div></body></tt>"""

        assert parse_ttml(text) is None

    def test_a_billion_laughs_document_is_rejected_before_expansion(self):
        text = """<?xml version="1.0"?>
<!DOCTYPE tt [
  <!ENTITY a "aaaaaaaaaa">
  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
  <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">
]>
<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="1s">&c;</p></div></body></tt>"""

        assert parse_ttml(text) is None

    def test_a_lowercase_doctype_is_also_rejected(self):
        text = '<!doctype tt><tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="1s">x</p></div></body></tt>'

        assert parse_ttml(text) is None

    def test_malformed_xml_returns_none(self):
        assert parse_ttml("<tt><body><div><p begin='1s'>unclosed") is None

    def test_a_document_without_timed_paragraphs_returns_none(self):
        assert parse_ttml('<tt xmlns="http://www.w3.org/ns/ttml"><body/></tt>') is None

    def test_a_non_ttml_document_returns_none(self):
        assert parse_ttml("<html><body>nope</body></html>") is None

    def test_empty_and_none_input_return_none(self):
        assert parse_ttml("") is None
        assert parse_ttml(None) is None

    def test_a_broken_paragraph_does_not_lose_the_good_ones(self):
        text = """<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
        <p begin="garbage">bad</p>
        <p begin="5s">good</p>
        </div></body></tt>"""

        found = parse_ttml(text)

        assert [line.text for line in found.lines] == ["good"]


# ---------------------------------------------------------------- سریال‌سازی


class TestSerialization:
    def test_to_lrc_matches_the_frontend_parser_expectation(self):
        found = parse_lrc("[00:10.00]one\n[01:05.50]two")

        assert to_lrc(found.lines) == "[00:10.00]one\n[01:05.50]two"

    def test_the_centisecond_rounding_loses_at_most_five_ms(self):
        """
        LRC فقط صدم‌ثانیه دارد. یک خطِ با ms عجیب می‌نویسیم، دوباره می‌خوانیم،
        و اندازه‌ی اتلاف را می‌سنجیم — به‌جای ادعای «دقیق است».
        """
        source = parse_lrc("[00:01.00]x").lines
        from app.lyrics.models import LyricLine

        for original in (12_505, 12_504, 12_514, 12_515):
            line = LyricLine(start_ms=original, text="x")
            round_tripped = parse_lrc(to_lrc([line])).lines[0].start_ms
            assert abs(round_tripped - original) <= 5

    def test_a_carry_does_not_produce_seconds_of_100(self):
        """۱۵۰۰ms باید `00:01.50` شود نه `00:00.150` یا `00:01.100`."""
        from app.lyrics.models import LyricLine

        assert to_lrc([LyricLine(start_ms=1_500, text="x")]) == "[00:01.50]x"

    def test_a_minute_boundary_rolls_correctly(self):
        from app.lyrics.models import LyricLine

        assert to_lrc([LyricLine(start_ms=59_999, text="x")]) == "[01:00.00]x"

    def test_to_enhanced_lrc_writes_word_tags(self):
        found = parse_enhanced_lrc("[00:12.00]<00:12.00>a<00:13.00>b")

        assert to_enhanced_lrc(found.lines) == "[00:12.00]<00:12.00>a<00:13.00>b"

    def test_to_enhanced_lrc_keeps_wordless_lines_simple(self):
        found = parse_enhanced_lrc("[00:12.00]<00:12.00>a\n[00:20.00]plain")

        assert to_enhanced_lrc(found.lines) == "[00:12.00]<00:12.00>a\n[00:20.00]plain"


class TestRoundTrip:
    def test_a_line_synced_round_trip_preserves_order_and_text(self):
        original = parse_lrc("[00:20.00]two\n[00:10.00]one\n[00:30.00]three")

        again = parse_lrc(to_lrc(original.lines))

        assert [line.text for line in again.lines] == ["one", "two", "three"]
        assert [line.start_ms for line in again.lines] == [10_000, 20_000, 30_000]
        assert [line.index for line in again.lines] == [0, 1, 2]

    def test_a_word_synced_round_trip_preserves_word_order(self):
        original = parse_enhanced_lrc(
            "[00:12.00]<00:12.00>one <00:13.00>two\n[00:20.00]<00:20.00>three"
        )

        again = parse_enhanced_lrc(to_enhanced_lrc(original.lines))

        assert [w.text for w in again.lines[0].words] == ["one ", "two"]
        assert [w.start_ms for w in again.lines[0].words] == [12_000, 13_000]
        assert again.lines[1].words[0].text == "three"

    def test_word_ends_are_rebuilt_from_the_next_word(self):
        """`end_ms` در LRC ذخیره نمی‌شود؛ باید از شروعِ کلمه‌ی بعدی ساخته شود."""
        original = parse_enhanced_lrc("[00:12.00]<00:12.00>a<00:13.00>b")

        again = parse_enhanced_lrc(to_enhanced_lrc(original.lines))

        assert again.lines[0].words[0].end_ms == 13_000


class TestInteropWithTheExistingModel:
    def test_the_result_uses_the_shared_lyrics_model(self):
        from app.lyrics.models import Lyrics

        found = parse_lrc("[00:10.00]x")

        assert isinstance(found, Lyrics)
        assert found.lines and found.plain and found.synced

    def test_the_model_still_carries_words_and_lines(self):
        """`LyricWord`/`LyricLine` و `lines` نباید حذف شوند."""
        from app.lyrics.models import LyricLine, LyricWord, Lyrics

        assert "lines" in Lyrics.__dataclass_fields__
        assert "words" in LyricLine.__dataclass_fields__
        assert "start_ms" in LyricWord.__dataclass_fields__

    def test_a_lyrics_object_with_only_lines_is_truthy(self):
        from app.lyrics.models import LyricLine, Lyrics

        assert bool(Lyrics(lines=(LyricLine(start_ms=0, text="x"),))) is True
