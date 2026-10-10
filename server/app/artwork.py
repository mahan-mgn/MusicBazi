"""
بزرگ کردن آدرس کاور.

هر کاتالوگ کاور را در چند اندازه می‌دهد و اندازه هم تقریباً همیشه داخل خودِ
آدرس است — پس بدون هیچ درخواست اضافه‌ای می‌شود نسخه‌ی بزرگ‌تر را ساخت.
APIها معمولاً کوچک‌ترین نسخه را در پاسخ می‌گذارند (اپل ۱۰۰، دیزر ۲۵۰) که برای
نمایش تار است و برای امبد کردن داخل فایل اسباب خجالت.

دو اندازه داریم چون یک اندازه برای هر دو کار درست نیست:

* `DISPLAY` برای کاور توی سایت. کارت آلبوم حدود ۲۰۰ پیکسل است و روی نمایشگر
  رتینا دو برابر پیکسل می‌خواهد؛ ۵۰۰ همان است. بزرگ‌تر فقط نتیجه‌ی جستجو را
  سنگین می‌کند بی‌آنکه چیزی دیده شود.
* `EMBED` برای کاوری که داخل فایل دانلودشده می‌نشیند. اینجا پهنای باند یک‌بار
  خرج می‌شود ولی فایل تا ابد می‌ماند، پس بزرگ‌ترین چیزی که CDN می‌دهد.
"""

from __future__ import annotations

import re

DISPLAY = 500
EMBED = 1400

# اپل: .../100x100bb.jpg — هر اندازه‌ای بدهی همان را می‌سازد. دو حرفِ بعدِ
# اندازه کدِ برش است و دست‌نخورده می‌ماند: کاورِ آلبوم `bb` است (نسبت را نگه
# می‌دارد و حاشیه می‌گذارد) ولی عکسِ پروفایلِ هنرمند `cc` (مربع می‌برد)، و
# یکسان کردنشان یکی از آن دو را خراب می‌کرد.
_APPLE = re.compile(r"/\d+x\d+([a-z]{2})\.(jpg|png)", re.I)

# دیزر: .../250x250-000000-80-0-0.jpg — دُم بعد از اندازه تنظیمات کیفیت است
_DEEZER = re.compile(r"/\d+x\d+(-[^/]*)?\.(jpg|png)$", re.I)

# ساندکلاد: ...-large.jpg / ...-t500x500.jpg / ...-original.jpg
_SOUNDCLOUD = re.compile(r"-(?:large|small|tiny|badge|t\d+x\d+|original)\.(jpg|png)$", re.I)

# یوتیوب موزیک از lh3.googleusercontent می‌آید: ...=w544-h544-l90-rj
_GOOGLE = re.compile(r"=w\d+-h\d+(-[^=]*)?$")

# تصویر ویدیوی یوتیوب: .../hqdefault.jpg
_YTIMG = re.compile(r"/(?:default|mqdefault|hqdefault|sddefault|maxresdefault)\.(jpg|webp)$", re.I)

# اسپاتیفای: i.scdn.co/image/ab67616d0000b273<هشِ ۲۴ حرفی>
# آدرس سه تکه است — نوعِ تصویر (آلبوم/هنرمند)، کدِ اندازه، و هش. اندازه‌ی دلخواه
# ندارد: فقط همین چند پله، و هرکدام کدِ ثابتِ خودش را دارد.
_SPOTIFY = re.compile(r"(//i\.scdn\.co/image/)(ab6761(?:6d|61))([0-9a-f]{8})", re.I)
_SPOTIFY_LADDER: dict[str, list[tuple[int, str]]] = {
    "ab67616d": [(64, "00004851"), (300, "00001e02"), (640, "0000b273")],  # کاور آلبوم
    "ab676161": [(160, "0000f178"), (320, "00005174"), (640, "0000e5eb")],  # عکس هنرمند
}

# سقف واقعی هر CDN. بالاتر از این یا ۴۰۴ می‌دهد یا همان را بزرگ‌شده پس می‌فرستد،
# که فقط حجم است بدون جزئیات بیشتر.
_DEEZER_MAX = 1000

# ساندکلاد برخلاف اپل و دیزر اندازه‌ی دلخواه نمی‌سازد؛ فقط همین فایل‌ها را از
# قبل دارد و هر اندازه‌ی دیگری ۴۰۴ متنی برمی‌گرداند — از جمله `t320x320` و
# `t640x640` که کاملاً طبیعی به نظر می‌رسند و دقیقاً همان‌هایی‌اند که ساختنِ
# `t{size}x{size}` از روی هر عددی تولیدشان می‌کرد. آن ۴۰۴ هم بی‌صدا بود: کاور
# فقط ناپدید می‌شد.
_SOUNDCLOUD_STEPS = (50, 60, 67, 80, 120, 200, 240, 250, 300, 500, 1080)


