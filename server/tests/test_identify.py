"""
شناسایی با فینگرپرینت — پارسِ پاسخ AcoustID.

خودِ fpcalc و شبکه اینجا نیستند؛ چیزی که سنجیده می‌شود انتخاب و یکتاسازیِ
حدس‌هاست، همان جایی که یک ضبطِ تکراری در پنج ریلیز می‌تواند فهرست را پر کند.
"""

from __future__ import annotations

import httpx
import pytest

import pathlib
import subprocess

from app import identify
from app import config


def _result(score, title, artists=("Farhad Mehrad",), duration=185.0):
    return {
        "score": score,
        "recordings": [
            {
                "title": title,
                "duration": duration,
                "artists": [{"name": name} for name in artists],
            }
        ],
    }


def test_sorted_by_confidence():
    found = identify._matches([_result(0.6, "B"), _result(0.95, "A")])
    assert [m.title for m in found] == ["A", "B"]


def test_low_confidence_is_dropped():
    assert identify._matches([_result(0.1, "A")]) == []


def test_same_recording_in_many_releases_is_shown_once():
    found = identify._matches([_result(0.9, "A"), _result(0.8, "A")])
    assert len(found) == 1


def test_duration_comes_back_in_milliseconds():
    assert identify._matches([_result(0.9, "A", duration=185.0)])[0].duration_ms == 185_000


def test_recording_without_a_title_is_skipped():
    assert identify._matches([{"score": 0.9, "recordings": [{"duration": 10}]}]) == []


def test_missing_artist_does_not_break_the_match():
    found = identify._matches([_result(0.9, "A", artists=())])
    assert found[0].artist == "ناشناس"


def test_result_count_is_capped():
    found = identify._matches([_result(0.9, f"T{i}") for i in range(20)])
    assert len(found) == identify.MAX_MATCHES


def test_without_a_key_nothing_is_attempted(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ACOUSTID_KEY", None)
    monkeypatch.setattr(config, "AUDD_TOKEN", None)
    assert identify.identify(tmp_path / "clip.ogg") == []


def test_fingerprint_retries_through_ffmpeg(monkeypatch, tmp_path):
    """
    ویسِ تلگرام (ogg/opus) را دیکدرِ خودِ fpcalc همیشه باز نمی‌کند؛ مسیر دوم
    از ffmpeg رد می‌شود و نباید بی‌صدا رها شود.
    """
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"x")
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"x")

    calls = []

    def fake_fpcalc(path):
        calls.append(path)
        return (30, "FP") if path == wav else None

    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    monkeypatch.setattr(identify, "_run_fpcalc", fake_fpcalc)
    monkeypatch.setattr(identify, "_to_wav", lambda _: wav)

    assert identify.fingerprint(clip) == (30, "FP")
    assert calls == [clip, wav]


def test_missing_names_the_piece_that_is_absent(monkeypatch):
    """
    «نشناختم» و «اصلاً تنظیم نشده» دو چیزند و قبلاً از بیرون یکسان دیده
    می‌شدند؛ این پیام تنها چیزی است که به کاربر می‌گوید بعدش چه کند.
    """
    monkeypatch.setattr(config, "AUDD_TOKEN", None)

    monkeypatch.setattr(config, "ACOUSTID_KEY", "k")
    monkeypatch.setattr(identify, "FPCALC", None)
    assert "fpcalc" in identify.missing()

    monkeypatch.setattr(config, "ACOUSTID_KEY", None)
    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    assert "ACOUSTID" in identify.missing()

    monkeypatch.setattr(identify, "FPCALC", None)
    assert "AUDD" in identify.missing()


def test_nothing_missing_when_configured(monkeypatch):
    monkeypatch.setattr(config, "ACOUSTID_KEY", "k")
    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    assert identify.missing() == ""


def test_audd_alone_is_enough(monkeypatch):
    """
    توکنِ AudD به‌تنهایی شناسایی را روشن می‌کند — fpcalc فقط برای مسیرِ
    AcoustID لازم است.
    """
    monkeypatch.setattr(config, "ACOUSTID_KEY", None)
    monkeypatch.setattr(identify, "FPCALC", None)
    monkeypatch.setattr(config, "AUDD_TOKEN", "t")
    assert identify.available()
    assert identify.missing() == ""


