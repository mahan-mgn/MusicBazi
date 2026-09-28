"""
منطق‌ِ app.bot.run — تنها فایلِ بات که قبلاً تست نداشت. برخلافِ test_bot_logic.py
که فقط توابعِ خالص را می‌زند، اینجا مسیرهای async (دانلود، تحویل، وضعیت) با
ApiClient و context.bot تقلبی واقعاً اجرا می‌شوند تا خطاهای زمانِ اجرا (نه فقط
منطقی) هم گیر بیفتند.
"""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from telegram import ForceReply
from telegram.error import BadRequest, NetworkError, TimedOut

from app.bot import run, store
from app.bot.logic import TELEGRAM_FILE_LIMIT
from app.models import (
    AlbumDetail,
    ArtistDetail,
    ChapterInfo,
    ChaptersInfo,
    DailyMix,
    DownloadProgress,
    Follow,
    LibraryItem,
    SongInfo,
    SplitStatus,
    TelegramJob,
    VibeSuggestion,
    ZipReady,
)


def _run(coro):
    return asyncio.run(coro)


class FakeSink:
    """جایگزینِ `_StatusSink` — فقط ادیت‌ها را ثبت می‌کند، به تلگرام کاری ندارد."""

    def __init__(self) -> None:
        self.edited: list[str] = []
        self.deleted = False

    async def edit(self, text: str, **kwargs) -> None:
        self.edited.append(text)

    async def delete(self) -> None:
        self.deleted = True


class FakeApi:
    def __init__(
        self,
        *,
        create_result: str = "job-1",
        create_exc: Exception | None = None,
        progress_events: list[DownloadProgress] | None = None,
        stream_exc: Exception | None = None,
        file_bytes: bytes | None = b"audio-bytes",
        song_info: SongInfo | None = None,
        lyrics: bytes | None = None,
        vibe_result: VibeSuggestion | None = None,
        chapters_result: ChaptersInfo | None = None,
        split_task: SplitStatus | None = None,
        favorites_list: list[LibraryItem] | None = None,
        daily_mix_result: DailyMix | None = None,
        zip_ready: ZipReady | None = None,
        zip_bytes: bytes | None = b"PK\x03\x04zipcontent",
    ) -> None:
        self.create_result = create_result
        self.create_exc = create_exc
        self.progress_events = progress_events or []
        self.stream_exc = stream_exc
        self._file_bytes = file_bytes
        self._song_info = song_info
        self._lyrics = lyrics
        self._vibe = vibe_result
        self._chapters = chapters_result
        self._split_task = split_task
        self._favorites = favorites_list
        self._daily_mix = daily_mix_result
        self._zip_ready = zip_ready
        self._zip_bytes = zip_bytes
        self.fav_calls: list[tuple[str, bool]] = []
        self.created_tracks: list[Track] = []

    async def create_download(self, track, quality):
        if self.create_exc:
            raise self.create_exc
        self.created_tracks.append(track)
        return self.create_result

    async def stream_progress(self, job_id):
        for event in self.progress_events:
            yield event
        if self.stream_exc:
            raise self.stream_exc

    def file_url(self, job_id: str) -> str:
        return f"https://example.com/dl/{job_id}"

    async def file_bytes(self, job_id: str):
        return self._file_bytes

    async def song_info(self, title: str, artist: str):
        return self._song_info

    async def raw_bytes(self, url: str):
        return b"img-bytes"

    async def thumb_bytes(self, job_id: str):
        return None

    async def lyrics_bytes(self, job_id: str):
        return self._lyrics

    async def vibe(self, text: str):
        if self._vibe is None:
            raise RuntimeError("vibe not configured")
        return self._vibe

    async def chapters(self, ref: str):
        return self._chapters

    async def create_split(self, url: str, quality: str = "320", indexes: list[int] | None = None):
        if self._split_task is None:
            raise RuntimeError("split_task not configured")
        return self._split_task

    async def split_status(self, task_id: str):
        if self._split_task is None:
            raise RuntimeError("split_task not configured")
        return self._split_task

    async def favorites(self):
        return self._favorites if self._favorites is not None else []

    async def set_favorite(self, job_id: str, favorite: bool):
        self.fav_calls.append((job_id, favorite))
        return favorite

    async def daily_mix(self, limit: int = 15):
        if self._daily_mix is not None:
            return self._daily_mix
        return DailyMix(source="none", items=[])

    async def create_zip(self, job_ids: list[str], name: str = "musicbazi"):
        if self._zip_ready is not None:
            return self._zip_ready
        return ZipReady(url="/api/downloads/zip/tok123", bytes=1000, files=len(job_ids))

    async def zip_bytes_by_url(self, relative_url: str):
        return self._zip_bytes

    def full_zip_url(self, relative_url: str):
        return f"https://example.com{relative_url}"





def _context(api: FakeApi) -> SimpleNamespace:
    return SimpleNamespace(bot_data={"api": api}, chat_data={}, bot=AsyncMock())


# ---------- توابعِ خالصِ فرمت‌بندی ----------


class TestFmtDuration:
    def test_formats_minutes_and_seconds(self):
        assert run._fmt_duration(185_000) == "3:05"

    def test_pads_single_digit_seconds(self):
        assert run._fmt_duration(60_000) == "1:00"


class TestTrackLine:
    def test_escapes_html_and_includes_source_badge(self, track):
        t = track.model_copy(update={"title": "<b>x</b>", "artist": "A & B"})
        line = run._track_line(t)
        assert "&lt;b&gt;x&lt;/b&gt;" in line
        assert "A &amp; B" in line
        assert line.startswith(run.source_badge(t.source))


class TestInfoCaption:
    def test_release_date_hidden_when_track_already_has_year(self, track):
        t = track.model_copy(update={"year": 1974})
        info = SongInfo(releaseDate="1974-05-01")
        caption = run._info_caption(t, info)
        assert "تاریخ انتشار" not in caption

    def test_release_date_shown_when_track_year_is_missing(self, track):
        t = track.model_copy(update={"year": None})
        info = SongInfo(releaseDate="1974-05-01")
        caption = run._info_caption(t, info)
        assert "تاریخ انتشار" in caption

    def test_writers_and_producers_included_when_present(self, track):
        info = SongInfo(writers=["A", "B"], producers=["C"])
        caption = run._info_caption(track, info)
        assert "آهنگساز" in caption
        assert "تهیه‌کننده" in caption

    def test_works_without_any_genius_info(self, track):
        caption = run._info_caption(track, None)
        assert "آهنگساز" not in caption
        assert "تهیه‌کننده" not in caption

    def test_caption_truncated_to_max_1024_chars(self, track):
        info = SongInfo(
            writers=["Very Long Writer Name " * 10 for _ in range(15)],
            producers=["Very Long Producer Name " * 10 for _ in range(15)],
        )
        caption = run._info_caption(track, info)
        assert len(caption) <= run.MAX_CAPTION_LEN


# ---------- _StatusSink ----------


class TestStatusSink:
    def test_message_mode_edits_the_message(self):
        message = AsyncMock()
        context = SimpleNamespace(bot=AsyncMock())
        sink = run._StatusSink(context, message=message)

        _run(sink.edit("hello"))

        message.edit_text.assert_awaited_once_with("hello")

    def test_inline_mode_edits_via_bot(self):
        bot = AsyncMock()
        context = SimpleNamespace(bot=bot)
        sink = run._StatusSink(context, inline_message_id="abc")

        _run(sink.edit("hello"))

        bot.edit_message_text.assert_awaited_once_with("hello", inline_message_id="abc")

    def test_edit_swallows_exceptions_instead_of_killing_the_download(self):
        message = AsyncMock()
        message.edit_text.side_effect = RuntimeError("rate limited")
        context = SimpleNamespace(bot=AsyncMock())
        sink = run._StatusSink(context, message=message)

        _run(sink.edit("hello"))  # نباید بالا برود

    def test_delete_swallows_exceptions(self):
        message = AsyncMock()
        message.delete.side_effect = RuntimeError("already gone")
        context = SimpleNamespace(bot=AsyncMock())
        sink = run._StatusSink(context, message=message)

        _run(sink.delete())  # نباید بالا برود


# ---------- _run_download ----------


class TestRunDownload:
    def test_create_download_failure_is_reported(self, track):
        api = FakeApi(create_exc=RuntimeError("network down"))
        context = _context(api)
        sink = FakeSink()

        result = _run(run._run_download(context, track, sink))

        assert result is None
        assert any("شروع دانلود ناموفق بود" in t for t in sink.edited)

    def test_successful_download_returns_job_id_and_final_progress(self, track):
        ready = DownloadProgress(status="ready", percent=100, format="mp3 320")
        api = FakeApi(
            progress_events=[
                DownloadProgress(status="searching"),
                DownloadProgress(status="downloading", percent=50),
                ready,
            ]
        )
        context = _context(api)
        sink = FakeSink()

        job_id, final = _run(run._run_download(context, track, sink))

        assert job_id == "job-1"
        assert final is ready

    def test_stream_ending_without_a_ready_status_is_a_failure(self, track):
        api = FakeApi(progress_events=[])
        context = _context(api)
        sink = FakeSink()

        result = _run(run._run_download(context, track, sink))

        assert result is None
        assert sink.edited[-1] == "دانلود ناموفق بود."

    def test_server_reported_error_is_shown_verbatim(self, track):
        api = FakeApi(progress_events=[DownloadProgress(status="error", error="فایل قفل دارد")])
        context = _context(api)
        sink = FakeSink()

        result = _run(run._run_download(context, track, sink))

        assert result is None
        assert sink.edited[-1] == "فایل قفل دارد"

    def test_stream_exception_mid_download_is_reported(self, track):
        api = FakeApi(
            progress_events=[DownloadProgress(status="downloading", percent=10)],
            stream_exc=RuntimeError("connection reset"),
        )
        context = _context(api)
        sink = FakeSink()

        result = _run(run._run_download(context, track, sink))

        assert result is None
        assert any("دریافت وضعیت ناموفق بود" in t for t in sink.edited)


