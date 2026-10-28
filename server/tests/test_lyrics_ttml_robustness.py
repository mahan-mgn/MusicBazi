"""
P2 — سخت‌سازیِ پارسرِ TTML.

اصل: وقتی ساختارِ سند از چیزی که پارسر پیاده کرده **بیرون** است، باید
`None` بدهد — نه زمان‌بندیِ خاموشِ غلط. یک متنِ با زمانِ اشتباه از نبودِ متن
بدتر است: کاربر نمی‌فهمد چرا پخش هماهنگ نیست.

سه چیزی که پشتیبانی نمی‌شوند و باید fail-safe شوند:
  ۱. `ttp:timeBase` غیر از `media` — عددِ بی‌واحد آنجا ثانیه نیست.
  ۲. `timeContainer="seq"` روی والد — فرزندها ترتیبی‌اند نه مطلق.
  ۳. زمانِ `begin` روی والدِ `<p>` — نسبی است نه مطلق.
"""

from __future__ import annotations

import pytest

from app.lyrics.parsers import parse_ttml

_NS = 'xmlns="http://www.w3.org/ns/ttml"'
_TTP = 'xmlns:ttp="http://www.w3.org/ns/ttml#parameter"'


class TestUnsupportedTimeBaseIsRejected:
    @pytest.mark.parametrize("base", ["clock", "smpte", "smpte-30-drop"])
    def test_a_non_media_time_base_yields_nothing(self, base):
        """
        با `timeBase="clock"`، `27.395` ثانیه نیست. اگر مثلِ media خوانده
        شود، زمانِ غلط تولید می‌شود.
        """
        ttml = (
            f'<tt {_NS} {_TTP} ttp:timeBase="{base}"><body><div>'
            '<p begin="27.395" end="28.5">x</p>'
            "</div></body></tt>"
        )

        assert parse_ttml(ttml) is None

    def test_the_media_base_is_still_accepted(self):
        ttml = (
            f'<tt {_NS} {_TTP} ttp:timeBase="media"><body><div>'
            '<p begin="27.395" end="28.5">x</p>'
            "</div></body></tt>"
        )

        found = parse_ttml(ttml)

        assert found is not None
        assert found.lines[0].start_ms == 27_395

    def test_an_absent_time_base_defaults_to_media(self):
        """پیش‌فرضِ متعارفِ TTML مدیاست؛ نبودش رد نمی‌کند."""
        ttml = f'<tt {_NS}><body><div><p begin="5s">x</p></div></body></tt>'

        assert parse_ttml(ttml) is not None


class TestSequentialContainersAreRejected:
    def test_time_container_seq_yields_nothing(self):
        """
        در `seq`، زمانِ هر فرزند از پایانِ قبلی شمرده می‌شود — نه از صفرِ
        متن. پارسر این را پیاده نکرده، پس باید `None` بدهد.
        """
        ttml = (
            f'<tt {_NS}><body><div timeContainer="seq">'
            '<p begin="2s">a</p><p begin="3s">b</p>'
            "</div></body></tt>"
        )

        assert parse_ttml(ttml) is None

    def test_time_container_par_is_still_accepted(self):
        ttml = (
            f'<tt {_NS}><body><div timeContainer="par">'
            '<p begin="2s">a</p><p begin="3s">b</p>'
            "</div></body></tt>"
        )

        found = parse_ttml(ttml)

        assert found is not None
        assert [line.start_ms for line in found.lines] == [2000, 3000]


