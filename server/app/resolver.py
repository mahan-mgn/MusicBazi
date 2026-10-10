"""
پیدا کردن بهترین نسخه‌ی قابل دانلود برای یک ترک.

متادیتا از اپل/دیزر می‌آید ولی فایل صوتی آنجا نیست. این ماژول با جستجو در یوتیوب
و امتیازدهی به نتایج، نزدیک‌ترین نسخه را انتخاب می‌کند — همان کاری که spotDL می‌کند.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from functools import lru_cache

from yt_dlp import YoutubeDL

from . import db, ydl
from .config import AUDIO_SOURCES
from .models import Track

log = logging.getLogger(__name__)

# پیشوند جستجوی yt-dlp برای هر منبع
SEARCH_PREFIX = {"youtube": "ytsearch", "soundcloud": "scsearch"}

# عبارت‌هایی که تقریباً همیشه یعنی نسخه‌ی اشتباه
NEGATIVE = (
    "live",
    "cover",
    "remix",
    "karaoke",
    "instrumental",
    "acapella",
    "reaction",
    "tutorial",
    "lesson",
    "concert",
    # بازنشرهای دستکاری‌شده — روی ساندکلاد و یوتیوب برای هر ترکِ محبوبی
    # پرشمارتر از خودِ ترک‌اند. عنوانشان کاملاً با ترک مچ می‌شود و مدتشان هم
    # (جز «slowed») تقریباً همان است، پس امتیازدهی بدون این‌ها بالاترین نمره
    # را دقیقاً به آن‌ها می‌داد: کاربر «Sweater Weather» می‌خواست و نسخه‌ی
    # 8D تحویل می‌گرفت.
    "8d audio",
    # «Kir To Rapfarsi[Distort Version]» روی ساندکلاد دقیقاً کنارِ خودِ ترک
    # می‌نشست: همان عنوان، همان هنرمند، همان ۱۱۱ ثانیه — فقط کلیپ‌شده و بلندتر.
    "distort",
    "slowed",
    "sped up",
    "speed up",
    "nightcore",
    "bass boosted",
    "reverb",
    "pitched",
    "mashup",
    "snippet",
    "teaser",
    "m&m",
    "mix & master",
    "mix and master",
    "type beat",
    "leak",
    "demo",
    # موزیک ویدیوها معمولاً افکت صوتی، دیالوگ، شلیک یا صدای پس‌زمینه دارند
    # و نباید جای نسخه‌ی استودیویی رسمی بنشینند
    "music video",
    "official video",
    "official music video",
    "official mv",
    "موزیک ویدیو",
    "ویدیو کلیپ",
    "اجرای زنده",
    "کاور",
    "ریمیکس",
    "بیکلام",
)
# نشانه‌های نسخه‌ی رسمی استودیویی.
#
# «audio»ی تنها عمداً اینجا نیست: با «official audio» فرق دارد و در عمل بیشتر
# به بازنشرهای «8D AUDIO» و «SLOWED AUDIO» جایزه می‌داد تا به نسخه‌ی رسمی.
# «official music» هم حذف شد چون با «official music video» تداخل داشت.
POSITIVE = ("official audio", "topic", "provided to youtube", "full album")

CANDIDATES = 6

# خطای جستجو همیشه یعنی «منبع در دسترس نیست» — نه؛ گاهی یک قطعیِ لحظه‌ایِ
# شبکه است که تلاشِ دوباره همان نتیجه را می‌دهد. چون ساندکلاد اولِ اولویت است،
# بیرون‌انداختنش با یک خطای گذرا یعنی فایلِ یوتیوبیِ کم‌کیفیت به‌جای فایلِ اصلیِ
# ساندکلاد، حتی وقتی ترک همان‌جا هست. پس یک تلاشِ دوباره قبل از رفتن سراغِ
# منبعِ بعدی. «ترک در این منبع نبود» خطا نیست — لیستِ خالی برمی‌گردد و به‌طور
# عادی منبعِ بعدی امتحان می‌شود؛ این مکانیزم فقط برای استثناهاست.
SOURCE_RETRIES = 1
SOURCE_RETRY_DELAY = 2.0


@dataclass
class Candidate:
    url: str
    title: str
    uploader: str
    duration_ms: int
    score: float
    source: str = "youtube"


def _normalize(text: str) -> str:
    """حذف اعراب، یکسان‌سازی ی/ک عربی، حذف پرانتز و علائم."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    text = re.sub(r"[ً-ْ‌]", "", text)
    text = re.sub(r"[\(\[].*?[\)\]]", " ", text)
    text = re.sub(r"[^\w\s؀-ۿ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if len(t) > 1}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a:
        return 0.0
    return len(a & b) / len(a)


@lru_cache(maxsize=256)
def _phrase(word: str) -> re.Pattern[str]:
    # صرف‌های معمولِ انگلیسی هم باید بگیرند («covers»، «remixed»، «reactions»)،
    # وگرنه مرزِ واژه دقیقاً همان چیزهایی را رد می‌کرد که باید جریمه شوند
    return re.compile(rf"(?<!\w){re.escape(word)}(?:e?s|ed|ing)?(?!\w)")


def _mentions(haystack: str, word: str) -> bool:
    """
    آیا این عبارت به‌عنوان یک *واژه* در متن هست؟

    زیررشته‌ی خالی کافی نیست: «live» داخل «deliverance» و «alive» هم هست و
    «cover» داخل «discover» — نسخه‌ی درست را با جریمه‌ی چیزی که اصلاً نیست
    می‌سوزاند. مرزِ واژه این را می‌بندد بی‌آنکه عبارت‌های چندکلمه‌ای
    («official audio») را بشکند.
    """
    return _phrase(word).search(haystack) is not None


def score_candidate(track: Track, title: str, uploader: str, duration_ms: int) -> float:
    """۰ تا ۱۰۰. مدت‌زمان مهم‌ترین سیگنال است چون جعل‌ناپذیرترین‌شان است."""
    haystack = _tokens(f"{title} {uploader}")

    title_match = _overlap(_tokens(track.title), haystack)

    primary = _primary_artist(track.artist)
    primary_tokens = _tokens(primary)
    artist_tokens = _tokens(track.artist)
    primary_match = _overlap(primary_tokens, haystack)
    all_match = _overlap(artist_tokens, haystack)
    artist_match = max(all_match, 0.7 * primary_match + 0.3 * all_match)

    uploader_is_artist = bool(primary_tokens and _overlap(primary_tokens, _tokens(uploader)) >= 0.8)
    if uploader_is_artist:
        artist_match = max(artist_match, primary_match)

    score = title_match * 45 + artist_match * 25
    # ponytail: بانس ترک رسمی با عنوان تمیز؛ در صورت نیاز به بررسی پیچیده‌تر با متادیتای آلبوم ارتقا یابد
    if uploader_is_artist and _tokens(title) == _tokens(track.title):
        score += 2

    if track.durationMs and duration_ms:
        delta = abs(track.durationMs - duration_ms) / 1000
        # «دو پنجره»ی ۲۹۲ ثانیه‌ای با یک پیش‌نمایشِ ۳۰ ثانیه‌ای تحویل شد و جاب
        # بدون هیچ هشداری ready شد — کاندیدِ کوتاه‌تر از ۶۰ ثانیه وقتی ترک کامل
        # است هرگز سگمنتِ معتبر نیست (پیش‌نمایشِ فروشگاه، اینترو، کلیپ). جریمه
        # سنگین تا پایین لیست برود؛ اگر چیز بهتری نبود، دانلودشدنش از نبودنش
        # بهتر است ولی `jobs` مدتِ فایل واقعی را چک می‌کند و هشدار می‌دهد.
        if duration_ms < 60_000 and track.durationMs >= 120_000:
            score -= 60
        if delta <= 2:
            score += 30
        elif delta <= 5:
            score += 22
        elif delta <= 10:
            score += 10
        elif delta > 30:
            # وقتی عنوان و هنرمند تقریباً کامل match هستند، اختلاف زیاد معمولاً
            # یعنی کاتِ متفاوتِ همان ترک (نسخه‌ی رادیویی/بلندتر در برابر نسخه‌ی
            # اسپاتیفای) نه ترکِ واقعاً اشتباه — جریمه سبک‌تر می‌شود
            exact_text = title_match >= 0.9 and artist_match >= 0.3
            score -= 15 if exact_text else 35
    elif not duration_ms:
        score -= 5

    low = f"{title} {uploader}".lower()
    # عبارت منفی فقط وقتی بد است که خودِ عنوانِ ترک آن کلمه را نداشته باشد
    track_low = track.title.lower()
    for word in NEGATIVE:
        if _mentions(low, word) and not _mentions(track_low, word):
            score -= 18
    for word in POSITIVE:
        if _mentions(low, word):
            score += 6
            break

    return score


MIN_SCORE = 35.0
# بالاتر از این یعنی به تطابق مطمئنیم
GOOD_ENOUGH = 80.0
# حداکثر تعداد کاندیدی که جاب حاضر است امتحان کند
MAX_ATTEMPTS = 4

# آستانه‌ی کوئریِ «فقط عنوان». آن کوئری نامِ هنرمند را ندارد، پس نتیجه‌هایش
# می‌توانند ترکِ هم‌نامِ کسِ دیگری باشند — فقط تطابقِ تقریباً کاملِ عنوان
# به‌علاوه‌ی مدت‌زمانِ نزدیک از این عدد رد می‌شود.
TITLE_ONLY_MIN_SCORE = 70.0

# جداکننده‌های فهرستِ هنرمندها. اسپاتیفای همه‌ی هنرمندهای یک ترک را با کاما به
# هم می‌چسباند («YOUNGRUDEE, 6ehtash») و جستجوی ساندکلاد سخت‌گیر است: هر واژه‌ای
# که در عنوان یا نامِ کاربرِ ترک نباشد نتیجه را *صفر* می‌کند، نه فقط پایین‌تر.
_ARTIST_SPLIT = re.compile(r"\s*(?:[,،;؛&/×]|\bfeat\.?|\bft\.?|\bwith\b)\s*", re.IGNORECASE)
# «(feat. X)»، «(Original Mix)»، «[Explicit]» — کوئری را تنگ می‌کنند بی‌آنکه
# چیزی به شناساییِ ترک اضافه کنند (امتیازدهی هم همین‌ها را دور می‌اندازد)
_BRACKETED = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")


def _primary_artist(artist: str) -> str:
    """فقط هنرمندِ اول — همان که ترک معمولاً روی حسابِ او منتشر شده."""
    return _ARTIST_SPLIT.split(artist.strip(), 1)[0].strip() or artist.strip()


def _search_title(title: str) -> str:
    return _BRACKETED.sub("", title).strip() or title.strip()


def _queries(track: Track) -> list[str]:
    """
    کوئری‌ها به‌ترتیبِ «دقیق ولی نه سخت‌گیر» تا «آخرین تیر».

    کوئریِ قدیمی همه‌ی هنرمندها را با هم می‌فرستاد و برای ترک‌های چندهنرمندی —
    که در فارسی یعنی تقریباً هر فیچرینگی — هیچ نتیجه‌ای برنمی‌گرداند، حتی وقتی
    خودِ ترک عیناً روی ساندکلاد بود. کوئریِ دوم برای وقتی است که نامِ هنرمند
    اصلاً در آن نسخه نمی‌آید (حسابِ فیچرینگ، املای متفاوت، خطِ فارسی در برابر
    فینگلیش)؛ چون هنرمند از کوئری می‌افتد، آستانه‌اش هم بالاتر است.
    """
    title = _search_title(track.title)
    queries = [f"{_primary_artist(track.artist)} - {title}".strip(" -"), title]
    return list(dict.fromkeys(q for q in queries if q))


def _search_source(
    track: Track, source: str, min_score: float | None = MIN_SCORE
) -> list[Candidate]:
    """`min_score=None` یعنی بدون آستانه — حالتِ `browse` که تصمیم با کاربر است."""
    prefix = SEARCH_PREFIX.get(source)
    if not prefix:
        return []

    options = ydl.opts(
        skip_download=True,
        extract_flat="in_playlist",
        ignoreerrors=True,
    )

    found: list[Candidate] = []
    for index, query in enumerate(_queries(track)):
        floor = min_score
        if floor is not None and index > 0:
            floor = max(floor, TITLE_ONLY_MIN_SCORE)

        with YoutubeDL(options) as y:
            info = y.extract_info(f"{prefix}{CANDIDATES}:{query}", download=False)

        for entry in ((info or {}).get("entries") or []):
            if not entry:
                continue
            title = entry.get("title") or ""
            uploader = entry.get("uploader") or entry.get("channel") or ""
            duration_ms = int(float(entry.get("duration") or 0) * 1000)
            url = entry.get("webpage_url") or entry.get("url") or ""
            if not url:
                continue

            score = score_candidate(track, title, uploader, duration_ms)
            if floor is not None and score < floor:
                continue
            found.append(
                Candidate(
                    url=url,
                    title=title,
                    uploader=uploader,
                    duration_ms=duration_ms,
                    score=score,
                    source=source,
                )
            )

        # کوئریِ بعدی فقط وقتی ارزش دارد که این یکی دست‌خالی برگشته باشد؛
        # وگرنه هر جستجو چند ثانیه (ساندکلاد بیشتر) وقتِ اضافه است.
        if found:
            break

    return found


def _search_source_retrying(
    track: Track, source: str, min_score: float | None = MIN_SCORE
) -> list[Candidate]:
    """
    جستجوی یک منبع، با تلاشِ دوباره روی خطا پیش از تسلیم شدن.

    بدون تلاشِ دوباره، یک قطعیِ لحظه‌ایِ شبکه برای ساندکلاد — که اولِ اولویت است —
    بی‌صدا به یوتیوب می‌رفت، حتی وقتی ترک دقیقاً روی ساندکلاد هست (خطای گذرا با
    «اینجا نیست» فرق دارد ولی قبلاً هر دو یک جور رفتار می‌شدند). «ترک در این منبع
    نبود» اصلاً استثنا نیست — لیستِ خالی برمی‌گردد و از این مکانیزم رد می‌شود.
    """
    for attempt in range(SOURCE_RETRIES + 1):
        try:
            return _search_source(track, source, min_score)
        except Exception as exc:  # noqa: BLE001 — هر خطایی از هر منبع یعنی «بعدی»
            if attempt < SOURCE_RETRIES:
                log.info(
                    "جستجوی %s برای «%s» خطا داد (%s) — تلاش دوباره",
                    source,
                    track.title,
                    exc,
                )
                time.sleep(SOURCE_RETRY_DELAY)
                continue
            log.warning(
                "جستجوی %s برای «%s» بعد از %d تلاش شکست خورد: %s",
                source,
                track.title,
                SOURCE_RETRIES + 1,
                exc,
            )
    return []


def _search_all_sources(track: Track, sources: Iterable[str] | None = None) -> list[Candidate]:
    found: list[Candidate] = []
    for source in AUDIO_SOURCES if sources is None else sources:
        found += _search_source_retrying(track, source)

        # منبع بعدی را فقط وقتی می‌زنیم که تا اینجا تطابق قانع‌کننده‌ای نداریم —
        # یعنی یوتیوب فقط زمانی امتحان می‌شود که ساندکلاد چیزی پیدا نکرده یا
        # امتیازش پایین بوده (مثلاً آن ترک اصلاً در ساندکلاد نیست).
        if any(c.score >= GOOD_ENOUGH for c in found):
            break

    found.sort(key=lambda c: c.score, reverse=True)
    return found[:MAX_ATTEMPTS]


_mem_candidate_cache: dict[str, list[Candidate]] = {}


def invalidate_cache(track_id: str) -> None:
    """حذف کش حافظه و دیتابیس برای یک ترک (مثلاً وقتی کاندیدا نامعتبر بود)."""
    _mem_candidate_cache.pop(track_id, None)
    try:
        db.delete_resolved_candidates(track_id)
    except Exception:
        pass


def resolve(track: Track, use_cache: bool = False) -> list[Candidate]:
    """
    کاندیدهای قابل دانلود را مرتب‌شده بر اساس امتیاز برمی‌گرداند.

    لیست برمی‌گردانیم نه یکی، چون «بهترین امتیاز» لزوماً «قابل دانلود» نیست:
    ویدیو ممکن است گیت ضدربات بخورد، ترک ساندکلاد DRM داشته باشد یا لینک مرده باشد.
    صدازننده تا اولین موفقیت پایین می‌رود.

    ترک‌هایی که خودشان از یوتیوب/ساندکلاد آمده‌اند لینک مستقیم دارند و همان
    تنها کاندید است — جستجوی معمولی (به‌خصوص ساندکلاد، حدود صد ثانیه) اینجا
    مفتِ دانلودهای معمولاً موفق نمی‌شود. اگر همان یک لینک DRM داشت یا حذف شده
    بود، `resolve_fallback` همان‌جا که صدا زده می‌شود (jobs._run) جایگزینش را
    پیدا می‌کند — فقط وقتی که واقعاً لازم شود.
    """
    if use_cache:
        if track.id in _mem_candidate_cache:
            return _mem_candidate_cache[track.id]
        try:
            cached_rows = db.get_resolved_candidates(track.id)
            if cached_rows is not None:
                candidates = [Candidate(**c) for c in cached_rows]
                _mem_candidate_cache[track.id] = candidates
                return candidates
        except Exception:
            pass

    if track.source in ("youtube", "youtube_music", "soundcloud") and track.sourceUrl:
        return [
            Candidate(
                url=track.sourceUrl,
                title=track.title,
                uploader=track.artist,
                duration_ms=track.durationMs,
                score=100.0,
                source=track.source,
            )
        ]

    found = _search_all_sources(track)
    if found and use_cache:
        _mem_candidate_cache[track.id] = found
        try:
            db.put_resolved_candidates(track.id, [asdict(c) for c in found])
        except Exception:
            pass

    return found


def resolve_fallback(track: Track, tried_sources: frozenset[str] = frozenset()) -> list[Candidate]:
    """
    فقط منبع‌هایی از AUDIO_SOURCES که هنوز امتحان نشده‌اند را جستجو می‌کند —
    برای وقتی کاندیدهای resolve() (لینکِ مستقیمِ یوتیوب/ساندکلاد، یا نتیجه‌ی
    زودهنگامِ «قانع‌کننده»ی یک منبع که مانع پرسیدن از بقیه شد) در عمل دانلود
    نشدند: DRM، گیتِ ضدربات، حذف‌شده. دوباره‌جستجوی همان منبع(ها) فقط وقت تلف
    می‌کند — نتیجه‌اش همان کاندیدهای از‌قبل‌شکست‌خورده خواهد بود.

    اگر همه‌ی منبع‌ها از قبل امتحان شده بودند، [] برمی‌گردد بدون هیچ جستجویی.
    """
    remaining = [s for s in AUDIO_SOURCES if s not in tried_sources]
    return _search_all_sources(track, remaining) if remaining else []


def browse(track: Track, source: str | None = None) -> list[Candidate]:
    """
    همه‌ی نسخه‌های پیداشده، برای انتخاب دستی.

    سه فرقِ عمدی با `resolve` دارد و هر سه از یک جا می‌آیند: اینجا کسی نشسته که
    انتخاب خودکار را قبول نکرده.

    ۱. آستانه‌ی امتیاز ندارد — دقیقاً وقتی به این صفحه می‌آیی که resolver همه را
       رد کرده باشد. امتیاز نمایش داده می‌شود، ولی تصمیم با کاربر است.
    ۲. لینک مستقیمِ ترک‌های یوتیوب/ساندکلاد را دور می‌زند و واقعاً جستجو می‌کند؛
       وگرنه همیشه همان یک نتیجه برمی‌گشت.
    ۳. منبع را صدازننده تعیین می‌کند؛ بدون آن فقط اولین منبعِ AUDIO_SOURCES
       زده می‌شود (پیش‌فرض: ساندکلاد) و بقیه فقط با درخواست صریح می‌آیند —
       چون جستجوی هرکدام (به‌خصوص ساندکلاد) حدود صد ثانیه طول می‌کشد.
    """
    sources = [source] if source else list(AUDIO_SOURCES[:1])

    found: list[Candidate] = []
    for name in sources:
        # همان تلاشِ دوباره‌ی `resolve`: خطای گذرای ساندکلاد نباید کاربری را که
        # برای انتخابِ دستی آمده بی‌نتیجه برگرداند
        found += _search_source_retrying(track, name, min_score=None)

    found.sort(key=lambda c: c.score, reverse=True)
    return found[:CANDIDATES]