# ---------- _deliver ----------


class TestDeliver:
    def test_missing_file_is_reported_without_sending_anything(self, track):
        api = FakeApi(file_bytes=None)
        context = _context(api)
        sink = FakeSink()

        _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320"))

        assert sink.edited == ["فایل آماده نبود."]
        context.bot.send_audio.assert_not_awaited()

    def test_oversized_file_gets_a_direct_link_instead_of_upload(self, track, monkeypatch):
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: True)
        api = FakeApi(file_bytes=b"x")
        context = _context(api)
        sink = FakeSink()

        _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320"))

        assert any("مستقیم بگیرش" in t for t in sink.edited)
        context.bot.send_audio.assert_not_awaited()

    def test_normal_delivery_sends_audio_with_track_metadata(self, track, monkeypatch):
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        api = FakeApi(file_bytes=b"audio-bytes", lyrics=b"[00:01.00]lyric line")
        context = _context(api)
        sink = FakeSink()

        _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320"))

        context.bot.send_audio.assert_awaited_once()
        _, kwargs = context.bot.send_audio.await_args
        assert kwargs["filename"] == run.audio_filename(track, "mp3 320")
        assert kwargs["title"] == track.title
        assert kwargs["performer"] == track.artist
        assert sink.deleted is True
        context.bot.send_document.assert_awaited_once()

    def test_thumbnail_fetch_crash_does_not_block_the_actual_file(self, track, monkeypatch):
        """
        رگرسیون: `_fetch_full_cover` قبلاً هم داخلِ try/except بود، ولی
        `_fetch_thumbnail` نبود — یک خطای غیرمنتظره (نه httpx.HTTPError، که
        خودِ raw_bytes قبلاً می‌گیرد) در گرفتنِ کاورِ کوچک کلِ ارسال را
        می‌ترکاند، با اینکه فایل صوتی از قبل آماده بود. حالا هر دو best-effort‌اند.
        """
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        t = track.model_copy(update={"artworkUrl": "https://example.com/cover.jpg"})
        api = FakeApi(file_bytes=b"audio-bytes")

        async def flaky_raw_bytes(url):
            raise RuntimeError("unexpected failure fetching artwork")

        api.raw_bytes = flaky_raw_bytes
        context = _context(api)
        sink = FakeSink()

        _run(run._deliver(context, 123, t, "job-1", sink, "mp3 320"))

        context.bot.send_audio.assert_awaited_once()
        _, kwargs = context.bot.send_audio.await_args
        assert kwargs["thumbnail"] is None
        context.bot.send_photo.assert_not_awaited()

    def test_deliver_with_send_cover_false_skips_photo(self, track, monkeypatch):
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        api = FakeApi(file_bytes=b"audio-bytes", lyrics=b"[00:01.00]x")
        context = _context(api)
        sink = FakeSink()

        _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320", send_cover=False))

        context.bot.send_audio.assert_awaited_once()
        context.bot.send_photo.assert_not_awaited()
        # وقتی send_lyrics به طور پیش‌فرض True است، متن همچنان فرستاده می‌شود
        context.bot.send_document.assert_awaited_once()

    def test_deliver_with_send_lyrics_false_skips_document(self, track, monkeypatch):
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        api = FakeApi(file_bytes=b"audio-bytes", lyrics=b"[00:01.00]x")
        context = _context(api)
        sink = FakeSink()

        _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320", send_lyrics=False))

        context.bot.send_audio.assert_awaited_once()
        context.bot.send_document.assert_not_awaited()


    def test_upload_timeout_is_retried_before_giving_up(self, track, monkeypatch):
        """
        رگرسیون: آپلودِ چند-مگابایتی روی لینکِ ناپایدار گاهی در تلاشِ اول
        TimedOut می‌گرفت و همان‌جا کلِ ارسال شکست می‌خورد — دکمه‌ی وب قرمز
        می‌شد با اینکه یک تلاشِ دیگر جواب می‌داد.
        """
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        monkeypatch.setattr(run, "UPLOAD_RETRY", 0)
        api = FakeApi(file_bytes=b"audio-bytes")
        context = _context(api)
        context.bot.send_audio.side_effect = [TimedOut(), SimpleNamespace()]
        sink = FakeSink()

        _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320"))

        assert context.bot.send_audio.await_count == 2
        assert sink.deleted is True

    def test_upload_uses_a_timeout_wide_enough_for_telegram_to_answer(
        self, track, monkeypatch
    ):
        """تلگرام بعدِ آپلود فایل را پردازش می‌کند و تازه بعدش جواب می‌دهد."""
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        api = FakeApi(file_bytes=b"audio-bytes")
        context = _context(api)
        sink = FakeSink()

        _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320"))

        _, kwargs = context.bot.send_audio.await_args
        assert kwargs["read_timeout"] == run.UPLOAD_TIMEOUT
        assert kwargs["write_timeout"] == run.UPLOAD_TIMEOUT

    def test_bad_request_is_not_retried(self, track, monkeypatch):
        """
        BadRequest زیرِ NetworkError نشسته ولی خطای خودِ درخواست است — تکرارش
        فقط سه برابر معطلی است.
        """
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        monkeypatch.setattr(run, "UPLOAD_RETRY", 0)
        api = FakeApi(file_bytes=b"audio-bytes")
        context = _context(api)
        context.bot.send_audio.side_effect = BadRequest("chat not found")
        sink = FakeSink()

        with pytest.raises(RuntimeError):
            _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320"))

        assert context.bot.send_audio.await_count == 1

    def test_dead_upload_falls_back_to_the_direct_link(self, track, monkeypatch):
        """
        فایل روی دیسکِ سرور آماده است؛ شکستِ آپلود نباید یعنی از دست رفتنش.
        خطا همچنان بالا می‌رود تا وبِ صف هم بداند نرسیده.
        """
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        monkeypatch.setattr(run, "UPLOAD_RETRY", 0)
        api = FakeApi(file_bytes=b"audio-bytes")
        context = _context(api)
        context.bot.send_audio.side_effect = NetworkError("connection reset")
        sink = FakeSink()

        with pytest.raises(RuntimeError):
            _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320"))

        assert context.bot.send_audio.await_count == run.UPLOAD_ATTEMPTS
        assert any(api.file_url("job-1") in t for t in sink.edited)
        assert sink.deleted is False

    def test_lyrics_failure_does_not_fail_an_arrived_track(self, track, monkeypatch):
        """
        رگرسیون: فایلِ صوتی از قبل در چت نشسته بود ولی تایم‌اوتِ .lrc کلِ کارِ
        صف را «ناموفق» گزارش می‌کرد و دکمه‌ی وب قرمز می‌شد.
        """
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        api = FakeApi(file_bytes=b"audio-bytes", lyrics=b"[00:01.00]x")
        context = _context(api)
        context.bot.send_document.side_effect = TimedOut()
        sink = FakeSink()

        _run(run._deliver(context, 123, track, "job-1", sink, "mp3 320"))

        context.bot.send_audio.assert_awaited_once()
        assert sink.deleted is True


# ---------- کشِ inline ----------


class TestCacheInlineTrack:
    def test_round_trips_the_track(self, track):
        run._inline_cache.clear()
        run._inline_cache_at.clear()

        key = run._cache_inline_track(track)

        assert run._inline_cache[key] is track

    def test_expired_entries_are_evicted_on_next_insert(self, track, monkeypatch):
        run._inline_cache.clear()
        run._inline_cache_at.clear()

        clock = {"t": 1000.0}
        monkeypatch.setattr(run.time, "monotonic", lambda: clock["t"])

        old_key = run._cache_inline_track(track)
        clock["t"] += run._INLINE_CACHE_TTL + 1

        run._cache_inline_track(track)

        assert old_key not in run._inline_cache
        assert old_key not in run._inline_cache_at


# ---------- انتخاب از لیستِ کاندید (index-based callback data) ----------


class _Query:
    def __init__(self, data: str, message=None):
        self.data = data
        self.message = message
        self.answer = AsyncMock()
        self.edit_message_text = AsyncMock()


class _Update:
    def __init__(self, query):
        self.callback_query = query


