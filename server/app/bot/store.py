"""
کشِ قدیمیِ بات — فقط برای مهاجرتِ یک‌باره.

دنبال‌کردنِ هنرمندها به دیتابیسِ سرور (`app/db.py`، جدول `follows`) منتقل شد تا
وب هم بتواند از همان‌جا هنرمند دنبال کند؛ بات حالا از طریقِ `/api/follows` با
همان جدول کار می‌کند. تنها کاری که این فایل می‌کند خواندنِ ردیف‌های باقی‌مانده
از bot.dbِ نسخه‌های قدیمی و هل‌دادنشان به سرور است (در `run._migrate_follows`)،
و بعد خالی‌کردنش.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass

from ..config import BOT_DB_PATH

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS follows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id             INTEGER NOT NULL,
    artist_id           TEXT NOT NULL,
    artist_name         TEXT NOT NULL,
    artist_source_url   TEXT NOT NULL,
    source              TEXT NOT NULL,
    artwork_url         TEXT,
    last_release_id     TEXT,
    last_release_title  TEXT,
    created_at          REAL NOT NULL,
    UNIQUE(chat_id, artist_id)
);

CREATE TABLE IF NOT EXISTS telegram_files (
    cache_key           TEXT PRIMARY KEY,
    file_id             TEXT NOT NULL,
    file_unique_id      TEXT,
    title               TEXT,
    artist              TEXT,
    duration_sec        INTEGER,
    quality             TEXT,
    job_id              TEXT,
    created_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS lyrics_cache (
    track_hash          TEXT PRIMARY KEY,
    title               TEXT,
    artist              TEXT,
    lyrics              TEXT NOT NULL,
    created_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id             INTEGER PRIMARY KEY,
    quality             TEXT NOT NULL,
    updated_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_cache (
    short_id            TEXT PRIMARY KEY,
    full_ref            TEXT NOT NULL,
    created_at          REAL NOT NULL
);
"""