def resized(url: str | None, size: int = DISPLAY) -> str | None:
    """
    همان کاور در اندازه‌ی خواسته‌شده. آدرسی که نشناسیم دست‌نخورده برمی‌گردد —
    منبع جدید نباید باعث شود کاور کلاً ناپدید شود.
    """
    if not url:
        return None

    if _APPLE.search(url):
        return _APPLE.sub(lambda m: f"/{size}x{size}{m.group(1)}.{m.group(2)}", url)

    if _DEEZER.search(url):
        px = min(size, _DEEZER_MAX)
        return _DEEZER.sub(lambda m: f"/{px}x{px}{m.group(1) or ''}.{m.group(2)}", url)

    if _SOUNDCLOUD.search(url):
        # کوچک‌ترین پله‌ای که از خواسته کم‌تر نباشد. بالای بزرگ‌ترین پله فقط
        # «اصل» هست، که اندازه‌اش دستِ آپلودکننده است نه ما.
        step = next((s for s in _SOUNDCLOUD_STEPS if s >= size), None)
        tail = f"t{step}x{step}" if step else "original"
        return _SOUNDCLOUD.sub(f"-{tail}.\\1", url)

    if _GOOGLE.search(url):
        # اگر نسبت عرض به ارتفاع متفاوت باشد (مانند بنر عریض)، ابعاد دست‌نخورده می‌ماند
        if m_dim := re.search(r"=w(\d+)-h(\d+)", url):
            if int(m_dim.group(1)) != int(m_dim.group(2)):
                return url
        # `-l90-rj` یعنی کیفیت ۹۰ و خروجی jpeg — نگهش می‌داریم
        return _GOOGLE.sub(lambda m: f"=w{size}-h{size}{m.group(1) or ''}", url)

    if _YTIMG.search(url):
        # یوتیوب پله‌های ثابت دارد و maxres هم فقط برای بعضی ویدیوهاست؛
        # `candidates` عقب‌گرد را پوشش می‌دهد
        return _YTIMG.sub("/maxresdefault.\\1" if size > 480 else "/hqdefault.\\1", url)

    if match := _SPOTIFY.search(url):
        ladder = _SPOTIFY_LADDER.get(match.group(2).lower())
        if not ladder:
            return url
        # کوچک‌ترین پله‌ای که از اندازه‌ی خواسته‌شده کم‌تر نباشد؛ بالاتر از
        # بزرگ‌ترین پله چیزی وجود ندارد، پس همان بزرگ‌ترین
        code = next((c for px, c in ladder if px >= size), ladder[-1][1])
        return url[: match.start(3)] + code + url[match.end(3) :]

    return url


def _distinct(*urls: str | None) -> list[str]:
    out: list[str] = []
    for url in urls:
        if url and url not in out:
            out.append(url)
    return out


# پله‌ی میانیِ `candidates`. بدون آن، نبودنِ بزرگ‌ترین اندازه یعنی سقوط یک‌باره
# به اندازه‌ی نمایش — در حالی که ساندکلاد دقیقاً همین‌جا `t1080x1080` دارد، که
# برای امبد کردن از ۵۰۰ خیلی بهتر است.
_FALLBACK = 1080


def candidates(url: str | None) -> list[str]:
    """
    آدرس‌های کاور از بزرگ به کوچک، برای جایی که می‌شود امتحان کرد و رد شد.

    لازم است چون بعضی پله‌ها همیشه وجود ندارند: `maxresdefault` فقط روی ویدیوی
    اچ‌دی هست و `original` ساندکلاد روی ترک‌های قدیمی نیست. اولی که جواب بدهد
    برنده است و آخرین گزینه همیشه همان آدرس اصلی است که مطمئنیم کار می‌کند.
    """
    if not url:
        return []
    return _distinct(resized(url, EMBED), resized(url, _FALLBACK), resized(url, DISPLAY), url)


def at_most(url: str | None, size: int) -> list[str]:
    """
    کاور برای جایی که سقفِ اندازه دارد — thumbnailِ تلگرام، که بالای ۲۰۰ پیکسل
    و ۲۰۰ کیلوبایت را رد می‌کند.

    برخلاف `candidates` از کوچک شروع می‌کند، ولی به همان دلیل بیش از یک گزینه
    دارد: پله‌ای که حساب می‌کنیم ممکن است روی آن CDN نباشد، و آدرسِ خامِ کاتالوگ
    تنها چیزی است که مطمئنیم هست. رد شدن از سقفِ حجم را صداکننده چک می‌کند —
    اینجا فقط ترتیبِ امتحان است.
    """
    if not url:
        return []
    return _distinct(resized(url, size), url)


__all__ = ["DISPLAY", "EMBED", "at_most", "candidates", "resized"]