class TestPickHandlers:
    def test_on_pick_with_stale_index_reports_gracefully(self, track):
        api = FakeApi()
        context = _context(api)
        context.chat_data["candidates"] = [track]
        message = AsyncMock()
        message.chat_id = 123
        query = _Query("pick:5", message=message)
        update = _Update(query)

        _run(run.on_pick(update, context))

        query.edit_message_text.assert_awaited_once()
        assert "معتبر نیست" in query.edit_message_text.await_args.args[0]

    def test_on_pick_inherits_album_metadata_from_collection(self, track):
        api = FakeApi(progress_events=_ready_events())
        context = _context(api)
        single_track = track.model_copy(update={
            "album": None,
            "albumArtist": None,
            "albumId": None,
            "trackNumber": None,
            "artworkUrl": None,
        })
        album = _album_detail([single_track], artwork_url="https://example.com/album-art.jpg")
        album.title = "FUCK MUSIC"
        album.artist = "Mvshreghi"
        album.id = "sc:playlist:2304743880"
        album.releaseType = "album"
        album.year = 2026

        context.chat_data["candidates"] = [single_track]
        context.chat_data["collection"] = album

        message = AsyncMock()
        message.chat_id = 123
        query = _Query("pick:0", message=message)
        update = _Update(query)

        _run(run.on_pick(update, context))

        query.answer.assert_awaited_once()
        assert len(api.created_tracks) == 1
        downloaded = api.created_tracks[0]
        assert downloaded.album == "FUCK MUSIC"
        assert downloaded.albumArtist == "Mvshreghi"
        assert downloaded.albumId == "sc:playlist:2304743880"
        assert downloaded.trackNumber == 1
        assert downloaded.artworkUrl == "https://example.com/album-art.jpg"
        assert downloaded.year == 2026

    def test_on_follow_pick_with_empty_candidates_reports_gracefully(self):
        context = _context(FakeApi())
        message = AsyncMock()
        query = _Query("followpick:0", message=message)
        update = _Update(query)

        _run(run.on_follow_pick(update, context))

        query.edit_message_text.assert_awaited_once()
        assert "دوباره" in query.edit_message_text.await_args.args[0]

    def test_on_download_all_with_album_sends_cover_once_and_completion(self, track):
        detail = _album_detail([track])
        api = FakeApi(progress_events=_ready_events())
        context = _context(api)
        context.chat_data["candidates"] = [track]
        context.chat_data["collection"] = detail
        message = AsyncMock()
        message.chat_id = 123
        query = _Query("all", message=message)
        update = _Update(query)

        _run(run.on_download_all(update, context))

        query.answer.assert_awaited_once()
        query.edit_message_text.assert_awaited_once()
        # کاور آلبوم یک‌بار فرستاده می‌شود
        assert context.bot.send_photo.await_count == 1
        # فایل صوتی فرستاده می‌شود
        context.bot.send_audio.assert_awaited_once()
        # پیام اتمام ارسال فرستاده می‌شود
        messages = [call.args[1] for call in context.bot.send_message.await_args_list if len(call.args) > 1]
        assert any("به پایان رسید" in msg and detail.title in msg for msg in messages)


# ---------- مرورگرِ پروفایلِ هنرمند: خطای شبکه نباید کاربر را در جا خشک کند ----------


class FlakyArtistApi(FakeApi):
    """`artist()` همیشه شکست می‌خورد — شبیه‌سازیِ یک بلیپِ شبکه/سرور."""

    async def artist(self, ref: str):
        raise RuntimeError("upstream unavailable")


class TestArtistProfileNetworkFailures:
    """
    رگرسیون: برخلافِ `_check_follows` که خطای `api.artist()` را از قبل می‌گرفت،
    مسیرهای مرورگرِ پروفایل (`_artist_profile_view`، `_artist_section_view`،
    `on_artist_follow`) این کار را نمی‌کردند — یک خطای شبکه‌ی معمولی کلِ
    هندلر را می‌ترکاند و دکمه‌ی کاربر بی‌جواب می‌ماند، به‌جای پیامِ «پیدا نشد».
    """

    def test_artist_profile_view_returns_none_instead_of_raising(self):
        context = _context(FlakyArtistApi())

        view = _run(run._artist_profile_view(context, "deezer:artist:1"))

        assert view is None

    def test_artist_section_view_returns_none_instead_of_raising(self):
        context = _context(FlakyArtistApi())

        view = _run(run._artist_section_view(context, "deezer:artist:1", "att"))

        assert view is None

    def test_on_artist_follow_reports_not_found_instead_of_raising(self):
        context = _context(FlakyArtistApi())
        message = AsyncMock()
        query = _Query("afollow:deezer:artist:1", message=message)
        update = _Update(query)

        _run(run.on_artist_follow(update, context))

        query.answer.assert_awaited_once()
        assert "پیدا نشد" in query.answer.await_args.args[0]


# ---------- وصل‌شدن به وب و صفِ «فرستادن به تلگرام» ----------


class _Chat:
    def __init__(self, chat_id=7, title=None, first_name=None, last_name=None, username=None):
        self.id = chat_id
        self.title = title
        self.first_name = first_name
        self.last_name = last_name
        self.username = username


def _message(chat: _Chat) -> AsyncMock:
    message = AsyncMock()
    message.chat = chat
    message.chat_id = chat.id
    return message


class PairingApi(FakeApi):
    def __init__(self, error: str | None = None) -> None:
        super().__init__()
        self.error = error
        self.claims: list[tuple[str, int, str]] = []

    async def claim_pair(self, code, chat_id, chat_title):
        self.claims.append((code, chat_id, chat_title))
        return self.error


class TestChatTitle:
    """اسمی که در وب کنارِ «وصل است» می‌نشیند — باید همیشه چیزی برای نشان دادن باشد."""

    def test_prefers_the_group_title(self):
        assert run._chat_title(_message(_Chat(title="گروهِ ما"))) == "گروهِ ما"

    def test_falls_back_to_the_persons_name(self):
        chat = _Chat(first_name="فرهاد", last_name="مهراد")

        assert run._chat_title(_message(chat)) == "فرهاد مهراد"

    def test_falls_back_to_the_username_then_the_id(self):
        assert run._chat_title(_message(_Chat(username="farhad"))) == "@farhad"
        assert run._chat_title(_message(_Chat(chat_id=42))) == "42"


class TestClaimLink:
    def test_valid_code_links_this_chat(self):
        api = PairingApi()
        message = _message(_Chat(chat_id=99, title="پیوی"))

        _run(run._claim_link(message, _context(api), " abc123 "))

        assert api.claims == [("abc123", 99, "پیوی")]
        assert "وصل شد" in message.reply_text.await_args.args[0]

    def test_rejected_code_shows_the_servers_reason(self):
        api = PairingApi(error="این کد معتبر نیست یا منقضی شده")
        message = _message(_Chat())

        _run(run._claim_link(message, _context(api), "abc123"))

        assert message.reply_text.await_args.args[0] == "این کد معتبر نیست یا منقضی شده"

    def test_bare_command_explains_instead_of_calling_the_server(self):
        api = PairingApi()
        message = _message(_Chat())

        _run(run._claim_link(message, _context(api), ""))

        assert api.claims == []
        assert "/link" in message.reply_text.await_args.args[0]


