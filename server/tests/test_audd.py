"""
شناسایی با AudD — پارسِ پاسخ.

خودِ سرویس پولی است و اینجا زده نمی‌شود. چیزی که سنجیده می‌شود مرزِ بینِ دو
حالتِ کاملاً متفاوت است: «سرویس جواب داد ولی نشناخت» (که None است و یک جوابِ
معتبر) در برابر «سرویس درخواست را رد کرد» (که استثناست و کاربر باید ببیندش).
"""

from __future__ import annotations

import httpx
import pytest

from app.providers import audd
from app import config


class _Res:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError("boom")

    def json(self):
        return self._payload


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "clip.ogg"
    path.write_bytes(b"x")
    return path


def _reply(monkeypatch, payload, status=200):
    monkeypatch.setattr(config, "AUDD_TOKEN", "t")
    monkeypatch.setattr(audd.httpx, "post", lambda *a, **k: _Res(payload, status))


def test_reads_title_and_artist(monkeypatch, clip):
    _reply(
        monkeypatch,
        {"status": "success", "result": {"title": "Taghdir", "artist": "Shadmehr Aghili"}},
    )
    found = audd.recognize(clip)
    assert (found.title, found.artist) == ("Taghdir", "Shadmehr Aghili")


def test_empty_result_is_not_a_match(monkeypatch, clip):
    """«پیدا نشد» هم status=success است، فقط result خالی دارد."""
    _reply(monkeypatch, {"status": "success", "result": None})
    assert audd.recognize(clip) is None


def test_rejection_is_an_error_not_a_no_match(monkeypatch, clip):
    """
    توکنِ غلط با «نشناختم» یکی نیست. یک بار همین یکسان‌بودن باعث شد یک کلیدِ
    نامعتبر ساعت‌ها شبیهِ «این آهنگ در کاتالوگ نیست» به نظر برسد.
    """
    _reply(
        monkeypatch,
        {"status": "error", "error": {"error_code": 900, "error_message": "Wrong API token"}},
    )
    with pytest.raises(audd.AuddError, match="Wrong API token"):
        audd.recognize(clip)


def test_network_failure_is_an_error_too(monkeypatch, clip):
    monkeypatch.setattr(config, "AUDD_TOKEN", "t")

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(audd.httpx, "post", boom)
    with pytest.raises(audd.AuddError):
        audd.recognize(clip)


def test_missing_artist_does_not_break_the_match(monkeypatch, clip):
    _reply(monkeypatch, {"status": "success", "result": {"title": "T"}})
    assert audd.recognize(clip).artist == "ناشناس"


def test_without_a_token_nothing_leaves_the_machine(monkeypatch, clip):
    """بدون توکن هیچ درخواستی نباید ساخته شود — صوتِ کاربر جای دیگری نمی‌رود."""
    monkeypatch.setattr(config, "AUDD_TOKEN", None)

    def boom(*a, **k):
        raise AssertionError("نباید صدا زده شود")

    monkeypatch.setattr(audd.httpx, "post", boom)
    assert audd.recognize(clip) is None
    assert not audd.enabled()


def test_missing_file_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AUDD_TOKEN", "t")
    assert audd.recognize(tmp_path / "gone.ogg") is None
