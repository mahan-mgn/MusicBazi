"""
smoke test دستی برای Providerهای متن — **فقط ساخت، اجرا ممنوع** (بند D.7).

اینجا هیچ Providerی import نمی‌شود و هیچ درخواستی زده نمی‌شود. کارش این است
که وقتی کاربر خودش تصمیم گرفت، در یک رفت‌وبرگشتِ کنترل‌شده نشان بدهد کدام
Providerها روی داده‌ی *واقعی* چه می‌دهند — چون تمام تست‌های پروژه mock هستند
و هیچ‌کدام نمی‌توانند بگویند یک سرویسِ زنده امروز جواب می‌دهد یا نه.

قواعدی که این اسکریپت عمداً رعایت می‌کند:

- **پیش‌فرض dry-run است.** بدون `--live` فقط فهرستِ نمونه و Providerهای فعال
  چاپ می‌شود و هیچ درخواستی زده نمی‌شود.
- **هیچ توکن و هیچ متنِ کاملی چاپ نمی‌شود.** از متنِ آهنگ فقط تعدادِ خط و
  «آیا زمان‌بندیِ کلمه‌ای دارد یا نه» چاپ می‌شود. URL هم چاپ نمی‌شود چون
  بعضی سرویس‌ها توکن را در query می‌گذارند.
- **فاصله‌ی زمانی بین درخواست‌ها** (`--interval`) تا به سرویسِ رایگان فشار
  نیاید و به 429 نخوریم.
- **تایم‌اوت صریح** روی هر درخواست.

نمونه‌ها از یک فایل JSON محلی می‌آیند تا تغییرشان بدون دست‌زدن به کد ممکن باشد:

    {
      "tracks": [
        {"title": "...", "artist": "...", "album": "...", "duration_ms": 185000},
      ]
    }

اجرا (وقتی کاربر تصمیم گرفت — این اسکریپت خودش هیچ‌وقت اجرا نشده است):

    cd server
    ./.venv/Scripts/python.exe scripts/lyrics_smoke.py --tracks ../smoke-tracks.json
    ./.venv/Scripts/python.exe scripts/lyrics_smoke.py --tracks ../smoke-tracks.json --live

خروجی به‌صورت JSON-per-line است تا بشود با `jq` هم خواند.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# والدِ server/ روی sys.path تا `app` مثل بقیه‌ی کد import شود
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# کنسولِ ویندوز پیش‌فرض cp1252 است و پیام‌های فارسی این اسکریپت را نمی‌تواند
# چاپ کند (UnicodeEncodeError). خروجیِ JSON هم همیشه UTF-8 می‌خواهیم تا با
# `jq` و ابزارهای دیگر مستقیم کار کند.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ⚠️ هیچ import‌ای از `app` در سطح ماژول نیست (اجرا نباید به importِ پروژه
# وابسته باشد). فهرستِ Providerها هم سخت‌کد نشده: از خودِ Registry خوانده
# می‌شود، پس هر Providerی که بعداً اضافه شود خودبه‌خود در smoke test می‌آید و
# روشن/خاموش‌بودنِ env هم رعایت می‌شود.


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tracks", required=True, help="مسیر فایل JSON نمونه‌ها")
    parser.add_argument(
        "--live",
        action="store_true",
        help="درخواست واقعی بزن. بدون این فقط چاپ خلاصه و خروج (پیش‌فرض).",
    )
    parser.add_argument("--interval", type=float, default=2.0, help="فاصله‌ی ثانیه بین درخواست‌ها")
    parser.add_argument(
        "--providers",
        default=None,
        help="فهرست با کاما؛ پیش‌فرض = Providerهای *فعالِ* Registry",
    )
    return parser.parse_args(argv)


def _load_tracks(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tracks = data.get("tracks") if isinstance(data, dict) else data
    if not isinstance(tracks, list):
        raise SystemExit("فایل نمونه باید لیستی از ترک‌ها باشد")
    return tracks


def _live_track(row: dict):
    """
    Track را از اینجا می‌سازیم تا importِ app داخل تابع باشد.

    `source` عمداً `"spotify"` است نه یک مقدارِ ساختگی: `Track.source` یک
    `Literal` محدود است (`app/models.py:9`) و مقداری بیرونِ آن اعتبارسنجی
    نمی‌شود. `source` فقط برچسبِ مبدأ است و Providerهای متن به آن کاری
    ندارند — تطبیق با `title`/`artist`/`duration` انجام می‌شود.
    """
    from app.models import Track

    return Track(
        id=f"smoke:{abs(hash(row.get('title') or ''))}",
        title=row.get("title") or "",
        artist=row.get("artist") or "",
        album=row.get("album"),
        durationMs=int(row.get("duration_ms") or 0),
        source="spotify",
        sourceUrl=f"https://example.invalid/{abs(hash(row.get('title') or ''))}",
    )


def _probe(provider_name: str, track) -> dict:
    """
    یک Providerِ مشخص را روی یک ترک می‌زند و شکلِ *خلاصه*ی نتیجه را برمی‌گرداند.

    هیچ URL و هیچ توکنی برنمی‌گردد. متنِ آهنگ هم برنمی‌گردد — فقط شمارش و
    نوعِ هم‌زمان‌سازی.

    تایم‌اوت: `entry.strict()` امضای قفل‌شده‌ی `(title, artist, album,
    duration_ms)` را دارد و تایم‌اوتِ خودش را داخلِ Provider می‌گذارد. پس
    `--timeout` اینجا فقط برای شمارشِ خودِ اسکریپت نیست و استفاده نمی‌شود —
    مقدارش همان چیزی است که در هر Provider تعریف شده (۸ تا ۱۲ ثانیه).
    """
    from app.lyrics.manager import LyricsManager
    from app.lyrics.registry import ProviderError

    manager = LyricsManager()
    entry = manager.registry.get(provider_name)
    if entry is None:
        return {"provider": provider_name, "status": "unknown", "reason": "ثبت نشده"}

    started = time.monotonic()
    try:
        # امضای Providerها `(title, artist, album, duration_ms)` است. آن‌هایی
        # که کلیدِ اضافه لازم دارند (simpmusic) اینجا کار نمی‌کنند و باید با
        # `--providers` کنار گذاشته شوند — صریحاً در گزارش ثبت شده.
        found = entry.strict()(track.title, track.artist, track.album, track.durationMs)
    except ProviderError as exc:
        return {
            "provider": provider_name,
            "status": "error",
            "kind": exc.kind,
            "status_code": exc.status,
            "elapsed_s": round(time.monotonic() - started, 2),
        }
    except Exception as exc:  # noqa: BLE001 — smoke test باید همیشه نتیجه بدهد
        return {
            "provider": provider_name,
            "status": "error",
            "kind": "unexpected",
            "error_type": exc.__class__.__name__,
            "elapsed_s": round(time.monotonic() - started, 2),
        }

    elapsed = round(time.monotonic() - started, 2)
    if found is None:
        return {"provider": provider_name, "status": "empty", "elapsed_s": elapsed}

    lines = len(found.lines)
    has_words = any(line.words for line in found.lines)
    return {
        "provider": provider_name,
        "status": "ok",
        "sync_type": found.sync_type,
        "format": found.format,
        "language": found.language,
        "lines": lines,
        "word_synced": has_words,
        "elapsed_s": elapsed,
    }


def _active_provider_names() -> list[str]:
    """
    Providerهای *فعال* — همان‌هایی که `LyricsManager` واقعاً صدا می‌زند.

    از خودِ Registry خوانده می‌شود، نه یک فهرستِ سخت‌کد، پس روشن‌کردنِ یک
    Provider با متغیر محیطی خودبه‌خود در smoke test هم دیده می‌شود.
    """
    from app.lyrics.manager import LyricsManager

    return [entry.name for entry in LyricsManager().registry.available()]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    path = Path(args.tracks)
    if not path.exists():
        print(f"فایل نمونه پیدا نشد: {path}", file=sys.stderr)
        return 2

    rows = _load_tracks(path)
    # فهرستِ سخت‌کد نداریم: پیش‌فرض از Registry می‌آید
    names = (
        [n.strip() for n in args.providers.split(",") if n.strip()]
        if args.providers
        else _active_provider_names()
    )

    if not args.live:
        # حالتِ امن. هیچ درخواستی زده نمی‌شود.
        print(json.dumps({
            "mode": "dry-run",
            "note": "هیچ درخواستی زده نشد. برای اجرای واقعی --live بده.",
            "tracks": len(rows),
            "providers": names,
            "interval_s": args.interval,
        }, ensure_ascii=False))
        return 0

    # ---- از اینجا به بعد فقط با --live می‌رسیم ----
    exit_code = 0
    first = True
    for row in rows:
        track = _live_track(row)
        for name in names:
            if not first:
                time.sleep(max(0.0, args.interval))
            first = False
            result = _probe(name, track)
            # عنوانِ ترک عمداً چاپ نمی‌شود؛ فقط یک برچسبِ کوتاه
            result["track"] = f"#{rows.index(row)}"
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if result["status"] == "error":
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
