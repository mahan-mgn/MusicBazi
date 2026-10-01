# -*- coding: utf-8 -*-
"""
اولویتِ بارگذاری env — جایی که داکر و ویزارد به هم می‌رسند.

`docker-compose.yml` برای هر کلیدی که در `.env` میزبان نباشد رشته‌ی خالی
تزریق می‌کند (`${MUSICBAZI_SPOTIFY_CLIENT_ID:-}`). اگر `load_dotenv` با
`override=False` استفاده شود، آن رشته‌ی خالی «ست‌شده» حساب می‌شود و فایلِ
نوشته‌شده‌ی ویزارد روی `/data/.env` بی‌صدا نادیده گرفته می‌شود — یعنی
«کلید ذخیره شد» ولی هیچ‌وقت به کار نمی‌رود.
"""

import os
import subprocess
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent


def _run(tmp: Path, env: dict[str, str]) -> dict[str, str]:
    """config.py را در یک فرایندِ تازه با MUSICBAZI_DATA_DIR ساختگی اجرا می‌کند."""
    (tmp / ".env").write_text(
        "MUSICBAZI_SPOTIFY_CLIENT_ID=from-wizard\nMUSICBAZI_AUDD_TOKEN=audd-from-wizard\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,os,sys;sys.path.insert(0,r'%s');import app.config as c;"
            "print(json.dumps({"
            "'spotify': os.environ.get('MUSICBAZI_SPOTIFY_CLIENT_ID',''),"
            "'audd': os.environ.get('MUSICBAZI_AUDD_TOKEN',''),"
            "'cfg': c.SPOTIFY_CLIENT_ID}))" % SERVER,
        ],
        env={
            **os.environ,
            "MUSICBAZI_DATA_DIR": str(tmp),
            # این تست *درباره‌ی* خواندنِ فایل است، پس کلیدِ خاموش‌کردنش (که
            # conftest برای بقیه‌ی تست‌ها ست می‌کند) باید اینجا باز شود
            "MUSICBAZI_ENV_NO_FILES": "",
            **env,
        },
        capture_output=True,
        text=True,
        check=True,
    )
    import json

    last = proc.stdout.strip().splitlines()[-1]
    return json.loads(last)


def test_compose_empty_string_does_not_shadow_the_wizard_file(tmp_path):
    out = _run(tmp_path, {"MUSICBAZI_SPOTIFY_CLIENT_ID": "", "MUSICBAZI_AUDD_TOKEN": ""})
    assert out["spotify"] == "from-wizard"
    assert out["audd"] == "audd-from-wizard"
    assert out["cfg"] == "from-wizard"


def test_real_env_value_still_wins(tmp_path):
    out = _run(tmp_path, {"MUSICBAZI_SPOTIFY_CLIENT_ID": "from-shell"})
    assert out["spotify"] == "from-shell"


def test_whitespace_only_counts_as_unset(tmp_path):
    out = _run(tmp_path, {"MUSICBAZI_AUDD_TOKEN": "   "})
    assert out["audd"] == "audd-from-wizard"
