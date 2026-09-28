"""
نقطه‌ی ورود بات تلگرام — یک کلاینت تازه برای همون API، نه یک مسیر دانلود جدا.

اجرا: `python -m app.bot.run` (کنار سرور اصلی که باید بالا باشد).
بدون UNSTREAM_TELEGRAM_BOT_TOKEN بی‌صدا خارج می‌شود — قابلیتِ اختیاری است.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import httpx
from telegram import (
    BotCommand,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    InputMediaAudio,
    InlineQueryResultArticle,
    InputTextMessageContent,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from ..artwork import EMBED as ARTWORK_EMBED
from ..artwork import at_most as artwork_at_most
from ..artwork import resized as resized_artwork
from ..config import (
    BOT_DB_PATH,
    FOLLOW_POLL_INTERVAL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CACHE_CHAT_ID,
    TELEGRAM_PROXY,
    TELEGRAM_WEBAPP_URL,
)
from ..models import (
    Album,
    AlbumDetail,
    Artist,
    ArtistDetail,
    ChaptersInfo,
    DownloadProgress,
    Follow,
    FollowRequest,
    LibraryItem,
    Playlist,
    SongInfo,
    SplitStatus,
    TelegramJob,
    Track,
)
from . import store
from .client import ApiClient, Unavailable
from .logic import (
    AUTO_QUALITY,
    DEFAULT_QUALITY,
    MAX_BATCH_DOWNLOAD,
    MAX_CAPTION_LEN,
    QUALITY_ROWS,
    SOURCE_NAME,
    THUMB_MAX_BYTES,
    THUMB_SIZE,
    audio_filename,
    clean_filename_part,
    clean_lrc_lyrics,
    extract_album_features,
    format_album_button,
    format_album_caption,
    format_album_duration,
    format_artist_button,
    format_artist_search_button,
    format_playlist_button,
    format_track_button,
    looks_like_profile_url,
    looks_like_social_media_video,
    looks_like_url,
    looks_like_youtube_video,
    new_releases,
    paginate_slice,
    progress_bar,
    quality_label,
    source_badge,
    too_large_for_telegram,
    track_lyrics_hash,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

# لاگِ ماندگار کنارِ دیتابیسِ بات.
#
# بات معمولاً از یک ترمینال بالا می‌آید و خروجی‌اش با بسته‌شدنِ آن پنجره می‌رود.
# نتیجه‌اش این بود که وقتی چیزی سرِ ارسال اشتباه می‌رفت — thumbnailی که نیامد،
# کاوری که گرفته نشد — هیچ ردی نمی‌ماند و تنها راهِ فهمیدنش نگاه کردن به خودِ
# پیامِ تلگرام بود. حالا همان WARNINGها روی دیسک هم می‌نشینند.
try:
    BOT_LOG_PATH = Path(BOT_DB_PATH).with_name("bot.log")
    _file_log = RotatingFileHandler(
        BOT_LOG_PATH, maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    _file_log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(_file_log)
except OSError:
    # دیسکِ پر یا مسیرِ فقط-خواندنی نباید جلوی بالا آمدنِ بات را بگیرد
    BOT_LOG_PATH = None

# httpx در INFO آدرسِ کاملِ هر درخواست را می‌نویسد و توکنِ بات داخلِ خودِ
# URL است (`api.telegram.org/bot<TOKEN>/getUpdates`) — یعنی هر جا خروجیِ بات
# به فایل برود، توکن هم با آن می‌رود. خطاهای واقعیِ شبکه در WARNING به بالا
# همچنان دیده می‌شوند، پس چیزی برای عیب‌یابی از دست نمی‌رود.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = logging.getLogger("unstream.bot")

# حداکثر طول کپشن برای ارسال عکس در تلگرام (۱۰۲۴ کاراکتر استاندارد)
MAX_CAPTION_LEN = 1024


async def _telegram_retry(coro_fn, *args, attempts: int = 3, delay: float = 1.5, **kwargs):
    """
    فراخوانیِ متدهای تلگرام با تلاشِ دوباره روی خطاهای گذرای شبکه.
    BadRequest و Forbidden فوراً بالا می‌روند و تکرار نمی‌شوند.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except (BadRequest, Forbidden):
            raise
        except (NetworkError, httpx.HTTPError) as exc:
            last_exc = exc
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)
    if last_exc:
        raise last_exc


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """رسیدگی به خطاهای برنامه — لاگ تمیز به‌جای tracebackهای طولانی هنگام قطعی شبکه."""
    err = context.error
    if err is None:
        return

    if isinstance(err, (TimedOut, NetworkError)) and not isinstance(err, BadRequest):
        log.warning("خطای شبکه در ارتباط با تلگرام: %s", err)
        return

    if isinstance(err, Forbidden):
        log.info("دسترسی تلگرام مسدود شده یا وجود ندارد: %s", err)
        return

    if isinstance(err, BadRequest):
        msg = str(err).lower()
        if "message is not modified" in msg or "query is too old" in msg:
            log.debug("درخواست نامعتبر ولی بی‌خطر تلگرام: %s", err)
            return
        log.warning("درخواست نامعتبر به تلگرام: %s", err)
        return

    log.error("خطای رسیدگی‌نشده در بات: %s", err, exc_info=err)

    if cb := getattr(update, "callback_query", None):
        try:
            await cb.answer("خطایی رخ داد — دوباره امتحان کن.", show_alert=True)
        except Exception:
            pass
    elif msg := getattr(update, "effective_message", None):
        try:
            await msg.reply_text("متأسفانه خطایی رخ داد — لطفاً دوباره امتحان کن.")
        except Exception:
            pass


async def _safe_edit_message_text(target, text: str, **kwargs) -> None:
    """ویرایش متن پیام با نادیده‌گرفتن خطای متن تکراری تلگرام."""
    try:
        await target.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise

# چند نتیجه‌ی اول جستجو/آلبوم/کتابخانه — بیشترش فقط اسکرول اضافه در تلگرام است
MAX_RESULTS = 8
# ادیتِ پیام روی هر تیکِ درصد، به rate limit تلگرام می‌خورد
EDIT_INTERVAL = 2.0

# سقفِ فایلی که برای شناسایی گرفته می‌شود — سقف متد getFile تلگرام ۲۰ مگابایت است
MAX_IDENTIFY_BYTES = 20 * 1024 * 1024

# ---------- آپلودِ فایل به تلگرام ----------
#
# تنها جای بات که چند مگابایت روی سیم می‌رود، و همان‌جا هم بود که ارسال از وب
# با «Timed out» می‌مرد. دو دلیل داشت و هر دو اینجا جواب می‌گیرند:
#
#   ۱. تلگرام بعد از تمام‌شدنِ آپلود تازه فایل را پردازش می‌کند و بعد جواب
#      می‌دهد؛ read_timeoutِ عمومی (۶۰ ثانیه) برای همین *انتظارِ بعد از
#      آپلود* کوتاه بود، نه برای خودِ فرستادن. پس مخصوصِ این فراخوانی بالا
#      برده می‌شود، نه روی کلِ کلاینت — وگرنه یک send_messageِ گیرکرده هم
#      پنج دقیقه معطل می‌ماند.
#   ۲. روی لینکِ ناپایدار، اولین تلاش گاهی وسطِ راه قطع می‌شود. یک بار دیگر
#      امتحان‌کردن تفاوتِ «نرسید» و «کند بود» را عملاً از بین می‌برد.
UPLOAD_ATTEMPTS = 3
UPLOAD_RETRY = 3.0
UPLOAD_TIMEOUT = 300.0

# پسوندی که سرور از روی آن تصمیم می‌گیرد فایل را چطور دیکد کند
_MIME_EXT = {
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/flac": ".flac",
    "audio/wav": ".wav",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}

STATUS_LABEL = {
    "queued": "در صف…",
    "searching": "در حال جستجو…",
    "tagging": "در حال تگ‌گذاری…",
}

# منوی اصلی و دائم پایین صفحه چت برای دسترسی سریع و راحت
MAIN_REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🔍 جستجوی موزیک"), KeyboardButton("🎧 تشخیص صدا (شازم)")],
        [KeyboardButton("✨ حال‌وهوا (وایب)"), KeyboardButton("🎲 میکس روزانه")],
        [KeyboardButton("❤️ علاقه‌مندی‌ها"), KeyboardButton("📁 کتابخانه من")],
        [KeyboardButton("⚙️ کیفیت دانلود"), KeyboardButton("❓ راهنما")],
    ],
    resize_keyboard=True,
)

# دکمه‌های /start — هرکدوم یک «مُد» را در chat_data می‌گذارد و یک ForceReply
# می‌فرستد؛ پیامِ بعدیِ کاربر (در on_text) طبق همین مُد مسیرش فرق می‌کند.
MODE_PROMPT = {
    "artist": "اسم هنرمند رو بفرست:",
    "album": "اسم آلبوم رو بفرست:",
    "playlist": "اسم پلی‌لیست رو بفرست:",
    "track": "اسم آهنگ یا لینک رو بفرست:",
    "vibe": "✨ حال‌وهوات چطوره یا چه سبکی موزیک می‌خوای؟ برام بنویس:",
}
MODE_PLACEHOLDER = {
    "artist": "اسم هنرمند…",
    "album": "اسم آلبوم…",
    "playlist": "اسم پلی‌لیست…",
    "track": "اسم آهنگ یا لینک…",
    "vibe": "مثلاً: آهنگ پرانرژی برای تمرین ورزش…",
}

SECTION_TITLE = {
    "att": "⭐ آهنگ‌های محبوب",
    "aal": "💿 آلبوم‌ها",
    "apl": "📃 پلی‌لیست‌ها",
    "ard": "📻 رادیو",
    "are": "🔗 هنرمندهای مرتبط",
}


def _api(context: ContextTypes.DEFAULT_TYPE) -> ApiClient:
    return context.bot_data["api"]


class _StatusSink:
    """
    پیامِ وضعیتِ یک دانلود — چه پیامِ معمولیِ یک چت، چه پیامِ inline.

    مسیرِ inline پیامِ ما نیست (تلگرام خودش نتیجه‌ی inline را فرستاده)، پس فقط
    `inline_message_id` داریم و باید با `bot.edit_message_text` ادیتش کنیم؛
    آن هم قابلِ حذف نیست. رابطِ یکسان یعنی `_run_download` نباید بداند کدام
    مسیر است.
    در ارسال گروهی که message اولیه ساخته نمی‌شود، با chat_id پیام جدید ارسال می‌شود.
    """

    def __init__(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        message: Message | None = None,
        inline_message_id: str | None = None,
        chat_id: int | None = None,
    ) -> None:
        self._bot = context.bot
        self._message = message
        self._inline_id = inline_message_id
        self._chat_id = chat_id or (message.chat_id if message is not None else None)

    async def edit(self, text: str, **kwargs) -> None:
        try:
            if self._message is not None:
                await self._message.edit_text(text, **kwargs)
            elif self._inline_id is not None:
                await self._bot.edit_message_text(
                    text, inline_message_id=self._inline_id, **kwargs
                )
            elif self._chat_id is not None:
                self._message = await self._bot.send_message(
                    self._chat_id, text, **kwargs
                )
        except Exception:
            pass  # ادیتِ ناموفق (rate limit یا متنِ تکراری) نباید دانلود را متوقف کند

    async def delete(self) -> None:
        if self._message is not None:
            try:
                await self._message.delete()
            except Exception:
                pass


def _get_chat_quality(context: ContextTypes.DEFAULT_TYPE, chat_id: Any = None) -> str:
    """دریافت کیفیت دانلود چت با اولویت حافظه، سپس دیتابیس ماندگار، و در نهایت پیش‌فرض."""
    q = context.chat_data.get("quality") if hasattr(context, "chat_data") and context.chat_data else None
    if not q and chat_id is not None:
        try:
            cid = int(chat_id)
            q = store.get_chat_quality(cid)
        except (ValueError, TypeError):
            q = None
        if q and hasattr(context, "chat_data") and context.chat_data is not None:
            context.chat_data["quality"] = q
    return q or DEFAULT_QUALITY


def _track_line(track: Track) -> str:
    """سرتیترِ پیامِ وضعیت — بج منبع + عنوانِ پررنگ + هنرمند. HTML‌ایمن."""
    return f"{source_badge(track.source)} <b>{html.escape(track.title)}</b> — {html.escape(track.artist)}"


async def _fetch_thumbnail(
    api: ApiClient, artwork_url: str | None, job_id: str | None = None
) -> InputFile | None:
    """
    کاورِ کوچکِ روی فایل صوتی — همان چیزی که تلگرام در *لیستِ* آهنگ‌ها نشان
    می‌دهد. با پلیرِ پایینِ صفحه فرق دارد: آن کاور را از تگِ داخلِ فایل می‌خواند
    و همیشه دارد، ولی ردیفِ لیست فقط همین thumbnail را می‌بیند. نبودنش یعنی
    آهنگی که کاور دارد، در لیست بی‌تصویر بنشیند.

    اول از خودِ سرور، که آن را از داخلِ فایلِ دانلودشده درمی‌آورد — بدونِ هیچ
    درخواستی به بیرون. گرفتنِ کاور از CDN فقط پشتیبان است: همان بود که گاهی
    تایم‌اوت می‌داد یا به پروکسی نمی‌رسید و ردیف بی‌تصویر می‌ماند.

    شکست در هر مرحله فقط یعنی بدون کاور بفرست، نه خطا.
    """
    if job_id and (data := await api.thumb_bytes(job_id)):
        if len(data) <= THUMB_MAX_BYTES:
            return InputFile(data, filename="cover.jpg")
        log.warning("thumbnail سرور برای %s بزرگ‌تر از حد مجاز است (%d بایت)", job_id, len(data))

    for url in artwork_at_most(artwork_url, THUMB_SIZE):
        data = await api.raw_bytes(url)
        if not data:
            continue
        if len(data) > THUMB_MAX_BYTES:
            # پله‌ای بزرگ‌تر از سقفِ تلگرام — گزینه‌ی بعدی شاید کوچک‌تر باشد
            log.warning("کاورِ %s برای thumbnail بزرگ است (%d بایت)", url, len(data))
            continue
        return InputFile(data, filename="cover.jpg")
    if artwork_url:
        log.warning("هیچ نسخه‌ای از کاورِ %s برای thumbnail نشد", artwork_url)
    return None


async def _fetch_full_cover(api: ApiClient, track: Track, info: SongInfo | None) -> bytes | None:
    """
    کاورِ کاملِ کارتِ اطلاعات — نه thumbnailِ کوچکِ روی فایل صوتی، همان محدودیتِ
    ۲۰۰ کیلوبایتی اینجا در کار نیست چون send_photo نه thumbnail.

    اولویت با کاورِ خودِ کاتالوگ است (در بزرگ‌ترین پله‌ی ممکن، `artwork.EMBED`) و
    Genius فقط وقتی می‌آید که کاتالوگ کاوری نداشته باشد. برعکسش — که قبلاً بود —
    یعنی کارتِ اطلاعات کاوری نشان بدهد که با thumbnailِ فایل، با کاورِ امبدشده
    داخلش و با آنچه کاربر در اسپاتیفای/ساندکلاد دیده یکی نیست؛ حتی وقتی Genius
    درست هم تطبیق داده باشد، تصویرش لزوماً همان کاورِ آن انتشار نیست.
    """
    # مثل thumbnail، بیش از یک آدرس: پله‌ی حساب‌شده ممکن است روی آن CDN نباشد و
    # آن‌وقت کارتِ اطلاعات بی‌تصویر می‌ماند در حالی که کاور موجود است
    for url in artwork_at_most(track.artworkUrl, ARTWORK_EMBED):
        if data := await api.raw_bytes(url):
            return data
    if info and info.artworkUrl:
        return await api.raw_bytes(info.artworkUrl)
    return None