class TestParentRelativeTimesAreRejected:
    def test_a_contradictory_parent_begin_is_rejected(self):
        """
        `<div begin="60s"><p begin="1s">`: زمانِ فرزند از والدش **کوچک‌تر**
        است. خوانشِ نسبی عددی بی‌معنا می‌دهد و خوانشِ مطلق خطی خارج از
        پنجرهٔ والد. هر دو غلط‌اند، پس سند رد می‌شود.
        """
        ttml = (
            f'<tt {_NS}><body><div begin="60s">'
            '<p begin="1s" end="2s">x</p>'
            "</div></body></tt>"
        )

        assert parse_ttml(ttml) is None

    def test_a_parent_begin_matching_the_child_is_accepted(self):
        """
        شکلِ **واقعیِ** binilyrics/lrc.red: `<div begin="27.395">` و
        `<p begin="27.395">` برابرند — یعنی زمان مطلق است. رد کردن این
        شکل به‌طورِ کلی یعنی دور ریختنِ متنِ واقعی.
        """
        ttml = (
            f'<tt {_NS}><body><div dur="3:21.570">'
            '<div begin="27.395" end="48.621">'
            '<p begin="27.395" end="28.96">a</p>'
            '<p begin="30.189" end="32.529">b</p>'
            "</div></div></body></tt>"
        )

        found = parse_ttml(ttml)

        assert found is not None
        assert [line.start_ms for line in found.lines] == [27_395, 30_189]

    def test_a_parent_begin_before_the_child_is_accepted_as_absolute(self):
        """
        `<div begin="2:30.712">` با `<p begin="3:10.387">` — فرزند بزرگ‌تر
        است، پس خوانشِ مطلق سازگار است (والد فقط پنجره را می‌گوید).
        """
        ttml = (
            f'<tt {_NS}><body><div begin="2:30.712" end="3:14.870">'
            '<p begin="3:10.387" end="3:14.870">x</p>'
            "</div></body></tt>"
        )

        found = parse_ttml(ttml)

        assert found is not None
        assert found.lines[0].start_ms == 190_387

    def test_a_nested_span_begin_does_not_invalidate_the_document(self):
        """
        `<span>`های داخلِ `p` زمان‌شان **مطلق** است (دادهٔ واقعیِ binilyrics
        همین را نشان داد)، پس والدِ span مشکل‌ساز نیست.
        """
        ttml = (
            f'<tt {_NS}><body><div>'
            '<p begin="10s" end="12s"><span begin="10s">a</span><span begin="11s">b</span></p>'
            "</div></body></tt>"
        )

        found = parse_ttml(ttml)

        assert found is not None
        assert [w.start_ms for w in found.lines[0].words] == [10_000, 11_000]

    def test_a_parent_dur_alone_does_not_invalidate(self):
        """
        `<div dur="3:21.570">` فقط طولِ ظرف را می‌گوید و به زمانِ فرزندها
        کاری ندارد — در دادهٔ واقعی هم همین شکل بود.
        """
        ttml = (
            f'<tt {_NS}><body><div dur="3:21.570">'
            '<p begin="27.395" end="28.96">x</p>'
            "</div></body></tt>"
        )

        assert parse_ttml(ttml) is not None


class TestRealWorldTimestampForms:
    """
    قالب‌های زمانیِ دیده‌شده در پاسخ‌های واقعی (ثبت‌شده در گزارش‌های ۰۴ و ۰۶).
    اگر روزی یکی از این‌ها بشکند، رگرسیونِ بی‌صدا است.
    """

    def _one(self, begin: str, end: str | None = None):
        end_attr = f' end="{end}"' if end else ""
        ttml = (
            f'<tt {_NS}><body><div><p begin="{begin}"{end_attr}>x</p></div></body></tt>'
        )
        return parse_ttml(ttml)

    @pytest.mark.parametrize(
        "begin,expected_ms",
        [
            ("27.395", 27_395),      # seconds with a fraction
            ("0.5", 500),            # sub-second
            ("60.9", 60_900),        # past a minute
            ("2:52.186", 172_186),   # m:ss.fff
            ("3:21.570", 201_570),   # m:ss.fff، همان مقدارِ dur در واقعیت
            ("1:00.964", 60_964),    # the line that survived the old bug
            ("00:00:12.500", 12_500),  # hh:mm:ss.fff
            ("27.395s", 27_395),     # explicit unit
            ("1500ms", 1_500),       # milliseconds
            ("1m", 60_000),          # whole minutes
        ],
    )
    def test_each_real_form_is_converted(self, begin, expected_ms):
        found = self._one(begin)

        assert found is not None
        assert found.lines[0].start_ms == expected_ms

    def test_the_pair_seen_in_real_payloads(self):
        """دادهٔ واقعی: `begin="27.395" end="28.960"`."""
        found = self._one("27.395", "28.960")

        assert found.lines[0].start_ms == 27_395
        assert found.lines[0].end_ms == 28_960

    def test_an_unparsable_stamp_does_not_kill_the_document(self):
        ttml = (
            f'<tt {_NS}><body><div>'
            '<p begin="garbage">bad</p>'
            '<p begin="5s">good</p>'
            "</div></body></tt>"
        )

        found = parse_ttml(ttml)

        assert [line.text for line in found.lines] == ["good"]


class TestRejectionIsNotOverzealous:
    """نبودِ این‌ها نباید سند را رد کند — وگرنه منابعِ سالم از کار می‌افتند."""

    def test_a_plain_document_without_clock_declarations_still_parses(self):
        ttml = f'<tt {_NS}><body><div><p begin="1s">a</p></div></body></tt>'

        assert parse_ttml(ttml) is not None

    def test_a_frame_rate_declaration_alone_is_fine(self):
        ttml = (
            f'<tt {_NS} {_TTP} ttp:frameRate="25"><body><div>'
            '<p begin="00:00:01:05">a</p>'
            "</div></body></tt>"
        )

        found = parse_ttml(ttml)

        assert found is not None and found.lines[0].start_ms == 1_200

    def test_a_tick_rate_declaration_alone_is_fine(self):
        ttml = (
            f'<tt {_NS} {_TTP} ttp:tickRate="1000"><body><div>'
            '<p begin="1500t">a</p>'
            "</div></body></tt>"
        )

        found = parse_ttml(ttml)

        assert found is not None and found.lines[0].start_ms == 1_500
