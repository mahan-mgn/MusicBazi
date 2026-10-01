"""صفِ دانلودِ معوق — دانلودی که موقعِ قطعی خواسته شده و بعداً خودش راه می‌افتد."""

from __future__ import annotations

import asyncio

import pytest

from app import jobs as jobs_mod
from app import reach
from app.jobs import JobManager


@pytest.fixture
def manager(fresh_db, monkeypatch):
    """
    مدیرِ صف با اجرای واقعی خاموش.

    `_run` همان چیزی است که به یوتیوب و ساندکلاد وصل می‌شود؛ چیزی که اینجا
    آزموده می‌شود *تصمیمِ* شروع‌کردن است، نه خودِ دانلود.
    """
    started: list[str] = []

    async def fake_run(self, job):
        started.append(job.id)

    monkeypatch.setattr(JobManager, "_run", fake_run)
    mgr = JobManager()
    mgr.started = started  # type: ignore[attr-defined]
    return mgr


@pytest.fixture(autouse=True)
def online_again():
    yield
    reach._set(True, ())


def test_a_download_asked_for_during_a_blackout_waits_instead_of_failing(manager, track):
    """
    رفتارِ قبلی این بود که جاب فوراً شروع می‌شد، سی ثانیه تایم‌اوت می‌خورد و
    `error` می‌گرفت — و کاربر باید یادش می‌ماند بعداً دوباره بزند.
    """
    reach._set(False, ())

    async def go():
        job, reused = manager.create(track, "320")
        return job, reused

    job, reused = asyncio.run(go())
    assert reused is False
    assert job.progress.status == "deferred"
    assert manager.started == []  # هیچ دانلودی شروع نشده


def test_the_deferred_queue_starts_when_the_internet_returns(manager, track):
    reach._set(False, ())

    async def go():
        manager.create(track, "320")
        reach._set(True, ())
        started = manager.resume_deferred()
        # به تسک‌های تازه‌ساخته‌شده فرصتِ اجرا بده
        await asyncio.sleep(0)
        return started

    assert asyncio.run(go()) == 1
    assert len(manager.started) == 1


def test_resuming_twice_does_not_download_the_same_track_twice(manager, track):
    """
    هم حلقه‌ی پس‌زمینه صدایش می‌زند هم دکمه‌ی «دوباره امتحان کن».

    بدونِ شرطِ وضعیت در `start_deferred`، دو تسکِ موازی روی یک فایل می‌نشستند.
    """
    reach._set(False, ())

    async def go():
        manager.create(track, "320")
        reach._set(True, ())
        first = manager.resume_deferred()
        second = manager.resume_deferred()
        await asyncio.sleep(0)
        return first, second

    first, second = asyncio.run(go())
    assert (first, second) == (1, 0)
    assert len(manager.started) == 1


def test_a_deferred_job_survives_a_server_restart(manager, fresh_db, track):
    """
    قطعی ممکن است روزها طول بکشد و سرور در آن مدت بارها بالا و پایین می‌شود.

    `mark_interrupted` هر کارِ نیمه‌کاره را به `error` می‌برد؛ اگر `deferred` را
    هم می‌برد، صف با هر ری‌استارت خالی می‌شد — یعنی اصلاً صف نبود.
    """
    reach._set(False, ())
    asyncio.run(_create(manager, track))

    fresh_db.mark_interrupted()

    rows = fresh_db.deferred_jobs()
    assert len(rows) == 1
    assert rows[0]["status"] == "deferred"


def test_a_manual_source_pick_is_not_lost_while_waiting(manager, fresh_db, track):
    """
    انتخابِ دستی یعنی «آنی که خودت می‌گیری غلط است».

    بین انتخاب و اجرا ممکن است روزها و یک ری‌استارت فاصله باشد. اگر آن انتخاب
    فقط در حافظه بماند، کار بعداً با همان نسخه‌ی ناخواسته اجرا می‌شود و کاربر
    هیچ‌وقت نمی‌فهمد چرا.
    """
    reach._set(False, ())
    picked = "https://soundcloud.com/user/the-right-one"
    asyncio.run(_create(manager, track, picked))

    row = fresh_db.deferred_jobs()[0]
    assert row["candidate_url"] == picked

    # بعد از ری‌استارت، از روی همان ردیف بازسازی می‌شود
    revived = JobManager()._from_row(row)
    assert revived.candidate_url == picked


def test_an_already_downloaded_track_is_reused_even_during_a_blackout(manager, fresh_db, track):
    """
    بازاستفاده هیچ ربطی به شبکه ندارد — فایل روی دیسک است.

    اگر قطعی جلوی این مسیر را می‌گرفت، «دانلودِ همه»ی آلبومی که نصفش را داری
    در حالتِ اینترانت کاملاً بی‌فایده می‌شد؛ با آن، نصفِ موجود فوراً می‌آید و
    فقط بقیه صف می‌کشند.
    """
    path = fresh_db.DB_PATH.parent / "song.mp3"
    path.write_bytes(b"audio")
    fresh_db.insert_job("old", track, "320", "ready", 1.0)
    fresh_db.update_job("old", path=str(path), bytes=5)

    reach._set(False, ())
    job, reused = asyncio.run(_create(manager, track))
    assert reused is True
    assert job.progress.status == "ready"


async def _create(manager, track, candidate_url=None):
    return manager.create(track, "320", candidate_url)


def test_defer_can_be_switched_off(manager, track, monkeypatch):
    """
    `MUSICBAZI_DEFER_DOWNLOADS=0` باید دقیقاً رفتارِ قبلی را برگرداند — تلاش
    کردن و شکست خوردن، برای کسی که ترجیح می‌دهد خطا را همان لحظه ببیند.
    """
    monkeypatch.setattr(jobs_mod, "DEFER_DOWNLOADS", False)
    reach._set(False, ())

    job, _ = asyncio.run(_create(manager, track))
    assert job.progress.status == "queued"
