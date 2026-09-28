"""
لایه‌ی ماندگاری روی SQLite.

قبلاً صف فقط در حافظه بود: با هر ری‌استارت سرور، هم تاریخچه می‌پرید و هم
فایل‌های روی دیسک بی‌صاحب می‌شدند (هیچ‌کس نمی‌دانست کدام فایل مال کدام ترک است).
حالا هر جاب یک ردیف است، و «کتابخانه» چیزی نیست جز جاب‌های موفقی که فایلشان هست.

نوشتن‌ها ریزند و با یک قفل سریالایز می‌شوند — استخر اتصال ارزشش را ندارد.
درصد پیشرفت عمداً ذخیره نمی‌شود؛ صدها نوشتن در ثانیه برای عددی که با ری‌استارت
بی‌معنی می‌شود.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import DB_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    track_id     TEXT NOT NULL,
    track_json   TEXT NOT NULL,
    search_text  TEXT NOT NULL DEFAULT '',
    quality      TEXT NOT NULL,
    status       TEXT NOT NULL,
    error        TEXT,
    warning      TEXT,
    format       TEXT,
    path         TEXT,
    lyrics_path  TEXT,
    bytes        INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    finished_at  REAL,
    valence      REAL,
    energy       REAL,
    loudness     REAL,
    peak         REAL,
    favorite     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_track   ON jobs(track_id, quality, status);

-- تاریخچه‌ی پخش. هر بار که ترکی واقعاً پخش می‌شود یک ردیف می‌گیرد — نه خودِ
-- ترک، بلکه *رویدادِ* گوش‌دادن. متادیتا (عنوان/هنرمند/کاور) عمداً اینجا کپی
-- می‌شود و نه فقط شناسه: اگر فایل بعداٌ از کتابخانه پاک شود، تاریخچه و آمار
-- نباید با آن بمیرند. `seconds` چند ثانیه واقعاً گوش‌شده است، برای وقتی که
-- کاربر وسط ترک رد می‌شود.
CREATE TABLE IF NOT EXISTS plays (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL,
    track_id    TEXT NOT NULL,
    title       TEXT NOT NULL,
    artist      TEXT NOT NULL,
    album       TEXT,
    artwork_url TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    seconds     INTEGER NOT NULL DEFAULT 0,
    played_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plays_at    ON plays(played_at DESC);
CREATE INDEX IF NOT EXISTS idx_plays_track ON plays(track_id);

-- پلی‌لیست‌های خودِ کاربر. دو نوع‌اند و عمداً در یک جدول می‌نشینند: تفاوتشان
-- فقط در این است که «دستی» فهرست عضوها را در playlist_items نگه می‌دارد و
-- «هوشمند» به‌جای فهرست، یک قانون (rule_json) دارد که موقع خواندن اجرا می‌شود.
CREATE TABLE IF NOT EXISTS playlists (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'manual',
    rule_json  TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id TEXT NOT NULL,
    job_id      TEXT NOT NULL,
    position    INTEGER NOT NULL,
    added_at    REAL NOT NULL,
    PRIMARY KEY (playlist_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_pl_items ON playlist_items(playlist_id, position);

-- چتی که دکمه‌ی «فرستادن به تلگرام» در وب به آن می‌فرستد. عمداً تک‌ردیفی است:
-- این اپ کاربر ندارد، پس «چتِ من» یک چیز است و وصل‌کردنِ دوباره جایش را می‌گیرد.
CREATE TABLE IF NOT EXISTS telegram_chat (
    chat_id   INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    linked_at REAL NOT NULL
);

-- صفِ کارهایی که وب برای بات گذاشته. بات پروسه‌ی جداست (شاید کانتینرِ جدا) و
-- توکن فقط دست اوست، پس سرور خودش چیزی به تلگرام نمی‌فرستد — فقط ردیف
-- می‌گذارد و بات با long-poll برشان می‌دارد. ماندگار است تا اگر بات موقع
-- کلیکِ کاربر پایین بود، بعدِ بالا آمدن همان کار را انجام دهد.
CREATE TABLE IF NOT EXISTS telegram_outbox (
    id         TEXT PRIMARY KEY,
    chat_id    INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    title      TEXT NOT NULL,
    status     TEXT NOT NULL,
    error      TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tg_outbox ON telegram_outbox(status, created_at);

-- آینه‌ی محلیِ کاورها. آدرسِ اصلی از CDNِ همان کاتالوگ می‌آید (اپل، اسپاتیفای،
-- دیزر) و آن‌ها روی اینترنتِ ملی در دسترس نیستند — یعنی موقع قطعیِ بین‌الملل
-- کتابخانه‌ای که کاملاً روی دیسک است، بی‌کاور و شکسته دیده می‌شود. هر کاوری که
-- یک‌بار دیده شده اینجا ثبت و روی دیسک ذخیره می‌شود.
--
-- `fetched_at` خالی یعنی فقط آدرسش را می‌شناسیم و هنوز نگرفته‌ایم؛ خودِ بایت‌ها
-- در فایل‌اند نه در دیتابیس (BLOBِ چندصدکیلوبایتی، هر کوئریِ دیگر را کند می‌کند).
CREATE TABLE IF NOT EXISTS artwork (
    sha        TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    mime       TEXT,
    bytes      INTEGER NOT NULL DEFAULT 0,
    seen_at    REAL NOT NULL,
    fetched_at REAL
);
CREATE INDEX IF NOT EXISTS idx_art_pending ON artwork(fetched_at, seen_at DESC);

-- هنرمندهای دنبال‌شده برای اطلاعِ انتشارِ تازه. مقصد همیشه همان چتِ وصل‌شده‌ی
-- تلگرام است، ولی ردیف‌ها (چت، هنرمند) نگه داشته می‌شوند نه صرفاً هنرمند: اگر
-- چت عوض شود، دنبال‌شده‌های چتِ قبلی نباید به چتِ تازه سرازیر شوند. منبعِ
-- واحدِ حقیقت همین‌جاست — هم وب از اینجا دنبال می‌کند، هم بات؛ دیتابیسِ محلیِ
-- بات فقط برای مهاجرتِ یک‌باره‌ی ردیف‌های قدیمی خوانده می‌شود.
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

-- کشِ کاتالوگ. سه جدول چون سه سؤالِ متفاوت‌اند و آفلاین هر سه باید جواب بدهند:
--
--   catalog_search — «همان جستجو را دوباره بزن» (پاسخِ کامل و دست‌نخورده)
--   catalog_ref    — «همان صفحه‌ی آلبوم/هنرمند را باز کن»
--   catalog_entity — «چیزی بگرد که قبلاً *ندیده‌ای* اما ردیفش از جای دیگری آمده»
--
-- بدونِ سومی، آفلاین فقط عیناً همان عبارت‌های قبلی جواب می‌داد؛ با آن، هر ترک و
-- آلبومی که از هر مسیری یک‌بار از جلوی چشم رد شده قابلِ جستجو می‌ماند.
CREATE TABLE IF NOT EXISTS catalog_search (
    query     TEXT PRIMARY KEY,
    payload   TEXT NOT NULL,
    cached_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS catalog_ref (
    ref       TEXT NOT NULL,
    kind      TEXT NOT NULL,
    payload   TEXT NOT NULL,
    cached_at REAL NOT NULL,
    PRIMARY KEY (ref, kind)
);
CREATE TABLE IF NOT EXISTS catalog_entity (
    id          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    source      TEXT NOT NULL,
    search_text TEXT NOT NULL,
    payload     TEXT NOT NULL,
    seen_at     REAL NOT NULL,
    PRIMARY KEY (id, kind)
);
CREATE INDEX IF NOT EXISTS idx_entity_kind ON catalog_entity(kind, seen_at DESC);

-- کش کاندیداهای حل‌شده برای هر ترک — تا جستجوی مجدد ساندکلاد/یوتیوب به صفر میلی‌ثانیه برسد
CREATE TABLE IF NOT EXISTS resolved_candidates (
    track_id    TEXT PRIMARY KEY,
    candidates  TEXT NOT NULL,
    resolved_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resolved_cand_at ON resolved_candidates(resolved_at DESC);
"""