def test_audd_is_tried_before_acoustid(monkeypatch, tmp_path):
    """
    ترتیب اتفاقی نیست: AudD تنها مسیری است که روی ضبطِ میکروفون جواب می‌دهد،
    پس نباید پشتِ یک AcoustIDِ محکوم‌به‌شکست صف بکشد.
    """
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"x")
    called = []

    monkeypatch.setattr(
        identify.audd,
        "recognize",
        lambda path, uid=None: called.append("audd")
        or identify.audd.AuddMatch(title="A", artist="B"),
    )
    monkeypatch.setattr(
        identify, "_by_acoustid", lambda path, fp=None, uid=None: called.append("acoustid") or []
    )

    found = identify.identify(clip)
    assert called == ["audd"]
    assert (found[0].title, found[0].artist) == ("A", "B")


def test_audd_match_has_no_fake_confidence(monkeypatch, tmp_path):
    """AudD عددِ اطمینان نمی‌دهد؛ ساختنِ «۱۰۰٪» فقط اعتمادِ بی‌جا می‌سازد."""
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"x")
    monkeypatch.setattr(
        identify.audd, "recognize", lambda path, uid=None: identify.audd.AuddMatch(title="A", artist="B")
    )
    assert identify.identify(clip)[0].score is None


def test_falls_back_to_acoustid_when_audd_finds_nothing(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp3"
    clip.write_bytes(b"x")
    monkeypatch.setattr(identify.audd, "recognize", lambda path, uid=None: None)
    monkeypatch.setattr(
        identify, "_by_acoustid", lambda path, fp=None, uid=None: [identify.Match("T", "A", 0.9)]
    )
    assert identify.identify(clip)[0].title == "T"


class _Res:
    """پاسخِ آماده‌ی AcoustID — بدون زدنِ شبکه."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_invalid_key_is_not_reported_as_no_match(monkeypatch, tmp_path):
    """
    یک بار همین دو حالت یکسان دیده شدند و کلیدِ نامعتبر ساعت‌ها شبیهِ «این آهنگ
    در کاتالوگ نیست» به نظر می‌رسید.
    """
    clip = tmp_path / "song.mp3"
    clip.write_bytes(b"x")
    monkeypatch.setattr(config, "ACOUSTID_KEY", "bad")
    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    monkeypatch.setattr(identify, "fingerprint", lambda p: (200, "FP"))
    monkeypatch.setattr(
        identify.httpx,
        "post",
        lambda *a, **k: _Res({"status": "error", "error": {"code": 4, "message": "invalid API key"}}),
    )

    with pytest.raises(identify.ServiceError) as caught:
        identify.identify(clip)
    # پیام باید بگوید کدام کلید را از کجا بردارد، نه فقط «رد شد»
    assert "my-applications" in str(caught.value)


def test_network_failure_is_not_a_no_match(monkeypatch, tmp_path):
    clip = tmp_path / "song.mp3"
    clip.write_bytes(b"x")
    monkeypatch.setattr(config, "ACOUSTID_KEY", "k")
    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    monkeypatch.setattr(identify, "fingerprint", lambda p: (200, "FP"))

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(identify.httpx, "post", boom)
    with pytest.raises(identify.ServiceError):
        identify.identify(clip)


def test_real_empty_result_is_still_a_plain_no_match(monkeypatch, tmp_path):
    """سرویس سالم جواب داده و چیزی نداشته — این خطا نیست."""
    clip = tmp_path / "song.mp3"
    clip.write_bytes(b"x")
    monkeypatch.setattr(config, "ACOUSTID_KEY", "k")
    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    monkeypatch.setattr(identify, "fingerprint", lambda p: (200, "FP"))
    monkeypatch.setattr(identify.httpx, "post", lambda *a, **k: _Res({"status": "ok", "results": []}))

    assert identify.identify(clip) == []


def test_audd_rejection_surfaces_when_acoustid_finds_nothing(monkeypatch, tmp_path):
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"x")

    def reject(path, uid=None):
        raise identify.audd.AuddError("AudD: Wrong API token")

    monkeypatch.setattr(identify.audd, "recognize", reject)
    monkeypatch.setattr(identify, "_by_acoustid", lambda p, fp=None, uid=None: [])

    with pytest.raises(identify.ServiceError, match="Wrong API token"):
        identify.identify(clip)


def test_a_working_path_hides_the_broken_one(monkeypatch, tmp_path):
    """
    اگر AudD توکنش خراب باشد ولی AcoustID جواب بدهد، کاربر باید جوابش را
    بگیرد — نه یک خطا درباره‌ی مسیری که اصلاً لازم نبود.
    """
    clip = tmp_path / "song.mp3"
    clip.write_bytes(b"x")

    def reject(path, uid=None):
        raise identify.audd.AuddError("AudD: Wrong API token")

    monkeypatch.setattr(identify.audd, "recognize", reject)
    monkeypatch.setattr(identify, "_by_acoustid", lambda p, fp=None, uid=None: [identify.Match("T", "A", 0.9)])

    assert identify.identify(clip)[0].title == "T"


def test_full_file_tries_the_free_path_first(monkeypatch, tmp_path):
    """
    هر درخواستِ AudD از سهمیه‌ی پولی کم می‌کند؛ فایلِ کامل را AcoustID رایگان
    و بهتر می‌شناسد، پس نباید اول سراغ AudD رفت.
    """
    song = tmp_path / "song.mp3"
    song.write_bytes(b"x")
    order = []

    monkeypatch.setattr(config, "ACOUSTID_KEY", "k")
    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    monkeypatch.setattr(identify, "fingerprint", lambda p: (240, "FP"))
    monkeypatch.setattr(
        identify,
        "_by_acoustid",
        lambda p, fp=None, uid=None: order.append("acoustid") or [identify.Match("T", "A", 0.9)],
    )
    monkeypatch.setattr(identify, "_by_audd", lambda p, uid=None: order.append("audd") or [])

    identify.identify(song)
    assert order == ["acoustid"]


def test_short_clip_goes_straight_to_audd(monkeypatch, tmp_path):
    """تکه‌ی کوتاه را AcoustID عملاً هیچ‌وقت نمی‌شناسد؛ زدنش فقط تأخیر است."""
    clip = tmp_path / "clip.mp3"
    clip.write_bytes(b"x")
    order = []

    monkeypatch.setattr(config, "ACOUSTID_KEY", "k")
    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    monkeypatch.setattr(identify, "fingerprint", lambda p: (15, "FP"))
    monkeypatch.setattr(identify, "_by_acoustid", lambda p, fp=None, uid=None: order.append("acoustid") or [])
    monkeypatch.setattr(
        identify, "_by_audd", lambda p, uid=None: order.append("audd") or [identify.Match("T", "A", None)]
    )

    identify.identify(clip)
    assert order == ["audd"]


def test_long_file_still_falls_through_to_audd(monkeypatch, tmp_path):
    """فایلِ کاملی که در کاتالوگِ AcoustID نیست باید شانسِ دومش را بگیرد."""
    song = tmp_path / "song.mp3"
    song.write_bytes(b"x")
    order = []

    monkeypatch.setattr(config, "ACOUSTID_KEY", "k")
    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    monkeypatch.setattr(identify, "fingerprint", lambda p: (240, "FP"))
    monkeypatch.setattr(identify, "_by_acoustid", lambda p, fp=None, uid=None: order.append("acoustid") or [])
    monkeypatch.setattr(
        identify, "_by_audd", lambda p, uid=None: order.append("audd") or [identify.Match("T", "A", None)]
    )

    assert identify.identify(song)[0].title == "T"
    assert order == ["acoustid", "audd"]


def test_temp_wav_is_removed(monkeypatch, tmp_path):
    """
    fd فایل موقت اگر باز بماند، ویندوز اجازه‌ی حذفش را نمی‌دهد و به‌ازای هر
    ویس/ویدیو یک wav روی دیسک جا می‌ماند.
    """
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"x")
    made: list[str] = []

    def fake_run(cmd, **kwargs):
        made.append(cmd[-1])
        pathlib.Path(cmd[-1]).write_bytes(b"RIFF")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(identify, "FPCALC", "fpcalc")
    monkeypatch.setattr(identify.subprocess, "run", fake_run)
    monkeypatch.setattr(identify, "_run_fpcalc", lambda p: (30, "FP") if p != clip else None)

    assert identify.fingerprint(clip) == (30, "FP")
    assert made and not pathlib.Path(made[0]).exists()
