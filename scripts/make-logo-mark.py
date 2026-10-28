"""ساختِ نشانِ شفافِ برند برای هدر.

`public/logo.png` یک تصویرِ ۱۲۵۴×۱۲۵۴ است که پنج نشانِ پلتفرم روی یک پلاکِ
سرمه‌ایِ گردگوشه، و آن هم روی پس‌زمینه‌ی مشکی نشسته — ~۷۲٪ پیکسل‌ها پس‌زمینه‌اند.
در هدر فقط خودِ نشان‌ها لازم است: بدونِ پلاک، بدونِ پس‌زمینه، بدونِ گوشه‌ی مربعی.

خروجی `public/logo-mark.png` است؛ `logo.png` دست نمی‌خورد چون صفحه‌ی ورود و
راه‌اندازی عمداً همان نشانِ اسکوار را نگه می‌دارند.

اجرا: python -I scripts/make-logo-mark.py
"""

from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "public" / "logo.png"
DST = ROOT / "public" / "logo-mark.png"
OUT_SIZE = 512

# آستانه‌ها با نمونه‌برداری از خودِ تصویر کالیبره شده‌اند. اگر منبعِ لوگو عوض
# شد، این سه عدد را باید دوباره از پروفایلِ رنگیِ فایلِ تازه گرفت.
DARK_L = 26  # روشناییِ زیرِ این = پس‌زمینه‌ی مشکی
PLATE_L = 150  # روشناییِ رینگِ آبیِ پلاک
HUE_LO, HUE_HI = 190, 245  # بازه‌ی آبیِ پلاک


def luminance(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def hue(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0
    d = mx - mn
    if mx == r:
        h = (g - b) / d % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60


def backdrop(r, g, b):
    """پیکسلی که باید شفاف شود: مشکیِ پس‌زمینه یا آبیِ پلاک و رینگ."""
    L = luminance(r, g, b)
    if L < DARK_L:
        return True
    return HUE_LO <= hue(r, g, b) <= HUE_HI and L < PLATE_L


def main():
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    px = im.load()

    # سیل از لبه‌ها: فقط ناحیه‌ی *متصل* به بیرون شفاف می‌شود، پس لکه‌های تیره‌ی
    # محصورِ داخلِ نشان‌ها دست‌نخورده می‌مانند.
    seen = bytearray(w * h)
    queue = deque()

    def push(x, y):
        if not seen[y * w + x] and backdrop(*px[x, y]):
            seen[y * w + x] = 1
            queue.append((x, y))

    for x in range(w):
        push(x, 0)
        push(x, h - 1)
    for y in range(h):
        push(0, y)
        push(w - 1, y)

    while queue:
        x, y = queue.popleft()
        if x:
            push(x - 1, y)
        if x + 1 < w:
            push(x + 1, y)
        if y:
            push(x, y - 1)
        if y + 1 < h:
            push(x, y + 1)

    # پس‌زمینه صفر-و-صد، فقط لبه نرم.
    #
    # بازه‌ی پس‌زمینه تا پیکسلِ مجاورِ نشان ادامه دارد (پروفایلِ روشنایی)، پس
    # یک پله‌ی جدید لازم نیست: یک `GaussianBlur` روی خودِ ماسک دامنه‌ی صفر-تا-صدی
    # می‌سازد و لبه‌ی نشان را ضدپله می‌کند. آلفای نیمه‌شفاف روی سایهِ نشان‌ها
    # اشتباه بود — آن پیکسل‌ها خودشان رنگِ نشان‌اند، نه پس‌زمینه.
    alpha = Image.frombytes("L", (w, h), bytes(0 if s else 255 for s in seen))
    alpha = alpha.filter(ImageFilter.GaussianBlur(3))

    out = im.convert("RGBA")
    out.putalpha(alpha)

    box = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    pad = round(max(box[2] - box[0], box[3] - box[1]) * 0.015)
    out = out.crop(
        (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
    ).resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)

    out.save(DST)

    kept = 100 - sum(seen) * 100 / (w * h)
    print(f"{SRC.name} {w}x{h} -> {DST.name} {OUT_SIZE}x{OUT_SIZE} (content {kept:.1f}%)")


if __name__ == "__main__":
    main()