async def _fetch_album_cover(api: ApiClient, album: AlbumDetail) -> bytes | None:
    """
    کاورِ باکیفیتِ آلبوم برای کارتِ معرفیِ آلبوم (`artwork.EMBED`). اگر آدرسِ کاورِ
    آلبوم در دسترس نبود، کاورِ اولین ترک‌های آلبوم امتحان می‌شود.
    """
    if album.artworkUrl:
        for url in artwork_at_most(album.artworkUrl, ARTWORK_EMBED):
            if data := await api.raw_bytes(url):
                return data
    for t in album.tracks[:3]:
        if t.artworkUrl and t.artworkUrl != album.artworkUrl:
            for url in artwork_at_most(t.artworkUrl, ARTWORK_EMBED):
                if data := await api.raw_bytes(url):
                    return data
    return None


def _fmt_duration(duration_ms: int) -> str:
    total = duration_ms // 1000
    return f"{total // 60}:{total % 60:02d}"


def _info_caption(track: Track, info: SongInfo | None) -> str:
    """کپشنِ کارتِ اطلاعات — حداکثر ۱۰۲۴ نویسه (سقفِ تلگرام)."""
    lines = [_track_line(track), f"⏱ {_fmt_duration(track.durationMs)}"]
    if track.album:
        lines.append(f"💿 آلبوم: {html.escape(track.album)}")
    if track.year:
        lines.append(f"📅 سال: {track.year}")
    if track.genre:
        lines.append(f"🎼 ژانر: {html.escape(track.genre)}")
    if info and info.writers:
        writers = "، ".join(info.writers)
        if len(writers) > 150:
            writers = writers[:147] + "…"
        lines.append(f"✍️ آهنگساز: {html.escape(writers)}")
    if info and info.producers:
        producers = "، ".join(info.producers)
        if len(producers) > 150:
            producers = producers[:147] + "…"
        lines.append(f"🎚 تهیه‌کننده: {html.escape(producers)}")
    if info and info.releaseDate and not track.year:
        lines.append(f"📅 تاریخ انتشار: {html.escape(info.releaseDate)}")

    caption = "\n".join(lines)
    if len(caption) > MAX_CAPTION_LEN:
        while lines and len("\n".join(lines)) > MAX_CAPTION_LEN:
            lines.pop()
        caption = "\n".join(lines)
    return caption


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    # لینکِ عمیقِ دکمه‌ی «فرستادن به تلگرام» در وب: t.me/<bot>?start=link_<code>
    # تلگرام payload را به‌عنوان اولین آرگومانِ /start می‌دهد، پس کاربر فقط
    # «Start» را می‌زند و کدی تایپ نمی‌کند.
    if context.args and context.args[0].startswith(LINK_PAYLOAD_PREFIX):
        await _claim_link(update.message, context, context.args[0][len(LINK_PAYLOAD_PREFIX) :])
        return

    keyboard = []
    if TELEGRAM_WEBAPP_URL and TELEGRAM_WEBAPP_URL.startswith("https://"):
        keyboard.append(
            [InlineKeyboardButton("🌐 ورود به موزیک‌بازی (Mini App)", web_app=WebAppInfo(url=TELEGRAM_WEBAPP_URL))]
        )
    keyboard.extend([
        [
            InlineKeyboardButton("✨ حال‌وهوا (وایب هوشمند)", callback_data="mode:vibe"),
        ],
        [
            InlineKeyboardButton("🧑‍🎤 هنرمند", callback_data="mode:artist"),
            InlineKeyboardButton("💿 آلبوم", callback_data="mode:album"),
        ],
        [
            InlineKeyboardButton("📃 پلی‌لیست", callback_data="mode:playlist"),
            InlineKeyboardButton("🎧 آهنگ", callback_data="mode:track"),
        ],
    ])
    await update.message.reply_text(
        "سلام! به موزیک‌بازی خوش اومدی 🎶\n\n"
        "یکی از دکمه‌ها رو بزن، یا مستقیم اسم آهنگ/هنرمند/لینک رو بفرست.\n"
        "لینک اسپاتیفای/دیزر/اپل‌موزیک/یوتیوب/ساندکلاد قبول است "
        "(لینکِ آلبوم/پلی‌لیست دکمه‌ی «دانلود همه» هم می‌ده).\n\n"
        "✨ با دکمه «حال‌وهوا» یا دستور /vibe می‌تونی با هوش مصنوعی بر اساس حس‌وحالت آهنگ پیدا کنی!\n"
        "با @نام‌بات آهنگ هم می‌تونی از هر چتی جستجو کنی، بدون اومدن اینجا.\n"
        "با /help بقیه‌ی دستورها رو ببین.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    try:
        await update.message.reply_text(
            "منوی دسترسی سریع آماده است 👇",
            reply_markup=MAIN_REPLY_KEYBOARD,
        )
    except Exception:
        pass


async def on_mode_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های هنرمند/آلبوم/پلی‌لیست/آهنگ/وایبِ /start — مُد را ست می‌کند و منتظرِ پیامِ بعدی می‌ماند."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    mode = query.data.split(":", 1)[1]
    if mode == "track":
        context.chat_data.pop("search_mode", None)
    else:
        context.chat_data["search_mode"] = mode

    if query.message is not None:
        await query.message.reply_text(
            MODE_PROMPT[mode],
            reply_markup=ForceReply(input_field_placeholder=MODE_PLACEHOLDER[mode]),
        )


async def vibe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /vibe — پیشنهاد موزیک بر اساس حال‌وهوا و سلیقه با هوش مصنوعی."""
    if update.message is None:
        return
    text = " ".join(context.args) if context.args else ""
    if not text.strip():
        context.chat_data["search_mode"] = "vibe"
        await update.message.reply_text(
            "✨ حال‌وهوات چطوره یا برای چه کاری موزیک می‌خوای؟\n"
            "برام بنویس تا با هوش مصنوعی برات پلی‌لیست اختصاصی بسازم:\n\n"
            "مثلاً:\n"
            "• یه پلی‌لیست شاد و پرانرژی برای تمرین تو باشگاه\n"
            "• آهنگ‌های آرامش‌بخش و بی‌کلام برای تمرکز و کار\n"
            "• موزیک‌های خاطره‌انگیز و نوستالژی برای جاده",
            reply_markup=ForceReply(input_field_placeholder="حال‌وهوات رو بنویس…"),
        )
        return
    await _run_vibe(update.message, context, text.strip())


async def _run_vibe(message: Message, context: ContextTypes.DEFAULT_TYPE, prompt: str) -> None:
    """اجرای وایب، نمایش پاسخ همدلانه و نمایش دکمه‌های آهنگ‌ها با امکان دانلود همه."""
    api = _api(context)
    status = await message.reply_text("✨ دارم بهترین آهنگ‌ها رو بر اساس حال‌وهوات پیدا می‌کنم…")
    try:
        suggestion = await api.vibe(prompt)
    except Exception as exc:
        log.warning("خطا در گرفتن وایب: %s", exc)
        await status.edit_text("متأسفانه دریافت پیشنهادها با خطا مواجه شد — سرور در دسترس نیست؟")
        return

    if not suggestion.tracks:
        await status.edit_text(f"✨ {suggestion.reply}\n\nمتأسفانه آهنگی برای این حال‌وهوا پیدا نشد.")
        return

    try:
        await status.delete()
    except Exception:
        pass

    text = f"✨ <b>{html.escape(suggestion.label)}</b>\n\n{html.escape(suggestion.reply)}"
    if suggestion.reason:
        text += f"\n\n💡 <i>{html.escape(suggestion.reason)}</i>"

    await _send_track_picker(
        context, message, suggestion.tracks, batchable=True, prompt_text=text
    )


async def app_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /app — باز کردن مینی‌اپ و پلیر آنلاین درون تلگرام."""
    if update.message is None:
        return
    if TELEGRAM_WEBAPP_URL and TELEGRAM_WEBAPP_URL.startswith("https://"):
        await update.message.reply_text(
            "🎵 <b>وب‌اپلیکیشن و پلیر آنلاین موزیک‌بازی</b>\n\n"
            "کیفیت اصلی، کاورهای بلور، صف پخش روان، لیریکس همگام و کتابخانه شخصی شما مستقیماً درون تلگرام!\n"
            "برای باز شدن روی دکمه زیر بزن:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🌐 ورود به موزیک‌بازی", web_app=WebAppInfo(url=TELEGRAM_WEBAPP_URL))]]
            ),
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            "مینی‌اپ تلگرام با دامنه HTTPS تنظیم نشده است.\n"
            "می‌تونی از دستور /link برای اتصال این چت به نسخه وب استفاده کنی."
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if message is None:
        return
    eff_chat = getattr(update, "effective_chat", None)
    chat_id = getattr(eff_chat, "id", None) or getattr(message, "chat_id", None)
    current = _get_chat_quality(context, chat_id)
    await message.reply_text(
        "اسم آهنگ رو بفرست یا لینک اسپاتیفای/دیزر/اپل‌موزیک/یوتیوب/ساندکلاد.\n"
        "لینکِ آلبوم/پلی‌لیست دکمه‌ی «دانلود همه» هم می‌ده.\n"
        "با @نام‌بات آهنگ از هر چتی می‌تونی جستجو و ارسال کنی.\n"
        "با منوی پایین یا دکمه‌های /start مستقیم می‌تونی نوع جستجو رو انتخاب کنی.\n\n"
        "/search <عبارت> — جستجوی آهنگ، آلبوم یا هنرمند\n"
        "/settings — تنظیمات و کیفیت دانلود\n"
        "/app — ورود به مینی‌اپ و پلیر آنلاین موزیک‌بازی درون تلگرام\n"
        "/vibe — پیشنهاد آهنگ بر اساس حال‌وهوا و سلیقه با هوش مصنوعی\n"
        "/mix — میکس روزانه اختصاصی بر اساس هوش موسیقی و سلیقه\n"
        "/favorites — آهنگ‌های محبوب و لایک‌شده\n"
        "/quality — کیفیت پیش‌فرض دانلود رو عوض کن\n"
        "/library — دانلودهای قبلی رو بدون صبر دوباره بگیر\n"
        "/follow — دنبال‌کردنِ یک هنرمند؛ انتشارِ تازه‌اش خودکار با فایل و کاور می‌آید\n"
        "/unfollow — دیگه دنبال نکردنِ یک هنرمند\n"
        "/following — لیستِ هنرمندهای دنبال‌شده\n"
        "/link — وصل‌کردنِ این چت به وب، تا دکمه‌ی تلگرامِ هر آهنگ/آلبوم اینجا بفرستد\n\n"
        f"کیفیت فعلی: {quality_label(current)}",
        reply_markup=MAIN_REPLY_KEYBOARD,
    )


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /search — جستجوی آهنگ با آرگومان یا درخواست نام آهنگ."""
    if update.message is None:
        return
    query = " ".join(context.args) if context.args else ""
    if query:
        api = _api(context)
        try:
            results = await api.search(query)
            tracks = results.tracks
        except Exception:
            await update.message.reply_text("جستجو ناموفق بود — دوباره امتحان کن.")
            return
        await _send_track_picker(context, update.message, tracks, batchable=False)
    else:
        context.chat_data["search_mode"] = "track"
        await update.message.reply_text(
            "🔍 اسم آهنگ، هنرمند یا آلبوم رو بفرست:",
            reply_markup=ForceReply(selective=True),
        )


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /settings — تنظیمات و کیفیت دانلود."""
    await quality_cmd(update, context)


