import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

files_to_include = [
    "main.py",
    "requirements.txt",
    "bot.env.example",
    "server/app/__init__.py",
    "server/app/artwork.py",
    "server/app/config.py",
    "server/app/models.py",
    "server/app/bot/__init__.py",
    "server/app/bot/client.py",
    "server/app/bot/logic.py",
    "server/app/bot/run.py",
    "server/app/bot/store.py",
]

zip_path = ROOT / "botkeep-musicbazi.zip"
print(f"Creating {zip_path}...")

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel_path in files_to_include:
        full_path = ROOT / rel_path
        if full_path.exists():
            zf.write(full_path, arcname=rel_path)
            print(f"  + Added: {rel_path}")
        else:
            print(f"  ! Missing: {rel_path}")

    # پوشه‌های خالی مورد نیاز را در آرشیو ثبت می‌کنیم
    zf.writestr("server/data/.gitkeep", "")
    zf.writestr("server/downloads/.gitkeep", "")

print(f"Done! Created {zip_path.name} ({zip_path.stat().st_size / 1024:.1f} KB)")