class OutboxApi(FakeApi):
    """FakeApi + باز کردنِ آلبوم، برای کارهای `kind="album"`."""

    def __init__(self, album=None, resolve_exc: Exception | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.album = album
        self.resolve_exc = resolve_exc
        self.qualities: list[str] = []

    async def create_download(self, track, quality):
        self.qualities.append(quality)
        return await super().create_download(track, quality)

    async def resolve_ref(self, ref):
        if self.resolve_exc:
            raise self.resolve_exc
        return self.album


def _application(api: FakeApi):
    """
    اپلیکیشنِ تقلبی برای `_run_outbox_job` — همان context معمولی را می‌دهد،
    چون کارِ صف نباید مسیرِ متفاوتی از پیامِ کاربر برود.
    """
    context = _context(api)
    return SimpleNamespace(
        bot_data={"api": api},
        context_types=SimpleNamespace(context=lambda app, chat_id=None: context),
    ), context


def _album_detail(tracks, artwork_url: str | None = "https://example.com/cover.jpg") -> AlbumDetail:
    return AlbumDetail(
        id="deezer:album:1",
        title="Mard-E Tanha",
        artist="Farhad Mehrad",
        source="deezer",
        sourceUrl="https://www.deezer.com/album/1",
        year=1978,
        artworkUrl=artwork_url,
        trackCount=len(tracks),
        durationMs=sum(x.durationMs for x in tracks),
        tracks=tracks,
    )


def _ready_events():
    return [
        DownloadProgress(status="downloading", percent=50),
        DownloadProgress(status="ready", percent=100, format="mp3 320"),
    ]


class TestRunOutboxJob:
    """کارِ صف = همان مسیرِ همیشگیِ دانلود و ارسال، فقط بدون پیامِ کاربر."""

    def test_track_job_downloads_and_sends_with_the_requested_quality(self, track):
        api = OutboxApi(progress_events=_ready_events())
        application, context = _application(api)
        job = TelegramJob(id="s1", chatId=5, kind="track", quality="flac", title=track.title, track=track)

        error = _run(run._run_outbox_job(application, job))

        assert error is None
        assert api.qualities == ["flac"]
        context.bot.send_audio.assert_awaited_once()

    def test_album_job_sends_every_track(self, track):
        detail = _album_detail([track, track.model_copy(update={"id": "itunes:track:2"})])
        api = OutboxApi(album=detail, progress_events=_ready_events())
        application, context = _application(api)
        job = TelegramJob(id="s2", chatId=5, kind="album", quality="320", title=detail.title, ref="deezer:album:1")

        error = _run(run._run_outbox_job(application, job))

        assert error is None
        assert context.bot.send_audio.await_count == 2
        # کاور آلبوم دقیقاً یک بار در ابتدا فرستاده می‌شود
        assert context.bot.send_photo.await_count == 1
        # پیام نهایی اتمام ارسال آلبوم فرستاده می‌شود
        messages = [call.args[1] for call in context.bot.send_message.await_args_list if len(call.args) > 1]
        assert any("به پایان رسید" in msg and detail.title in msg for msg in messages)

    def test_album_job_sends_cover_once_with_album_caption_and_completion_message(self, track):
        feature_track = track.model_copy(
            update={"id": "itunes:track:2", "title": "Track 2", "artist": "Farhad Mehrad, Shahyar Ghanbari"}
        )
        detail = _album_detail([track, feature_track])
        detail.releaseDate = "1978-01-01"
        api = OutboxApi(album=detail, progress_events=_ready_events())
        application, context = _application(api)
        job = TelegramJob(id="s2", chatId=5, kind="album", quality="320", title=detail.title, ref="deezer:album:1")

        error = _run(run._run_outbox_job(application, job))

        assert error is None
        # کاور آلبوم دقیقاً یک بار فرستاده می‌شود (نه با هر ترک)
        assert context.bot.send_photo.await_count == 1
        _, photo_kwargs = context.bot.send_photo.await_args
        caption = photo_kwargs["caption"]
        assert detail.title in caption
        assert detail.artist in caption
        assert "Shahyar Ghanbari" in caption
        assert "1978-01-01" in caption
        # دو فایل صوتی فرستاده می‌شوند
        assert context.bot.send_audio.await_count == 2
        # هیچ فایل لیریکسی برای آلبوم فرستاده نمی‌شود
        context.bot.send_document.assert_not_awaited()
        # پیام نهایی اتمام ارسال آلبوم فرستاده می‌شود
        messages = [call.args[1] for call in context.bot.send_message.await_args_list if len(call.args) > 1]
        assert any("به پایان رسید" in msg and detail.title in msg for msg in messages)

    def test_album_job_falls_back_to_text_message_if_cover_fetch_fails(self, track):
        detail = _album_detail([track])
        api = OutboxApi(album=detail, progress_events=_ready_events())
        api.raw_bytes = AsyncMock(return_value=None)
        application, context = _application(api)
        job = TelegramJob(id="s2", chatId=5, kind="album", quality="320", title=detail.title, ref="deezer:album:1")

        error = _run(run._run_outbox_job(application, job))

        assert error is None
        context.bot.send_photo.assert_not_awaited()
        # پیام اطلاعات آلبوم به‌صورت متنی ارسال می‌شود
        messages = [call.args[1] for call in context.bot.send_message.await_args_list if len(call.args) > 1]
        assert any(detail.title in msg for msg in messages)
        assert any("به پایان رسید" in msg for msg in messages)

    def test_album_job_ensures_tracks_get_album_artwork(self, track):
        """ترک‌هایی که در آلبوم ارسال می‌شوند، کاور آلبوم را می‌گیرند."""
        t1 = track.model_copy(update={"id": "sc:1", "title": "Single", "album": "The Album", "artworkUrl": "http://single-art.jpg"})
        detail = _album_detail([t1])
        detail.artworkUrl = "http://album-art.jpg"
        detail.title = "The Album"
        api = OutboxApi(album=detail)
        application, context = _application(api)
        job = TelegramJob(id="s2c", chatId=5, kind="album", quality="320", title="The Album", ref="sc:playlist:1")

        error = _run(run._run_outbox_job(application, job))

        assert error is None
        assert t1.artworkUrl == "http://album-art.jpg"

    def test_empty_album_reports_instead_of_going_quiet(self, track):
        api = OutboxApi(album=_album_detail([]))
        application, _ = _application(api)
        job = TelegramJob(id="s2b", chatId=5, kind="album", quality="320", title="خالی", ref="deezer:album:1")

        assert _run(run._run_outbox_job(application, job)) is not None

    def test_unopenable_album_reports_the_reason(self):
        api = OutboxApi(resolve_exc=RuntimeError("۵۰۴"))
        application, _ = _application(api)
        job = TelegramJob(id="s3", chatId=5, kind="album", quality="320", title="آلبوم", ref="deezer:album:1")

        error = _run(run._run_outbox_job(application, job))

        assert error is not None and "۵۰۴" in error

    def test_missing_payload_reports_instead_of_raising(self):
        """
        ردیفِ ناقص در صف نباید حلقه را بترکاند — وگرنه دکمه‌ی وب تا ابد اسپینر
        نشان می‌دهد و بقیه‌ی صف هم پشتش می‌ماند.
        """
        application, _ = _application(OutboxApi())

        missing_track = _run(
            run._run_outbox_job(
                application, TelegramJob(id="s4", chatId=5, kind="track", quality="320", title="x")
            )
        )
        missing_ref = _run(
            run._run_outbox_job(
                application, TelegramJob(id="s5", chatId=5, kind="album", quality="320", title="x")
            )
        )

        assert missing_track is not None
        assert missing_ref is not None


class TestApiClientCreateDownload:
    def test_create_download_sends_album_artist_and_album_id(self, track):
        import json
        import httpx
        from app.bot.client import ApiClient
        sent_body = {}

        class DummyTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                nonlocal sent_body
                sent_body = json.loads(request.content.decode("utf-8"))
                return httpx.Response(200, json={"jobId": "j1"})

        client = ApiClient("http://testserver")
        client._http = httpx.AsyncClient(transport=DummyTransport(), base_url="http://testserver")

        t = track.model_copy(update={
            "album": "FUCK MUSIC",
            "albumArtist": "Mvshreghi",
            "albumId": "sc:playlist:2304743880",
        })

        job_id = _run(client.create_download(t, "320"))
        assert job_id == "j1"
        assert sent_body.get("albumArtist") == "Mvshreghi"
        assert sent_body.get("albumId") == "sc:playlist:2304743880"
        assert sent_body.get("album") == "FUCK MUSIC"


    def test_track_job_fails_when_download_fails(self, track):
        """شکستِ دانلود نباید در وب «done» دیده شود — باید پیام خطا گزارش شود."""
        api = OutboxApi(create_exc=RuntimeError("سرور در دسترس نیست"))
        application, _ = _application(api)
        job = TelegramJob(id="s6", chatId=5, kind="track", quality="320", title=track.title, track=track)

        error = _run(run._run_outbox_job(application, job))

        assert error is not None
        assert "دانلود" in error


# ---------- _download_all ----------


class TestDownloadAll:
    def test_continues_when_one_track_fails(self, track, monkeypatch):
        """شکست یک ترک در آلبوم نباید دانلود بقیه ترک‌ها را متوقف کند."""
        tracks = [
            track.model_copy(update={"id": "t1", "title": "Track 1"}),
            track.model_copy(update={"id": "t2", "title": "Track 2"}),
        ]
        api = FakeApi(progress_events=_ready_events())
        context = _context(api)

        call_count = 0

        async def flaky_download_and_send(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("upload failed for track 1")

        monkeypatch.setattr(run, "_download_and_send", flaky_download_and_send)

        _run(run._download_all(context, 123, tracks))

        assert call_count == 2

    def test_proceeds_even_if_summary_message_fails(self, track, monkeypatch):
        """اگر فرستادن پیام خلاصه شکست بخورد، دانلود ترک‌ها همچنان انجام می‌شود."""
        api = FakeApi(progress_events=_ready_events())
        context = _context(api)
        context.bot.send_message.side_effect = NetworkError("connection reset")

        downloaded: list[str] = []

        async def track_download_and_send(ctx, chat_id, t, *args, **kwargs):
            downloaded.append(t.title)

        monkeypatch.setattr(run, "_download_and_send", track_download_and_send)

        _run(run._download_all(context, 123, [track]))

        assert downloaded == [track.title]


# ---------- _is_media_document ----------


class TestIsMediaDocument:
    def test_audio_mime_type_is_recognized(self):
        doc = SimpleNamespace(mime_type="audio/mpeg", file_name="song.mp3")
        assert run._is_media_document(doc) is True

    def test_video_mime_type_is_recognized(self):
        doc = SimpleNamespace(mime_type="video/mp4", file_name="video.mp4")
        assert run._is_media_document(doc) is True

    def test_generic_octet_stream_with_audio_ext_is_recognized(self):
        doc = SimpleNamespace(mime_type="application/octet-stream", file_name="song.mp3")
        assert run._is_media_document(doc) is True

    def test_pdf_document_is_rejected(self):
        doc = SimpleNamespace(mime_type="application/pdf", file_name="document.pdf")
        assert run._is_media_document(doc) is False

    def test_none_document_is_rejected(self):
        assert run._is_media_document(None) is False


# ---------- error_handler ----------


class TestErrorHandler:
    def test_network_error_does_not_crash(self):
        context = SimpleNamespace(error=NetworkError("connection lost"))
        _run(run.error_handler(None, context))

    def test_forbidden_logged_gracefully(self):
        from telegram.error import Forbidden
        context = SimpleNamespace(error=Forbidden("bot was blocked"))
        _run(run.error_handler(None, context))

    def test_unexpected_error_answers_callback(self):
        query = AsyncMock()
        update = SimpleNamespace(callback_query=query, effective_message=None)
        context = SimpleNamespace(error=ValueError("unexpected"))

        _run(run.error_handler(update, context))

        query.answer.assert_awaited_once()


# ---------- تست‌های قابلیت‌های فاز ۱ ----------


class TestVibeFeature:
    def test_vibe_cmd_without_args_prompts_and_sets_mode(self):
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)
        context = SimpleNamespace(args=[], chat_data={})

        _run(run.vibe_cmd(update, context))

        assert context.chat_data.get("search_mode") == "vibe"
        msg.reply_text.assert_awaited_once()
        _, kwargs = msg.reply_text.await_args
        assert "ForceReply" in str(type(kwargs.get("reply_markup")))

    def test_vibe_cmd_with_args_executes_vibe(self, track, monkeypatch):
        msg = AsyncMock()
        status_msg = AsyncMock()
        msg.reply_text.return_value = status_msg
        update = SimpleNamespace(message=msg)

        vibe_res = VibeSuggestion(
            vibe="party",
            label="مهمونی و دورهمی",
            reply="این آهنگ‌ها انرژی‌بخش هستند!",
            tracks=[track],
            reason="انتخاب شده برای ریتم شاد",
        )
        api = FakeApi(vibe_result=vibe_res)
        context = _context(api)
        context.args = ["آهنگ", "شاد"]

        _run(run.vibe_cmd(update, context))

        # باید پاسخ حاوی برچسب و پیام وایب باشد
        calls = msg.reply_text.await_args_list
        assert any(c.args and "مهمونی و دورهمی" in c.args[0] for c in calls)
        assert context.chat_data.get("candidates") == [track]

    def test_run_vibe_handles_empty_results(self):
        msg = AsyncMock()
        status_msg = AsyncMock()
        msg.reply_text.return_value = status_msg

        vibe_res = VibeSuggestion(
            vibe="chill",
            label="آرامش",
            reply="یه حس خوب",
            tracks=[],
        )
        api = FakeApi(vibe_result=vibe_res)
        context = _context(api)

        _run(run._run_vibe(msg, context, "آرامش"))

        status_msg.edit_text.assert_awaited_once()
        assert "آهنگی برای این حال‌وهوا پیدا نشد" in status_msg.edit_text.await_args[0][0]


class TestReplyKeyboardRouting:
    def test_start_sends_persistent_keyboard(self):
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)
        context = SimpleNamespace(args=[], chat_data={})

        _run(run.start(update, context))

        # باید دو پیام ارسال شود: یکی با اینلاین و دومی با کیبورد ثابت
        assert msg.reply_text.await_count >= 2
        calls = msg.reply_text.await_args_list
        assert any(c.kwargs.get("reply_markup") == run.MAIN_REPLY_KEYBOARD for c in calls)

    def test_help_sends_reply_keyboard(self):
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)
        context = SimpleNamespace(chat_data={"quality": "320"})

        _run(run.help_cmd(update, context))

        msg.reply_text.assert_awaited_once()
        assert msg.reply_text.await_args.kwargs.get("reply_markup") == run.MAIN_REPLY_KEYBOARD
        assert "/vibe" in msg.reply_text.await_args[0][0]

    def test_on_text_routes_menu_buttons(self, monkeypatch):
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)
        context = SimpleNamespace(chat_data={}, bot_data={"api": FakeApi()})

        # دکمه جستجو
        msg.text = "🔍 جستجوی موزیک"
        _run(run.on_text(update, context))
        assert "اسم آهنگ" in msg.reply_text.await_args[0][0]

        # دکمه شازم
        msg.text = "🎧 تشخیص صدا (شازم)"
        _run(run.on_text(update, context))
        assert "ویس" in msg.reply_text.await_args[0][0]

    def test_on_text_in_vibe_mode_triggers_run_vibe(self, track, monkeypatch):
        msg = AsyncMock()
        status_msg = AsyncMock()
        msg.reply_text.return_value = status_msg
        msg.text = "موزیک جاده چالوس"
        update = SimpleNamespace(message=msg)

        vibe_res = VibeSuggestion(
            vibe="roadtrip",
            label="سفر جاده‌ای",
            reply="پیشنهاد عالی برای جاده",
            tracks=[track],
        )
        api = FakeApi(vibe_result=vibe_res)
        context = _context(api)
        context.chat_data["search_mode"] = "vibe"

        _run(run.on_text(update, context))

        # search_mode باید پاک شده باشد
        assert "search_mode" not in context.chat_data
        assert any(c.args and "سفر جاده‌ای" in c.args[0] for c in msg.reply_text.await_args_list)


