"""
منطق مشترکِ تطبیق برای همه‌ی Providerهای متن.

قبلاً هر Provider تطبیقِ خودش را داشت: LRCLIB فیلتر مدت را داخل `fetch`
پیاده کرده بود و Genius فهرست نشانگرهای نسخه را داخل `_best_hit`. با افزودن
Provider بعدی این دو نسخه سه‌تا می‌شد و سه نسخه یعنی سه رفتار متفاوت برای
یک سؤال واحد («این نتیجه مالِ همین آهنگ است؟»).

اینجا فقط *منطق* جمع شده، بدون I/O: تابع‌های خالص که هم Providerها می‌توانند
صدا بزنند و هم تست‌ها بدون شبکه بسنجند.

دو قاعده‌ی مهم که در پیاده‌سازی‌های قبلی هرکدام یک‌جای متفاوت بودند:

۱. «مدتِ نامعلوم» با «مدتِ متناقض» یکی نیست. صفر یا None یعنی Provider اصلاً
   مدتی اعلام نکرده و هیچ چیزی را رد نکرده؛ عددِ متفاوت یعنی شاهدِ مخالف.
   اولی نباید رد کند، دومی باید.
۲. نشانگرِ نسخه‌ی ناخواسته ردِ قطعی نیست، آخرین چاره است. «Barf (Live)» وقتی
   «Barf» هم موجود است اشتباه است، ولی وقتی تنها نتیجه‌ی موجود است بهتر از
   هیچ متنی است — کاربر دست‌کم متن می‌بیند و خودش می‌فهمد کدام نسخه است.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

# نرمال‌سازی: کلمه‌های یونیکد، بدون توجه به حروف بزرگ و کوچک
_WORDS = re.compile(r"\w+", re.UNICODE)

# ثانیه. ⚠️ **موقت و تأییدنشده**: عددِ ۵ موروثی است از
# `providers/lrclib.py:_DURATION_TOLERANCE_S` — تنها عددی که واقعاً در کد و
# تست‌های همین پروژه بود، نه یک مقدارِ اندازه‌گیری‌شده.
#
# هیچ smoke test زنده‌ای اجرا نشده تا ببینیم ترک‌های واقعی چقدر اختلاف مدت
# دارند (برشِ ابتدا/انتها، سکوتِ اضافه، نسخه‌ی رادیویی). تا آن موقع این عدد
# فقط «بهتر از هیچ» است: تنگ‌ترش یعنی رد کردنِ نتیجه‌ی درست، گشادترش یعنی
# پذیرشِ نسخه‌ی اشتباه. مرزِ فعلی در `test_lyrics_matching.py` قفل شده است.
DEFAULT_DURATION_TOLERANCE_S = 5

# نشانگرهایی که یعنی «ضبطِ دیگری از همان آهنگ»: متن عوض شده یا حداقل
# هم‌خوانیِ زمانی ندارد، پس با نسخه‌ی استودیو یکی نیست.
#
# ⚠️ **بدهیِ شناخته‌شده (فاز ۲B.8، ثبت شد، تغییر نکرد):** `slowed`/`sped`
# در این فهرست برای **LRC همگام** درست‌اند — زمان‌بندیِ نسخه‌ی اسلوموشن با
# استودیو نمی‌خواند، پس اگر به‌جای آن بیاید، پخش خط‌به‌خط غلط می‌شود. ولی
# برای **متنِ plain** ممکن است متنِ معتبری را دور بریزد: نسخه‌ی slowed متنِ
# عیناً یکسان دارد و اگر تنها گزینه باشد، «هیچ متن» بهتر نیست.
#
# پیشنهاد (پیاده نشد): جداکردنِ نشانگرها بر اساسِ نوعِ هم‌زمانی — مثلاً
# `HARD_MARKERS` (live/remix/acoustic/cover/karaoke/unplugged/instrumental/demo)
# که در هر حالت رد می‌شوند، و `TIMING_MARKERS` (slowed/sped) که فقط وقتی
# کاندید داده‌ی زمان‌دار دارد رد شوند. این نیازمندِ عبورِ `sync_type` به
# `unwanted_version_markers` است و تصمیمِ کاربر می‌خواهد.
VERSION_MARKERS = frozenset(
    {
        "live",
        "remix",
        "acoustic",
        "instrumental",
        "slowed",
        "sped",
        "karaoke",
        "cover",
        "unplugged",
        "demo",
    }
)

# ریمستر همان ضبط است با مسترینگِ تازه؛ متنش عوض نشده. جریمه‌کردنش یعنی از
# دست دادنِ نسخه‌ی درست در کاتالوگی که فقط همین را دارد.
SAME_RECORDING_MARKERS = frozenset({"remaster", "remastered", "remasterd"})

# آستانه‌ی شباهتِ املا وقتی کلمه‌ی مشترکی نیست — همان ۰٫۸ که Genius داشت، چون
# «mordi»↔«moordi» را می‌پذیرد (۰٫۹۱) و «mordi»↔«mahdi» را رد می‌کند (۰٫۶).
_SPELLING_RATIO = 0.8


def normalize(text: str | None) -> frozenset[str]:
    """کلمه‌های نرمال‌شده‌ی یک عنوان/نام — مبنای همه‌ی مقایسه‌ها."""
    return frozenset(_WORDS.findall((text or "").lower()))


def content_fingerprint(text: str | None) -> frozenset[str]:
    """
    اثرِ انگشتِ *متنِ* آهنگ — برای تشخیصِ نتیجه‌ی تکراری بین دو Provider.

    چرا لازم است: بعضی Providerها mirror‌اند و از یک مبدأ می‌خوانند (مثلاً
    `lrc.red` و `BiniLyrics` هر دو TTML با namespace یکسان می‌دهند، یا
    `Unison` و `BetterLyrics` قراردادِ یکی دارند). وقتی Providerِ اول از
    قبل جواب داده، رأی‌گیریِ دوباره از mirror فقط وقت و پهنای باند می‌خورد.

    فقط *مجموعه‌ی کلمه‌ها* را نگه می‌دارد: ترتیب و فاصله و timestamp‌ها
    دور می‌ریزند، چون دو mirror می‌توانند یک متن را با شکستِ خطِ متفاوت
    بدهند و باز هم «همان متن» باشند. این عمداً سبک است — برای تشخیصِ
    تکراری‌بودن، نه برای داورِ کیفیت.
    """
    return normalize(text)


def looks_like_a_duplicate(left: str | None, right: str | None) -> bool:
    """
    دو متن عملاً یکی‌اند؟

    ⚠️ مصرف‌کنندهٔ تولیدی: `sources.LyricsSources.duplicate_of` (که خودش از
    `content_fingerprint` استفاده می‌کند). این تابع در جریانِ *خودکارِ*
    Manager صدا زده **نمی‌شود** — عمدی: اگر Providerی با متنِ خطی جواب می‌داد
    و بعدی متنِ کلمه‌ای می‌داده، «تکراری» شمردنشان یعنی دور ریختنِ دادهٔ
    بهتر. تشخیص فقط جایی مصرف می‌شود که کاربر خودش انتخاب می‌کند.
    """
    """
    دو متنِ آهنگ عملاً همان یکی‌اند؟

    معیار: هر دو غیرخالی و مجموعه‌ی کلمه‌هایشان یکی. آستانه‌ی شباهت عمداً
    سخت‌گیر است — «شبیه» کافی نیست. دو اجرای متفاوتِ همان آهنگ (استودیو و
    لایو) کلمه‌های مشترکِ زیادی دارند، پس با آستانه‌ی نرم اشتباهاً تکراری
    شمرده می‌شدند و نسخه‌ی درست دور می‌افتاد.
    """
    left_words = content_fingerprint(left)
    right_words = content_fingerprint(right)
    if not left_words or not right_words:
        return False
    return left_words == right_words


def spelling_similarity(want: str | None, got: str | None) -> float:
    """
    شباهتِ املا در بازه‌ی [۰،۱]، مستقل از ترتیب کلمه‌ها.

    برای رومانیزه‌ی فارسی لازم است: «Mordi» و «Moordi» هیچ کلمه‌ی مشترکی
    ندارند ولی یک آهنگ‌اند.
    """
    left = " ".join(sorted(normalize(want)))
    right = " ".join(sorted(normalize(got)))
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def unwanted_version_markers(got_title: str | None, want_title: str | None) -> frozenset[str]:
    """
    نشانگرهای نسخه‌ای که در عنوانِ نتیجه هست و در عنوانِ درخواستی نیست.

    نسبت به عنوانِ *درخواستی* سنجیده می‌شود، نه مطلق: کاربری که خودش
    «Barf (Live)» خواسته باید لایو بگیرد نه استودیو.
    """
    return (normalize(got_title) & VERSION_MARKERS) - normalize(want_title)


def duration_matches(
    candidate_ms: int | None,
    wanted_ms: int | None,
    tolerance_s: int = DEFAULT_DURATION_TOLERANCE_S,
) -> bool | None:
    """
    مدتِ کاندید با مدتِ خواسته‌شده می‌خواند؟

    سه حالته عمداً، چون دو حالت کافی نیست:
      `None` — بی‌سیگنال: یکی از دو طرف مدت ندارد (یا ۰ است). نه تأیید، نه رد.
      `True` — هم‌خوان، در بازه‌ی تحمل.
      `False` — متناقض: هر دو عدد دارند و نمی‌خوانند. شاهدِ مخالف.

    تفکیکِ `None` از `False` همان چیزی است که جلوی باگِ قبلی را می‌گیرد:
    نتیجه‌ای که مدتش را اعلام نکرده نباید مثل نتیجه‌ای رفتار کند که مدتِ
    دیگری را اعلام کرده است.
    """
    if not candidate_ms or not wanted_ms:
        return None
    return abs(candidate_ms - wanted_ms) <= tolerance_s * 1000


@dataclass(frozen=True)
class MatchScore:
    """نتیجه‌ی سنجشِ یک کاندید. تصمیمِ نهایی با مصرف‌کننده است، نه اینجا."""

    title_overlap: frozenset[str]
    artist_overlap: frozenset[str]
    spelling: float
    duration: bool | None
    unwanted_markers: frozenset[str]
    # آیا از این Provider هنرمند خواسته بودیم؟ بدونش، نبودِ همپوشانیِ هنرمند
    # با «هنرمندِ ناهمخوان» اشتباه گرفته می‌شد.
    artist_expected: bool = True

    @property
    def title_matches(self) -> bool:
        """همپوشانیِ کلمه، یا املاِ نزدیک وقتی هنرمند هم خورده باشد."""
        return bool(self.title_overlap) or self.spelling >= _SPELLING_RATIO

    @property
    def artist_matches(self) -> bool:
        return bool(self.artist_overlap)

    @property
    def acceptable(self) -> bool:
        """
        آیا این کاندید اصلاً قابلِ استفاده است؟

        قاعده: مدت نباید *متناقض* باشد، عنوان باید بخورد، و هنرمند هم باید
        بخورد مگر اینکه اصلاً هنرمندی نخواسته باشیم. نشانگرِ نسخه اینجا رد
        نمی‌کند — آن تصمیمِ ترجیحِ ترتیبی است (`rank_candidates`)، نه شرطِ
        پذیرش، چون نسخه‌ی علامت‌دارِ تنها بهتر از هیچ متنی است.
        """
        if self.duration is False or not self.title_matches:
            return False
        return self.artist_matches or not self.artist_expected


def score_candidate(
    *,
    want_title: str,
    want_artist: str = "",
    got_title: str | None,
    got_artist: str | None = "",
    candidate_duration_ms: int | None = None,
    wanted_duration_ms: int | None = None,
    tolerance_s: int = DEFAULT_DURATION_TOLERANCE_S,
) -> MatchScore:
    """
    یک کاندید را در برابر خواسته بسنج.

    همه‌چیز اینجا خالص است: نه شبکه، نه زمان، نه فایل. پس هر Provider
    می‌تواند بی‌دردسر صدا بزند و تست هم بی‌mock بنویسد.
    """
    return MatchScore(
        title_overlap=normalize(want_title) & normalize(got_title),
        artist_overlap=normalize(want_artist) & normalize(got_artist),
        spelling=spelling_similarity(want_title, got_title),
        duration=duration_matches(candidate_duration_ms, wanted_duration_ms, tolerance_s),
        unwanted_markers=unwanted_version_markers(got_title, want_title),
        artist_expected=bool(normalize(want_artist)),
    )


def rank_candidates(scored: list[tuple[int, MatchScore]]) -> list[int]:
    """
    ایندکسِ کاندیدها را به‌ترتیبِ اولویت مرتب کن.

    اولویت: بی‌نشانگرِ نسخه ← هم‌مدت ← املاِ نزدیک‌تر. نشانگرِ نسخه‌ی ناخواسته
    آخر می‌افتد ولی حذف نمی‌شود؛ اگر تنها گزینه باشد همان انتخاب می‌شود.
    """
    return [
        idx
        for idx, _ in sorted(
            scored,
            key=lambda pair: (
                bool(pair[1].unwanted_markers),
                pair[1].duration is not True,
                -pair[1].spelling,
            ),
        )
    ]