# ستون‌هایی که بعد از اولین نسخه اضافه شدند. CREATE TABLE IF NOT EXISTS روی
# دیتابیسِ از قبل موجود کاری نمی‌کند، پس هر ستونِ تازه باید اینجا هم اضافه شود —
# با ALTER TABLE ایمن (اگر ستون از قبل بود، خطا را بی‌صدا رد می‌کنیم).
_NEW_COLUMNS = (
    ("valence", "REAL"),
    ("energy", "REAL"),
    ("loudness", "REAL"),
    ("peak", "REAL"),
    # نسخه‌ای که کاربر دستی انتخاب کرده. تا وقتی جاب همیشه بلافاصله اجرا می‌شد
    # فقط در حافظه لازم بود؛ با آمدنِ وضعیتِ `deferred` ممکن است روزها (و یک
    # ری‌استارت) بینِ انتخاب و اجرا فاصله بیفتد و آن انتخاب نباید گم شود.
    ("candidate_url", "TEXT"),
    # لایکِ کاربر — ستون روی خودِ جاب است نه جدول جدا: هر جاب یک فایل است و
    # «علاقه‌مندی» صفتِ همان فایل است، نه رابطه‌ی جدا.
    ("favorite", "INTEGER NOT NULL DEFAULT 0"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for name, sql_type in _NEW_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}")
        except sqlite3.OperationalError:
            pass  # ستون از قبل هست


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        # WAL: خواندنِ کتابخانه نباید پشت نوشتنِ یک جاب صف بکشد
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.executescript(SCHEMA)
        _migrate(_conn)
        _conn.commit()
    return _conn


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _exec(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    with _lock:
        conn = connect()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur


def _query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return connect().execute(sql, params).fetchall()


# ---------- جاب‌ها ----------


def _search_text(track: Any) -> str:
    """ستونی که جستجوی کتابخانه رویش می‌نشیند."""
    return f"{track.title} {track.artist} {track.album or ''}".lower()


# `\` به‌عنوان کاراکترِ فرار انتخاب شده و در هر کوئریِ LIKE هم صریح اعلام
# می‌شود؛ SQLite بدونِ ESCAPE هیچ فرارِ پیش‌فرضی ندارد.
_LIKE_ESCAPE = "\\"


def _like(text: str) -> str:
    """
    متنِ کاربر را به یک الگوی LIKEِ *تحت‌اللفظی* تبدیل می‌کند.

    پارامترها bind می‌شوند پس مسئله تزریق نیست — مسئله این است که `%` و `_`
    برای خودِ LIKE معنی دارند. بدون فرار دادنشان، جستجوی «_» در کتابخانه کلِ
    کتابخانه را برمی‌گرداند (هر کاراکتری با `_` مچ می‌شود) و «%» هم همین‌طور:
    کاربر دنبال یک آهنگ می‌گشت و همه‌چیز را می‌گرفت.
    """
    escaped = (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def insert_job(
    job_id: str,
    track: Any,
    quality: str,
    status: str,
    created_at: float,
    candidate_url: str | None = None,
) -> None:
    _exec(
        """INSERT OR REPLACE INTO jobs
           (id, track_id, track_json, search_text, quality, status, created_at, candidate_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            track.id,
            track.model_dump_json(),
            _search_text(track),
            quality,
            status,
            created_at,
            candidate_url,
        ),
    )


_UPDATABLE = (
    "status",
    "error",
    "warning",
    "format",
    "path",
    "lyrics_path",
    "bytes",
    "finished_at",
    "valence",
    "energy",
    "loudness",
    "peak",
)


def update_job(job_id: str, **fields: Any) -> None:
    """فقط ستون‌های شناخته‌شده — بقیه (مثلاً percent) بی‌سروصدا نادیده می‌روند."""
    known = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not known:
        return
    assignments = ", ".join(f"{k} = ?" for k in known)
    _exec(
        f"UPDATE jobs SET {assignments} WHERE id = ?",
        (*known.values(), job_id),
    )


def update_track(job_id: str, track: Any) -> None:
    """
    متادیتای ترکِ یک جاب.

    جدا از `update_job` است چون `track_json` ستونِ وضعیت نیست: فقط وقتی عوض
    می‌شود که درخواستِ تازه چیزی بیاورد که موقع دانلود نداشتیم — و آن‌وقت
    `search_text` هم باید با آن هماهنگ بماند.
    """
    _exec(
        "UPDATE jobs SET track_json = ?, search_text = ? WHERE id = ?",
        (track.model_dump_json(), _search_text(track), job_id),
    )


def delete_job(job_id: str) -> None:
    _exec("DELETE FROM jobs WHERE id = ?", (job_id,))
    # عضوِ پلی‌لیستی که فایلش رفته، ردیفِ مرده است — پلی‌لیست باید کوتاه شود،
    # نه اینکه به چیزی اشاره کند که دیگر نیست
    _exec("DELETE FROM playlist_items WHERE job_id = ?", (job_id,))


def get_job(job_id: str) -> sqlite3.Row | None:
    rows = _query("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return rows[0] if rows else None


def find_ready(track_id: str, quality: str) -> sqlite3.Row | None:
    """همین ترک با همین کیفیت، از قبل و با موفقیت. مبنای «دوباره دانلود نکن»."""
    rows = _query(
        """SELECT * FROM jobs
           WHERE track_id = ? AND quality = ? AND status = 'ready' AND path IS NOT NULL
           ORDER BY created_at DESC LIMIT 1""",
        (track_id, quality),
    )
    return rows[0] if rows else None


def find_any_ready(
    track_id: str, preferred_quality: str | None = None
) -> sqlite3.Row | None:
    """هر فایلِ آماده‌ای از همین ترک در کتابخانه، با بالاترین کیفیت ممکن."""
    if preferred_quality:
        row = find_ready(track_id, preferred_quality)
        if row and row["path"] and Path(row["path"]).exists():
            return row

    rows = _query(
        """SELECT * FROM jobs
           WHERE track_id = ? AND status = 'ready' AND path IS NOT NULL
           ORDER BY
             CASE quality
               WHEN 'flac' THEN 7
               WHEN 'original' THEN 6
               WHEN '320' THEN 5
               WHEN 'opus' THEN 4
               WHEN 'm4a' THEN 3
               WHEN '192' THEN 2
               WHEN '128' THEN 1
               ELSE 0
             END DESC,
             created_at DESC""",
        (track_id,),
    )
    for r in rows:
        if r["path"] and Path(r["path"]).exists():
            return r
    return rows[0] if rows else None


def get_resolved_candidates(track_id: str) -> list[dict] | None:
    """دریافت کاندیداهای کش‌شده برای یک ترک از دیتابیس."""
    rows = _query("SELECT candidates FROM resolved_candidates WHERE track_id = ?", (track_id,))
    if not rows:
        return None
    try:
        return json.loads(rows[0]["candidates"])
    except Exception:
        return None


def put_resolved_candidates(
    track_id: str, candidates: list[dict], resolved_at: float | None = None
) -> None:
    """ذخیره‌ی کاندیداهای حل‌شده برای استفاده مجدد."""
    if resolved_at is None:
        resolved_at = time.time()
    payload = json.dumps(candidates)
    _exec(
        """INSERT OR REPLACE INTO resolved_candidates (track_id, candidates, resolved_at)
           VALUES (?, ?, ?)""",
        (track_id, payload, resolved_at),
    )


def delete_resolved_candidates(track_id: str) -> None:
    """حذف کاندیداهای کش‌شده (مثلاً در صورت نامعتبر شدن لینک)."""
    _exec("DELETE FROM resolved_candidates WHERE track_id = ?", (track_id,))


def ready_jobs() -> list[sqlite3.Row]:
    """برای هیدریت کردن حافظه موقع بالا آمدن سرور."""
    return _query("SELECT * FROM jobs WHERE status = 'ready' ORDER BY created_at DESC")


def mark_interrupted() -> int:
    """
    جابی که موقع خاموش شدن سرور نیمه‌کاره بوده هیچ‌وقت خودش تمام نمی‌شود.
    به‌جای اینکه برای همیشه «در حال دانلود» بماند، صریح شکست‌خورده اعلامش می‌کنیم.

    زمان از پایتون می‌آید نه از strftime: بقیه‌ی ستون‌های زمانی float اپاکِ
    پایتون‌اند و strftime رشته می‌دهد. اینجا affinity ستون نجاتش می‌داد، ولی
    تکیه کردن به تبدیل ضمنیِ SQLite برای ستونی که مستقیم با time.time() مقایسه
    می‌شود، ریسکِ بی‌دلیل است.
    """
    cur = _exec(
        """UPDATE jobs SET status = 'error', error = ?, finished_at = ?
           WHERE status NOT IN ('ready', 'error', 'canceled', 'deferred')""",
        ("سرور موقع دانلود ری‌استارت شد — دوباره تلاش کن", time.time()),
    )
    return cur.rowcount


def deferred_jobs() -> list[sqlite3.Row]:
    """
    کارهایی که منتظرِ برگشتنِ اینترنتِ بین‌الملل‌اند — قدیمی‌ترین اول.

    برخلاف بقیه‌ی وضعیت‌های غیرنهایی، `deferred` از ری‌استارت جان سالم به در
    می‌برد (به `mark_interrupted` بالا نگاه کن): قطعیِ اینترنت ممکن است چند روز
    طول بکشد و در آن مدت سرور بارها بالا و پایین می‌شود. صفی که با هر
    ری‌استارت خالی شود، اصلاً صف نیست.
    """
    return _query(
        "SELECT * FROM jobs WHERE status = 'deferred' ORDER BY created_at LIMIT 200"
    )


# ---------- کتابخانه ----------


def library(query: str = "", limit: int = 50, offset: int = 0) -> tuple[list[sqlite3.Row], int, int]:
    """(ردیف‌ها، تعداد کل، مجموع حجم) — فیلترِ متنی روی عنوان/هنرمند/آلبوم."""
    where = "status = 'ready' AND path IS NOT NULL"
    params: tuple = ()
    if query.strip():
        where += f" AND search_text LIKE ? ESCAPE '{_LIKE_ESCAPE}'"
        params = (_like(query.strip().lower()),)

    head = _query(f"SELECT COUNT(*) c, COALESCE(SUM(bytes), 0) b FROM jobs WHERE {where}", params)[0]
    # play_count زیرکوئری است نه JOIN: با LEFT JOIN و GROUP BY ساختارِ ردیف‌ها
    # عوض می‌شد و prune سمتِ main.py که row["path"] می‌خواند به هم می‌ریخت
    rows = _query(
        f"""SELECT *,
                   (SELECT COUNT(*) FROM plays p WHERE p.job_id = jobs.id) AS play_count,
                   (SELECT MAX(p.played_at) FROM plays p WHERE p.job_id = jobs.id) AS last_played_at
            FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    )
    return rows, int(head["c"]), int(head["b"])


def expired_files(cutoff: float) -> list[sqlite3.Row]:
    """جاب‌های موفقی که فایلشان از عمر مجاز گذشته."""
    return _query(
        "SELECT * FROM jobs WHERE status = 'ready' AND path IS NOT NULL AND created_at < ?",
        (cutoff,),
    )


def expired_failures(cutoff: float) -> list[str]:
    rows = _query(
        "SELECT id FROM jobs WHERE status IN ('error','canceled') AND COALESCE(finished_at, created_at) < ?",
        (cutoff,),
    )
    return [r["id"] for r in rows]


def known_paths() -> set[str]:
    """هر مسیری که دیتابیس می‌شناسد — بقیه‌ی فایل‌های پوشه یتیم‌اند."""
    paths: set[str] = set()
    for row in _query("SELECT path, lyrics_path FROM jobs WHERE path IS NOT NULL"):
        paths.add(row["path"])
        if row["lyrics_path"]:
            paths.add(row["lyrics_path"])
    return paths


# ---------- پخش‌ها، علاقه‌مندی‌ها و آمار ----------


def record_play(
    job_id: str,
    track_id: str,
    title: str,
    artist: str,
    album: str | None,
    artwork_url: str | None,
    duration_ms: int,
    seconds: int,
    played_at: float,
) -> None:
    _exec(
        """INSERT INTO plays
           (job_id, track_id, title, artist, album, artwork_url, duration_ms, seconds, played_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, track_id, title, artist, album, artwork_url, duration_ms, seconds, played_at),
    )


def set_favorite(job_id: str, favorite: bool) -> bool:
    """False برمی‌گردد اگر جابی با این شناسه نبود."""
    cur = _exec(
        "UPDATE jobs SET favorite = ? WHERE id = ?",
        (1 if favorite else 0, job_id),
    )
    return bool(cur.rowcount)


def favorite_jobs() -> list[sqlite3.Row]:
    """
    ترک‌های لایک‌شده، تازه‌ترین اول — برای نمایشِ «علاقه‌مندی‌ها».

    `play_count` با همان زیرکوئریِ کتابخانه می‌آید تا مرتب‌سازیِ «بیشترین‌ها»
    در این نما هم کار کند.
    """
    return _query(
        """SELECT *,
                  (SELECT COUNT(*) FROM plays p WHERE p.job_id = jobs.id) AS play_count,
                  (SELECT MAX(p.played_at) FROM plays p WHERE p.job_id = jobs.id) AS last_played_at
           FROM jobs
           WHERE favorite = 1 AND status = 'ready' AND path IS NOT NULL
           ORDER BY created_at DESC"""
    )


def recent_moods(since: float, limit: int) -> list[sqlite3.Row]:
    """
    حس‌وحالِ بیشترین‌های گوش‌داده‌شده — برای ساختِ میکس وقتی لایکی در کار نیست.

    جدولِ پخش‌ها خودش والانس ندارد، پس از روی جابِ هر پخش خوانده می‌شود؛ جاب‌های
    تحلیل‌نشده (بدونِ والانس) اصلاً وارد نمی‌شوند، چون مرکزِ حسیِ نامعلوم فقط
    نویز به انتخاب می‌دهد.
    """
    return _query(
        """SELECT j.valence AS valence, j.energy AS energy, COUNT(*) AS plays
           FROM plays p JOIN jobs j ON j.id = p.job_id
           WHERE p.played_at >= ? AND j.valence IS NOT NULL
           GROUP BY j.id ORDER BY plays DESC LIMIT ?""",
        (since, limit),
    )


def recent_plays(limit: int) -> list[sqlite3.Row]:
    """تاریخچه‌ی پخش — تازه‌ترین اول."""
    return _query("SELECT * FROM plays ORDER BY played_at DESC LIMIT ?", (limit,))


def play_totals(since: float) -> tuple[int, int, int]:
    """(تعداد پخش، مجموع ثانیه‌های گوش‌شده، تعداد ترک‌های متفاوت) از یک زمان به بعد."""
    row = _query(
        """SELECT COUNT(*) c, COALESCE(SUM(seconds), 0) s,
                  COUNT(DISTINCT track_id) u
           FROM plays WHERE played_at >= ?""",
        (since,),
    )[0]
    return int(row["c"]), int(row["s"]), int(row["u"])


def top_tracks(since: float, limit: int) -> list[sqlite3.Row]:
    """
    بیشترین‌های یک بازه، گروه‌شده بر اساسِ ترک.

    یک ترک ممکن است چند جاب داشته باشد (دو کیفیت)، پس گروه‌بندی روی track_id
    است نه job_id — وگرنه همان آهنگ دو بار در صدر می‌نشست.

    ادغامِ فراتر از track_id: همان آهنگ از دو کاتالوگ دو شناسه دارد
    («itunes:track:…» و «deezer:track:…») و هنرمندش هم با دو نگارشِ همکاری
    می‌آید. کلیدِ ادغام، عنوانِ نرمال + `_artist_key` است — همان قاعده‌ی
    ردیفِ هنرمندان. نمایش نام/کاور از نگارشی است که بیشترین پخش را داشته.
    """
    rows = _query(
        """SELECT track_id, title, artist, album, artwork_url,
                  COUNT(*) AS plays, COALESCE(SUM(seconds), 0) AS seconds,
                  MAX(played_at) AS last_at
           FROM plays WHERE played_at >= ?
           GROUP BY track_id
           ORDER BY plays DESC, last_at DESC LIMIT ?""",
        (since, limit * 3),
    )

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (
            re.sub(r"\s+", " ", (r["title"] or "").strip().lower()),
            _artist_key(r["artist"] or ""),
        )
        if bucket := merged.get(key):
            bucket["plays"] += int(r["plays"])
            bucket["seconds"] += int(r["seconds"])
            bucket["last_at"] = max(bucket["last_at"], float(r["last_at"]))
            # نمایش: ترک/هنرمندِ پخش‌بیشتر؛ کاور را هم اگر نداشتیم پر کن
            if int(r["plays"]) > bucket["name_plays"]:
                bucket.update(
                    name_plays=int(r["plays"]),
                    track_id=r["track_id"],
                    title=r["title"],
                    artist=r["artist"],
                    album=r["album"],
                )
            if not bucket["artwork_url"] and r["artwork_url"]:
                bucket["artwork_url"] = r["artwork_url"]
        else:
            merged[key] = {
                "track_id": r["track_id"],
                "title": r["title"],
                "artist": r["artist"],
                "album": r["album"],
                "artwork_url": r["artwork_url"],
                "name_plays": int(r["plays"]),
                "plays": int(r["plays"]),
                "seconds": int(r["seconds"]),
                "last_at": float(r["last_at"]),
            }

    ranked = sorted(merged.values(), key=lambda m: (-m["plays"], -m["last_at"]))[:limit]
    return [  # sqlite3.Row نیست ولی اندیسِ رشته‌ای پایین لازم است، نه بیشتر
        {
            "track_id": m["track_id"],
            "title": m["title"],
            "artist": m["artist"],
            "album": m["album"],
            "artwork_url": m["artwork_url"],
            "plays": m["plays"],
            "seconds": m["seconds"],
            "last_at": m["last_at"],
        }
        for m in ranked
    ]


def top_artists(since: float, limit: int) -> list[sqlite3.Row]:
    """
    بیشترین‌های هنرمند — با ادغامِ جداکننده‌ها.

    یک همکاریِ مشترک از پلتفرم‌های مختلف با جداکننده‌های ناهمسان می‌آید
    («A, B» از اسپاتیفای و «A & B» از اپل). گروه‌بندیِ خام روی رشته‌ی artist
    همین یک نفر را دو ردیف می‌کند. این‌جا جداکننده‌ها نرمال می‌شوند تا ردیف
    واحدی برگردد؛ نمایش نام، شکلِ رایج‌ترین نگارشِ خودش را نگه می‌دارد.
    """
    rows = _query(
        """SELECT artist, COUNT(*) AS plays, COALESCE(SUM(seconds), 0) AS seconds
           FROM plays WHERE played_at >= ?
           GROUP BY artist ORDER BY plays DESC LIMIT ?""",
        (since, limit * 3),
    )

    merged: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = _artist_key(r["artist"])
        if bucket := merged.get(key):
            bucket["plays"] += int(r["plays"])
            bucket["seconds"] += int(r["seconds"])
            # نامِ نمایشی: نگارشی که بیشترین پخش را داشته — احتمالاً آشناترین
            if int(r["plays"]) > bucket["name_plays"]:
                bucket["name"], bucket["name_plays"] = r["artist"], int(r["plays"])
        else:
            merged[key] = {
                "artist": r["artist"],
                "name_plays": int(r["plays"]),
                "plays": int(r["plays"]),
                "seconds": int(r["seconds"]),
            }

    ranked = sorted(merged.values(), key=lambda m: (-m["plays"], -m["seconds"]))[:limit]
    return [  # sqlite3.Row نیست ولی اندیسِ رشته‌ای همین‌جا لازم است، نه بیشتر
        {"artist": m["artist"], "plays": m["plays"], "seconds": m["seconds"]}  # type: ignore[misc]
        for m in ranked
    ]


# جداکننده‌های ناهمسانی که پلتفرم‌ها برای «همکاری» می‌گذارند
_ARTIST_SEP = re.compile(r"\s*[,;&/]\s*|\s+x\s+|\s+×\s+")


def _artist_key(artist: str) -> str:
    """
    کلیدِ ادغام: جداکننده‌ها نرمال، بی‌توجه به بزرگ/کوچکیِ حروف و ترتیبِ
    اعضا — «A, B» و «B & A» از دو پلتفرم یک همکاری‌اند.
    """
    return ", ".join(sorted(p.strip().lower() for p in _ARTIST_SEP.split(artist) if p.strip()))


# فاصله‌ی مربعیِ حس‌وحال در بازه‌ی [0, 1]×[0, 1] حداکثر ۲ است؛ این پاداش یعنی
# یک لایک معادلِ «کمی نزدیک‌تر بودن به مرکزِ حسی» ارزش دارد — نه آن‌قدر که
# لایک‌های بی‌ربط کلِ میکس را ببلعند، نه آن‌قدر کم که اصلاً اثر نکنند.
_FAVORITE_BONUS = 0.35


def daily_mix(
    center: tuple[float, float] | None,
    exclude_ids: set[str],
    limit: int,
) -> list[sqlite3.Row]:
    """
    میکسِ روزانه: نزدیک‌ترین ترک‌های کتابخانه به مرکزِ حسیِ کاربر.

    مرکز (`(والانس، انرژی)`) از لایک‌ها یا پخش‌های اخیر می‌آید؛ `None` یعنی
    هنوز سیگنالی نیست و میکس می‌شود «لایک‌ها، بعد تازه‌ترین‌ها». ترک‌های
    `exclude_ids` (گوش‌داده‌شده‌ی اخیر) وارد نمی‌شوند تا میکس هر روز تکراری
    نباشد — آن‌ها را همین چند روز پیش شنیده‌ای.

    تحلیل‌نشده‌ها (بدونِ والانس) وقتی مرکز هست در انتها می‌نشینند نه بیرون:
    بیرون‌انداختنشان در کتابخانه‌ای که librosa خاموش است یعنی میکسِ خالی.
    """
    rows = _query("SELECT * FROM jobs WHERE status = 'ready' AND path IS NOT NULL")
    candidates = [r for r in rows if r["track_id"] not in exclude_ids]

    if center is None:
        candidates.sort(key=lambda r: (0 if r["favorite"] else 1, -float(r["created_at"])))
        return candidates[:limit]

    v, e = center

    def score(r: sqlite3.Row) -> float:
        if r["valence"] is None or r["energy"] is None:
            return 10.0  # بیرون از بازه‌ی ممکن — تحلیل‌نشده‌ها همیشه ته صف
        d = (float(r["valence"]) - v) ** 2 + (float(r["energy"]) - e) ** 2
        if r["favorite"]:
            d -= _FAVORITE_BONUS
        return d

    candidates.sort(key=lambda r: (score(r), -float(r["created_at"])))
    return candidates[:limit]


# ---------- پلی‌لیست‌ها ----------


def owned_refs(track_ids: list[str]) -> dict[str, sqlite3.Row]:
    """
    کدام از این ترک‌ها از قبل در کتابخانه‌اند — برای چت‌باتِ وایب.

    کلید، `track_id` است و مقدار ردیفِ جابِ آماده. اگر یک ترک دو جاب دارد
    (دو کیفیت)، پرحجم‌تر انتخاب می‌شود: چت دارد پیشنهاد می‌دهد نه آرشیو، و
    نسخه‌ی باکیفیت‌تر همان فایل است که کاربر دوست دارد بشنود.

    ترتیبِ `ORDER BY bytes DESC` به‌تنهایی این را تضمین می‌کند و `dict.setdefault`
    اولین (یعنی بهترین) را نگه می‌دارد.
    """
    if not track_ids:
        return {}
    marks = ", ".join("?" for _ in track_ids)
    rows = _query(
        f"""SELECT id, track_id, lyrics_path, loudness, peak, bytes
            FROM jobs
            WHERE status = 'ready' AND path IS NOT NULL AND track_id IN ({marks})
            ORDER BY bytes DESC""",
        tuple(track_ids),
    )
    found: dict[str, sqlite3.Row] = {}
    for row in rows:
        found.setdefault(row["track_id"], row)
    return found


def create_playlist(playlist_id: str, name: str, kind: str, rule: dict | None, created_at: float) -> None:
    _exec(
        "INSERT INTO playlists (id, name, kind, rule_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (playlist_id, name, kind, json.dumps(rule, ensure_ascii=False) if rule else None, created_at),
    )


def update_playlist(playlist_id: str, name: str | None = None, rule: dict | None = None) -> None:
    if name is not None:
        _exec("UPDATE playlists SET name = ? WHERE id = ?", (name, playlist_id))
    if rule is not None:
        _exec(
            "UPDATE playlists SET rule_json = ? WHERE id = ?",
            (json.dumps(rule, ensure_ascii=False), playlist_id),
        )


def delete_playlist(playlist_id: str) -> None:
    _exec("DELETE FROM playlist_items WHERE playlist_id = ?", (playlist_id,))
    _exec("DELETE FROM playlists WHERE id = ?", (playlist_id,))


def get_playlist(playlist_id: str) -> sqlite3.Row | None:
    rows = _query("SELECT * FROM playlists WHERE id = ?", (playlist_id,))
    return rows[0] if rows else None


def playlists() -> list[sqlite3.Row]:
    """
    همه‌ی پلی‌لیست‌ها، تازه‌ترین اول.

    شمارشِ اعضا در همین کوئری می‌آید چون سرِ فهرست لازم است و بدونش به‌ازای هر
    پلی‌لیست یک کوئری اضافه می‌شد. پلی‌لیستِ هوشمند عضوِ ذخیره‌شده ندارد، پس
    صفر می‌گیرد و صدازننده باید قانونش را اجرا کند.
    """
    return _query(
        """SELECT p.*, (
               SELECT COUNT(*) FROM playlist_items i WHERE i.playlist_id = p.id
           ) AS item_count
           FROM playlists p ORDER BY p.created_at DESC"""
    )


def playlist_jobs(playlist_id: str) -> list[sqlite3.Row]:
    """اعضای یک پلی‌لیستِ دستی، به ترتیبی که کاربر چیده."""
    return _query(
        """SELECT j.* FROM playlist_items i
           JOIN jobs j ON j.id = i.job_id
           WHERE i.playlist_id = ? AND j.status = 'ready' AND j.path IS NOT NULL
           ORDER BY i.position""",
        (playlist_id,),
    )


def add_to_playlist(playlist_id: str, job_ids: list[str], now: float) -> int:
    """
    به انتها اضافه می‌کند و تکراری‌ها را رد. تعداد ردیف‌های واقعاً اضافه‌شده
    برمی‌گردد — «۳ تا اضافه شد» باید راست بگوید حتی وقتی دو تایشان از قبل بودند.
    """
    row = _query(
        "SELECT COALESCE(MAX(position), -1) AS m FROM playlist_items WHERE playlist_id = ?",
        (playlist_id,),
    )[0]
    position = int(row["m"]) + 1
    added = 0
    for job_id in job_ids:
        cur = _exec(
            """INSERT OR IGNORE INTO playlist_items (playlist_id, job_id, position, added_at)
               VALUES (?, ?, ?, ?)""",
            (playlist_id, job_id, position, now),
        )
        if cur.rowcount:
            position += 1
            added += 1
    return added


def remove_from_playlist(playlist_id: str, job_id: str) -> bool:
    cur = _exec(
        "DELETE FROM playlist_items WHERE playlist_id = ? AND job_id = ?",
        (playlist_id, job_id),
    )
    return bool(cur.rowcount)


def reorder_playlist(playlist_id: str, job_ids: list[str]) -> None:
    """ترتیب تازه. شناسه‌ای که عضو نباشد بی‌اثر است."""
    for position, job_id in enumerate(job_ids):
        _exec(
            "UPDATE playlist_items SET position = ? WHERE playlist_id = ? AND job_id = ?",
            (position, playlist_id, job_id),
        )


# مرتب‌سازی‌های مجازِ پلی‌لیستِ هوشمند. رشته مستقیم داخل SQL می‌رود، پس
# whitelist لازم است — نه به‌خاطر کاربرِ بدخواه، به‌خاطر تایپوی خودمان.
SMART_SORT = {
    "recent": "created_at DESC",
    "oldest": "created_at ASC",
    "energy": "energy DESC",
    "calm": "energy ASC",
    "happy": "valence DESC",
    "sad": "valence ASC",
}


def smart_jobs(rule: dict) -> list[sqlite3.Row]:
    """
    اجرای قانونِ یک پلی‌لیستِ هوشمند روی کتابخانه.

    همیشه در لحظه‌ی خواندن اجرا می‌شود، نه موقع ساخت: «شادهای پرانرژی» باید
    ترکی را که دیروز دانلود کرده‌ای هم شامل شود، بدون اینکه کسی چیزی را
    دوباره بسازد.
    """
    where = ["status = 'ready'", "path IS NOT NULL"]
    params: list = []

    if (text := str(rule.get("query") or "").strip().lower()):
        where.append(f"search_text LIKE ? ESCAPE '{_LIKE_ESCAPE}'")
        params.append(_like(text))

    # ترکی که تحلیل نشده (librosa خاموش بوده یا فایل عجیب بوده) valence ندارد؛
    # وارد کردنش در فیلترِ حس‌وحال یعنی نتیجه‌ی تصادفی، پس بیرون می‌ماند
    for column, low, high in (
        ("valence", rule.get("valenceMin"), rule.get("valenceMax")),
        ("energy", rule.get("energyMin"), rule.get("energyMax")),
    ):
        if low is None and high is None:
            continue
        where.append(f"{column} IS NOT NULL")
        if low is not None:
            where.append(f"{column} >= ?")
            params.append(float(low))
        if high is not None:
            where.append(f"{column} <= ?")
            params.append(float(high))

    order = SMART_SORT.get(str(rule.get("sort") or "recent"), SMART_SORT["recent"])
    limit = max(1, min(int(rule.get("limit") or 50), 200))
    return _query(
        f"SELECT * FROM jobs WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?",
        (*params, limit),
    )


# ---------- تلگرام ----------


def link_telegram(chat_id: int, title: str, now: float) -> None:
    """چتِ تازه جای قبلی را می‌گیرد — همیشه یک مقصد، همان که آخر وصل شده."""
    with _lock:
        conn = connect()
        conn.execute("DELETE FROM telegram_chat")
        conn.execute(
            "INSERT INTO telegram_chat (chat_id, title, linked_at) VALUES (?, ?, ?)",
            (chat_id, title, now),
        )
        conn.commit()


def telegram_chat() -> sqlite3.Row | None:
    rows = _query("SELECT * FROM telegram_chat LIMIT 1")
    return rows[0] if rows else None


def unlink_telegram() -> bool:
    """قطعِ اتصال؛ کارهای هنوز نرفته هم می‌روند، وگرنه بعداً به چتِ بعدی می‌رسیدند."""
    with _lock:
        conn = connect()
        cur = conn.execute("DELETE FROM telegram_chat")
        conn.execute("DELETE FROM telegram_outbox WHERE status IN ('pending', 'sending')")
        conn.commit()
        return cur.rowcount > 0


# ---------- هنرمندهای دنبال‌شده ----------


def add_follow(
    chat_id: int,
    artist_id: str,
    artist_name: str,
    artist_source_url: str,
    source: str,
    artwork_url: str | None,
    last_release_id: str | None,
    last_release_title: str | None,
    now: float,
) -> bool:
    """True یعنی تازه اضافه شد؛ False یعنی این چت از قبل همین هنرمند را دنبال می‌کرد."""
    with _lock:
        conn = connect()
        try:
            conn.execute(
                """INSERT INTO follows
                   (chat_id, artist_id, artist_name, artist_source_url, source,
                    artwork_url, last_release_id, last_release_title, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chat_id,
                    artist_id,
                    artist_name,
                    artist_source_url,
                    source,
                    artwork_url,
                    last_release_id,
                    last_release_title,
                    now,
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def all_follows() -> list[sqlite3.Row]:
    return _query("SELECT * FROM follows")


def follows_for_chat(chat_id: int) -> list[sqlite3.Row]:
    return _query(
        "SELECT * FROM follows WHERE chat_id = ? ORDER BY artist_name COLLATE NOCASE",
        (chat_id,),
    )


def follows_for_artist(artist_id: str) -> list[sqlite3.Row]:
    return _query("SELECT * FROM follows WHERE artist_id = ?", (artist_id,))


def follow_mark_seen(follow_id: int, release_id: str, release_title: str) -> None:
    _exec(
        "UPDATE follows SET last_release_id = ?, last_release_title = ? WHERE id = ?",
        (release_id, release_title, follow_id),
    )


def remove_follow(chat_id: int, artist_id: str) -> bool:
    with _lock:
        conn = connect()
        cur = conn.execute(
            "DELETE FROM follows WHERE chat_id = ? AND artist_id = ?",
            (chat_id, artist_id),
        )
        conn.commit()
        return cur.rowcount > 0


def enqueue_telegram(
    send_id: str, chat_id: int, kind: str, payload: dict, title: str, now: float
) -> None:
    _exec(
        """INSERT INTO telegram_outbox
           (id, chat_id, kind, payload, title, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (send_id, chat_id, kind, json.dumps(payload, ensure_ascii=False), title, now, now),
    )


def claim_telegram(now: float) -> sqlite3.Row | None:
    """
    قدیمی‌ترین کارِ در انتظار را برای بات برمی‌دارد.

    انتخاب و علامت‌زدن زیر یک قفل‌اند: دو نمونه‌ی بات (یا یک long-poll که دوباره
    وصل شده) نباید یک ردیف را دوبار بگیرند و آهنگ دوبار فرستاده شود.
    """
    with _lock:
        conn = connect()
        row = conn.execute(
            "SELECT * FROM telegram_outbox WHERE status = 'pending' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE telegram_outbox SET status = 'sending', updated_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM telegram_outbox WHERE id = ?", (row["id"],)
        ).fetchone()


def finish_telegram(send_id: str, error: str | None, now: float) -> None:
    _exec(
        "UPDATE telegram_outbox SET status = ?, error = ?, updated_at = ? WHERE id = ?",
        ("error" if error else "done", error, now, send_id),
    )


def telegram_send(send_id: str) -> sqlite3.Row | None:
    rows = _query("SELECT * FROM telegram_outbox WHERE id = ?", (send_id,))
    return rows[0] if rows else None


def requeue_telegram() -> int:
    """
    کارهای نیمه‌کاره را به صف برمی‌گرداند.

    `sending` یعنی باتی آن را برداشته بود؛ اگر سرور (یا بات) وسطش ری‌استارت شده
    باشد کسی دیگر سراغش نمی‌آید و کاربر تا ابد اسپینر می‌بیند.
    """
    return _exec("UPDATE telegram_outbox SET status = 'pending' WHERE status = 'sending'").rowcount


def prune_telegram(cutoff: float) -> int:
    """کارهای تمام‌شده‌ی قدیمی — فقط برای اینکه جدول بی‌نهایت رشد نکند."""
    return _exec(
        "DELETE FROM telegram_outbox WHERE status IN ('done', 'error') AND updated_at < ?",
        (cutoff,),
    ).rowcount


# ---------- آینه‌ی کاور ----------


def remember_artwork(rows: list[tuple[str, str]], now: float) -> None:
    """
    (sha، آدرس) هایی که تازه دیده شده‌اند.

    `seen_at` حتی برای ردیفِ تکراری به‌روز می‌شود تا پاک‌سازیِ آینده بداند کدام
    کاور هنوز در گردش است — ولی `fetched_at` و بقیه دست‌نخورده می‌مانند، وگرنه
    هر بار دیدنِ یک نتیجه‌ی جستجو، کاورِ از قبل گرفته‌شده را دوباره «نگرفته»
    اعلام می‌کرد.
    """
    if not rows:
        return
    with _lock:
        conn = connect()
        conn.executemany(
            """INSERT INTO artwork (sha, url, seen_at) VALUES (?, ?, ?)
               ON CONFLICT(sha) DO UPDATE SET seen_at = excluded.seen_at""",
            [(sha, url, now) for sha, url in rows],
        )
        conn.commit()


def artwork_row(sha: str) -> sqlite3.Row | None:
    rows = _query("SELECT * FROM artwork WHERE sha = ?", (sha,))
    return rows[0] if rows else None


def artwork_stored(sha: str, mime: str, size: int, now: float) -> None:
    _exec(
        "UPDATE artwork SET mime = ?, bytes = ?, fetched_at = ? WHERE sha = ?",
        (mime, size, now, sha),
    )


def artwork_pending(limit: int) -> list[sqlite3.Row]:
    """کاورهایی که آدرسشان را داریم ولی هنوز روی دیسک نیستند — تازه‌ترین اول."""
    return _query(
        "SELECT * FROM artwork WHERE fetched_at IS NULL ORDER BY seen_at DESC LIMIT ?",
        (limit,),
    )


def artwork_stats() -> tuple[int, int, int]:
    """(گرفته‌شده، در انتظار، مجموع بایت) — برای نمایش در تنظیمات."""
    row = _query(
        """SELECT COUNT(fetched_at) AS done,
                  COUNT(*) - COUNT(fetched_at) AS todo,
                  COALESCE(SUM(bytes), 0) AS size
           FROM artwork"""
    )[0]
    return int(row["done"]), int(row["todo"]), int(row["size"])


def forget_artwork(sha: str) -> None:
    """فایلش روی دیسک نبود — ردیف باید دوباره «نگرفته» شود، نه اینکه ۴۰۴ بماند."""
    _exec("UPDATE artwork SET fetched_at = NULL, bytes = 0 WHERE sha = ?", (sha,))


def drop_artwork(sha: str) -> None:
    """
    حذفِ کاملِ ردیف.

    برای ردیفی که خودِ داده‌اش باطل است و «دوباره بگیر» هم درستش نمی‌کند —
    مثل ردیفی که آدرسِ منبعش به خودش اشاره می‌کند (artcache.fetch). گذاشتنش
    یعنی حلقه‌ی warm تا ابد همان درخواستِ بی‌معنی را تکرار کند.
    """
    _exec("DELETE FROM artwork WHERE sha = ?", (sha,))


# ---------- کشِ کاتالوگ ----------


def put_search(query: str, payload: str, now: float) -> None:
    _exec(
        """INSERT INTO catalog_search (query, payload, cached_at) VALUES (?, ?, ?)
           ON CONFLICT(query) DO UPDATE SET payload = excluded.payload,
                                            cached_at = excluded.cached_at""",
        (query, payload, now),
    )


def get_search(query: str) -> sqlite3.Row | None:
    rows = _query("SELECT * FROM catalog_search WHERE query = ?", (query,))
    return rows[0] if rows else None


def put_ref(ref: str, kind: str, payload: str, now: float) -> None:
    _exec(
        """INSERT INTO catalog_ref (ref, kind, payload, cached_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(ref, kind) DO UPDATE SET payload = excluded.payload,
                                                cached_at = excluded.cached_at""",
        (ref, kind, payload, now),
    )


def get_ref(ref: str, kind: str) -> sqlite3.Row | None:
    rows = _query("SELECT * FROM catalog_ref WHERE ref = ? AND kind = ?", (ref, kind))
    return rows[0] if rows else None


def put_entities(rows: list[tuple[str, str, str, str, str]], now: float) -> None:
    """
    (id، نوع، منبع، متنِ جستجو، payload) — ردیف‌های تکیِ هر چیزی که دیده شده.

    `INSERT OR REPLACE` نه `DO NOTHING`: همان ترک ممکن است بار دوم از صفحه‌ی
    آلبوم بیاید و آنجا متادیتای کامل‌تری دارد (شماره‌ی ترک، سال، هنرمندِ آلبوم)
    که موقع نمایشِ آفلاین همان نسخه باید بماند.
    """
    if not rows:
        return
    with _lock:
        conn = connect()
        conn.executemany(
            """INSERT OR REPLACE INTO catalog_entity
               (id, kind, source, search_text, payload, seen_at) VALUES (?, ?, ?, ?, ?, ?)""",
            [(*row, now) for row in rows],
        )
        conn.commit()


def search_entities(kind: str, query: str, limit: int) -> list[sqlite3.Row]:
    """جستجوی متنی روی چیزهایی که قبلاً دیده شده‌اند — همان LIKEِ کتابخانه."""
    text = query.strip().lower()
    if not text:
        return _query(
            "SELECT * FROM catalog_entity WHERE kind = ? ORDER BY seen_at DESC LIMIT ?",
            (kind, limit),
        )
    return _query(
        f"""SELECT * FROM catalog_entity
            WHERE kind = ? AND search_text LIKE ? ESCAPE '{_LIKE_ESCAPE}'
            ORDER BY seen_at DESC LIMIT ?""",
        (kind, _like(text), limit),
    )


def catalog_stats() -> tuple[int, int]:
    """(تعداد ردیف‌های کش‌شده، تعداد جستجوهای ذخیره‌شده)."""
    entities = int(_query("SELECT COUNT(*) c FROM catalog_entity")[0]["c"])
    searches = int(_query("SELECT COUNT(*) c FROM catalog_search")[0]["c"])
    return entities, searches


# ---------- کمکی ----------


def row_track(row: sqlite3.Row) -> dict:
    return json.loads(row["track_json"])


def row_path(row: sqlite3.Row) -> Path | None:
    return Path(row["path"]) if row["path"] else None