class TestInteractiveLyricsCallback:
    def test_on_lyrics_pick_replies_with_lyrics(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BOT_DB_PATH", tmp_path / "bot.db")
        store.save_lyrics("hash123456789012", "بوی عیدی بوی توپ\nبوی کاغذ رنگی", title="کودکانه", artist="فرهاد")

        query = AsyncMock()
        query.data = "lyr:hash123456789012"
        query_msg = AsyncMock()
        query.message = query_msg
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace()

        _run(run.on_lyrics_pick(update, context))

        query.answer.assert_awaited_once()
        query_msg.reply_text.assert_awaited_once()
        sent_text = query_msg.reply_text.await_args[0][0]
        assert "کودکانه" in sent_text
        assert "بوی عیدی" in sent_text

    def test_on_lyrics_pick_missing_shows_alert(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BOT_DB_PATH", tmp_path / "bot.db")

        query = AsyncMock()
        query.data = "lyr:nonexistent1234"
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace()

        _run(run.on_lyrics_pick(update, context))

        query.answer.assert_awaited_once()
        assert "متن ترانه‌ای برای این آهنگ موجود نیست" in query.answer.await_args[0][0]


class TestFileIdCacheDelivery:
    def test_instant_delivery_from_cache(self, track, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BOT_DB_PATH", tmp_path / "bot.db")
        store.save_telegram_file(
            f"{track.id}:320",
            file_id="cached_file_id_999",
            title=track.title,
            artist=track.artist,
            duration_sec=180,
            quality="mp3 320",
        )

        api = FakeApi()
        context = _context(api)
        context.chat_data["quality"] = "320"

        _run(run._download_and_send(context, 12345, track, quality="320"))

        # باید مستقیم send_audio با file_id بدون صدا زدن create_download فراخوانی شود!
        assert len(api.created_tracks) == 0
        context.bot.send_audio.assert_awaited_once()
        assert context.bot.send_audio.await_args.kwargs["audio"] == "cached_file_id_999"

    def test_cache_failure_falls_back_to_normal_download(self, track, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BOT_DB_PATH", tmp_path / "bot.db")
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        store.save_telegram_file(
            f"{track.id}:320",
            file_id="bad_file_id",
            quality="mp3 320",
        )

        api = FakeApi(
            progress_events=[DownloadProgress(status="ready")],
            file_bytes=b"normal-file-bytes",
        )
        context = _context(api)
        context.chat_data["quality"] = "320"

        # بار اول ارسال فایل کش با خطا می‌افتد، سپس دانلود عادی صدا زده می‌شود
        context.bot.send_audio.side_effect = [
            BadRequest("Wrong file identifier"),  # شکست کش
            SimpleNamespace(audio=SimpleNamespace(file_id="new_good_id", file_unique_id="u1", duration=120)),  # دانلود عادی
        ]

        _run(run._download_and_send(context, 12345, track, quality="320"))

        # کلید خراب باید از دیتابیس پاک شده باشد
        assert store.get_telegram_file(f"{track.id}:320")["file_id"] == "new_good_id"
        # دانلود واقعی باید اجرا شده باشد
        assert len(api.created_tracks) == 1


# ---------- تست‌های قابلیت‌های فاز ۲ ----------


class TestMiniApp:
    def test_app_cmd_with_webapp_url(self, monkeypatch):
        monkeypatch.setattr(run, "TELEGRAM_WEBAPP_URL", "https://music.example.com")
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)
        context = SimpleNamespace()

        _run(run.app_cmd(update, context))

        msg.reply_text.assert_awaited_once()
        _, kwargs = msg.reply_text.await_args
        markup = kwargs.get("reply_markup")
        assert markup is not None
        button = markup.inline_keyboard[0][0]
        assert button.web_app is not None
        assert button.web_app.url == "https://music.example.com"

    def test_app_cmd_without_webapp_url(self, monkeypatch):
        monkeypatch.setattr(run, "TELEGRAM_WEBAPP_URL", None)
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)
        context = SimpleNamespace()

        _run(run.app_cmd(update, context))

        msg.reply_text.assert_awaited_once()
        assert "دامنه HTTPS" in msg.reply_text.await_args[0][0]

    def test_start_includes_webapp_button_when_configured(self, monkeypatch):
        monkeypatch.setattr(run, "TELEGRAM_WEBAPP_URL", "https://music.example.com")
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)
        context = SimpleNamespace(args=[], chat_data={})

        _run(run.start(update, context))

        # بررسی وجود دکمه وب‌اپلیکیشن در پیام استارت
        calls = msg.reply_text.await_args_list
        inline_call = calls[0]
        markup = inline_call.kwargs.get("reply_markup")
        assert any(
            btn.web_app and btn.web_app.url == "https://music.example.com"
            for row in markup.inline_keyboard
            for btn in row
        )


class TestYouTubeChapterSplitter:
    def test_on_text_detects_chapters_and_shows_prompt(self, track):
        chapters_info = ChaptersInfo(
            url="https://www.youtube.com/watch?v=mix123",
            title="Best of 2024 Mix",
            uploader="DJ Channel",
            durationMs=3600_000,
            chapters=[
                ChapterInfo(index=0, title="01. Artist A - Track 1", startMs=0, endMs=180_000, songTitle="Track 1", artist="Artist A"),
                ChapterInfo(index=1, title="02. Artist B - Track 2", startMs=180_000, endMs=360_000, songTitle="Track 2", artist="Artist B"),
            ],
        )
        api = FakeApi(chapters_result=chapters_info)
        context = _context(api)

        msg = AsyncMock()
        msg.text = "https://www.youtube.com/watch?v=mix123"
        update = SimpleNamespace(message=msg)

        _run(run.on_text(update, context))

        # باید دو دکمه تفکیک و یکپارچه نشان داده شود
        msg.reply_text.assert_awaited_once()
        text = msg.reply_text.await_args[0][0]
        assert "این میکس شامل" in text
        assert "Track 1" in text
        markup = msg.reply_text.await_args.kwargs.get("reply_markup")
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "split:all" in callbacks
        assert "split:whole" in callbacks
        assert context.chat_data["split_info"] == chapters_info

    def test_on_split_pick_whole_downloads_full_mix(self, track):
        chapters_info = ChaptersInfo(
            url="https://www.youtube.com/watch?v=mix123",
            title="Best of 2024 Mix",
            uploader="DJ Channel",
            durationMs=3600_000,
            chapters=[ChapterInfo(index=0, title="T1", startMs=0, endMs=100, songTitle="T1")],
        )
        api = FakeApi(chapters_result=chapters_info)
        detail = AlbumDetail(
            id="yt:mix123",
            title="Best of 2024 Mix",
            artist="DJ Channel",
            year=2024,
            trackCount=1,
            durationMs=3600_000,
            tracks=[track],
            source="youtube",
            sourceUrl="https://www.youtube.com/watch?v=mix123",
        )

        async def fake_resolve(ref):
            return detail

        api.resolve_ref = fake_resolve
        context = _context(api)
        context.chat_data["split_url"] = "https://www.youtube.com/watch?v=mix123"
        context.chat_data["split_info"] = chapters_info

        query = AsyncMock()
        query.data = "split:whole"
        query_msg = AsyncMock()
        query.message = query_msg
        update = SimpleNamespace(callback_query=query)

        _run(run.on_split_pick(update, context))

        query.answer.assert_awaited_once()
        query.edit_message_text.assert_awaited_once()
        # باید به دانلود کل میکس یکپارچه هدایت شود
        assert "دانلود کامل میکس" in query.edit_message_text.await_args[0][0]

    def test_on_split_pick_all_runs_split_and_delivers_items(self, track, monkeypatch):
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        item1 = LibraryItem(
            jobId="j1",
            track=track.model_copy(update={"title": "Track 1"}),
            quality="320",
            format="mp3 320",
            path="/tmp/track1.mp3",
            fileUrl="https://example.com/f1",
            streamUrl="https://example.com/s1",
            bytes=1000,
            createdAt=100.0,
        )
        item2 = LibraryItem(
            jobId="j2",
            track=track.model_copy(update={"title": "Track 2"}),
            quality="320",
            format="mp3 320",
            path="/tmp/track2.mp3",
            fileUrl="https://example.com/f2",
            streamUrl="https://example.com/s2",
            bytes=1000,
            createdAt=100.0,
        )
        split_task = SplitStatus(
            taskId="split-task-1",
            status="done",
            percent=100.0,
            done=2,
            total=2,
            items=[item1, item2],
        )

        api = FakeApi(
            split_task=split_task,
            file_bytes=b"track-audio-bytes",
        )
        context = _context(api)
        context.chat_data["split_url"] = "https://www.youtube.com/watch?v=mix123"
        context.chat_data["split_info"] = ChaptersInfo(
            url="https://www.youtube.com/watch?v=mix123",
            title="Mix",
            uploader="DJ",
            durationMs=1000,
            chapters=[
                ChapterInfo(index=0, title="T1", startMs=0, endMs=10, songTitle="T1"),
                ChapterInfo(index=1, title="T2", startMs=10, endMs=20, songTitle="T2"),
            ],
        )

        query = AsyncMock()
        query.data = "split:all"
        query_msg = AsyncMock()
        query_msg.chat_id = 999
        query.message = query_msg
        update = SimpleNamespace(callback_query=query)

        _run(run.on_split_pick(update, context))

        query.answer.assert_awaited_once()
        # هر دو قطعه باید از طریق send_audio ارسال شده باشند
        assert context.bot.send_audio.await_count == 2


# ---------- تست‌های قابلیت‌های فاز ۳ ----------


class TestFavoritesFeature:
    def test_favorites_cmd_empty(self):
        api = FakeApi(favorites_list=[])
        context = _context(api)
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)

        _run(run.favorites_cmd(update, context))

        msg.reply_text.assert_awaited_once()
        assert "هنوز هیچ آهنگی رو به علاقه‌مندی‌ها اضافه نکردی" in msg.reply_text.await_args[0][0]

    def test_favorites_cmd_with_items(self, track):
        item1 = LibraryItem(
            jobId="j1",
            track=track.model_copy(update={"title": "Song 1"}),
            quality="320",
            format="mp3 320",
            path="/tmp/song1.mp3",
            fileUrl="https://example.com/f1",
            streamUrl="https://example.com/s1",
            bytes=1000,
            createdAt=100.0,
        )
        item2 = LibraryItem(
            jobId="j2",
            track=track.model_copy(update={"title": "Song 2"}),
            quality="320",
            format="mp3 320",
            path="/tmp/song2.mp3",
            fileUrl="https://example.com/f2",
            streamUrl="https://example.com/s2",
            bytes=1000,
            createdAt=100.0,
        )
        api = FakeApi(favorites_list=[item1, item2])
        context = _context(api)
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)

        _run(run.favorites_cmd(update, context))

        msg.reply_text.assert_awaited_once()
        text = msg.reply_text.await_args[0][0]
        assert "آهنگ‌های محبوب شما (2 قطعه)" in text
        markup = msg.reply_text.await_args.kwargs.get("reply_markup")
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "lib:j1" in callbacks
        assert "lib:j2" in callbacks
        assert "fav:all" in callbacks
        assert "zip:fav" in callbacks

    def test_on_favorite_pick_add_and_del(self):
        api = FakeApi()
        context = _context(api)

        # ۱. اضافه کردن به علاقه‌مندی‌ها
        query = AsyncMock()
        query.data = "fav:add:job-123"
        query_msg = AsyncMock()
        # کیبورد پیام شامل دکمه افزودن
        fav_btn = run.InlineKeyboardButton("❤️ پسندیدم", callback_data="fav:add:job-123")
        query_msg.reply_markup = run.InlineKeyboardMarkup([[fav_btn]])
        query.message = query_msg
        update = SimpleNamespace(callback_query=query)

        _run(run.on_favorite_pick(update, context))

        assert ("job-123", True) in api.fav_calls
        query.answer.assert_awaited_once()
        assert "اضافه شد" in query.answer.await_args[0][0]
        # بررسی تغییر دکمه به حذف
        query.edit_message_reply_markup.assert_awaited_once()
        new_markup = query.edit_message_reply_markup.await_args.kwargs["reply_markup"]
        assert new_markup.inline_keyboard[0][0].callback_data == "fav:del:job-123"

        # ۲. حذف از علاقه‌مندی‌ها
        query2 = AsyncMock()
        query2.data = "fav:del:job-123"
        del_btn = run.InlineKeyboardButton("💔 حذف", callback_data="fav:del:job-123")
        query_msg.reply_markup = run.InlineKeyboardMarkup([[del_btn]])
        query2.message = query_msg
        update2 = SimpleNamespace(callback_query=query2)

        _run(run.on_favorite_pick(update2, context))

        assert ("job-123", False) in api.fav_calls
        query2.answer.assert_awaited_once()
        assert "حذف شد" in query2.answer.await_args[0][0]


