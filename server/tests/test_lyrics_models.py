"""
مدل خروجیِ متن و سازگاریِ عقب‌گردِ فیلدهای تازه.

`language`، `provider_id`، `index` و `role` اضافه شده‌اند تا مسیر TTML و
چندزبانه بعداً بدون شکستنِ مصرف‌کننده‌های امروز باز بماند. تست‌های اینجا قفل
می‌کنند که ساختِ مدل *بدون* آن فیلدها هنوز کار می‌کند.
"""

from __future__ import annotations

import dataclasses

from app.lyrics.models import LyricLine, LyricWord, Lyrics


class TestOldConstructionStillWorks:
    """همان چیزی که Providerهای موجود امروز می‌سازند."""

    def test_lrclib_shaped_result(self):
        result = Lyrics(
            plain="plain",
            synced="[00:01.00]line",
            format="lrc",
            sync_type="line",
        )
        assert result.language is None
        assert result.provider_id is None
        assert result.lines == ()
        assert bool(result) is True

    def test_genius_shaped_result(self):
        result = Lyrics(plain="text", format="plain", sync_type="plain")
        assert result.synced is None
        assert result.language is None

    def test_a_line_with_only_the_old_fields(self):
        line = LyricLine(start_ms=1000, text="hello")
        assert line.end_ms is None
        assert line.words == ()
        assert line.index is None
        assert line.role is None

    def test_a_word_with_only_the_old_fields(self):
        word = LyricWord(start_ms=1000, text="hello")
        assert word.end_ms is None


class TestNewFields:
    def test_the_new_fields_are_settable(self):
        result = Lyrics(
            plain="x",
            language="fa",
            provider_id="lrclib",
        )
        assert result.language == "fa"
        assert result.provider_id == "lrclib"

    def test_a_line_can_carry_index_and_role(self):
        line = LyricLine(start_ms=0, text="x", index=3, role="translation")
        assert line.index == 3
        assert line.role == "translation"

    def test_a_fully_populated_ttml_shaped_result(self):
        """شکلی که یک Provider آینده‌ی TTML تولید می‌کند."""
        result = Lyrics(
            language="fa",
            provider_id="ttml-source",
            format="ttml",
            sync_type="word",
            lines=(
                LyricLine(
                    start_ms=1000,
                    end_ms=2000,
                    text="سلام",
                    index=0,
                    role="main",
                    words=(LyricWord(start_ms=1000, end_ms=1500, text="س"),),
                ),
            ),
        )
        assert result.lines[0].words[0].text == "س"
        assert bool(result) is True


class TestModelInvariants:
    def test_lines_are_immutable(self):
        result = Lyrics(lines=(LyricLine(start_ms=0, text="x"),))
        try:
            result.lines[0].text = "y"
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError("LyricLine should be frozen")

    def test_each_result_gets_its_own_lines_tuple(self):
        """default_factory لازم است؛ یک تاپلِ مشترک بین نمونه‌ها یعنی باگِ کلاسیک."""
        a, b = Lyrics(), Lyrics()
        assert a.lines == b.lines == ()

    def test_an_empty_result_is_falsy(self):
        assert bool(Lyrics()) is False

    def test_a_lines_only_result_is_truthy(self):
        assert bool(Lyrics(lines=(LyricLine(start_ms=0, text="x"),))) is True