async def quality_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if message is None:
        return
    eff_chat = getattr(update, "effective_chat", None)
    chat_id = getattr(eff_chat, "id", None) or getattr(message, "chat_id", None)
    current = _get_chat_quality(context, chat_id)
    keyboard = [
        [
            InlineKeyboardButton(
                f"✓ {quality_label(q)}" if q == current else quality_label(q),
                callback_data=f"q:{q}",
            )
            for q in row
        ]
        for row in QUALITY_ROWS
    ]
    await message.reply_text(
        f"کیفیت فعلی: {quality_label(current)}\nیکی رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def on_quality_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    quality = query.data.split(":", 1)[1]
    context.chat_data["quality"] = quality
    eff_chat = getattr(update, "effective_chat", None)
    chat_id = getattr(eff_chat, "id", None) or (query.message.chat_id if query.message else None)
    if chat_id is not None:
        store.save_chat_quality(chat_id, quality)
    await _safe_edit_message_text(query, f"کیفیت روی «{quality_label(quality)}» ست شد.")


async def library_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    query = " ".join(context.args) if context.args else ""
    api = _api(context)
    try:
        page = await api.library(query)
    except Exception:
        await update.message.reply_text("گرفتن کتابخانه ناموفق بود.")
        return

    if not page.items:
        await update.message.reply_text("چیزی تو کتابخانه نیست.")
        return

    items = page.items[:MAX_RESULTS]
    context.chat_data["library"] = {item.jobId: item for item in items}
    keyboard = [
        [
            InlineKeyboardButton(
                f"{source_badge(item.track.source)} {format_track_button(item.track)}",
                callback_data=f"lib:{item.jobId}",
            )
        ]
        for item in items
    ]
    await update.message.reply_text(
        "بزن تا دوباره برات بفرستم:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def on_library_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    await query.answer()

    job_id = query.data.split(":", 1)[1]
    items: dict[str, LibraryItem] = context.chat_data.get("library", {})
    item = items.get(job_id)
    if item is None:
        await query.edit_message_text("این مورد دیگر در دسترس نیست — دوباره /library بزن.")
        return

    await query.edit_message_text(
        f"{_track_line(item.track)}\nدر حال آماده‌سازی…", parse_mode=ParseMode.HTML
    )
    # فایل از قبل روی دیسک آماده است — نه دانلود دوباره، نه انتظار SSE
    sink = _StatusSink(context, message=query.message)
    try:
        await _deliver(context, query.message.chat_id, item.track, item.jobId, sink, item.format)
    except Exception as exc:
        log.warning("تحویلِ مجددِ %s ناموفق بود: %s", item.track.title, exc)


async def favorites_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دیدن و مدیریت آهنگ‌های مورد علاقه (لایک‌شده)."""
    if update.message is None:
        return
    api = _api(context)
    try:
        favs = await api.favorites()
    except Exception:
        await update.message.reply_text("دریافت لیست علاقه‌مندی‌ها ناموفق بود — سرور در دسترس نیست؟")
        return

    if not favs:
        await update.message.reply_text(
            "هنوز هیچ آهنگی رو به علاقه‌مندی‌ها اضافه نکردی ❤️\n\n"
            "با دکمه ❤️ زیر هر فایل صوتی می‌تونی آهنگ‌های دلخواهت رو ذخیره کنی تا همیشه سریع بهشون دسترسی داشته باشی."
        )
        return

    items = favs[:MAX_RESULTS]
    context.chat_data["library"] = {item.jobId: item for item in favs}
    context.chat_data["favorites_list"] = favs

    lines = [f"❤️ <b>آهنگ‌های محبوب شما ({len(favs)} قطعه):</b>\n"]
    keyboard = [
        [
            InlineKeyboardButton(
                f"❤️ {format_track_button(item.track)}",
                callback_data=f"lib:{item.jobId}",
            )
        ]
        for item in items
    ]
    action_row = []
    if len(favs) > 1:
        action_row.append(InlineKeyboardButton("⬇️ دانلود همه", callback_data="fav:all"))
        action_row.append(InlineKeyboardButton("📦 دانلود ZIP", callback_data="zip:fav"))
    if action_row:
        keyboard.append(action_row)

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def on_favorite_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لایک و آن‌لایک کردن ترک در کتابخانه از طریق دکمه شیشه‌ای زیر آهنگ."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    parts = query.data.split(":")
    if len(parts) < 3:
        return
    action, job_id = parts[1], parts[2]
    api = _api(context)

    is_add = action == "add"
    try:
        await api.set_favorite(job_id, is_add)
    except Exception as exc:
        log.warning("تغییر وضعیت علاقه‌مندی برای %s ناموفق بود: %s", job_id, exc)
        await query.answer("خطا در تغییر وضعیت — سرور در دسترس نیست؟", show_alert=True)
        return

    alert_msg = "❤️ به لیست علاقه‌مندی‌ها اضافه شد!" if is_add else "💔 از علاقه‌مندی‌ها حذف شد."
    await query.answer(alert_msg)

    if query.message and query.message.reply_markup:
        new_keyboard = []
        for row in query.message.reply_markup.inline_keyboard:
            new_row = []
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("fav:"):
                    new_action = "del" if is_add else "add"
                    new_label = "💔 حذف" if is_add else "❤️ پسندیدم"
                    new_row.append(
                        InlineKeyboardButton(
                            new_label, callback_data=f"fav:{new_action}:{job_id}"
                        )
                    )
                else:
                    new_row.append(btn)
            new_keyboard.append(new_row)
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_keyboard))
        except Exception:
            pass


async def on_fav_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return
    await query.answer()

    favs: list[LibraryItem] = context.chat_data.get("favorites_list", [])
    if not favs:
        await query.edit_message_text("لیست علاقه‌مندی‌ها خالی است یا منقضی شده — دوباره /favorites بزنید.")
        return

    batch = favs[:MAX_BATCH_DOWNLOAD]
    await query.edit_message_text(f"در حال آماده‌سازی و ارسال {len(batch)} آهنگ محبوب…")
    for item in batch:
        sink = _StatusSink(context, message=None, chat_id=query.message.chat_id)
        try:
            await _deliver(context, query.message.chat_id, item.track, item.jobId, sink, item.format)
        except Exception as exc:
            log.warning("ارسال %s از علاقه‌مندی‌ها ناموفق بود: %s", item.track.title, exc)


async def mix_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /mix — میکس روزانه اختصاصی بر اساس هوش موسیقی و تاریخچه شنیداری."""
    if update.message is None:
        return
    api = _api(context)
    try:
        dm = await api.daily_mix(limit=10)
    except Exception:
        await update.message.reply_text("دریافت میکس روزانه ناموفق بود — سرور در دسترس نیست؟")
        return

    if not dm.items or dm.source == "none":
        await update.message.reply_text(
            "🎲 <b>میکس روزانه هنوز آماده نیست!</b>\n\n"
            "میکس روزانه هوشمندانه بر اساس علاقه‌مندی‌ها و سلیقه شنیداری شما چیده می‌شود.\n"
            "چند آهنگ دانلود، گوش یا لایک کن (❤️) تا سلیقه‌ات تحلیل بشه و میکس روزانه‌ت هر روز به‌روز بشه!",
            parse_mode=ParseMode.HTML,
        )
        return

    context.chat_data["library"] = {item.jobId: item for item in dm.items}
    context.chat_data["daily_mix_items"] = dm.items

    reason_text = "آهنگ‌های محبوبت" if dm.source == "favorites" else "تاریخچه شنیداری اخیرت"
    lines = [
        "🎲 <b>میکس روزانه اختصاصی شما</b>",
        f"انتخاب‌شده بر اساس {reason_text}:\n",
    ]
    keyboard = [
        [
            InlineKeyboardButton(
                f"🎵 {format_track_button(item.track)}",
                callback_data=f"lib:{item.jobId}",
            )
        ]
        for item in dm.items[:MAX_RESULTS]
    ]

    action_row = []
    if len(dm.items) > 1:
        action_row.append(InlineKeyboardButton(f"⬇️ دریافت همه ({len(dm.items)})", callback_data="mix:all"))
        action_row.append(InlineKeyboardButton("📦 دانلود ZIP", callback_data="zip:mix"))
    if action_row:
        keyboard.append(action_row)

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def on_mix_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return
    await query.answer()

    items: list[LibraryItem] = context.chat_data.get("daily_mix_items", [])
    if not items:
        await query.edit_message_text("لیست میکس روزانه منقضی شده — دوباره /mix بزنید.")
        return

    batch = items[:MAX_BATCH_DOWNLOAD]
    await query.edit_message_text(f"در حال آماده‌سازی و ارسال {len(batch)} قطعه از میکس روزانه…")
    for item in batch:
        sink = _StatusSink(context, message=None, chat_id=query.message.chat_id)
        try:
            await _deliver(context, query.message.chat_id, item.track, item.jobId, sink, item.format)
        except Exception as exc:
            log.warning("ارسال قطعه %s از میکس روزانه ناموفق بود: %s", item.track.title, exc)


async def on_zip_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ساخت و تحویل فایل فشرده ZIP از قطعات انتخابی."""
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    await query.answer()

    target = query.data.split(":", 1)[1]
    api = _api(context)

    job_ids: list[str] = []
    zip_name = "musicbazi"

    if target == "fav":
        items = context.chat_data.get("favorites_list", [])
        if not items:
            try:
                items = await api.favorites()
            except Exception:
                items = []
        job_ids = [it.jobId for it in items]
        zip_name = "favorites"
    elif target == "mix":
        items = context.chat_data.get("daily_mix_items", [])
        job_ids = [it.jobId for it in items]
        zip_name = "daily_mix"
    elif target.startswith("album:"):
        album_id = target.split(":", 1)[1]
        job_ids = context.chat_data.get(f"album_jobs_{album_id}", [])
        zip_name = clean_filename_part(album_id) or "album"
    elif target.startswith("alb:"):
        alb_key = target.split(":", 1)[1]
        album_id = store.resolve_callback_ref(alb_key)
        job_ids = context.chat_data.get(f"album_jobs_{alb_key}") or context.chat_data.get(f"album_jobs_{album_id}", [])
        zip_name = clean_filename_part(album_id) or "album"

    if not job_ids:
        await query.edit_message_text("قطعه‌ای برای ساخت فایل ZIP پیدا نشد.")
        return

    await query.edit_message_text("📦 در حال فشرده‌سازی و ساخت فایل ZIP…")
    sink = _StatusSink(context, message=query.message)

    try:
        ready = await api.create_zip(job_ids, name=zip_name)
    except Exception as exc:
        log.warning("ساخت فایل ZIP ناموفق بود: %s", exc)
        await sink.edit("ساخت فایل ZIP با خطا مواجه شد.")
        return

    if too_large_for_telegram(ready.bytes):
        direct_url = api.full_zip_url(ready.url)
        await sink.edit(
            f"📦 فایل ZIP آماده شد ({round(ready.bytes / (1024 * 1024), 1)} مگابایت).\n"
            f"به دلیل حجم بالای تلگرام، با لینک مستقیم زیر دانلودش کنید:\n{html.escape(direct_url)}",
            parse_mode=ParseMode.HTML,
        )
        return

    await sink.edit("📦 در حال آپلود فایل ZIP در تلگرام…")
    zip_bytes = await api.zip_bytes_by_url(ready.url)
    if not zip_bytes:
        direct_url = api.full_zip_url(ready.url)
        await sink.edit(
            f"دریافت بایت‌های فایل از سرور ناموفق بود — از لینک مستقیم بگیرید:\n{html.escape(direct_url)}",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        await _telegram_retry(
            context.bot.send_document,
            query.message.chat_id,
            document=zip_bytes,
            filename=f"{zip_name}.zip",
            caption=f"📦 آرشیو فشرده شامل {ready.files} فایل ({round(ready.bytes / (1024 * 1024), 1)} مگابایت)",
            read_timeout=UPLOAD_TIMEOUT,
            write_timeout=UPLOAD_TIMEOUT,
        )
        await sink.delete()
    except Exception as exc:
        log.warning("آپلود فایل ZIP در تلگرام نشد: %s", exc)
        direct_url = api.full_zip_url(ready.url)
        await sink.edit(
            f"آپلود فایل ZIP به تلگرام ناموفق بود — مستقیم دانلود کنید:\n{html.escape(direct_url)}",
            parse_mode=ParseMode.HTML,
        )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not update.message.text:
        return
    text = update.message.text.strip()
    api = _api(context)

    # مدیریت حالت گروه: در گروه‌ها فقط به منشن یا ریپلای پاسخ داده می‌شود تا اسپم نشود
    chat = getattr(update, "effective_chat", None) or (update.message.chat if update.message else None)
    if chat and getattr(chat, "type", "") in ("group", "supergroup"):
        bot_username = (context.bot_data.get("username") or "").lower()
        is_reply_to_bot = bool(
            update.message.reply_to_message
            and update.message.reply_to_message.from_user
            and context.bot
            and update.message.reply_to_message.from_user.id == context.bot.id
        )
        is_mentioned = bool(bot_username and f"@{bot_username}" in text.lower())
        if not (is_reply_to_bot or is_mentioned):
            return
        if is_mentioned and bot_username:
            text = re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.I).strip()
            if not text:
                await update.message.reply_text("برای جستجو، نام آهنگ یا هنرمند رو بعد از منشن بنویس.")
                return

    # پردازش دکمه‌های کیبورد ثابت پایین صفحه
    if text == "🔍 جستجوی موزیک":
        await update.message.reply_text(
            "🔍 اسم آهنگ، آلبوم، هنرمند یا لینک مورد نظرت رو بفرست:",
            reply_markup=ForceReply(input_field_placeholder="اسم آهنگ، هنرمند یا لینک…"),
        )
        return
    if text == "🎧 تشخیص صدا (شازم)":
        await update.message.reply_text(
            "🎧 یک ویس ضبط کن یا یک فایل صوتی/ویدیو بفرست (یا از چت‌های دیگه فوروارد کن) تا برات شناساییش کنم!"
        )
        return
    if text in ("✨ حال‌وهوا (وایب)", "✨ حال‌وهوا (وایب هوشمند)"):
        await vibe_cmd(update, context)
        return
    if text in ("🎲 میکس روزانه", "میکس روزانه"):
        await mix_cmd(update, context)
        return
    if text in ("❤️ علاقه‌مندی‌ها", "❤️ آهنگ‌های محبوب", "علاقه‌مندی‌ها"):
        await favorites_cmd(update, context)
        return
    if text == "📁 کتابخانه من":
        await library_cmd(update, context)
        return
    if text == "⚙️ کیفیت دانلود":
        await quality_cmd(update, context)
        return
    if text == "❓ راهنما":
        await help_cmd(update, context)
        return

    is_direct_url = (
        looks_like_url(text)
        or looks_like_profile_url(text)
        or looks_like_youtube_video(text)
        or looks_like_social_media_video(text)
    )

    if not is_direct_url:
        # دکمه‌ی هنرمند/آلبوم/پلی‌لیست/وایبِ /start مُد را روی این پیام گذاشته — فقط
        # همین یک پیام را تحت تاثیر قرار می‌دهد (pop، نه get)
        mode = context.chat_data.pop("search_mode", None)
        if mode == "vibe":
            await _run_vibe(update.message, context, text)
            return
        if mode == "artist":
            await _artist_search(update.message, context, text)
            return
        if mode in ("album", "playlist"):
            await _collection_search(update.message, context, text, kind=mode)
            return
    else:
        context.chat_data.pop("search_mode", None)

    # لینکِ پروفایل (هنرمند، یا کاربری که فقط پلی‌لیستِ عمومی دارد) ترک‌لیست
    # ندارد و از مسیرِ پایین فقط «این لینک شناخته نشد» می‌گرفت — مرورگرِ
    # پروفایل، که آلبوم‌ها و پلی‌لیست‌هایش را دکمه می‌کند، جای اوست
    if looks_like_profile_url(text):
        await _artist_search(update.message, context, text)
        return

    # بررسی ویدیوی یوتیوب دارای چپتر برای تفکیک به آهنگ‌های جداگانه
    if looks_like_youtube_video(text):
        try:
            chapters_info = await api.chapters(text)
        except Exception:
            chapters_info = None

        if chapters_info and len(chapters_info.chapters) > 1:
            context.chat_data["split_info"] = chapters_info
            context.chat_data["split_url"] = text
            preview_lines = []
            for c in chapters_info.chapters[:5]:
                artist_part = f"{c.artist} — " if c.artist else ""
                preview_lines.append(f"• {artist_part}{c.songTitle or c.title}")
            if len(chapters_info.chapters) > 5:
                preview_lines.append(f"• و {len(chapters_info.chapters) - 5} قطعه دیگر…")

            caption = (
                f"📻 <b>{html.escape(chapters_info.title)}</b>\n"
                f"👤 کانال: <b>{html.escape(chapters_info.uploader)}</b>\n"
                f"🔢 این میکس شامل <b>{len(chapters_info.chapters)} آهنگ/چپتر</b> است:\n\n"
                + "\n".join(preview_lines)
                + "\n\nچطور مایلید دریافتش کنید؟"
            )
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"✂️ تفکیک و دریافت تک‌تک آهنگ‌ها ({len(chapters_info.chapters)})",
                        callback_data="split:all",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📦 دانلود کل میکس یکپارچه",
                        callback_data="split:whole",
                    )
                ],
            ]
            await update.message.reply_text(
                caption,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML,
            )
            return

    # بررسی لینک ریلز اینستاگرام یا تیک‌تاک برای استخراج ساندترک
    if looks_like_social_media_video(text):
        status = await update.message.reply_text("🎬 در حال استخراج صدای ویدیو…")
        try:
            detail = await api.resolve_ref(text)
            if detail and detail.tracks:
                try:
                    await status.delete()
                except Exception:
                    pass
                await _send_track_picker(context, update.message, detail.tracks, batchable=False)
                return
        except Exception as exc:
            log.warning("استخراج صدا از ویدیو ناموفق بود: %s", exc)
        await status.edit_text("استخراج صدا از این لینک ناموفق بود — ممکن است ویدیو خصوصی باشد یا سرور در دسترس نباشد.")
        return

    # فقط لینکِ آلبوم/پلی‌لیست «همه رو بگیر» می‌گیرد — نتایجِ جستجو نسخه‌های
    # جایگزینِ یک ترک‌اند، نه اعضای یک مجموعه
    batchable = looks_like_url(text)

    collection: AlbumDetail | None = None
    if batchable:
        try:
            detail = await api.resolve_ref(text)
        except Exception:
            await update.message.reply_text("این لینک شناخته نشد یا محتوایی نداشت.")
            return
        tracks = detail.tracks
        collection = detail
    else:
        try:
            results = await api.search(text)
        except Exception:
            await update.message.reply_text("جستجو ناموفق بود — دوباره امتحان کن.")
            return
        tracks = results.tracks

    await _send_track_picker(
        context, update.message, tracks, batchable=batchable, collection=collection
    )


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    «این چه آهنگی بود؟» — ویس، فایل صوتی یا ویدیو که بیاید، با فینگرپرینت
    آکوستیک شناسایی می‌شود و بعد همان مسیرِ همیشگیِ انتخاب/دانلود ادامه می‌دهد.

    فایل از سرورِ تلگرام گرفته و همان‌طور خام به `/api/identify` داده می‌شود؛
    بات هیچ تبدیلی نمی‌کند — ffmpeg سمتِ سرور هست و اینجا نه.
    """
    message = update.message
    if message is None:
        return

    # در گروه‌ها تنها اگر فایل ریپلای به بات باشد یا کپشن حاوی منشن بات باشد بررسی می‌شود
    chat = getattr(update, "effective_chat", None) or (message.chat if message else None)
    if chat and getattr(chat, "type", "") in ("group", "supergroup"):
        is_reply_to_bot = bool(
            message.reply_to_message
            and message.reply_to_message.from_user
            and context.bot
            and message.reply_to_message.from_user.id == context.bot.id
        )
        caption = (message.caption or "").lower()
        bot_username = (context.bot_data.get("username") or "").lower()
        is_mentioned = bool(bot_username and f"@{bot_username}" in caption)
        if not (is_reply_to_bot or is_mentioned):
            return

    media = (
        message.voice
        or message.audio
        or message.video
        or message.video_note
        or (message.document if _is_media_document(message.document) else None)
    )
    if media is None:
        return

    if media.file_size and media.file_size > MAX_IDENTIFY_BYTES:
        await message.reply_text("حجم فایل بیشتر از سقف مجاز تلگرام (۲۰ مگابایت) است — یک تکه‌ی کوتاه‌تر (۱۰ تا ۳۰ ثانیه) بفرست.")
        return

    status = await message.reply_text("🎧 دارم گوش می‌دم…")
    try:
        handle = await _telegram_retry(
            context.bot.get_file,
            media.file_id,
            read_timeout=UPLOAD_TIMEOUT,
            write_timeout=UPLOAD_TIMEOUT,
        )
        data = bytes(await handle.download_as_bytearray())
    except BadRequest as exc:
        if "file is too big" in str(exc).lower():
            await status.edit_text("حجم فایل برای دانلود از تلگرام بیشتر از سقف مجاز (۲۰ مگابایت) است.")
        else:
            await status.edit_text("فایل از تلگرام گرفته نشد — دوباره بفرست.")
        return
    except Exception:
        await status.edit_text("فایل از تلگرام گرفته نشد — دوباره بفرست.")
        return

    try:
        result = await _api(context).identify(data, _media_filename(media))
    except Unavailable as exc:
        await status.edit_text(str(exc))
        return

    if not result.matches:
        await status.edit_text(
            "نشناختمش. شناساییِ رایگان فقط فایلِ کاملِ آهنگ را می‌شناسد — نه صدایی "
            "که از بلندگو ضبط شده. اسمش را بفرست تا از راه معمول بگردم."
        )
        return

    best = result.matches[0]
    # بعضی سرویس‌ها عددِ اطمینان نمی‌دهند؛ ساختنِ یک «۱۰۰٪» الکی فقط اعتمادِ
    # بی‌جا می‌سازد
    confidence = (
        f"\n<i>اطمینان {round(best.score * 100)}٪</i>" if best.score is not None else ""
    )
    await status.edit_text(
        f"🎵 <b>{html.escape(best.title)}</b>\n{html.escape(best.artist)}{confidence}",
        parse_mode=ParseMode.HTML,
    )

    if result.tracks:
        # نتیجه‌های کاتالوگ همان لیستِ «کدوم یکی؟»ِ همیشگی‌اند — تک‌نتیجه‌ای
        # مستقیم دانلود می‌شود، چندتایی دکمه می‌گیرد
        await _send_track_picker(context, message, result.tracks, batchable=False)
        return

    # شناسایی درست بوده ولی کاتالوگ در دسترس نبوده؛ لااقل اسم را داریم
    await message.reply_text(f"{best.artist} — {best.title}\nبفرستش تا دانلودش کنم.")


MEDIA_EXTENSIONS = (
    ".mp3", ".m4a", ".ogg", ".opus", ".flac", ".wav", ".aac", ".wma",
    ".mp4", ".webm", ".mkv",
)


def _is_media_document(document) -> bool:
    """
    فایلی که به‌جای «صوت» به‌عنوان «داکیومنت» فرستاده شده.

    تلگرام هر فایلی را داکیومنت می‌فرستد اگر فرستنده گزینه‌ی «فایل» را زده
    باشد؛ همچنین تلگرام دسکتاپ گاهی mime_type را application/octet-stream
    می‌فرستد، پس پسوند فایل هم بررسی می‌شود.
    """
    if document is None:
        return False
    mime = (document.mime_type or "").lower()
    if mime.startswith(("audio/", "video/")):
        return True
    filename = (getattr(document, "file_name", "") or "").lower()
    return filename.endswith(MEDIA_EXTENSIONS)


def _media_filename(media) -> str:
    """
    نامِ فایل فقط برای پسوندش مهم است — سرور از روی همان تصمیم می‌گیرد که
    مستقیم به fpcalc بدهد یا اول از ffmpeg رد کند.
    """
    name = getattr(media, "file_name", None)
    if name:
        return name
    mime = (getattr(media, "mime_type", "") or "").lower()
    return "clip" + _MIME_EXT.get(mime, ".ogg")


def _track_picker_keyboard(
    tracks: list[Track],
    page: int = 1,
    batchable: bool = False,
) -> InlineKeyboardMarkup:
    start_idx, end_idx, valid_page, total_pages = paginate_slice(len(tracks), page, MAX_RESULTS)
    picks = tracks[start_idx:end_idx]
    keyboard = [
        [
            InlineKeyboardButton(
                f"{source_badge(t.source)} {format_track_button(t)}", callback_data=f"pick:{start_idx + i}"
            )
        ]
        for i, t in enumerate(picks)
    ]
    if total_pages > 1:
        nav_row = []
        if valid_page > 1:
            nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"page:track:{valid_page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {valid_page}/{total_pages}", callback_data="noop"))
        if valid_page < total_pages:
            nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"page:track:{valid_page + 1}"))
        keyboard.append(nav_row)

    if batchable:
        keyboard.append(
            [InlineKeyboardButton(f"⬇️ دانلود همه ({len(tracks)})", callback_data="all")]
        )
    return InlineKeyboardMarkup(keyboard)


