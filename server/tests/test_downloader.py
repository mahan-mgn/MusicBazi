"""نام‌گذاری فایل، انتخاب فرمت و نوشتن متن آهنگ."""

from __future__ import annotations

import pytest

from app import downloader
from app.downloader import (
    BITRATE,
    CODEC_BITRATE,
    EXT,
    _ydl_opts,
    download,
    safe_name,
    write_lrc,
)
from app.models import Track
from app.providers.lrclib import Lyrics


class TestSafeName:
    @pytest.mark.parametrize("char", list('\\/:*?"<>|'))
    def test_windows_forbidden_characters_are_replaced(self, char):
        assert char not in safe_name(f"a{char}b")

    def test_persian_is_untouched(self):
        assert safe_name("فرهاد مهراد - مرد تنها") == "فرهاد مهراد - مرد تنها"

    def test_length_is_capped(self):
        assert len(safe_name("x" * 500)) == 120

    def test_trailing_dot_is_stripped(self):
        # ویندوز فایلی که به نقطه ختم شود را نمی‌پذیرد
        assert not safe_name("album.").endswith(".")

    def test_empty_falls_back(self):
        assert safe_name("   ") == "track"


class TestQualityOptions:
    def test_every_quality_has_an_extension(self):
        for quality in (*BITRATE, *CODEC_BITRATE):
            assert quality in EXT

    def test_mp3_bitrate_reaches_the_postprocessor(self, tmp_path):
        opts = _ydl_opts(tmp_path / "x", "192", lambda _: None)
        step = opts["postprocessors"][0]
        assert step["preferredcodec"] == "mp3"
        assert step["preferredquality"] == "192"

    def test_flac_does_not_carry_a_bitrate(self, tmp_path):
        """بیت‌ریت روی کدک بی‌اتلاف بی‌معنی است و ffmpeg هم قبولش نمی‌کند."""
        step = _ydl_opts(tmp_path / "x", "flac", lambda _: None)["postprocessors"][0]
        assert step["preferredcodec"] == "flac"
        assert "preferredquality" not in step

    def test_m4a_prefers_a_source_it_can_copy(self, tmp_path):
        opts = _ydl_opts(tmp_path / "x", "m4a", lambda _: None)
        assert "ext=m4a" in opts["format"]

    def test_original_does_not_transcode(self, tmp_path):
        assert _ydl_opts(tmp_path / "x", "original", lambda _: None)["postprocessors"] == []

    def test_hook_aborts_when_the_job_is_canceled(self, tmp_path):
        """
        لغو تسکِ asyncio نخِ دانلود را نمی‌کشد؛ yt-dlp تا آخر ادامه می‌داد و فایل
        را بعد از «لغو شد» روی دیسک می‌نوشت. hook تنها جایی است که می‌شود
        از داخل نخ جلویش را گرفت.
        """
        from app.downloader import DownloadCanceled

        stop = False
        hook = _ydl_opts(tmp_path / "x", "320", lambda _: None, lambda: stop)[
            "progress_hooks"
        ][0]

        hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})

        stop = True
        with pytest.raises(DownloadCanceled):
            hook({"status": "downloading", "downloaded_bytes": 2, "total_bytes": 2})

    def test_hook_without_an_abort_check_never_raises(self, tmp_path):
        hook = _ydl_opts(tmp_path / "x", "320", lambda _: None)["progress_hooks"][0]
        hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})

    def test_progress_hook_is_normalized_to_percent(self, tmp_path):
        seen: list[float] = []
        opts = _ydl_opts(tmp_path / "x", "320", seen.append)
        hook = opts["progress_hooks"][0]

        hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 200})
        hook({"status": "finished"})  # باید نادیده برود
        hook({"status": "downloading", "downloaded_bytes": 200, "total_bytes": 200})

        # سقف ۹۹ است: ۱۰۰٪ مال وقتی است که تگ‌گذاری هم تمام شده باشد
        assert seen == [25.0, 99.0]


