"""
دکمه‌ی «فرستادن به تلگرام» در وب.

سرور خودش با تلگرام حرف نمی‌زند — فقط یک اتصال و یک صف نگه می‌دارد و بات
(پروسه‌ی جدا) صف را برمی‌دارد. پس چیزی که اینجا باید ثابت شود این است: کد
یک‌بار بیشتر خرج نمی‌شود، بدونِ اتصال چیزی در صف نمی‌نشیند، و یک کار دوبار
تحویلِ دو بات نمی‌شود.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import HTTPException

from app import main, telegram
from app.models import (
    TelegramHeartbeat,
    TelegramJobResult,
    TelegramPairClaim,
    TelegramSendRequest,
    TrackRef,
)


@pytest.fixture
def tg(fresh_db):
    """دیتابیسِ خالی + حالتِ درون‌حافظه‌ایِ پاک، و باتی که «بالاست»."""
    telegram.reset()
    telegram.heartbeat("musicbazi_bot")
    return fresh_db


def _ref(track) -> TrackRef:
    return TrackRef(
        trackId=track.id,
        sourceUrl=track.sourceUrl,
        title=track.title,
        artist=track.artist,
        album=track.album,
        durationMs=track.durationMs,
    )


def _send(track, quality="320"):
    return TelegramSendRequest(kind="track", track=_ref(track), title=track.title, quality=quality)


def _link(chat_id=42, title="پیوی من"):
    return asyncio.run(main.telegram_claim(TelegramPairClaim(code=_code(), chatId=chat_id, chatTitle=title)))


def _code() -> str:
    return asyncio.run(main.telegram_pair()).code


# ---------- وصل‌شدن ----------


def test_pairing_links_the_chat_that_used_the_code(tg):
    status = _link(chat_id=99, title="گروهِ ما")

    assert status.linked is True
    assert status.chatTitle == "گروهِ ما"
    assert tg.telegram_chat()["chat_id"] == 99


def test_a_code_works_only_once(tg):
    code = _code()
    asyncio.run(main.telegram_claim(TelegramPairClaim(code=code, chatId=1, chatTitle="اول")))

    # همان کد اگر فوروارد شود نباید چتِ دومی را هم وصل کند
    with pytest.raises(HTTPException) as err:
        asyncio.run(main.telegram_claim(TelegramPairClaim(code=code, chatId=2, chatTitle="دوم")))
    assert err.value.status_code == 404
    assert tg.telegram_chat()["chat_id"] == 1


def test_expired_code_is_rejected(tg):
    code = telegram.new_code(now=time.time() - telegram.PAIR_TTL - 1)

    with pytest.raises(HTTPException) as err:
        asyncio.run(main.telegram_claim(TelegramPairClaim(code=code, chatId=1, chatTitle="x")))
    assert err.value.status_code == 404


def test_relinking_replaces_the_previous_chat(tg):
    _link(chat_id=1, title="اول")
    _link(chat_id=2, title="دوم")

    assert tg.telegram_chat()["chat_id"] == 2


def test_pairing_needs_a_running_bot(tg):
    telegram.reset()

    with pytest.raises(HTTPException) as err:
        asyncio.run(main.telegram_pair())
    assert err.value.status_code == 503


def test_deep_link_carries_the_code(tg):
    pairing = asyncio.run(main.telegram_pair())

    assert pairing.deepLink == f"https://t.me/musicbazi_bot?start=link_{pairing.code}"


def test_status_separates_not_linked_from_bot_down(tg):
    down = asyncio.run(main.telegram_status())
    assert (down.connected, down.linked) == (True, False)

    _link()
    telegram.reset()
    offline = asyncio.run(main.telegram_status())
    assert (offline.connected, offline.linked) == (False, True)


def test_unlink_drops_pending_work(tg, track):
    _link()
    asyncio.run(main.telegram_send(_send(track), request=None))

    asyncio.run(main.telegram_unlink())

    assert tg.telegram_chat() is None
    assert asyncio.run(main.telegram_next_job(wait=0)) is None


# ---------- صف ----------


def test_send_without_a_link_is_refused(tg, track):
    with pytest.raises(HTTPException) as err:
        asyncio.run(main.telegram_send(_send(track), request=None))
    assert err.value.status_code == 409


def test_send_while_bot_is_down_is_refused(tg, track):
    _link()
    telegram.reset()

    with pytest.raises(HTTPException) as err:
        asyncio.run(main.telegram_send(_send(track), request=None))
    assert err.value.status_code == 503


def test_queued_track_reaches_the_bot_whole(tg, track):
    _link(chat_id=77)
    sent = asyncio.run(main.telegram_send(_send(track, quality="flac"), request=None))

    job = asyncio.run(main.telegram_next_job(wait=0))

    assert job.id == sent.id
    assert job.chatId == 77
    assert job.kind == "track"
    # کیفیتِ لحظه‌ی کلیک، نه پیش‌فرضِ بات
    assert job.quality == "flac"
    # متادیتای فرانت باید سالم برسد وگرنه بات مجبور به lookup دوباره است
    assert (job.track.title, job.track.artist) == (track.title, track.artist)


def test_album_is_queued_as_a_reference(tg):
    _link()
    asyncio.run(
        main.telegram_send(
            TelegramSendRequest(kind="album", ref="deezer:album:5", title="آلبوم"), request=None
        )
    )

    job = asyncio.run(main.telegram_next_job(wait=0))

    assert (job.kind, job.ref, job.track) == ("album", "deezer:album:5", None)


def test_album_without_a_reference_is_refused(tg):
    _link()

    with pytest.raises(HTTPException) as err:
        asyncio.run(
            main.telegram_send(TelegramSendRequest(kind="album", title="آلبوم"), request=None)
        )
    assert err.value.status_code == 400


def test_a_job_is_handed_out_only_once(tg, track):
    _link()
    asyncio.run(main.telegram_send(_send(track), request=None))

    first = asyncio.run(main.telegram_next_job(wait=0))
    second = asyncio.run(main.telegram_next_job(wait=0))

    assert first is not None
    assert second is None


def test_jobs_come_out_in_order(tg, track):
    _link()
    ids = [asyncio.run(main.telegram_send(_send(track), request=None)).id for _ in range(3)]

    got = [asyncio.run(main.telegram_next_job(wait=0)).id for _ in range(3)]

    assert got == ids


def test_web_sees_the_result_the_bot_reported(tg, track):
    _link()
    sent = asyncio.run(main.telegram_send(_send(track), request=None))
    asyncio.run(main.telegram_next_job(wait=0))

    asyncio.run(main.telegram_job_done(sent.id, TelegramJobResult(error="فایل آماده نبود.")))

    status = asyncio.run(main.telegram_send_status(sent.id))
    assert (status.status, status.error) == ("error", "فایل آماده نبود.")


def test_successful_send_ends_as_done(tg, track):
    _link()
    sent = asyncio.run(main.telegram_send(_send(track), request=None))
    asyncio.run(main.telegram_next_job(wait=0))

    asyncio.run(main.telegram_job_done(sent.id, TelegramJobResult()))

    assert asyncio.run(main.telegram_send_status(sent.id)).status == "done"


def test_interrupted_jobs_go_back_to_the_queue(tg, track):
    """
    بات وسطِ کار ری‌استارت شد: ردیف روی `sending` مانده و کسی سراغش نمی‌آید.
    بدون این، کاربر اسپینری می‌بیند که هیچ‌وقت تمام نمی‌شود.
    """
    _link()
    asyncio.run(main.telegram_send(_send(track), request=None))
    asyncio.run(main.telegram_next_job(wait=0))

    assert tg.requeue_telegram() == 1
    assert asyncio.run(main.telegram_next_job(wait=0)) is not None


def test_finished_sends_are_pruned(tg, track, monkeypatch):
    _link()
    sent = asyncio.run(main.telegram_send(_send(track), request=None))
    asyncio.run(main.telegram_next_job(wait=0))
    asyncio.run(main.telegram_job_done(sent.id, TelegramJobResult()))

    # ردیفِ کهنه با تمام‌شدنِ ارسالِ بعدی جارو می‌شود
    tg.finish_telegram(sent.id, None, time.time() - main.TELEGRAM_SEND_TTL - 1)
    second = asyncio.run(main.telegram_send(_send(track), request=None))
    asyncio.run(main.telegram_next_job(wait=0))
    asyncio.run(main.telegram_job_done(second.id, TelegramJobResult()))

    assert tg.telegram_send(sent.id) is None
    assert tg.telegram_send(second.id) is not None


def test_polling_reports_the_bot_as_alive(tg):
    telegram.reset()
    asyncio.run(main.telegram_next_job(username="musicbazi_bot", wait=0))

    assert telegram.connected() is True
    assert telegram.bot_username() == "musicbazi_bot"


def test_heartbeat_goes_stale(tg):
    telegram.reset()
    telegram.heartbeat("musicbazi_bot", now=time.time() - telegram.PRESENCE_TTL - 1)

    assert telegram.connected() is False
    assert telegram.bot_username() is None


def test_bot_registration_returns_current_status(tg, track):
    telegram.reset()
    status = asyncio.run(main.telegram_bot_heartbeat(TelegramHeartbeat(username="musicbazi_bot")))

    assert (status.connected, status.botUsername) == (True, "musicbazi_bot")


def test_unknown_send_is_not_found(tg):
    with pytest.raises(HTTPException) as err:
        asyncio.run(main.telegram_send_status("نبود"))
    assert err.value.status_code == 404