def _collection_picker_keyboard(items: list, page: int = 1) -> InlineKeyboardMarkup:
    start_idx, end_idx, valid_page, total_pages = paginate_slice(len(items), page, MAX_RESULTS)
    picks = items[start_idx:end_idx]
    keyboard = []
    for i, x in enumerate(picks):
        label = format_album_button(x) if isinstance(x, (Album, AlbumDetail)) else format_playlist_button(x)
        keyboard.append([
            InlineKeyboardButton(
                f"{source_badge(x.source)} {label}", callback_data=f"cl:{start_idx + i}"
            )
        ])
    if total_pages > 1:
        nav_row = []
        if valid_page > 1:
            nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"page:cl:{valid_page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {valid_page}/{total_pages}", callback_data="noop"))
        if valid_page < total_pages:
            nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"page:cl:{valid_page + 1}"))
        keyboard.append(nav_row)
    return InlineKeyboardMarkup(keyboard)


def _artist_picker_keyboard(artists: list[Artist], page: int = 1) -> InlineKeyboardMarkup:
    start_idx, end_idx, valid_page, total_pages = paginate_slice(len(artists), page, MAX_RESULTS)
    picks = artists[start_idx:end_idx]
    keyboard = [
        [
            InlineKeyboardButton(
                f"{source_badge(a.source)} {format_artist_search_button(a)}",
                callback_data=f"ba:{start_idx + i}",
            )
        ]
        for i, a in enumerate(picks)
    ]
    if total_pages > 1:
        nav_row = []
        if valid_page > 1:
            nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"page:ba:{valid_page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {valid_page}/{total_pages}", callback_data="noop"))
        if valid_page < total_pages:
            nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"page:ba:{valid_page + 1}"))
        keyboard.append(nav_row)
    return InlineKeyboardMarkup(keyboard)


async def on_page_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیمایش صفحات نتایج جستجو (ورق‌زدن)."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    parts = query.data.split(":")
    if len(parts) < 3:
        return
    kind, page_str = parts[1], parts[2]
    try:
        page = int(page_str)
    except ValueError:
        return

    if kind == "track":
        tracks: list[Track] = context.chat_data.get("candidates", [])
        if not tracks:
            return
        batchable = context.chat_data.get("collection") is not None
        markup = _track_picker_keyboard(tracks, page=page, batchable=batchable)
        try:
            await query.edit_message_reply_markup(reply_markup=markup)
        except Exception:
            pass
    elif kind == "cl":
        items = context.chat_data.get("collection_candidates", [])
        if not items:
            return
        markup = _collection_picker_keyboard(items, page=page)
        try:
            await query.edit_message_reply_markup(reply_markup=markup)
        except Exception:
            pass
    elif kind == "ba":
        artists = context.chat_data.get("browse_artist_candidates", [])
        if not artists:
            return
        markup = _artist_picker_keyboard(artists, page=page)
        try:
            await query.edit_message_reply_markup(reply_markup=markup)
        except Exception:
            pass


async def on_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()


async def _send_track_picker(
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    tracks: list[Track],
    *,
    batchable: bool,
    collection: AlbumDetail | None = None,
    prompt_text: str | None = None,
) -> None:
    """
    لیستِ «کدوم یکی؟» — چه از جستجوی متنی/لینک، چه از باز کردنِ یک آلبوم/پلی‌لیست
    از مرورگرِ هنرمند یا وایب هوشمند. با صفحه‌بندی هوشمند اینلاین.
    """
    if not tracks:
        await message.reply_text("چیزی پیدا نشد.")
        return

    # لینکِ تک‌آهنگ یا نتیجه‌ی تک‌ترکه: دکمه لازم نیست، مستقیم برو سراغ دانلود
    # مگر زمانی که متن توضیحی اختصاصی (مثل وایب) همراه باشد
    if len(tracks) == 1 and not prompt_text:
        try:
            await _download_and_send(context, message.chat_id, tracks[0])
        except Exception as exc:
            log.warning("دانلود یا ارسال برای %s ناموفق بود: %s", tracks[0].title, exc)
        return

    context.chat_data["candidates"] = tracks
    context.chat_data["collection"] = collection
    prompt = prompt_text or ("کدوم یکی؟ یا همه رو یکجا بگیر:" if batchable else "کدوم یکی؟")
    markup = _track_picker_keyboard(tracks, page=1, batchable=batchable)
    await message.reply_text(
        prompt,
        reply_markup=markup,
        parse_mode=ParseMode.HTML if prompt_text else None,
    )


async def _open_collection(context: ContextTypes.DEFAULT_TYPE, message: Message, ref: str) -> None:
    """باز کردنِ یک آلبوم/پلی‌لیست — چه از جستجوی متنیِ مُد آلبوم/پلی‌لیست، چه از مرورگرِ هنرمند."""
    api = _api(context)
    try:
        detail = await api.resolve_ref(ref)
    except Exception:
        detail = None
    if detail is None:
        await message.reply_text("این مورد باز نشد.")
        return
    await _send_track_picker(
        context, message, detail.tracks, batchable=True, collection=detail
    )


async def _collection_search(
    update_message: Message, context: ContextTypes.DEFAULT_TYPE, text: str, *, kind: str
) -> None:
    """مُدِ «آلبوم»/«پلی‌لیست» روی /start — جستجوی نام یا resolve مستقیمِ لینک."""
    api = _api(context)

    if looks_like_url(text):
        await _open_collection(context, update_message, text)
        return

    try:
        results = await api.search(text)
    except Exception:
        await update_message.reply_text("جستجو ناموفق بود — دوباره امتحان کن.")
        return

    items = results.albums if kind == "album" else results.playlists
    if not items:
        await update_message.reply_text("چیزی پیدا نشد.")
        return

    if len(items) == 1:
        await _open_collection(context, update_message, items[0].sourceUrl or items[0].id)
        return

    context.chat_data["collection_candidates"] = items
    markup = _collection_picker_keyboard(items, page=1)
    await update_message.reply_text("کدوم یکی؟", reply_markup=markup)


async def on_collection_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return

    items: list = context.chat_data.get("collection_candidates", [])
    try:
        index = int(query.data.split(":", 1)[1])
        item = items[index]
    except (ValueError, IndexError):
        await query.answer("این انتخاب دیگر معتبر نیست.", show_alert=True)
        return
    await query.answer()

    await query.edit_message_text(f"{source_badge(item.source)} {item.title}")
    await _open_collection(context, query.message, item.sourceUrl or item.id)


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    await query.answer()

    candidates: list[Track] = context.chat_data.get("candidates", [])
    try:
        index = int(query.data.split(":", 1)[1])
        track = candidates[index]
    except (ValueError, IndexError):
        await query.edit_message_text("این انتخاب دیگر معتبر نیست — دوباره جستجو کن.")
        return

    collection = context.chat_data.get("collection")
    if isinstance(collection, AlbumDetail):
        is_album = not (":playlist:" in collection.id and collection.releaseType not in ("album", "ep", "compilation"))
        if is_album or collection.title:
            updates: dict[str, Any] = {}
            if not track.album or is_album:
                updates["album"] = collection.title
            if (not track.albumArtist or is_album) and collection.artist:
                updates["albumArtist"] = collection.artist
            if (not track.albumId or is_album) and collection.id:
                updates["albumId"] = collection.id
            if collection.artworkUrl and (not track.artworkUrl or is_album):
                updates["artworkUrl"] = collection.artworkUrl
            if track.trackNumber is None:
                updates["trackNumber"] = index + 1
            if track.year is None and collection.year:
                updates["year"] = collection.year
            if updates:
                track = track.model_copy(update=updates)

    await query.edit_message_text(_track_line(track), parse_mode=ParseMode.HTML)
    try:
        await _download_and_send(context, query.message.chat_id, track)
    except Exception as exc:
        log.warning("دانلود یا ارسال برای %s ناموفق بود: %s", track.title, exc)


async def on_download_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return
    await query.answer()

    tracks: list[Track] = context.chat_data.get("candidates", [])
    if not tracks:
        await query.edit_message_text("این لیست دیگر معتبر نیست — لینک را دوباره بفرست.")
        return

    collection = context.chat_data.get("collection")
    album = (
        collection
        if (
            isinstance(collection, AlbumDetail)
            and not (":playlist:" in collection.id and collection.releaseType not in ("album", "ep", "compilation"))
        )
        else None
    )

    batch = tracks[:MAX_BATCH_DOWNLOAD]
    note = (
        f" (فقط {MAX_BATCH_DOWNLOAD} تای اول)" if len(tracks) > MAX_BATCH_DOWNLOAD else ""
    )
    await query.edit_message_text(f"دانلودِ {len(batch)} آهنگ{note} شروع شد…")
    await _download_all(context, query.message.chat_id, batch, album=album)


async def on_split_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """انتخاب تفکیک قطعات یا دانلود یکپارچه‌ی میکس یوتیوب."""
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    await query.answer()

    action = query.data.split(":", 1)[1]
    url = context.chat_data.get("split_url")
    chapters_info: ChaptersInfo | None = context.chat_data.get("split_info")

    if not url or not chapters_info:
        await query.edit_message_text("اطلاعات این میکس دیگر معتبر نیست — لطفاً لینک را دوباره ارسال کنید.")
        return

    if action == "whole":
        await query.edit_message_text(f"📦 در حال دانلود کامل میکس:\n{html.escape(chapters_info.title)}", parse_mode=ParseMode.HTML)
        api = _api(context)
        try:
            detail = await api.resolve_ref(url)
            await _send_track_picker(context, query.message, detail.tracks, batchable=False)
        except Exception as exc:
            log.warning("دانلود کامل میکس ناموفق بود: %s", exc)
            await query.message.reply_text("دانلود کامل میکس ناموفق بود — دوباره امتحان کن.")
        return

    # action == "all"
    await query.edit_message_text(f"✂️ آماده‌سازی و برش {len(chapters_info.chapters)} قطعه از میکس…")
    await _run_split_download(context, query.message, url, chapters_info=chapters_info)


async def _run_split_download(
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    url: str,
    *,
    chapters_info: ChaptersInfo | None = None,
    quality: str | None = None,
) -> None:
    """ایجاد تسک برش میکس، دنبال‌کردن وضعیت پیشرفت، و تحویل تک‌تک قطعات به کاربر."""
    api = _api(context)
    target_quality = quality or context.chat_data.get("quality", DEFAULT_QUALITY)

    status_msg = await message.reply_text("✂️ در حال ایجاد کارِ برش روی سرور…")
    sink = _StatusSink(context, message=status_msg)

    try:
        task = await api.create_split(url, target_quality)
    except Exception as exc:
        log.warning("شروع برش میکس ناموفق بود: %s", exc)
        await sink.edit(f"شروع برش میکس ناموفق بود: {exc}")
        return

    last_edit = 0.0
    last_text = ""
    start_time = time.monotonic()
    max_wait_time = 600.0
    consecutive_errors = 0
    max_consecutive_errors = 15

    while task.status not in ("done", "error"):
        if time.monotonic() - start_time > max_wait_time:
            log.warning("عملیات برش میکس به دلیل گذشت زمان طولانی متوقف شد")
            await sink.edit("عملیات برش میکس بیش از حد طول کشید و متوقف شد.")
            return

        await asyncio.sleep(2.0)
        try:
            task = await api.split_status(task.taskId)
            consecutive_errors = 0
        except Exception:
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive_errors:
                log.warning("استعلام وضعیت برش میکس به دلیل خطاهای متوالی سرور متوقف شد")
                await sink.edit("ارتباط با سرور برای بررسی وضعیت برش میکس قطع شد.")
                return
            continue

        now = time.monotonic()
        bar = progress_bar(task.percent)
        if task.status == "downloading":
            text = f"📻 در حال دانلود فایل اصلی میکس…\n{bar} {task.percent:.0f}٪"
        elif task.status == "cutting":
            text = f"✂️ در حال برش قطعات ({task.done}/{task.total})…\n{bar} {task.percent:.0f}٪"
        else:
            text = f"در حال پردازش قطعات…\n{bar} {task.percent:.0f}٪"

        if text != last_text and now - last_edit >= EDIT_INTERVAL:
            last_text, last_edit = text, now
            await sink.edit(text)

    if task.status == "error" or not task.items:
        await sink.edit(task.error or "برش میکس با خطا مواجه شد.")
        return

    await sink.edit(f"✅ برش تمام شد ({len(task.items)} قطعه). ارسال به تلگرام آغاز شد…")

    # ارسال کاور اصلی میکس در ابتدا
    chat_id = message.chat_id
    if chapters_info and chapters_info.artworkUrl:
        try:
            cover_data = await api.raw_bytes(chapters_info.artworkUrl)
            if cover_data and len(cover_data) <= 10 * 1024 * 1024:
                caption = (
                    f"📻 <b>{html.escape(chapters_info.title)}</b>\n"
                    f"👤 کانال: <b>{html.escape(chapters_info.uploader)}</b>\n"
                    f"🔢 تعداد قطعات: {len(task.items)}"
                )
                await _telegram_retry(
                    context.bot.send_photo,
                    chat_id,
                    photo=cover_data,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    read_timeout=UPLOAD_TIMEOUT,
                    write_timeout=UPLOAD_TIMEOUT,
                )
        except Exception:
            pass

    # ارسال ترتیبی قطعات برش‌خورده
    total = len(task.items)
    summary = None
    try:
        summary = await _telegram_retry(
            context.bot.send_message, chat_id, f"صفِ قطعات میکس — 0/{total}"
        )
    except Exception:
        pass

    done = 0
    for item in task.items:
        try:
            sink_item = _StatusSink(context, message=None, chat_id=chat_id)
            await _deliver(
                context,
                chat_id,
                item.track,
                item.jobId,
                sink_item,
                item.format,
                keep=True,
                send_cover=False,
                send_lyrics=True,
            )
            done += 1
        except Exception as exc:
            log.warning("ارسال قطعه %s ناموفق بود: %s", item.track.title, exc)

        if summary is not None:
            try:
                await summary.edit_text(f"صفِ قطعات میکس — {done}/{total}")
            except Exception:
                pass

    if summary is not None:
        try:
            await summary.edit_text(f"✅ ارسال تمام آهنگ‌های میکس تمام شد ({done}/{total})")
        except Exception:
            pass