class TestOutputIsolation:
    """
    اسم فایل فقط «هنرمند - عنوان» است و کیفیت را در خود ندارد. وقتی همه‌ی
    جاب‌ها در یک پوشه می‌نوشتند، گرفتن همان ترک با کیفیت دیگر فایل قبلی را پاک
    می‌کرد و ردیف قدیمی به فایل جدید اشاره می‌ماند — کتابخانه یک فایل را دو بار
    با دو برچسبِ متفاوت نشان می‌داد و «۱۲۸» عملاً ۳۲۰ تحویل می‌داد.
    """

    @pytest.fixture
    def fake_ydl(self, monkeypatch):
        """yt-dlp تقلبی که فقط یک فایل با حجم مشخص می‌سازد."""
        import yt_dlp

        def factory(size: int):
            class FakeYDL:
                def __init__(self, opts):
                    self.opts = opts

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def extract_info(self, url, download=True):
                    from pathlib import Path

                    target = Path(self.opts["outtmpl"].replace(".%(ext)s", ".mp3"))
                    target.write_bytes(b"a" * size)
                    return {"id": "x"}

            monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

        return factory

    def test_two_qualities_do_not_share_a_file(self, tmp_path, track, fake_ydl):
        fake_ydl(1000)
        low = download(track, "u", "128", lambda _: None, tmp_path / "job-a")

        fake_ydl(4000)
        high = download(track, "u", "320", lambda _: None, tmp_path / "job-b")

        assert low != high
        assert low.exists() and high.exists()
        # فایل کیفیت پایین باید دست‌نخورده مانده باشد
        assert low.stat().st_size == 1000
        assert high.stat().st_size == 4000

    def test_filename_stays_clean(self, tmp_path, track, fake_ydl):
        """کیفیت در مسیر می‌نشیند نه در نام — نام همان چیزی است که کاربر می‌گیرد."""
        fake_ydl(10)
        path = download(track, "u", "320", lambda _: None, tmp_path / "job-a")
        assert path.name == f"{track.artist} - {track.title}.mp3"

    def test_leftovers_of_a_previous_attempt_are_cleared(self, tmp_path, track, fake_ydl):
        out = tmp_path / "job-a"
        out.mkdir()
        stale = out / f"{track.artist} - {track.title}.part"
        stale.write_bytes(b"junk")

        fake_ydl(10)
        download(track, "u", "320", lambda _: None, out)
        assert not stale.exists()


class TestLyrics:
    def test_lrc_lands_next_to_the_audio(self, tmp_path):
        audio = tmp_path / "Farhad - Barf.mp3"
        audio.write_bytes(b"")
        path = write_lrc(audio, Lyrics(plain="x", synced="[00:01.00]x"))
        # هم‌نامی با فایل صوتی همان چیزی است که پلیرها دنبالش می‌گردند
        assert path == tmp_path / "Farhad - Barf.lrc"
        assert path.read_text(encoding="utf-8") == "[00:01.00]x"

    def test_plain_only_falls_back_to_plain_text(self, tmp_path):
        """جینیوس هیچ‌وقت هم‌زمان‌شده نمی‌دهد — بدون این، متنش هیچ‌وقت به .lrc نمی‌رسید."""
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"")
        path = write_lrc(audio, Lyrics(plain="just text", synced=None))
        assert path == tmp_path / "a.lrc"
        assert path.read_text(encoding="utf-8") == "just text"

    def test_no_lyrics_writes_nothing(self, tmp_path):
        assert write_lrc(tmp_path / "a.mp3", None) is None

    def test_empty_lyrics_is_falsy(self):
        assert not Lyrics(plain=None, synced=None)
        assert Lyrics(plain="x", synced=None)