class TestDailyMixFeature:
    def test_mix_cmd_none(self):
        api = FakeApi(daily_mix_result=DailyMix(source="none", items=[]))
        context = _context(api)
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)

        _run(run.mix_cmd(update, context))

        msg.reply_text.assert_awaited_once()
        assert "میکس روزانه هنوز آماده نیست" in msg.reply_text.await_args[0][0]

    def test_mix_cmd_with_items(self, track):
        item = LibraryItem(
            jobId="j1",
            track=track,
            quality="320",
            format="mp3 320",
            path="/tmp/song.mp3",
            fileUrl="https://example.com/f",
            streamUrl="https://example.com/s",
            bytes=1000,
            createdAt=100.0,
        )
        api = FakeApi(daily_mix_result=DailyMix(source="favorites", items=[item]))
        context = _context(api)
        msg = AsyncMock()
        update = SimpleNamespace(message=msg)

        _run(run.mix_cmd(update, context))

        msg.reply_text.assert_awaited_once()
        text = msg.reply_text.await_args[0][0]
        assert "میکس روزانه اختصاصی شما" in text
        assert "آهنگ‌های محبوبت" in text
        markup = msg.reply_text.await_args.kwargs.get("reply_markup")
        assert markup.inline_keyboard[0][0].callback_data == "lib:j1"


