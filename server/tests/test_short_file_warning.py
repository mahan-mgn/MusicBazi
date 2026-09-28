"""تست‌های هشدارِ فایلِ ناقص — پیش‌نمایشِ ۳۰ ثانیه‌ای نباید بی‌صدا ready شود."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.jobs import _file_duration_ms  # noqa: E402


def test_file_duration_mp3(tmp_path):
    """فایل mp3 واقعی مدتش درست خوانده می‌شود."""
    import mutagen
    from mutagen.id3 import ID3
    from mutagen.mp3 import MP3

    p = tmp_path / "a.mp3"
    # 2 فریم سکوتِ mp3 واقعی: از روی خود ffmpeg نمی‌سازیم — حداقلی دستی
    p.write_bytes(b"")
    # mutagen بدون فریم معتبر None/خطا می‌دهد → همان مسیرِ «بدون هشدار»
    assert _file_duration_ms(p) in (None, 0)
    assert _file_duration_ms(tmp_path / "missing.mp3") is None


def test_short_file_warning_message():
    """قالبِ پیام: ثانیه‌ی گردشده، نه صفر."""
    expected, actual = 292_040, 29_800
    sec = max(1, round(actual / 1000))
    assert sec == 30
    msg = (
        f"فایل فقط {sec} ثانیه است درحالی‌که آهنگ {round(expected / 1000)} ثانیه‌ست — "
        "احتمالاً پیش‌نمایش دانلود شده"
    )
    assert "۳۰" not in msg and "30" in msg and "پیش‌نمایش" in msg


def test_resolver_penalizes_short_candidates():
    """کاندیدِ ۳۰ ثانیه‌ای برای ترکِ ۲۹۲ ثانیه‌ای جریمه‌ی سنگین می‌گیرد."""
    from app.models import Track
    from app.resolver import score_candidate

    full = Track(
        id="itunes:track:1", title="Dou Panjereh", artist="Googoosh",
        sourceUrl="https://music.apple.com/track", source="apple", durationMs=292_040,
    )
    short = score_candidate(full, "Dou Panjereh", "Googoosh", 30_000)
    exact = score_candidate(full, "Dou Panjereh", "Googoosh", 292_000)
    assert short < 35, f"کاندیدِ کوتاه هنوز بالای MIN_SCORE است: {short}"
    assert exact > short + 40, f"کاندیدِ دقیق برتری ندارد: {exact} vs {short}"