async def _download_all(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    tracks: list[Track],
    quality: str | None = None,
    *,
    keep: bool = True,
    album: AlbumDetail | None = None,
    send_cover: bool | None = None,
    send_lyrics: bool | None = None,
) -> None:
    """
    صفِ ترتیبی برای «دانلود همه». شکستِ یک ترک بقیه‌ی صف را متوقف نمی‌کند.

    اگر `album` داده شود: کاورِ آلبوم با توضیحات کامل یک‌بار در ابتدا فرستاده
    می‌شود و ترک‌ها فقط فایلِ صوتی (بدون کاور جدا و بدون متن .lrc) خواهند بود.
    در پایان نیز پیامِ اتمام ارسال فرستاده می‌شود.
    """
    if send_cover is None:
        send_cover = album is None
    if send_lyrics is None:
        send_lyrics = album is None

    total = len(tracks)

    if album is not None:
        caption = format_album_caption(album, total)
        api = _api(context)
        cover = None
        try:
            cover = await _fetch_album_cover(api, album)
        except Exception:
            log.warning("گرفتن کاور آلبوم %s ناموفق بود", album.title, exc_info=True)
        if cover and len(cover) <= 10 * 1024 * 1024:
            try:
                await _telegram_retry(
                    context.bot.send_photo,
                    chat_id,
                    photo=cover,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    read_timeout=UPLOAD_TIMEOUT,
                    write_timeout=UPLOAD_TIMEOUT,
                )
            except Exception as exc:
                log.warning("فرستادن عکس کاور آلبوم %s ناموفق بود: %s", album.title, exc)
                try:
                    await _telegram_retry(
                        context.bot.send_message,
                        chat_id,
                        caption,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
        else:
            try:
                await _telegram_retry(
                    context.bot.send_message,
                    chat_id,
                    caption,
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

    summary = None
    try:
        summary = await _telegram_retry(
            context.bot.send_message, chat_id, f"صفِ آلبوم — 0/{total}"
        )
    except Exception:
        log.warning("فرستادن خلاصه صفِ آلبوم ناموفق بود", exc_info=True)

    downloaded_jobs: list[str] = []
    done = 0
    for idx, track in enumerate(tracks, start=1):
        if album is not None:
            updates: dict[str, Any] = {}
            if not track.album:
                updates["album"] = album.title
            if not track.albumArtist and album.artist:
                updates["albumArtist"] = album.artist
            if not track.albumId and album.id:
                updates["albumId"] = album.id
            if album.artworkUrl and (not track.artworkUrl or track.album == album.title):
                updates["artworkUrl"] = album.artworkUrl
            if track.trackNumber is None:
                updates["trackNumber"] = idx
            if track.year is None and album.year:
                updates["year"] = album.year
            if updates:
                track = track.model_copy(update=updates)
        try:
            jid = await _download_and_send(
                context,
                chat_id,
                track,
                quality,
                keep=keep,
                send_cover=send_cover,
                send_lyrics=send_lyrics,
            )
            if jid:
                downloaded_jobs.append(jid)
            done += 1
        except Exception as exc:
            log.warning("دانلود یا ارسالِ %s در آلبوم ناموفق بود: %s", track.title, exc)
        if summary is not None:
            try:
                await summary.edit_text(f"صفِ آلبوم — {done}/{total}")
            except Exception:
                pass
    if summary is not None:
        try:
            await summary.edit_text(f"صفِ آلبوم تمام شد ✅ {done}/{total}")
        except Exception:
            pass

    if album is not None:
        markup = None
        if downloaded_jobs:
            alb_key = store.safe_callback_ref(album.id)
            context.chat_data[f"album_jobs_{alb_key}"] = downloaded_jobs
            context.chat_data[f"album_jobs_{album.id}"] = downloaded_jobs
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📦 دانلود کل آلبوم به صورت ZIP", callback_data=f"zip:alb:{alb_key}")]]
            )
        try:
            msg_text = (
                f"✅ ارسال تمام آهنگ‌های آلبوم «{html.escape(album.title)}» به پایان رسید."
                if done == total
                else f"✅ ارسال آهنگ‌های آلبوم «{html.escape(album.title)}» به پایان رسید ({done}/{total})."
            )
            await _telegram_retry(
                context.bot.send_message,
                chat_id,
                msg_text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.warning("فرستادن پیام پایان آلبوم ناموفق بود", exc_info=True)


async def _download_and_send(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    track: Track,
    quality: str | None = None,
    *,
    keep: bool = True,
    send_cover: bool = True,
    send_lyrics: bool = True,
) -> str | None:
    """
    `quality` را فقط مسیرهایی می‌دهند که خودشان انتخابش کرده‌اند (دکمه‌ی وب)؛
    None یعنی همان کیفیتِ پیش‌فرضِ همین چت. `keep=False` یعنی «فقط تلگرام» —
    پس از ارسال، فایل و ردیفِ جاب پاک می‌شوند و کتابخانه نمی‌بیندشان.
    """
    target_quality = quality or _get_chat_quality(context, chat_id)
    track_hash = track_lyrics_hash(track.id)

    # ۱. بررسی کش فایل‌های تلگرام — تحویل فوق‌سریع بدون دانلود و آپلود دوباره
    cached = store.get_telegram_file(f"{track.id}:{target_quality}")
    if not cached and track.sourceUrl:
        cached = store.get_telegram_file(f"{track.sourceUrl}:{target_quality}")
    if not cached and target_quality == AUTO_QUALITY:
        cached = store.get_telegram_file(track.id)
    elif not cached:
        bare = store.get_telegram_file(track.id)
        if bare and bare.get("quality") == target_quality:
            cached = bare

    if cached and cached.get("file_id"):
        try:
            status = await _telegram_retry(
                context.bot.send_message,
                chat_id,
                f"{_track_line(track)}\n⚡ در حال ارسال فوری از کش…",
                parse_mode=ParseMode.HTML,
            )
            sink = _StatusSink(context, message=status)
            api = _api(context)

            if send_cover:
                try:
                    info = await api.song_info(track.title, track.artist)
                    cover = await _fetch_full_cover(api, track, info)
                    if cover and len(cover) <= 10 * 1024 * 1024:
                        await _telegram_retry(
                            context.bot.send_photo,
                            chat_id,
                            photo=cover,
                            caption=_info_caption(track, info),
                            parse_mode=ParseMode.HTML,
                            read_timeout=UPLOAD_TIMEOUT,
                            write_timeout=UPLOAD_TIMEOUT,
                        )
                except Exception:
                    log.warning("کارت اطلاعات در تحویل از کش ارسال نشد", exc_info=True)

            has_lyrics = store.get_lyrics(track_hash) is not None
            cached_job_id = cached.get("job_id")
            action_buttons = []
            if has_lyrics:
                action_buttons.append(InlineKeyboardButton("📜 متن ترانه", callback_data=f"lyr:{track_hash}"))
            if cached_job_id:
                action_buttons.append(InlineKeyboardButton("❤️ پسندیدم", callback_data=f"fav:add:{cached_job_id}"))
            reply_markup = InlineKeyboardMarkup([action_buttons]) if action_buttons else None

            thumb = await _fetch_thumbnail(api, track.artworkUrl)
            await _upload_audio(
                context,
                chat_id,
                data=cached["file_id"],
                track=track,
                format_label=cached.get("quality"),
                thumb=thumb,
                reply_markup=reply_markup,
                job_id=cached_job_id,
            )
            await sink.delete()
            return cached_job_id
        except Exception as exc:
            log.warning("ارسال با file_id کش تلگرام شکست خورد (%s) — دانلود معمول انجام می‌شود", exc)
            store.delete_telegram_file(f"{track.id}:{target_quality}")
            if track.sourceUrl:
                store.delete_telegram_file(f"{track.sourceUrl}:{target_quality}")
            store.delete_telegram_file(track.id)
            if "sink" in locals():
                await sink.delete()

    # ۲. مسیر عادی دانلود و ارسال
    try:
        status = await _telegram_retry(
            context.bot.send_message,
            chat_id,
            f"{_track_line(track)}\nدر صف…",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        log.warning("فرستادن پیام وضعیت اولیه برای %s ناموفق بود: %s", track.title, exc)
        raise RuntimeError(f"ارسال پیام به تلگرام نشد: {exc}") from exc
    sink = _StatusSink(context, message=status)

    result = await _run_download(context, track, sink, quality)
    if result is None:
        raise RuntimeError(f"دانلودِ «{track.title}» ناموفق بود.")
    job_id, final = result
    await _deliver(
        context,
        chat_id,
        track,
        job_id,
        sink,
        final.format,
        keep=keep,
        send_cover=send_cover,
        send_lyrics=send_lyrics,
    )
    return job_id


async def _run_download(
    context: ContextTypes.DEFAULT_TYPE,
    track: Track,
    sink: _StatusSink,
    quality: str | None = None,
) -> tuple[str, DownloadProgress] | None:
    """جاب را می‌سازد و SSE را دنبال می‌کند. None یعنی شکست — پیام از قبل ادیت شده."""
    api = _api(context)
    quality = quality or context.chat_data.get("quality", DEFAULT_QUALITY)

    try:
        job_id = await api.create_download(track, quality)
    except Exception as exc:
        await sink.edit(f"شروع دانلود ناموفق بود: {exc}")
        return None

    header = _track_line(track)
    final: DownloadProgress | None = None
    last_text, last_edit = "", 0.0
    try:
        async for progress in api.stream_progress(job_id):
            final = progress
            if progress.status == "downloading":
                bar = progress_bar(progress.percent)
                text = f"{header}\n{bar} {progress.percent:.0f}٪ — در حال دانلود"
            else:
                label = STATUS_LABEL.get(progress.status, progress.status)
                text = f"{header}\n{label}"
            now = time.monotonic()
            if text != last_text and now - last_edit >= EDIT_INTERVAL:
                last_text, last_edit = text, now
                await sink.edit(text, parse_mode=ParseMode.HTML)
    except Exception as exc:
        await sink.edit(f"دریافت وضعیت ناموفق بود: {exc}")
        return None

    if final is None or final.status != "ready":
        await sink.edit((final.error if final else None) or "دانلود ناموفق بود.")
        return None
    return job_id, final


async def _upload_audio(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    data: bytes | str,
    track: Track,
    format_label: str | None,
    thumb: InputFile | None,
    reply_markup: InlineKeyboardMarkup | None = None,
    job_id: str | None = None,
) -> Message:
    """
    `send_audio` با مهلتِ آپلود و تلاشِ دوباره.
    پشتیبانی از بایت‌های خام یا file_id کش‌شده در تلگرام.
    """
    # مقدارِ اولیه فقط برای وقتی است که حلقه اصلاً نچرخد؛ در عمل همیشه با
    # خطای آخرین تلاش جایگزین می‌شود.
    last: NetworkError = NetworkError("آپلود به تلگرام نشد.")
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            msg = await context.bot.send_audio(
                chat_id,
                audio=data,
                filename=audio_filename(track, format_label),
                title=track.title,
                performer=track.artist,
                thumbnail=thumb,
                reply_markup=reply_markup,
                read_timeout=UPLOAD_TIMEOUT,
                write_timeout=UPLOAD_TIMEOUT,
            )
            # ذخیره شناسه فایل تلگرام در صورت موفقیت
            if msg and getattr(msg, "audio", None):
                audio_obj = msg.audio
                file_id = getattr(audio_obj, "file_id", None)
                if file_id and isinstance(file_id, str):
                    file_unique_id = getattr(audio_obj, "file_unique_id", None)
                    duration = getattr(audio_obj, "duration", None)
                    current_q = context.chat_data.get("quality", DEFAULT_QUALITY) if hasattr(context, "chat_data") and context.chat_data else DEFAULT_QUALITY
                    for key in (
                        f"{track.id}:{format_label or 'default'}",
                        f"{track.id}:{current_q}",
                        track.id,
                    ):
                        store.save_telegram_file(
                            key,
                            file_id=file_id,
                            file_unique_id=file_unique_id,
                            title=track.title,
                            artist=track.artist,
                            duration_sec=duration,
                            quality=format_label,
                            job_id=job_id,
                        )
                    if track.sourceUrl:
                        store.save_telegram_file(
                            f"{track.sourceUrl}:{format_label or 'default'}",
                            file_id=file_id,
                            file_unique_id=file_unique_id,
                            title=track.title,
                            artist=track.artist,
                            duration_sec=duration,
                            quality=format_label,
                            job_id=job_id,
                        )
            return msg
        except (BadRequest, Forbidden):
            # خطای خودِ درخواست یا مسدود بودن است — تلاشِ دوباره جوابش را عوض نمی‌کند.
            raise
        except NetworkError as exc:
            last = exc
            log.warning(
                "آپلودِ %s به تلگرام در تلاشِ %d/%d نشد: %s",
                track.title,
                attempt,
                UPLOAD_ATTEMPTS,
                exc,
            )
            if attempt < UPLOAD_ATTEMPTS:
                await asyncio.sleep(UPLOAD_RETRY)
    raise last


async def _deliver(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    track: Track,
    job_id: str,
    sink: _StatusSink,
    format_label: str | None,
    *,
    keep: bool = True,
    send_cover: bool = True,
    send_lyrics: bool = True,
) -> None:
    """
    فایلِ آماده را می‌گیرد و می‌فرستد — چه تازه دانلود شده باشد چه از
    کتابخانه (`/library`) دوباره خواسته شده باشد.

    `keep=False` یعنی «فقط تلگرام»: بعد از رسیدنِ موفقِ فایل (و متن)، فایل و
    ردیفِ جاب پاک می‌شوند. شکستِ آپلود پاک‌سازی را رد می‌کند تا فایلِ روی سرور
    از طریق لینکِ مستقیم از دست نرود.
    """
    api = _api(context)
    track_hash = track_lyrics_hash(track.id)

    tasks = [api.file_bytes(job_id)]
    if send_cover:
        tasks.append(api.song_info(track.title, track.artist))
    else:
        tasks.append(asyncio.sleep(0, result=None))
    tasks.append(api.lyrics_bytes(job_id))

    data, info, lyrics = await asyncio.gather(*tasks)

    if data is None:
        await sink.edit("فایل آماده نبود.")
        return

    if too_large_for_telegram(len(data)):
        await sink.edit(
            "این فایل بزرگ‌تر از حدی است که تلگرام قبول می‌کند — "
            f"مستقیم بگیرش:\n{html.escape(api.file_url(job_id))}",
            parse_mode=ParseMode.HTML,
        )
        return

    # کارتِ اطلاعات: شکستِ گرفتنِ کاور/اطلاعات نباید جلوی رسیدنِ خودِ فایل را
    # بگیرد — best-effort، جدا از مسیر اصلی
    if send_cover:
        try:
            cover = await _fetch_full_cover(api, track, info)
            if cover and len(cover) <= 10 * 1024 * 1024:
                await _telegram_retry(
                    context.bot.send_photo,
                    chat_id,
                    photo=cover,
                    caption=_info_caption(track, info),
                    parse_mode=ParseMode.HTML,
                    read_timeout=UPLOAD_TIMEOUT,
                    write_timeout=UPLOAD_TIMEOUT,
                )
        except Exception:
            log.warning("فرستادن کارتِ اطلاعات برای %s ناموفق بود", track.title, exc_info=True)

    await sink.edit(f"{_track_line(track)}\nدر حال ارسال…", parse_mode=ParseMode.HTML)
    # مثل کاورِ کاملِ بالا، best-effort است — شکستِ گرفتنِ thumbnail نباید
    # جلوی رسیدنِ خودِ فایل صوتی را بگیرد
    try:
        thumb = await _fetch_thumbnail(api, track.artworkUrl, job_id)
    except Exception:
        thumb = None
        log.warning("گرفتنِ thumbnail برای %s ناموفق بود", track.title, exc_info=True)

    # پردازش و ذخیره متن ترانه جهت استفاده دکمه شیشه‌ای
    clean_lyrics_text = None
    if lyrics:
        raw_text = lyrics.decode("utf-8", errors="ignore")
        clean_lyrics_text = clean_lrc_lyrics(raw_text)
        if clean_lyrics_text:
            store.save_lyrics(track_hash, clean_lyrics_text, title=track.title, artist=track.artist)

    has_lyrics = clean_lyrics_text is not None or store.get_lyrics(track_hash) is not None
    action_buttons = []
    if has_lyrics:
        action_buttons.append(InlineKeyboardButton("📜 متن ترانه", callback_data=f"lyr:{track_hash}"))
    action_buttons.append(InlineKeyboardButton("❤️ پسندیدم", callback_data=f"fav:add:{job_id}"))
    audio_markup = InlineKeyboardMarkup([action_buttons])

    try:
        await _upload_audio(
            context,
            chat_id,
            data=data,
            track=track,
            format_label=format_label,
            thumb=thumb,
            reply_markup=audio_markup,
            job_id=job_id,
        )
    except Forbidden as exc:
        await sink.edit("ربات در این چت مسدود شده یا دسترسی ندارد.")
        raise RuntimeError(f"ربات در تلگرام مسدود شده است ({exc}).") from exc
    except NetworkError as exc:
        # فایل روی دیسکِ سرور هست و از LAN می‌شود گرفتش — همان راهی که برای
        # فایلِ بزرگ‌تر از حدِ تلگرام هم می‌رود. پیامِ وضعیت را با لینک نگه
        # می‌داریم تا آهنگ به‌خاطرِ یک قطعیِ لحظه‌ای کلاً از دست نرود.
        await sink.edit(
            f"{_track_line(track)}\nآپلود به تلگرام نشد — مستقیم بگیرش:\n{html.escape(api.file_url(job_id))}",
            parse_mode=ParseMode.HTML,
        )
        raise RuntimeError(f"آپلود به تلگرام نشد ({exc}) — فایل روی سرور آماده است.") from exc

    await sink.delete()

    # فایلِ صوتی از قبل رسیده؛ نرسیدنِ .lrc نباید کلِ ارسال را «ناموفق» کند —
    # دکمه‌ی وب همان لحظه قرمز می‌شد در حالی که آهنگ در چت نشسته بود.
    if send_lyrics and lyrics:
        try:
            safe_artist = clean_filename_part(track.artist)
            safe_title = clean_filename_part(track.title)
            await _telegram_retry(
                context.bot.send_document,
                chat_id,
                document=lyrics,
                filename=f"{safe_artist} - {safe_title}.lrc",
                read_timeout=UPLOAD_TIMEOUT,
                write_timeout=UPLOAD_TIMEOUT,
            )
        except Exception:
            log.warning("فرستادنِ متنِ %s ناموفق بود", track.title, exc_info=True)

    if not keep:
        # «فقط تلگرام»: فایل رسیده، پس اثری در کتابخانه نماند. DELETE هم فایل
        # و هم ردیفِ دیتابیس را برمی‌دارد؛ شکستش فقط هشدار است — پیگیریِ دکمه‌ی
        # وب قبلاً با رسیدنِ آپلود تمام شده و نباید حالا قرمز شود.
        try:
            await api.delete_download(job_id)
        except Exception:
            log.warning("پاک‌سازیِ «فقط تلگرام» برای %s ناموفق بود", track.title, exc_info=True)


async def on_lyrics_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش درون‌پیامی و شکیل متن ترانه با کلیک روی دکمه شیشه‌ای «📜 متن ترانه»."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    track_hash = query.data.split(":", 1)[1]
    cached = store.get_lyrics(track_hash)
    if not cached:
        await query.answer("متأسفانه متن ترانه‌ای برای این آهنگ موجود نیست.", show_alert=True)
        return

    await query.answer()

    title = cached.get("title") or "آهنگ"
    artist = cached.get("artist") or ""
    header = f"📜 <b>متن ترانه: {html.escape(title)}</b>"
    if artist:
        header += f" — {html.escape(artist)}"

    body = cached.get("lyrics", "")
    max_body_len = max(500, 3900 - len(header))
    if len(body) > max_body_len:
        cut_pos = body.rfind("\n", 0, max_body_len)
        if cut_pos < max_body_len // 2:
            cut_pos = max_body_len
        body = body[:cut_pos] + "\n\n…"

    full_text = f"{header}\n\n{html.escape(body)}"

    if query.message is not None:
        await query.message.reply_text(full_text, parse_mode=ParseMode.HTML)
    elif query.from_user is not None:
        await context.bot.send_message(query.from_user.id, full_text, parse_mode=ParseMode.HTML)


# ---------- inline mode ----------

# نتیجه‌ی inline فقط یک id کوتاه دارد (محدودیتِ تلگرام)، نه کلِ ترک؛ همان id
# را روی این کش نگه می‌داریم تا وقتی کاربر یکی را انتخاب کرد (chosen_inline_result)
# بدانیم واقعاً چه چیزی انتخاب شده. TTL کوتاه چون نتایجِ inline زودگذرند.
_INLINE_CACHE_TTL = 600.0
_inline_cache: dict[str, Track] = {}
_inline_cache_at: dict[str, float] = {}


def _cache_inline_track(track: Track) -> str:
    now = time.monotonic()
    cutoff = now - _INLINE_CACHE_TTL
    for key in [k for k, at in _inline_cache_at.items() if at < cutoff]:
        _inline_cache.pop(key, None)
        _inline_cache_at.pop(key, None)

    key = uuid.uuid4().hex[:16]
    _inline_cache[key] = track
    _inline_cache_at[key] = now
    return key


async def on_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    جستجو از هر چتی با `@botname آهنگ`، بدون باز کردن پی‌وی بات.

    لینک اینجا پشتیبانی نمی‌شود — resolve یک آلبوم/پلی‌لیست ممکن است طول
    بکشد و inline query چند ثانیه بیشتر مهلت نمی‌دهد؛ برای لینک همچنان باید
    مستقیم به بات پیام داد.
    """
    query = update.inline_query
    text = query.query.strip()
    if not text or looks_like_url(text):
        await query.answer([], cache_time=1, is_personal=True)
        return

    api = _api(context)
    try:
        results = await api.search(text)
    except Exception:
        await query.answer([], cache_time=1, is_personal=True)
        return

    articles = []
    for track in results.tracks[:MAX_RESULTS]:
        key = _cache_inline_track(track)
        thumb = resized_artwork(track.artworkUrl, THUMB_SIZE) if track.artworkUrl else None
        articles.append(
            InlineQueryResultArticle(
                id=key,
                title=f"{source_badge(track.source)} {track.title}",
                description=track.artist,
                thumbnail_url=thumb,
                input_message_content=InputTextMessageContent(
                    f"{_track_line(track)}\nدر صف…", parse_mode=ParseMode.HTML
                ),
            )
        )
    try:
        await query.answer(articles, cache_time=5, is_personal=True)
    except BadRequest as exc:
        if "query is too old" in str(exc).lower():
            log.debug("کوئری اینلاین منقضی شده: %s", exc)
            return
        raise


async def on_chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    کاربر یکی از نتایجِ inline را زد — همان پیامِ متنی که در `input_message_content`
    ساختیم الان در آن چت نشسته و ما فقط `inline_message_id`اش را داریم.
    """
    chosen = update.chosen_inline_result
    log.info(
        "chosen_inline_result: result_id=%s inline_message_id=%s",
        chosen.result_id,
        chosen.inline_message_id,
    )
    try:
        if chosen.inline_message_id is None:
            return
        track = _inline_cache.pop(chosen.result_id, None)
        _inline_cache_at.pop(chosen.result_id, None)
        if track is None:
            await context.bot.edit_message_text(
                "این نتیجه دیگر معتبر نیست — دوباره جستجو کن.",
                inline_message_id=chosen.inline_message_id,
            )
            return

        sink = _StatusSink(context, inline_message_id=chosen.inline_message_id)
        result = await _run_download(context, track, sink)
        if result is None:
            return
        job_id, final = result
        await _deliver_inline(context, chosen.inline_message_id, track, job_id, final.format)
    except Exception:
        log.exception("on_chosen_inline_result کلاً شکست خورد")


async def _deliver_inline(
    context: ContextTypes.DEFAULT_TYPE,
    inline_message_id: str,
    track: Track,
    job_id: str,
    format_label: str | None,
) -> None:
    """
    برخلافِ چتِ معمولی، اینجا نمی‌شود مستقیم فایل فرستاد: ادیتِ پیامِ inline
    فقط `file_id` یا URL قبول می‌کند، نه آپلودِ تازه. اگر چتِ کش تنظیم شده
    باشد، فایل یک‌بار آنجا فرستاده می‌شود تا `file_id` بگیرد و همان روی پیامِ
    inline بنشیند؛ وگرنه فقط لینکِ مستقیمِ فایل نشان داده می‌شود.
    """
    api = _api(context)
    sink = _StatusSink(context, inline_message_id=inline_message_id)
    data = await api.file_bytes(job_id)
    if data is None:
        await sink.edit("فایل آماده نبود.")
        return

    if too_large_for_telegram(len(data)) or TELEGRAM_CACHE_CHAT_ID is None:
        await sink.edit(
            f"{_track_line(track)}\nآماده شد — بگیرش:\n{html.escape(api.file_url(job_id))}",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        thumb = await _fetch_thumbnail(api, track.artworkUrl, job_id)
        cached = await _upload_audio(
            context,
            TELEGRAM_CACHE_CHAT_ID,
            data=data,
            track=track,
            format_label=format_label,
            thumb=thumb,
        )
        if not cached or not cached.audio:
            raise RuntimeError("فایل صوتی در کش تلگرام آپلود نشد.")
        await context.bot.edit_message_media(
            inline_message_id=inline_message_id,
            media=InputMediaAudio(
                media=cached.audio.file_id,
                title=track.title,
                performer=track.artist,
                thumbnail=thumb,
                duration=track.durationMs // 1000 if track.durationMs else None,
                caption=_track_line(track),
                parse_mode=ParseMode.HTML,
            ),
        )
    except Exception:
        log.warning("تحویلِ inline برای %s ناموفق بود", track.title, exc_info=True)
        await sink.edit(
            f"{_track_line(track)}\nآماده شد — بگیرش:\n{html.escape(api.file_url(job_id))}",
            parse_mode=ParseMode.HTML,
        )


# ---------- دنبال‌کردنِ هنرمند ----------


# ---------- وصل‌شدن به وب و صفِ «فرستادن به تلگرام» ----------
#
# وب توکنِ تلگرام ندارد و نمی‌داند چت کیست، پس دو تکه لازم است: یک کدِ
# یک‌بارمصرف که این چت را به آن نصب وصل می‌کند، و یک صف که دکمه‌ی وب رویش
# ردیف می‌گذارد و همین‌جا برداشته می‌شود. خودِ دانلود و ارسال همان مسیرِ
# همیشگیِ بات است — هیچ کدِ موازی‌ای برای وب نوشته نشده.

LINK_PAYLOAD_PREFIX = "link_"

# وقفه‌ی تلاش دوباره وقتی سرور در دسترس نیست — نه آن‌قدر تند که لاگ پر شود
OUTBOX_RETRY = 5.0

# سقفِ انتظارِ هر long-poll (ثانیه). باید با telegram.OUTBOX_WAIT سمت سرور جور
# باشد؛ سرور خودش هم بیشتر از آن صبر نمی‌کند.
OUTBOX_WAIT = 25.0


def _chat_title(message: Message) -> str:
    """اسمی که در وب کنارِ «وصل است» نشان داده می‌شود."""
    chat = message.chat
    if chat.title:
        return chat.title
    name = " ".join(x for x in (chat.first_name, chat.last_name) if x)
    return name or (f"@{chat.username}" if chat.username else str(chat.id))


async def _claim_link(message: Message, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    code = code.strip()
    if not code:
        await message.reply_text("کد را هم بنویس: /link ABC123 — کد را از دکمه‌ی تلگرامِ وب بگیر.")
        return

    error = await _api(context).claim_pair(code, message.chat_id, _chat_title(message))
    if error:
        await message.reply_text(error)
        return
    await message.reply_text(
        "وصل شد ✅\n"
        "از این به بعد هر آهنگ یا آلبومی که در وب دکمه‌ی تلگرامش را بزنی، "
        "کامل همین‌جا می‌آید."
    )


async def link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/link ABC123` — همان کدی که وب نشان می‌دهد، برای وقتی لینکِ عمیق باز نشد."""
    if update.message is None:
        return
    await _claim_link(update.message, context, context.args[0] if context.args else "")


async def _run_outbox_job(application: Application, job: TelegramJob) -> str | None:
    """
    یک کارِ صف. برگشتی None یعنی موفق، وگرنه دلیلِ شکست تا در وب دیده شود.

    context را دستی می‌سازیم چون این کار از هیچ آپدیتی نیامده — ولی همان
    context معمولی است، پس `_download_and_send` فرقی بین این مسیر و پیامِ
    کاربر نمی‌بیند.
    """
    context = application.context_types.context(application, chat_id=job.chatId)

    if job.kind == "track":
        if job.track is None:
            return "خودِ آهنگ در صف نبود."
        try:
            await _download_and_send(context, job.chatId, job.track, job.quality, keep=job.keep)
        except Exception as exc:
            return str(exc)
        return None

    if not job.ref:
        return "لینکِ آلبوم در صف نبود."
    try:
        album = await _api(context).resolve_ref(job.ref)
    except Exception as exc:
        return f"باز کردنِ آلبوم ناموفق بود: {exc}"
    if not album.tracks:
        return "این آلبوم ترکی نداشت."

    batch = album.tracks[:MAX_BATCH_DOWNLOAD]
    # اطمینان از اینکه همه‌ی ترک‌های ارسالیِ آلبوم، کاورِ خودِ آلبوم را دارند
    if album.artworkUrl:
        for t in batch:
            if not t.artworkUrl or t.album == album.title:
                t.artworkUrl = album.artworkUrl

    await _download_all(context, job.chatId, batch, job.quality, keep=job.keep, album=album)
    return None


async def _outbox_loop(application: Application) -> None:
    """
    long-pollِ همیشگی روی صفِ سرور.

    خطای شبکه فقط یعنی سرور هنوز بالا نیست یا ری‌استارت شده — کمی صبر و دوباره؛
    خطای خودِ کار به سرور گزارش می‌شود تا دکمه‌ی وب از حالتِ «در حال ارسال»
    دربیاید و کاربر معطلِ اسپینری نماند که هیچ‌وقت تمام نمی‌شود.
    """
    api = _api_from_app(application)
    username = application.bot_data.get("username")
    await api.register(username)

    while True:
        try:
            job = await api.next_telegram_job(username, OUTBOX_WAIT)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("خواندنِ صفِ تلگرام ناموفق بود", exc_info=True)
            await asyncio.sleep(OUTBOX_RETRY)
            continue

        if job is None:
            continue

        try:
            error = await _run_outbox_job(application, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("کارِ صفِ تلگرام شکست خورد", exc_info=True)
            error = str(exc)
        await api.finish_telegram_job(job.id, error)


async def follow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    text = " ".join(context.args) if context.args else ""
    if not text.strip():
        await update.message.reply_text(
            "اسم هنرمند یا لینک صفحه‌اش رو بعد از /follow بفرست؛ مثلاً:\n"
            "/follow Farhad Mehrad"
        )
        return

    api = _api(context)
    try:
        if looks_like_url(text):
            detail = await api.artist(text)
            artists: list = [detail] if detail else []
        else:
            results = await api.search(text)
            artists = list(results.artists)
    except Exception:
        await update.message.reply_text("پیدا کردنِ هنرمند ناموفق بود.")
        return

    if not artists:
        await update.message.reply_text("هنرمندی پیدا نشد.")
        return

    if len(artists) == 1:
        await _follow_artist(update.message, context, artists[0])
        return

    picks = artists[:MAX_RESULTS]
    context.chat_data["artist_candidates"] = picks
    keyboard = [
        [
            InlineKeyboardButton(
                f"{source_badge(a.source)} {format_artist_button(a.name)}",
                callback_data=f"followpick:{i}",
            )
        ]
        for i, a in enumerate(picks)
    ]
    await update.message.reply_text("کدوم یکی؟", reply_markup=InlineKeyboardMarkup(keyboard))


async def _follow_artist(message: Message, context: ContextTypes.DEFAULT_TYPE, artist) -> None:
    """
    دنبال‌کردن را در سرور ثبت می‌کند؛ اگر جزئیاتِ کامل (با آلبوم‌ها) از قبل نداریم
    (مسیرِ جستجو فقط کارتِ خلاصه می‌دهد)، یک `artist()` دیگر برای seed کردنِ
    آخرین انتشار لازم است — بدونش، اولین چکِ پس‌زمینه هر آلبومِ قدیمی را هم
    «تازه» حساب می‌کرد و برای هر هنرمند یک پیامِ کاذب می‌فرستاد.
    """
    api = _api(context)
    detail = artist if isinstance(artist, ArtistDetail) else await api.artist(artist.sourceUrl)

    latest = detail.albums[0] if detail and detail.albums else None
    try:
        state = await api.add_follow(
            message.chat_id,
            FollowRequest(
                artistId=artist.id,
                artistName=artist.name,
                artistSourceUrl=artist.sourceUrl,
                source=artist.source,
                artworkUrl=artist.artworkUrl,
                lastReleaseId=latest.id if latest else None,
                lastReleaseTitle=latest.title if latest else None,
            ),
        )
    except Exception:
        await message.reply_text("ثبتِ دنبال‌کردن ناموفق بود — سرور در دسترس نیست؟")
        return
    if state.created:
        await message.reply_text(
            f"{source_badge(artist.source)} دنبال‌کردنِ «{artist.name}» شروع شد — "
            "هر انتشارِ تازه‌ای را خودکار با فایل، کاور و لینکش همین‌جا می‌فرستم."
        )
    else:
        await message.reply_text(f"«{artist.name}» از قبل دنبال می‌شد.")


async def on_follow_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    await query.answer()

    candidates = context.chat_data.get("artist_candidates", [])
    try:
        index = int(query.data.split(":", 1)[1])
        artist = candidates[index]
    except (ValueError, IndexError):
        await query.edit_message_text("این انتخاب دیگر معتبر نیست — دوباره /follow بزن.")
        return

    await query.edit_message_text(f"{source_badge(artist.source)} {artist.name}")
    await _follow_artist(query.message, context, artist)


async def unfollow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    try:
        follows = await _api(context).follows(update.message.chat_id)
    except Exception:
        await update.message.reply_text("گرفتنِ لیستِ دنبال‌شده‌ها ناموفق بود.")
        return
    if not follows:
        await update.message.reply_text("چیزی دنبال نمی‌کنی.")
        return

    keyboard = [
        [InlineKeyboardButton(f"✕ {f.artistName}", callback_data=f"unfollow:{store.safe_callback_ref(f.artistId)}")]
        for f in follows
    ]
    await update.message.reply_text(
        "کدوم رو دیگه دنبال نکنم؟", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def on_unfollow_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    await query.answer()

    raw_id = query.data.split(":", 1)[1]
    artist_id = store.resolve_callback_ref(raw_id)
    try:
        removed = await _api(context).remove_follow(query.message.chat_id, artist_id)
    except Exception:
        await query.edit_message_text("حذف ناموفق بود — سرور در دسترس نیست؟")
        return
    await query.edit_message_text("دیگه دنبال نمی‌شود." if removed else "این مورد پیدا نشد.")


async def following_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    try:
        follows = await _api(context).follows(update.message.chat_id)
    except Exception:
        await update.message.reply_text("گرفتنِ لیستِ دنبال‌شده‌ها ناموفق بود.")
        return
    if not follows:
        await update.message.reply_text("چیزی دنبال نمی‌کنی — با /follow شروع کن.")
        return

    lines = [f"{source_badge(f.source)} {f.artistName}" for f in follows]
    await update.message.reply_text("دنبال‌شده‌ها:\n" + "\n".join(f"• {l}" for l in lines))


# ---------- مرورگرِ هنرمند ----------


async def _artist_search(message: Message, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """مُدِ «هنرمند» روی /start — همان جستجوی دوشاخه‌ی `follow_cmd` (لینک یا اسم)."""
    api = _api(context)
    try:
        if looks_like_url(text):
            detail = await api.artist(text)
            if detail is None:
                await message.reply_text("هنرمندی پیدا نشد.")
                return
            view = await _artist_profile_view(context, detail)
            if view is None:
                await message.reply_text("هنرمندی پیدا نشد.")
                return
            await _reply_artist_profile(message, view)
            return
        results = await api.search(text)
    except Exception:
        await message.reply_text("جستجوی هنرمند ناموفق بود.")
        return

    artists = results.artists
    if not artists:
        await message.reply_text("هنرمندی پیدا نشد.")
        return

    if len(artists) == 1:
        view = await _artist_profile_view(context, artists[0].id)
        if view is None:
            await message.reply_text("این هنرمند پیدا نشد.")
            return
        await _reply_artist_profile(message, view)
        return

    context.chat_data["browse_artist_candidates"] = artists
    markup = _artist_picker_keyboard(artists, page=1)
    await message.reply_text("کدوم یکی؟", reply_markup=markup)


async def _artist_profile_view(
    context: ContextTypes.DEFAULT_TYPE, ref_or_detail: str | ArtistDetail
) -> tuple[str, InlineKeyboardMarkup] | None:
    """
    متن + کیبورد صفحه‌ی پروفایل هنرمند — None یعنی پیدا نشد.

    ورودی یا ref است یا یک `ArtistDetail` از قبل آماده (وقتی جستجو با لینک
    خودش کاملش داده)، همان الگوی `_follow_artist`.
    """
    api = _api(context)
    if isinstance(ref_or_detail, ArtistDetail):
        detail = ref_or_detail
    else:
        try:
            detail = await api.artist(ref_or_detail)
        except Exception:
            log.warning("گرفتنِ پروفایلِ %s ناموفق بود", ref_or_detail, exc_info=True)
            detail = None
    if detail is None:
        return None

    # کش می‌شود تا رفت‌وبرگشت بین بخش‌ها (`_artist_section_view`) یک هنرمند را
    # دوباره fetch نکند
    context.chat_data["artist_view"] = {"ref": detail.id, "detail": detail}

    text = (
        f"{source_badge(detail.source)} <b>{html.escape(detail.name)}</b>\n"
        f"{html.escape(detail.subtitle)}"
    )

    safe_id = store.safe_callback_ref(detail.id)
    rows: list[list[InlineKeyboardButton]] = []
    if detail.topTracks:
        rows.append([InlineKeyboardButton("⭐ آهنگ‌های محبوب", callback_data=f"att:{safe_id}")])
    if detail.albums:
        rows.append(
            [
                InlineKeyboardButton(
                    f"💿 آلبوم‌ها ({len(detail.albums)})", callback_data=f"aal:{safe_id}"
                )
            ]
        )
    if detail.playlists:
        rows.append([InlineKeyboardButton("📃 پلی‌لیست‌ها", callback_data=f"apl:{safe_id}")])
    if detail.radio:
        rows.append([InlineKeyboardButton("📻 رادیو", callback_data=f"ard:{safe_id}")])
    if detail.related:
        rows.append([InlineKeyboardButton("🔗 هنرمندهای مرتبط", callback_data=f"are:{safe_id}")])
    rows.append([InlineKeyboardButton("➕ دنبال کردن", callback_data=f"afollow:{safe_id}")])

    return text, InlineKeyboardMarkup(rows)


async def _reply_artist_profile(message: Message, view: tuple[str, InlineKeyboardMarkup]) -> None:
    text, keyboard = view
    await message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def _edit_artist_profile(query, view: tuple[str, InlineKeyboardMarkup]) -> None:
    text, keyboard = view
    await _safe_edit_message_text(query, text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def _artist_section_view(
    context: ContextTypes.DEFAULT_TYPE, ref: str, section: str
) -> tuple[str, InlineKeyboardMarkup] | None:
    """
    متن + کیبورد یک بخش از صفحه‌ی هنرمند (آهنگ محبوب/آلبوم/پلی‌لیست/رادیو/مرتبط).

    از `artist_view` (آخرین هنرمندِ دیده‌شده) استفاده می‌کند تا رفت‌وبرگشت بین
    بخش‌ها یک هنرمند را دوباره fetch نکند.
    """
    cached = context.chat_data.get("artist_view")
    if cached and cached.get("ref") == ref:
        detail = cached["detail"]
    else:
        try:
            detail = await _api(context).artist(ref)
        except Exception:
            log.warning("گرفتنِ پروفایلِ %s ناموفق بود", ref, exc_info=True)
            detail = None
        if detail is None:
            return None
        context.chat_data["artist_view"] = {"ref": ref, "detail": detail}

    if section in ("att", "ard"):
        items: list[Track] = detail.topTracks if section == "att" else detail.radio
        context.chat_data["artist_view_tracks"] = items
        rows = [
            [
                InlineKeyboardButton(
                    f"{source_badge(t.source)} {format_track_button(t)}", callback_data=f"tk:{i}"
                )
            ]
            for i, t in enumerate(items[:MAX_RESULTS])
        ]
    elif section == "aal":
        albums: list[Album] = detail.albums
        context.chat_data["artist_view_albums"] = albums
        rows = [
            [InlineKeyboardButton(format_album_button(a), callback_data=f"ab:{i}")]
            for i, a in enumerate(albums[:MAX_RESULTS])
        ]
    elif section == "apl":
        playlists: list[Playlist] = detail.playlists
        context.chat_data["artist_view_playlists"] = playlists
        rows = [
            [InlineKeyboardButton(format_playlist_button(p), callback_data=f"pl:{i}")]
            for i, p in enumerate(playlists[:MAX_RESULTS])
        ]
    else:  # are — هرکدام مستقیم به پروفایل همان هنرمند می‌رود، نیازی به index ندارد
        related: list[Artist] = detail.related
        rows = [
            [
                InlineKeyboardButton(
                    f"{source_badge(a.source)} {format_artist_search_button(a)}",
                    callback_data=f"au:{store.safe_callback_ref(a.id)}",
                )
            ]
            for a in related[:MAX_RESULTS]
        ]

    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"au:{store.safe_callback_ref(ref)}")])
    return SECTION_TITLE[section], InlineKeyboardMarkup(rows)


async def on_browse_artist_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """انتخاب از لیستِ «کدوم یکی؟»ی جستجوی هنرمند (مُد «هنرمند» روی /start)."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    candidates: list[Artist] = context.chat_data.get("browse_artist_candidates", [])
    try:
        index = int(query.data.split(":", 1)[1])
        artist = candidates[index]
    except (ValueError, IndexError):
        await query.answer("این انتخاب دیگر معتبر نیست.", show_alert=True)
        return
    await query.answer()

    view = await _artist_profile_view(context, artist.id)
    if view is None:
        await query.edit_message_text("این هنرمند پیدا نشد.")
        return
    await _edit_artist_profile(query, view)


async def on_artist_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`au:{ref}` — پروفایل هنرمند: بازگشت از یک بخش، یا رفتن به یک هنرمندِ مرتبط."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    raw_ref = query.data.split(":", 1)[1]
    ref = store.resolve_callback_ref(raw_ref)
    view = await _artist_profile_view(context, ref)
    if view is None:
        await query.edit_message_text("این هنرمند دیگر پیدا نشد.")
        return
    await _edit_artist_profile(query, view)


async def on_artist_section(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`att:`/`aal:`/`apl:`/`ard:`/`are:` — یک بخش از صفحه‌ی هنرمند."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    section, raw_ref = query.data.split(":", 1)
    ref = store.resolve_callback_ref(raw_ref)
    view = await _artist_section_view(context, ref, section)
    if view is None:
        await query.edit_message_text("این هنرمند دیگر پیدا نشد.")
        return
    text, keyboard = view
    await _safe_edit_message_text(query, text, reply_markup=keyboard)


async def on_artist_follow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌ی «➕ دنبال کردن» روی کارتِ پروفایل — همان `_follow_artist` موجود."""
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return

    raw_ref = query.data.split(":", 1)[1]
    ref = store.resolve_callback_ref(raw_ref)
    cached = context.chat_data.get("artist_view")
    if cached and cached.get("ref") == ref:
        detail = cached["detail"]
    else:
        try:
            detail = await _api(context).artist(ref)
        except Exception:
            log.warning("گرفتنِ پروفایلِ %s ناموفق بود", ref, exc_info=True)
            detail = None
    if detail is None:
        await query.answer("این هنرمند دیگر پیدا نشد.", show_alert=True)
        return
    await query.answer()
    await _follow_artist(query.message, context, detail)


async def on_artist_track_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """انتخابِ یک ترک از «آهنگ‌های محبوب» یا «رادیو»ی صفحه‌ی هنرمند."""
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return

    items: list[Track] = context.chat_data.get("artist_view_tracks", [])
    try:
        index = int(query.data.split(":", 1)[1])
        track = items[index]
    except (ValueError, IndexError):
        await query.answer("این انتخاب دیگر معتبر نیست.", show_alert=True)
        return
    await query.answer()

    await query.edit_message_text(_track_line(track), parse_mode=ParseMode.HTML)
    try:
        await _download_and_send(context, query.message.chat_id, track)
    except Exception as exc:
        log.warning("دانلود یا ارسال برای %s ناموفق بود: %s", track.title, exc)


async def on_artist_album_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return

    albums: list[Album] = context.chat_data.get("artist_view_albums", [])
    try:
        index = int(query.data.split(":", 1)[1])
        album = albums[index]
    except (ValueError, IndexError):
        await query.answer("این انتخاب دیگر معتبر نیست.", show_alert=True)
        return
    await query.answer()

    await query.edit_message_text(f"💿 {album.title}")
    await _open_collection(context, query.message, album.sourceUrl or album.id)


async def on_artist_playlist_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return

    playlists: list[Playlist] = context.chat_data.get("artist_view_playlists", [])
    try:
        index = int(query.data.split(":", 1)[1])
        pl = playlists[index]
    except (ValueError, IndexError):
        await query.answer("این انتخاب دیگر معتبر نیست.", show_alert=True)
        return
    await query.answer()

    await query.edit_message_text(f"📃 {pl.title}")
    await _open_collection(context, query.message, pl.sourceUrl or pl.id)


async def _auto_send_release(
    application: Application,
    api: ApiClient,
    f: Follow,
    album: Album,
) -> bool:
    """
    تحویلِ خودکارِ یک انتشارِ تازه: کاورِ باکیفیت + لینکِ پلتفرم، بعد خودِ
    فایل‌ها (تک‌آهنگ یا کلِ آلبوم) با کیفیتِ خودکار.

    هیچ شکستی نباید انتشار را گم کند — اگر ارسالِ فایل‌ها نشد، لااقل همان خبرِ
    قدیمی با لینکِ پلتفرم می‌رسد تا کاربر خودش بتواند بگیرد. برگشتیِ تابع
    می‌گوید آیا اصلاً خبری به چت رسید — اگر نه، صداکننده «دیده‌شده» ثبت نمی‌کند
    تا در چکِ بعدی دوباره امتحان شود.
    """
    bot = application.bot
    badge = source_badge(album.source)
    platform = SOURCE_NAME.get(album.source, str(album.source))

    async def _announce(failed: bool = False) -> bool:
        """خبرِ انتشار + کاور + لینک؛ `failed` یعنی فایل‌ها نرسیدند و فقط خبر می‌دهیم."""
        text = (
            f"🆕 {badge} <b>{html.escape(f.artistName)}</b> یه اثر تازه منتشر کرد:\n"
            f"💿 <b>{html.escape(album.title)}</b>"
        )
        if album.sourceUrl:
            text += f'\n🔗 <a href="{html.escape(album.sourceUrl)}">لینک در {platform}</a>'
        if failed:
            text += (
                "\n⚠️ فرستادنِ فایل‌ها نشد — از لینک بالا بگیرش."
                if album.sourceUrl
                else "\n⚠️ فرستادنِ فایل‌ها نشد."
            )
        try:
            if album.artworkUrl:
                for url in artwork_at_most(album.artworkUrl, ARTWORK_EMBED):
                    if data := await api.raw_bytes(url):
                        try:
                            await _telegram_retry(
                                bot.send_photo,
                                f.chatId,
                                photo=data,
                                caption=text,
                                parse_mode=ParseMode.HTML,
                                read_timeout=UPLOAD_TIMEOUT,
                                write_timeout=UPLOAD_TIMEOUT,
                            )
                            return True
                        except Exception:
                            log.warning("فرستادن کاور انتشار با عکس نشد؛ با متن امتحان می‌شود", exc_info=True)
                            break
            await _telegram_retry(bot.send_message, f.chatId, text, parse_mode=ParseMode.HTML)
            return True
        except Exception:
            log.warning("خبرِ انتشارِ %s به %s نرسید", album.title, f.chatId, exc_info=True)
            return False

    try:
        resolved = await api.resolve_ref(album.sourceUrl or album.id)
    except Exception:
        resolved = None
        log.warning("باز کردنِ انتشارِ %s برای %s نشد", album.title, f.artistName, exc_info=True)

    tracks = resolved.tracks if resolved else []
    if not tracks:
        return await _announce(failed=True)

    announced = await _announce()

    context = application.context_types.context(application, chat_id=f.chatId)
    try:
        if len(tracks) == 1:
            await _download_and_send(context, f.chatId, tracks[0], AUTO_QUALITY)
        else:
            await _download_all(
                context, f.chatId, tracks[:MAX_BATCH_DOWNLOAD], AUTO_QUALITY, album=resolved
            )
    except Exception:
        # خودِ مسیرِ دانلود پیامِ خطا/لینکِ مستقیمش را در چت گذاشته؛ اینجا فقط
        # ثبت می‌شود تا در لاگِ فایل ردش بماند
        log.warning("ارسالِ خودکارِ %s کامل نشد", album.title, exc_info=True)
    return announced


async def _check_follows(application: Application) -> None:
    """
    حلقه‌ی پس‌زمینه: انتشارهای تازه‌ی هر هنرمندِ دنبال‌شده را پیدا و خودکار
    تحویل می‌دهد. چند کاربر ممکن است یک هنرمند را دنبال کنند — صفحه‌ی هنرمند
    فقط یک‌بار به‌ازای هر هنرمند گرفته می‌شود، نه هر ردیف.
    """
    api = _api_from_app(application)
    try:
        follows = await api.follows()
    except Exception as exc:
        log.warning("گرفتنِ لیستِ دنبال‌شده‌ها از سرور نشد: %s", exc)
        return
    if not follows:
        return

    cache: dict[str, ArtistDetail | None] = {}
    for f in follows:
        if f.artistSourceUrl not in cache:
            try:
                cache[f.artistSourceUrl] = await api.artist(f.artistSourceUrl)
            except Exception:
                cache[f.artistSourceUrl] = None

        detail = cache[f.artistSourceUrl]
        if detail is None or not detail.albums:
            continue

        latest = detail.albums[0]
        if f.lastReleaseId is None:
            # اولین چک: فقط پرکردنِ وضعیت، بدونِ ارسالِ تاریخچه‌ی قدیمی
            await api.mark_follow_seen(f.id, latest.id, latest.title)
            continue
        if latest.id == f.lastReleaseId:
            continue

        # قدیمی‌ترِ تازه‌ها اول، تا ترتیبِ پیام‌ها ترتیبِ واقعیِ انتشار باشد
        for album in reversed(new_releases(f.lastReleaseId, detail.albums)):
            delivered = await _auto_send_release(application, api, f, album)
            if delivered:
                await api.mark_follow_seen(f.id, album.id, album.title)
            else:
                # خبری به چت نرسید؛ ادامه دادن فقط شکستِ بعدی را هم می‌بلعد —
                # در چکِ بعدی از همین‌جا دوباره
                break


async def _migrate_follows(application: Application) -> None:
    """
    یک‌بار در بالا آمدن: ردیف‌های bot.dbِ نسخه‌های قدیمی به دیتابیسِ سرور
    منتقل می‌شوند تا وب هم همان‌ها را ببیند.

    اگر سرور پایین باشد یا ردیفی نرسد، پاک‌کردن انجام نمی‌شود — مهاجرت
    idempotent است (کلیکِ دوباره روی ردیفِ موجود خطا نیست) و در بالا آمدنِ
    بعدی از اول امتحان می‌شود.
    """
    legacy = await asyncio.to_thread(store.all_follows)
    if not legacy:
        return

    api = _api_from_app(application)
    moved = 0
    for f in legacy:
        try:
            await api.add_follow(
                f.chat_id,
                FollowRequest(
                    artistId=f.artist_id,
                    artistName=f.artist_name,
                    artistSourceUrl=f.artist_source_url,
                    source=f.source,
                    artworkUrl=f.artwork_url,
                    lastReleaseId=f.last_release_id,
                    lastReleaseTitle=f.last_release_title,
                ),
            )
            moved += 1
        except Exception:
            log.warning("مهاجرتِ دنبال‌کردنِ %s نشد", f.artist_name, exc_info=True)

    if moved == len(legacy):
        await asyncio.to_thread(store.clear_all)
        log.info("%d دنبال‌کردن قدیمی به سرور منتقل شد.", moved)


async def _follow_poll_loop(application: Application) -> None:
    """
    JobQueue داخلیِ PTB نیامده (وابسته به APScheduler است، در requirements
    نیست)؛ همان الگوی `jobs.sweep_loop` سمت سرور — یک تسکِ ساده که در
    `post_init` بالا می‌آید.
    """
    while True:
        try:
            await asyncio.sleep(FOLLOW_POLL_INTERVAL)
            await _check_follows(application)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("چک‌کردنِ دنبال‌شده‌ها ناموفق بود", exc_info=True)


async def _post_init(application: Application) -> None:
    """منوی «/» کنار جعبه‌ی پیام — تلگرام همین‌جا نگهش می‌دارد، نه سمت ما."""
    await application.bot.set_my_commands(
        [
            BotCommand("start", "شروع و منوی اصلی"),
            BotCommand("search", "جستجوی آهنگ، آلبوم یا هنرمند"),
            BotCommand("settings", "تنظیمات بات و کیفیت دانلود"),
            BotCommand("app", "ورود به مینی‌اپ و پلیر آنلاین"),
            BotCommand("vibe", "پیشنهاد آهنگ بر اساس حال‌وهوا (هوش مصنوعی)"),
            BotCommand("mix", "میکس روزانه هوشمند"),
            BotCommand("favorites", "آهنگ‌های محبوب و لایک‌شده"),
            BotCommand("help", "راهنما"),
            BotCommand("library", "دیدن/گرفتن دوباره‌ی دانلودهای قبلی"),
            BotCommand("quality", "تغییر کیفیت پیش‌فرض"),
            BotCommand("follow", "دنبال‌کردنِ هنرمند؛ انتشارِ تازه خودکار می‌رسد"),
            BotCommand("unfollow", "دیگر دنبال نکردنِ یک هنرمند"),
            BotCommand("following", "لیستِ هنرمندهای دنبال‌شده"),
            BotCommand("link", "وصل‌کردنِ این چت به نسخه‌ی وب"),
        ]
    )
    # اگر آدرس وب‌اپلیکیشن HTTPS ست شده باشد، دکمه منوی مینی‌اپ را فعال می‌کنیم
    if TELEGRAM_WEBAPP_URL and TELEGRAM_WEBAPP_URL.startswith("https://"):
        try:
            await application.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🎵 موزیک‌بازی",
                    web_app=WebAppInfo(url=TELEGRAM_WEBAPP_URL),
                )
            )
            log.info("دکمه منوی تلگرام مینی‌اپ با آدرس %s تنظیم شد.", TELEGRAM_WEBAPP_URL)
        except Exception as exc:
            log.warning("تنظیم دکمه منوی تلگرام مینی‌اپ ناموفق بود: %s", exc)

    # نامِ کاربری برای لینکِ عمیقی که وب نشان می‌دهد (t.me/<bot>?start=link_…)
    application.bot_data["username"] = (await application.bot.get_me()).username
    # ردیف‌های bot.dbِ قدیمی پیش از اولین چک به سرور می‌روند، وگرنه دنبال‌شده‌های
    # کاربر از نسخه‌ی قبل یک‌بار «تازه» حساب می‌شدند و اسپم می‌شد
    await _migrate_follows(application)
    application.bot_data["follow_task"] = asyncio.create_task(_follow_poll_loop(application))
    application.bot_data["outbox_task"] = asyncio.create_task(_outbox_loop(application))


async def _shutdown(application: Application) -> None:
    for key in ("follow_task", "outbox_task"):
        task: asyncio.Task | None = application.bot_data.get(key)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    await _api_from_app(application).aclose()
    await asyncio.to_thread(store.close)


def _api_from_app(application: Application) -> ApiClient:
    return application.bot_data["api"]


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        log.info("UNSTREAM_TELEGRAM_BOT_TOKEN ست نشده — بات غیرفعال می‌ماند.")
        sys.exit(0)

    # پایتون ۳.۱۴ دیگر لوپ را خودکار نمی‌سازد (asyncio.get_event_loop بدون
    # لوپِ جاری خطا می‌دهد)، و run_polling داخلی PTB 21.x هنوز به همان متکی
    # است — قبل از صدا زدنش خودمان یکی می‌سازیم و جاری‌اش می‌کنیم.
    asyncio.set_event_loop(asyncio.new_event_loop())

    # پیش‌فرضِ PTB (۵ ثانیه‌ی خواندن/نوشتن) برای آپلود فایل صوتی چند-مگابایتی
    # کوتاه است — send_audio/send_photo با شبکه‌ی معمولی همین‌جا TimedOut
    # می‌گرفت با اینکه خودِ فایل رسیده بود. media_write_timeout مخصوص
    # آپلودهاست؛ read_timeout هم باید بالا برود چون تلگرام بعد از آپلود قبل
    # از پاسخ دادن پردازش می‌کند. سقفِ واقعیِ آپلود اما اینجا نیست: خودِ
    # `_upload_audio` مهلتِ بازتری (UPLOAD_TIMEOUT) به فراخوانیِ خودش می‌دهد،
    # تا یک send_messageِ گیرکرده به‌خاطرِ آن پنج دقیقه معطل نماند.
    #
    # پروکسی روی *هر دو* کلاینت لازم است: PTB برای getUpdates کلاینتِ جدا
    # می‌سازد، و اگر فقط این یکی پروکسی داشته باشد بات اصلاً آپدیت نمی‌گیرد.
    request = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=30.0,
        read_timeout=90.0,
        write_timeout=90.0,
        media_write_timeout=180.0,
        proxy=TELEGRAM_PROXY,
    )
    updates_request = HTTPXRequest(
        connection_pool_size=4,
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=30.0,
        proxy=TELEGRAM_PROXY,
    )
    if TELEGRAM_PROXY:
        log.info("تلگرام از پروکسی می‌رود.")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .get_updates_request(updates_request)
        .concurrent_updates(True)
        .post_init(_post_init)
        .post_shutdown(_shutdown)
        .build()
    )
    app.add_error_handler(error_handler)
    app.bot_data["api"] = ApiClient()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("app", app_cmd))
    app.add_handler(CommandHandler("vibe", vibe_cmd))
    app.add_handler(CommandHandler("mix", mix_cmd))
    app.add_handler(CommandHandler("favorites", favorites_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("quality", quality_cmd))
    app.add_handler(CommandHandler("library", library_cmd))
    app.add_handler(CommandHandler("follow", follow_cmd))
    app.add_handler(CommandHandler("unfollow", unfollow_cmd))
    app.add_handler(CommandHandler("following", following_cmd))
    app.add_handler(CommandHandler("link", link_cmd))
    app.add_handler(CallbackQueryHandler(on_lyrics_pick, pattern=r"^lyr:[a-f0-9]{16}$"))
    app.add_handler(CallbackQueryHandler(on_favorite_pick, pattern=r"^fav:(add|del):"))
    app.add_handler(CallbackQueryHandler(on_fav_all, pattern=r"^fav:all$"))
    app.add_handler(CallbackQueryHandler(on_mix_all, pattern=r"^mix:all$"))
    app.add_handler(CallbackQueryHandler(on_zip_pick, pattern=r"^zip:"))
    app.add_handler(CallbackQueryHandler(on_split_pick, pattern=r"^split:(all|whole)$"))
    app.add_handler(CallbackQueryHandler(on_page_pick, pattern=r"^page:(track|cl|ba):\d+$"))
    app.add_handler(CallbackQueryHandler(on_noop, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(on_pick, pattern=r"^pick:\d+$"))
    app.add_handler(CallbackQueryHandler(on_download_all, pattern=r"^all$"))
    app.add_handler(CallbackQueryHandler(on_quality_pick, pattern=r"^q:"))
    app.add_handler(CallbackQueryHandler(on_library_pick, pattern=r"^lib:"))
    app.add_handler(CallbackQueryHandler(on_follow_pick, pattern=r"^followpick:\d+$"))
    app.add_handler(CallbackQueryHandler(on_unfollow_pick, pattern=r"^unfollow:"))
    app.add_handler(CallbackQueryHandler(on_mode_button, pattern=r"^mode:"))
    app.add_handler(CallbackQueryHandler(on_collection_pick, pattern=r"^cl:\d+$"))
    app.add_handler(CallbackQueryHandler(on_browse_artist_pick, pattern=r"^ba:\d+$"))
    app.add_handler(CallbackQueryHandler(on_artist_open, pattern=r"^au:"))
    app.add_handler(CallbackQueryHandler(on_artist_follow, pattern=r"^afollow:"))
    app.add_handler(CallbackQueryHandler(on_artist_section, pattern=r"^(att|aal|apl|ard|are):"))
    app.add_handler(CallbackQueryHandler(on_artist_track_pick, pattern=r"^tk:\d+$"))
    app.add_handler(CallbackQueryHandler(on_artist_album_pick, pattern=r"^ab:\d+$"))
    app.add_handler(CallbackQueryHandler(on_artist_playlist_pick, pattern=r"^pl:\d+$"))
    app.add_handler(InlineQueryHandler(on_inline_query))
    app.add_handler(ChosenInlineResultHandler(on_chosen_inline_result))
    app.add_handler(
        MessageHandler(
            filters.VOICE | filters.AUDIO | filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL,
            on_media,
        )
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("بات تلگرام بالا آمد.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
