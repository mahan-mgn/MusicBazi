#!/usr/bin/env python3
"""
نقطه‌ی ورود بات برای میزبان‌هایی که از ریشه‌ی مخزن اجرا می‌کنند (Botkeep).

این فایل هیچ منطقی از بات را عوض نمی‌کند — فقط دو کار می‌کند که برای اجرا از
ریشه لازم است:

1. `server/` را به `sys.path` می‌گذارد. خودِ بات با `python -m app.bot.run` و
   از داخل `server/` اجرا می‌شود؛ از ریشه، پکیجِ `app` پیدا نمی‌شود.

2. `.env` ریشه‌ی مخزن را بارگذاری می‌کند. `app/config.py` فقط
   `server/.env` و `$DATA_DIR/.env` را می‌خواند و میزبان‌ها معمولاً `.env`
   را کنارِ همان فایلی می‌گذارند که اجرا می‌کنند — یعنی ریشه. بدون این خط،
   توکن در فایل هست ولی بات آن را نمی‌بیند و بی‌صدا خارج می‌شود.

اجرا: `python main.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER_DIR = ROOT / "server"

# پیش از هر import از پکیجِ `app` — وگرنه `ModuleNotFoundError: app`.
sys.path.insert(0, str(SERVER_DIR))

try:
    from dotenv import load_dotenv

    # override=False تا متغیرهای واقعیِ محیط همیشه برنده باشند؛ میزبان‌ها
    # مقادیر را هم در محیط و هم در فایل می‌گذارند و محیط باید اولویت داشته باشد.
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    # داخل داکر/ترمینالِ خودِ پروژه معمولاً .env جای دیگری است و کسی این
    # مسیر را صدا نمی‌زند؛ نبودنِ dotenv نباید جلوی بالا آمدن را بگیرد.
    pass

# ایجاد پوشه‌های داده و دانلود قبل از لود کانفیگ تا خطای دسترسی ندهد
try:
    (SERVER_DIR / "data" / "cache" / "stream").mkdir(parents=True, exist_ok=True)
    (SERVER_DIR / "downloads").mkdir(parents=True, exist_ok=True)
except OSError:
    pass

from app.bot.run import main  # noqa: E402  — بعد از تنظیمِ sys.path

if __name__ == "__main__":
    main()