class TestArtworkProxy:
    """
    کاورِ ساندکلاد/یوتیوب از همان شبکه‌ای می‌آید که فایل صوتی از آن خوانده
    می‌شود. `MUSICBAZI_YTDLP_PROXY` برای همین هست: وقتی فقط آن دو پروکسی
    می‌خواهند و کاتالوگ‌ها مستقیم در دسترس‌اند. تا پیش از این، کاور همیشه از
    `PROXY` می‌رفت — یعنی با آن تنظیمِ کاملاً مجاز، متادیتای ترک از پروکسی
    می‌آمد ولی کاورش مستقیم، و فایل بی‌کاور می‌شد بدون اینکه چیزی خطا بدهد.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://i1.sndcdn.com/artworks-abc-original.jpg",
            "https://i.ytimg.com/vi/abc/maxresdefault.jpg",
            "https://lh3.googleusercontent.com/abc=w1400-h1400",
        ],
    )
    def test_media_cdns_go_through_the_extractor_proxy(self, url, monkeypatch):
        monkeypatch.setattr(downloader, "YTDLP_PROXY", "socks5h://ytdlp:1080")
        monkeypatch.setattr(downloader, "PROXY", "http://catalog:8080")

        assert downloader._proxy_for(url) == "socks5h://ytdlp:1080"

    @pytest.mark.parametrize(
        "url",
        [
            "https://is1-ssl.mzstatic.com/image/thumb/Music/abc/source/100x100bb.jpg",
            "https://e-cdns-images.dzcdn.net/images/cover/abc/500x500.jpg",
            "https://i.scdn.co/image/ab67616d0000b273" + "1" * 24,
        ],
    )
    def test_catalog_cdns_keep_the_general_proxy(self, url, monkeypatch):
        monkeypatch.setattr(downloader, "YTDLP_PROXY", "socks5h://ytdlp:1080")
        monkeypatch.setattr(downloader, "PROXY", "http://catalog:8080")

        assert downloader._proxy_for(url) == "http://catalog:8080"

    def test_a_lookalike_domain_is_not_treated_as_the_cdn(self):
        """`evil-sndcdn.com` زیردامنه‌ی sndcdn نیست؛ پسوندِ خام این را قاطی می‌کرد."""
        assert downloader._proxy_for("https://evil-sndcdn.com/x.jpg") == downloader.PROXY


class TestCoverIsReported:
    """
    شکستِ گرفتنِ کاور کشنده نیست ولی بی‌صدا هم نباید باشد: فایل پخش می‌شود و در
    پلیر بی‌تصویر می‌ماند، و تا پیش از این هیچ‌جا نوشته نمی‌شد که چرا.
    """

    def _track(self, **over):
        base = {
            "id": "sc:track:1",
            "title": "BAD VIBE SHIT",
            "artist": "Mvshreghi",
            "durationMs": 143_225,
            "source": "soundcloud",
            "sourceUrl": "https://soundcloud.com/mvshreghi/bad-vibe-shit",
            "artworkUrl": "https://i1.sndcdn.com/artworks-abc-t500x500.jpg",
        }
        return Track(**{**base, **over})

    def test_a_cover_that_lands_is_reported_as_landed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(downloader, "_fetch_artwork", lambda url: (b"\xff\xd8", "image/jpeg"))
        monkeypatch.setitem(downloader._TAGGERS, ".mp3", lambda *a: None)
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"")

        assert downloader.tag(audio, self._track()) is True

    def test_a_cover_that_never_arrives_is_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(downloader, "_fetch_artwork", lambda url: None)
        monkeypatch.setitem(downloader._TAGGERS, ".mp3", lambda *a: None)
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"")

        assert downloader.tag(audio, self._track()) is False

    def test_a_tagger_that_blows_up_still_leaves_the_audio_alone(self, tmp_path, monkeypatch):
        def boom(*_a):
            raise RuntimeError("mutagen said no")

        monkeypatch.setattr(downloader, "_fetch_artwork", lambda url: (b"\xff\xd8", "image/jpeg"))
        monkeypatch.setitem(downloader._TAGGERS, ".mp3", boom)
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"audio")

        assert downloader.tag(audio, self._track()) is False
        assert audio.read_bytes() == b"audio"

    def test_finalize_carries_both_the_lrc_and_the_cover_verdict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(downloader, "fetch_lyrics", lambda track: Lyrics(plain="x", synced=None))
        monkeypatch.setattr(downloader, "_fetch_artwork", lambda url: None)
        monkeypatch.setitem(downloader._TAGGERS, ".mp3", lambda *a: None)
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"")

        final = downloader.finalize(audio, self._track())

        assert final.cover is False
        assert final.lyrics_path == tmp_path / "a.lrc"