class TestZipExportFeature:
    def test_on_zip_pick_fav_small_file_uploads_document(self, track, monkeypatch):
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        item = LibraryItem(
            jobId="j1",
            track=track,
            quality="320",
            format="mp3 320",
            path="/tmp/song.mp3",
            fileUrl="https://example.com/f",
            streamUrl="https://example.com/s",
            bytes=1000,
            createdAt=100.0,
        )
        api = FakeApi(
            favorites_list=[item],
            zip_ready=ZipReady(url="/api/downloads/zip/token123", bytes=5000, files=1),
            zip_bytes=b"PK\x03\x04zipcontent",
        )
        context = _context(api)
        context.chat_data["favorites_list"] = [item]

        query = AsyncMock()
        query.data = "zip:fav"
        query_msg = AsyncMock()
        query_msg.chat_id = 12345
        query.message = query_msg
        update = SimpleNamespace(callback_query=query)

        _run(run.on_zip_pick(update, context))

        query.answer.assert_awaited_once()
        context.bot.send_document.assert_awaited_once()
        kwargs = context.bot.send_document.await_args.kwargs
        assert kwargs["filename"] == "favorites.zip"
        assert kwargs["document"] == b"PK\x03\x04zipcontent"

    def test_on_zip_pick_large_file_sends_direct_link(self, track, monkeypatch):
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: True)
        item = LibraryItem(
            jobId="j1",
            track=track,
            quality="320",
            format="mp3 320",
            path="/tmp/song.mp3",
            fileUrl="https://example.com/f",
            streamUrl="https://example.com/s",
            bytes=1000,
            createdAt=100.0,
        )
        api = FakeApi(
            favorites_list=[item],
            zip_ready=ZipReady(url="/api/downloads/zip/token123", bytes=80 * 1024 * 1024, files=15),
        )
        context = _context(api)
        context.chat_data["favorites_list"] = [item]

        query = AsyncMock()
        query.data = "zip:fav"
        query_msg = AsyncMock()
        query_msg.chat_id = 12345
        query.message = query_msg
        update = SimpleNamespace(callback_query=query)

        _run(run.on_zip_pick(update, context))

        query.answer.assert_awaited_once()
        # نباید سند ارسال شود؛ پیام با لینک مستقیم ادیت می‌شود
        context.bot.send_document.assert_not_awaited()
        calls = query_msg.edit_text.await_args_list
        assert any("لینک مستقیم" in str(c) for c in calls)


# ---------- تست‌های قابلیت‌های فاز ۴ ----------


class TestPaginationPick:
    def test_track_pagination_next_page(self, track):
        tracks = [track.model_copy(update={"id": f"t_{i}", "title": f"Song {i}"}) for i in range(18)]
        context = SimpleNamespace(chat_data={"candidates": tracks, "collection": None})

        query = AsyncMock()
        query.data = "page:track:2"
        update = SimpleNamespace(callback_query=query)

        _run(run.on_page_pick(update, context))

        query.answer.assert_awaited_once()
        query.edit_message_reply_markup.assert_awaited_once()
        markup = query.edit_message_reply_markup.await_args.kwargs["reply_markup"]
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        # در صفحه دوم (8 تا 15) دکمه‌ها باید از pick:8 شروع شوند
        assert "pick:8" in callbacks
        assert "pick:15" in callbacks
        assert "page:track:1" in callbacks
        assert "page:track:3" in callbacks

    def test_cl_pagination(self):
        albums = [
            AlbumDetail(
                id=f"alb_{i}",
                title=f"Album {i}",
                artist="Artist",
                year=2024,
                trackCount=1,
                durationMs=1000,
                tracks=[],
                source="spotify",
                sourceUrl="https://example.com",
            )
            for i in range(12)
        ]
        context = SimpleNamespace(chat_data={"collection_candidates": albums})

        query = AsyncMock()
        query.data = "page:cl:2"
        update = SimpleNamespace(callback_query=query)

        _run(run.on_page_pick(update, context))

        query.answer.assert_awaited_once()
        query.edit_message_reply_markup.assert_awaited_once()
        markup = query.edit_message_reply_markup.await_args.kwargs["reply_markup"]
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "cl:8" in callbacks
        assert "page:cl:1" in callbacks

    def test_on_noop(self):
        query = AsyncMock()
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace()

        _run(run.on_noop(update, context))

        query.answer.assert_awaited_once()


class TestSocialMediaVideoExtraction:
    def test_instagram_reel_resolves_and_delivers(self, track, monkeypatch):
        monkeypatch.setattr(run, "too_large_for_telegram", lambda n: False)
        api = FakeApi()

        async def fake_resolve(url):
            return AlbumDetail(
                id="ig:reel1",
                title="Trending Audio",
                artist="InstaCreator",
                year=2024,
                trackCount=1,
                durationMs=30_000,
                tracks=[track],
                source="youtube",
                sourceUrl=url,
            )

        api.resolve_ref = fake_resolve
        context = _context(api)

        status_msg = AsyncMock()
        msg = AsyncMock()
        msg.reply_text.return_value = status_msg
        msg.text = "https://www.instagram.com/reel/C-123456789/"
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(type="private"))

        _run(run.on_text(update, context))

        # پیام اولیه استخراج نمایش داده شده
        msg.reply_text.assert_awaited_once()
        assert "استخراج" in msg.reply_text.await_args[0][0]
        # ترک ارسال شده
        context.bot.send_audio.assert_awaited_once()


class TestGroupAntiSpam:
    def test_group_ignores_normal_messages(self):
        api = FakeApi()
        context = _context(api)
        context.bot_data["username"] = "musicbazi_bot"

        msg = AsyncMock()
        msg.text = "سلام بچه‌ها حالتون چطوره؟"
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(type="supergroup"))

        _run(run.on_text(update, context))

        # در گروه نباید به پیام چت معمولی اعضا هیچ پاسخی داده شود
        msg.reply_text.assert_not_awaited()

    def test_group_responds_when_bot_is_mentioned(self, track, monkeypatch):
        api = FakeApi()
        track2 = track.model_copy(update={"id": "t2", "title": "Track 2"})

        async def fake_search(q):
            assert q == "مرد تنها"
            return SimpleNamespace(tracks=[track, track2])

        api.search = fake_search
        context = _context(api)
        context.bot_data["username"] = "musicbazi_bot"

        msg = AsyncMock()
        msg.text = "@musicbazi_bot مرد تنها"
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(type="supergroup"))

        _run(run.on_text(update, context))

        # به پیام دارای منشن پاسخ داده شده و منشن از جستجو پاک شده است
        msg.reply_text.assert_awaited_once()
        assert context.chat_data.get("candidates") == [track, track2]

    def test_group_responds_when_reply_to_bot(self, track, monkeypatch):
        api = FakeApi()
        track2 = track.model_copy(update={"id": "t2", "title": "Track 2"})

        async def fake_search(q):
            return SimpleNamespace(tracks=[track, track2])

        api.search = fake_search
        context = _context(api)
        context.bot.id = 999

        msg = AsyncMock()
        msg.text = "مرد تنها"
        msg.reply_to_message = SimpleNamespace(from_user=SimpleNamespace(id=999))
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(type="group"))

        _run(run.on_text(update, context))

        msg.reply_text.assert_awaited_once()
        assert context.chat_data.get("candidates") == [track, track2]


class TestLyricsTruncation:
    def test_long_lyrics_truncation_preserves_html_entities(self):
        padding = "A" * 3850
        body = f"{padding} &amp; &lt;hello&gt; and some more text exceeding four thousand characters total"
        store.save_lyrics("testhash12345678", body, title="Song & More", artist="Artist & Band")

        query = AsyncMock()
        query.data = "lyr:testhash12345678"
        query.message = AsyncMock()
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(bot=AsyncMock())

        _run(run.on_lyrics_pick(update, context))

        query.message.reply_text.assert_awaited_once()
        sent_text = query.message.reply_text.await_args[0][0]
        assert not re.search(r"&[a-zA-Z0-9#]+…", sent_text)
        assert "…" in sent_text


class TestCallbackDataLimits:
    def test_zip_album_callback_fits_telegram_limit(self):
        long_id = "https://music.youtube.com/playlist?list=OLAK5uy_k9876543210123456789012345678901234567890"
        alb_key = store.safe_callback_ref(long_id)
        callback_data = f"zip:alb:{alb_key}"
        assert len(callback_data.encode("utf-8")) <= 64
        assert store.resolve_callback_ref(alb_key) == long_id

    def test_artist_profile_view_buttons_fit_64_bytes(self):
        long_artist_id = "https://open.spotify.com/artist/4Z8W4fKeB5YxbusRsdQVPb_extra_long_padding_url_1234567890"
        detail = ArtistDetail(
            id=long_artist_id,
            name="Test Artist",
            source="spotify",
            sourceUrl=long_artist_id,
            subtitle="Bio text",
            topTracks=[],
            albums=[],
            playlists=[],
            radio=[],
            related=[],
        )
        context = _context(FakeApi())
        view = _run(run._artist_profile_view(context, detail))
        assert view is not None
        text, markup = view
        for row in markup.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode("utf-8")) <= 64

    def test_unfollow_cmd_buttons_fit_64_bytes(self):
        long_artist_id = "https://open.spotify.com/artist/4Z8W4fKeB5YxbusRsdQVPb_extra_long_padding_url_1234567890"
        follow = Follow(
            id=1,
            chatId=123,
            artistId=long_artist_id,
            artistName="Very Long Artist Name",
            artistSourceUrl=long_artist_id,
            source="spotify",
        )
        api = FakeApi()
        api.follows = AsyncMock(return_value=[follow])
        context = _context(api)
        msg = AsyncMock()
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=123, type="private"))
        _run(run.unfollow_cmd(update, context))
        msg.reply_text.assert_awaited_once()
        markup = msg.reply_text.await_args[1]["reply_markup"]
        for row in markup.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode("utf-8")) <= 64
                raw_id = btn.callback_data.split(":", 1)[1]
                assert store.resolve_callback_ref(raw_id) == long_artist_id