_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        BOT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(BOT_DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        try:
            _conn.execute("PRAGMA journal_mode = WAL")
            _conn.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.OperationalError:
            pass
        _conn.executescript(SCHEMA)
        try:
            _conn.execute("ALTER TABLE telegram_files ADD COLUMN job_id TEXT")
            _conn.commit()
        except sqlite3.OperationalError:
            pass
        _conn.commit()
    return _conn


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


@dataclass
class LegacyFollow:
    id: int
    chat_id: int
    artist_id: str
    artist_name: str
    artist_source_url: str
    source: str
    artwork_url: str | None
    last_release_id: str | None
    last_release_title: str | None


def _row(r: sqlite3.Row) -> LegacyFollow:
    return LegacyFollow(
        id=r["id"],
        chat_id=r["chat_id"],
        artist_id=r["artist_id"],
        artist_name=r["artist_name"],
        artist_source_url=r["artist_source_url"],
        source=r["source"],
        artwork_url=r["artwork_url"],
        last_release_id=r["last_release_id"],
        last_release_title=r["last_release_title"],
    )


def all_follows() -> list[LegacyFollow]:
    with _lock:
        return [_row(r) for r in _db().execute("SELECT * FROM follows").fetchall()]


def clear_all() -> None:
    """ردیف‌ها سرور نشسته‌اند — این‌جا دیگر جایی ندارند."""
    with _lock:
        conn = _db()
        conn.execute("DELETE FROM follows")
        conn.commit()


# ---------- کش فایل‌های تلگرام (File ID Cache) ----------


def save_telegram_file(
    cache_key: str,
    file_id: str,
    file_unique_id: str | None = None,
    title: str = "",
    artist: str = "",
    duration_sec: int | None = None,
    quality: str | None = None,
    job_id: str | None = None,
) -> None:
    """ذخیره شناسه فایل ارسال‌شده در تلگرام برای تحویل فوری دفعات بعدی."""
    if not cache_key or not file_id:
        return
    with _lock:
        conn = _db()
        conn.execute(
            """INSERT OR REPLACE INTO telegram_files
               (cache_key, file_id, file_unique_id, title, artist, duration_sec, quality, job_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cache_key,
                file_id,
                file_unique_id,
                title,
                artist,
                duration_sec,
                quality,
                job_id,
                time.time(),
            ),
        )
        conn.commit()


def get_telegram_file(cache_key: str) -> dict | None:
    """دریافت اطلاعات فایل کش‌شده بر اساس کلید ترک و کیفیت."""
    if not cache_key:
        return None
    with _lock:
        row = _db().execute(
            "SELECT file_id, file_unique_id, title, artist, duration_sec, quality, job_id FROM telegram_files WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def delete_telegram_file(cache_key: str) -> None:
    """حذف ردیف کش در صورت نامعتبر بودن file_id."""
    if not cache_key:
        return
    with _lock:
        conn = _db()
        conn.execute("DELETE FROM telegram_files WHERE cache_key = ?", (cache_key,))
        conn.commit()


# ---------- کش متن ترانه (Lyrics Cache) ----------


def save_lyrics(track_hash: str, lyrics: str, title: str = "", artist: str = "") -> None:
    """ذخیره متن ترانه تمیزشده برای نمایش تعاملی دکمه تلگرام."""
    if not track_hash or not lyrics:
        return
    with _lock:
        conn = _db()
        conn.execute(
            """INSERT OR REPLACE INTO lyrics_cache
               (track_hash, title, artist, lyrics, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (track_hash, title, artist, lyrics, time.time()),
        )
        conn.commit()


def get_lyrics(track_hash: str) -> dict | None:
    """دریافت متن ترانه ذخیره‌شده بر اساس هش شناسه ترک."""
    if not track_hash:
        return None
    with _lock:
        row = _db().execute(
            "SELECT track_hash, title, artist, lyrics FROM lyrics_cache WHERE track_hash = ?",
            (track_hash,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


# ---------- تنظیمات کاربر (Chat Settings) ----------


def save_chat_quality(chat_id: int, quality: str) -> None:
    """ذخیره کیفیت انتخابی کاربر برای پایداری پس از ری‌استارت بات."""
    if chat_id is None or not quality:
        return
    try:
        cid = int(chat_id)
    except (ValueError, TypeError):
        return
    with _lock:
        conn = _db()
        conn.execute(
            """INSERT OR REPLACE INTO chat_settings (chat_id, quality, updated_at)
               VALUES (?, ?, ?)""",
            (cid, quality, time.time()),
        )
        conn.commit()


def get_chat_quality(chat_id: int) -> str | None:
    """دریافت کیفیت دانلود انتخابی کاربر."""
    if chat_id is None:
        return None
    try:
        cid = int(chat_id)
    except (ValueError, TypeError):
        return None
    with _lock:
        row = _db().execute(
            "SELECT quality FROM chat_settings WHERE chat_id = ?",
            (cid,),
        ).fetchone()
        if row is None:
            return None
        return str(row["quality"])


# ---------- کش کوتاه‌سازی شناسه/لینک برای دکمه‌های تلگرام (Ref Cache) ----------


def save_ref(short_id: str, full_ref: str) -> None:
    """ذخیره شناسه کامل برای دکمه‌هایی با callback_data بیش از ۶۴ بایت."""
    if not short_id or not full_ref:
        return
    with _lock:
        conn = _db()
        conn.execute(
            """INSERT OR REPLACE INTO ref_cache (short_id, full_ref, created_at)
               VALUES (?, ?, ?)""",
            (short_id, full_ref, time.time()),
        )
        conn.commit()


def get_ref(short_id: str) -> str | None:
    """بازیابی شناسه کامل از روی هش کوتاه."""
    if not short_id:
        return None
    with _lock:
        row = _db().execute(
            "SELECT full_ref FROM ref_cache WHERE short_id = ?",
            (short_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row["full_ref"])


def safe_callback_ref(ref: str, max_safe_len: int = 40) -> str:
    """
    بررسی طول شناسه/لینک برای قرارگیری در callback_data تلگرام (سقف ۶۴ بایت).
    اگر طول کم و بدون کاراکتر جداکننده باشد همان برمی‌گردد؛
    در غیر این صورت هش ۱۶ کاراکتری ساخته و در جدول ref_cache کش می‌شود.
    """
    if not ref:
        return ""
    encoded = ref.encode("utf-8")
    if len(encoded) <= max_safe_len and ":" not in ref:
        return ref
    h = "h_" + hashlib.sha256(encoded).hexdigest()[:16]
    save_ref(h, ref)
    return h


def resolve_callback_ref(short_or_ref: str) -> str:
    """تبدیل شناسه کوتاه (h_...) به مقدار اصلی یا برگرداندن خود شناسه."""
    if not short_or_ref:
        return ""
    if short_or_ref.startswith("h_"):
        found = get_ref(short_or_ref)
        if found:
            return found
    return short_or_ref