class TestSearchAndSettingsCommands:
    def test_search_cmd_with_arguments(self, track):
        api = FakeApi()
        track2 = track.model_copy(update={"id": "t2", "title": "Track 2"})
        async def fake_search(q):
            return SimpleNamespace(tracks=[track, track2])
        api.search = fake_search
        context = _context(api)
        context.args = ["farhad", "mehrad"]
        msg = AsyncMock()
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=123, type="private"))
        _run(run.search_cmd(update, context))
        msg.reply_text.assert_awaited_once()

    def test_search_cmd_without_arguments_sends_force_reply(self):
        api = FakeApi()
        context = _context(api)
        context.args = []
        msg = AsyncMock()
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=123, type="private"))
        _run(run.search_cmd(update, context))
        msg.reply_text.assert_awaited_once()
        assert context.chat_data.get("search_mode") == "track"
        assert isinstance(msg.reply_text.await_args[1].get("reply_markup"), ForceReply)

    def test_settings_cmd_invokes_quality(self):
        api = FakeApi()
        context = _context(api)
        msg = AsyncMock()
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=123, type="private"))
        _run(run.settings_cmd(update, context))
        msg.reply_text.assert_awaited_once()
        assert "کیفیت" in msg.reply_text.await_args[0][0]


class TestUrlPriorityOverSearchMode:
    def test_direct_track_url_clears_and_bypasses_search_mode(self, track):
        api = FakeApi()
        track2 = track.model_copy(update={"id": "t2", "title": "Track 2"})
        async def fake_resolve(url):
            return AlbumDetail(
                id="alb-1",
                title="Album",
                artist="Artist",
                year=2024,
                trackCount=2,
                durationMs=180_000,
                tracks=[track, track2],
                source="spotify",
                sourceUrl=url,
            )
        api.resolve_ref = fake_resolve
        context = _context(api)
        context.chat_data["search_mode"] = "vibe"

        msg = AsyncMock()
        msg.text = "https://open.spotify.com/album/4Z8W4fKeB5YxbusRsdQVPb"
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=123, type="private"))

        _run(run.on_text(update, context))

        assert "search_mode" not in context.chat_data
        assert context.chat_data.get("collection") is not None


class TestStatusSinkFallback:
    def test_status_sink_sends_new_message_when_no_existing_message(self):
        bot = AsyncMock()
        bot.send_message.return_value = AsyncMock()
        context = SimpleNamespace(bot=bot)
        sink = run._StatusSink(context, message=None, chat_id=12345)
        _run(sink.edit("پیام جدید فالبک"))
        bot.send_message.assert_awaited_once_with(12345, "پیام جدید فالبک")


class TestQualityCacheDowngradePrevention:
    def test_cached_128_does_not_satisfy_flac_request(self, track):
        store.save_telegram_file(track.id, file_id="fid-128", quality="128")
        api = FakeApi()
        context = _context(api)
        context.chat_data["quality"] = "flac"

        with pytest.raises(Exception):
            _run(run._download_and_send(context, chat_id=123, track=track, quality="flac"))

        context.bot.send_audio.assert_not_called()


class TestIdentifyLimits:
    def test_media_larger_than_20mb_rejected_immediately(self):
        api = FakeApi()
        context = _context(api)
        msg = AsyncMock()
        msg.voice = SimpleNamespace(file_id="voice-large", file_size=21 * 1024 * 1024)
        msg.audio = None
        msg.video = None
        msg.video_note = None
        msg.document = None
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=123, type="private"))

        _run(run.on_media(update, context))

        msg.reply_text.assert_awaited_once()
        assert "۲۰ مگابایت" in msg.reply_text.await_args[0][0]
        context.bot.get_file.assert_not_called()


class TestArtistSearchNoneView:
    def test_artist_search_with_url_handles_none_view(self):
        import unittest.mock as mock
        api = FakeApi()
        api.artist = AsyncMock(return_value=ArtistDetail(
            id="art-1", name="Art", subtitle="Sub", source="spotify", sourceUrl="https://open.spotify.com/artist/1",
            topTracks=[], albums=[], playlists=[], radio=[], related=[]
        ))
        context = _context(api)
        msg = AsyncMock()
        with mock.patch("app.bot.run._artist_profile_view", new=AsyncMock(return_value=None)):
            _run(run._artist_search(msg, context, "https://open.spotify.com/artist/1"))
        msg.reply_text.assert_awaited_once_with("هنرمندی پیدا نشد.")


class TestApiClientConfiguration:
    def test_client_has_follow_redirects_enabled(self):
        from app.bot.client import ApiClient
        client = ApiClient(base_url="http://localhost:8000")
        assert client._http.follow_redirects is True
        _run(client.aclose())

    def test_client_mounts_bypass_localhost_when_proxy_set(self):
        from app.bot.client import ApiClient
        client = ApiClient(base_url="http://localhost:8000", proxy="http://127.0.0.1:1080")
        assert client._http._mounts is not None
        _run(client.aclose())


class TestBatchDeliveryWithFallbackSink:
    def test_fav_all_delivers_items_safely(self, track):
        item = LibraryItem(
            jobId="j1",
            track=track,
            quality="320",
            format="mp3",
            bytes=1000,
            fileUrl="http://localhost/file",
            streamUrl="http://localhost/stream",
            createdAt=1.0,
            favorite=True,
        )
        api = FakeApi()
        context = _context(api)
        context.chat_data["favorites_list"] = [item]

        query = AsyncMock()
        query.message = AsyncMock()
        query.message.chat_id = 12345
        update = SimpleNamespace(callback_query=query)

        _run(run.on_fav_all(update, context))
        context.bot.send_audio.assert_awaited_once()

    def test_mix_all_delivers_items_safely(self, track):
        item = LibraryItem(
            jobId="j1",
            track=track,
            quality="320",
            format="mp3",
            bytes=1000,
            fileUrl="http://localhost/file",
            streamUrl="http://localhost/stream",
            createdAt=1.0,
            favorite=True,
        )
        api = FakeApi()
        context = _context(api)
        context.chat_data["daily_mix_items"] = [item]

        query = AsyncMock()
        query.message = AsyncMock()
        query.message.chat_id = 12345
        update = SimpleNamespace(callback_query=query)

        _run(run.on_mix_all(update, context))
        context.bot.send_audio.assert_awaited_once()


class TestSplitDownloadTimeout:
    def test_split_download_times_out(self):
        api = FakeApi()
        task = SplitStatus(taskId="t1", status="cutting", percent=10.0, done=1, total=5, items=[])
        api.create_split = AsyncMock(return_value=task)
        api.split_status = AsyncMock(return_value=task)
        context = _context(api)

        msg = AsyncMock()
        msg.reply_text.return_value = AsyncMock()

        # Monkeypatch time.monotonic to simulate 700s passage
        import time as pytime
        current_time = 100.0
        def fake_monotonic():
            nonlocal current_time
            current_time += 150.0
            return current_time

        import unittest.mock as mock
        with mock.patch("time.monotonic", side_effect=fake_monotonic):
            _run(run._run_split_download(context, msg, "https://youtube.com/watch?v=123"))

        status_sink_msg = msg.reply_text.return_value
        status_sink_msg.edit_text.assert_awaited()
        last_edit = status_sink_msg.edit_text.await_args[0][0]
        assert "طول کشید" in last_edit


class TestMediaIdentificationFlow:
    def test_on_media_success_identifies_and_sends_picker(self, track):
        from app.models import IdentifyMatch, IdentifyResult
        api = FakeApi()
        match = IdentifyMatch(title="Track 1", artist="Artist 1", score=0.95)
        api.identify = AsyncMock(return_value=IdentifyResult(matches=[match], tracks=[track]))
        context = _context(api)

        file_handle = AsyncMock()
        file_handle.download_as_bytearray = AsyncMock(return_value=bytearray(b"fakeaudiobytes"))
        context.bot.get_file = AsyncMock(return_value=file_handle)

        msg = AsyncMock()
        status_msg = AsyncMock()
        msg.reply_text.return_value = status_msg
        msg.voice = SimpleNamespace(file_id="voice-123", file_size=1000)
        msg.audio = None
        msg.video = None
        msg.video_note = None
        msg.document = None
        update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=123, type="private"))

        _run(run.on_media(update, context))

        status_msg.edit_text.assert_awaited()
        # Single track in result.tracks sends track directly
        context.bot.send_audio.assert_awaited_once()





