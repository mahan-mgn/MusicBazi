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
from .db import GUEST_ID
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
    # نگارش‌های دستکاری‌شده، سرعت‌تغییریافته یا نسخه‌های جادویی/جایگزین
    "magical",
    "magical version",
    "alternative version",
    "alt version",
    "slow",
    "slow reverb",
    "slowed reverb",
    "slowed down",
    "fast version",
    "faster",
    "ai cover",
    "vocal cover",
    "acoustic",
    "acoustic cover",
    "remake",
    "re-recorded",
    "rerecorded",
    "tribute",
    "parody",
    "tiktok version",
    "tiktok edit",
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
POSITIVE = (
    "official audio",
    "topic",
    "provided to youtube",
    "full album",
    "official visualizer",
    "official lyric video",
    "original mix",
)

CANDIDATES = 12

# خطای جستجو همیشه یعنی «منبع در دسترس نیست» — نه؛ گاهی یک قطعیِ لحظه‌ایِ
# شبکه است که تلاشِ دوباره همان نتیجه را می‌دهد. چون ساندکلاد اولِ اولویت است،
# بیرون‌انداختنش با یک خطای گذرا یعنی فایلِ یوتیوبیِ کم‌کیفیت به‌جای فایلِ اصلیِ
# ساندکلاد، حتی وقتی ترک همان‌جا هست. پس یک تلاشِ دوباره قبل از رفتن سراغِ
# منبعِ بعدی. «ترک در این منبع نبود» خطا نیست — لیستِ خالی برمی‌گردد و به‌طور
# عادی منبعِ بعدی امتحان می‌شود؛ این مکانیزم فقط برای استثناهاست.
SOURCE_RETRIES = 1
SOURCE_RETRY_DELAY = 2.0

_LEADING_TRACK_NUM = re.compile(r"^\d{1,3}\s*[-–—.]?\s*")

# نگاشت ترک‌های خاص یا گزارش‌شده به آدرس قطعی و اصلی‌شان
# کلید: (normalized_artist, normalized_title)
CANONICAL_TRACK_OVERRIDES: dict[tuple[str, str], str] = {
    ("sinazza", "sex drug"): "https://soundcloud.com/sinazza/sex-drug-6",
    ("sinazza", "deja vu"): "https://soundcloud.com/sinazza/deja-vu",
    ("dorcci", "b hessi"): "https://www.youtube.com/watch?v=P8Y8KwliBKo",
    ("دورچی", "بی حسی"): "https://www.youtube.com/watch?v=P8Y8KwliBKo",
    ("lithe", "lychee martini"): "https://soundcloud.com/lithe9/lychee-martini",
    ("dorcci", "addi"): "https://www.youtube.com/watch?v=tw9ZOCCkgvw",
    ("دورچی", "اددی"): "https://www.youtube.com/watch?v=tw9ZOCCkgvw",
    ("دورچی", "ادی"): "https://www.youtube.com/watch?v=tw9ZOCCkgvw",
    ("dorcci", "young morvarid"): "https://www.youtube.com/watch?v=61Cz3eOdWKA",
    ("دورچی", "یانگ مروارید"): "https://www.youtube.com/watch?v=61Cz3eOdWKA",
    ("tlkhoon", "havasam"): "https://music.youtube.com/watch?v=AK3KLv7MWno",
    ("talkhoon", "havasam"): "https://music.youtube.com/watch?v=AK3KLv7MWno",
    ("matin fattahi", "havasam"): "https://music.youtube.com/watch?v=AK3KLv7MWno",
    ("تلخون", "حواسم"): "https://music.youtube.com/watch?v=AK3KLv7MWno",
    ("متین فتاحی", "حواسم"): "https://music.youtube.com/watch?v=AK3KLv7MWno",
}


def is_youtube_video(track: Track) -> bool:
    """
    بررسی اینکه آیا ترک یک ویدیوی مستقل / موزیک ویدیو در بخش Videos یوتیوب است.
    در بخش Videos، کاربر خواهان پخش دقیق فایل صوتی همان موزیک ویدیو است
    و نباید با نسخه استودیویی، انتشار رسمی یا اورراید جایگزین شود.
    فقط بخش Releases یوتیوب (OLAK...) و پلتفرم YouTube Music شامل استخراج استودیویی هستند.
    """
    if track.source != "youtube":
        return False
    if track.albumId and "OLAK" in track.albumId:
        return False
    if "list=OLAK" in (track.sourceUrl or ""):
        return False
    return True


def _clean_candidate_title(title: str) -> str:
    """شماره‌ی ترک ابتدای عنوان را حذف می‌کند تا 06. Sex Drug یا 06 Sex Drug با عنوان اصلی مچ شود."""
    return _LEADING_TRACK_NUM.sub("", title.strip()).strip() or title.strip()


def _is_sinazza_sex_drug(track: Track) -> bool:
    title_str = (track.title or "").lower()
    artist_str = (track.artist or "").lower()
    url_str = (track.sourceUrl or "").lower()
    album_str = (track.album or "").lower()

    has_sex_drug = (
        ("sex" in title_str and "drug" in title_str)
        or "sex-drug" in url_str
    )
    has_sinazza = (
        "sinazza" in artist_str
        or "sinazza" in title_str
        or "sinazza" in url_str
        or "vision" in album_str
    )
    return has_sex_drug and has_sinazza


def _is_sinazza_deja_vu(track: Track) -> bool:
    title_str = (track.title or "").lower()
    artist_str = (track.artist or "").lower()
    url_str = (track.sourceUrl or "").lower()
    album_str = (track.album or "").lower()
    clean_title = _clean_candidate_title(title_str).lower()

    has_deja_vu = (
        ("deja" in title_str and "vu" in title_str)
        or ("deja" in clean_title and "vu" in clean_title)
        or "dejavu" in title_str
        or "2dufjajfrk0xyb2snx4wdp" in url_str
        or "deja-vu" in url_str
    )
    has_sinazza = (
        "sinazza" in artist_str
        or "sinazza" in title_str
        or "sinazza" in url_str
        or "vision" in album_str
    )
    return has_deja_vu and has_sinazza


def _is_dorcci_b_hessi(track: Track) -> bool:
    title_str = (track.title or "").lower()
    artist_str = (track.artist or "").lower()
    url_str = (track.sourceUrl or "").lower()
    album_str = (track.album or "").lower()

    has_b_hessi = (
        ("b" in title_str and "hessi" in title_str)
        or ("bi" in title_str and "hessi" in title_str)
        or "بی حسی" in title_str
        or "بی‌حسی" in title_str
        or "2750780811" in url_str
        or "6897r1e9kfd1kpetb9mtxc" in url_str
    )
    has_dorcci = (
        "dorcci" in artist_str
        or "دورچی" in artist_str
        or "dorcci" in title_str
        or "دورچی" in title_str
    )
    return has_b_hessi and has_dorcci


def _is_dorcci_addi(track: Track) -> bool:
    title_str = (track.title or "").lower()
    artist_str = (track.artist or "").lower()
    url_str = (track.sourceUrl or "").lower()

    clean_title = _clean_candidate_title(title_str).lower()
    has_addi = (
        "addi" in title_str
        or "addi" in clean_title
        or "اددی" in title_str
        or "ادی" in title_str
        or "addi" in url_str
        or "1yfa" in url_str
        or "3278339721" in url_str
        or "1802135132" in url_str
        or "tw9zocckgvw" in url_str
    )
    has_dorcci = (
        "dorcci" in artist_str
        or "دورچی" in artist_str
        or "dorcci" in title_str
        or "دورچی" in title_str
    )
    return has_addi and has_dorcci


def _is_dorcci_young_morvarid(track: Track) -> bool:
    title_str = (track.title or "").lower()
    artist_str = (track.artist or "").lower()
    url_str = (track.sourceUrl or "").lower()

    clean_title = _clean_candidate_title(title_str).lower()
    # مهم: فقط عنوان و URL بررسی می‌شوند، نه نام آلبوم، تا قطعات دیگر مثل BOY تداخل پیدا نکنند
    has_young_morvarid = (
        ("young" in title_str and "morvarid" in title_str)
        or ("young" in clean_title and "morvarid" in clean_title)
        or "یانگ مروارید" in title_str
        or "یانگ‌مروارید" in title_str
        or "young-morvarid" in url_str
        or "0gy6" in url_str
        or "3278339731" in url_str
        or "1802135133" in url_str
        or "61cz3eodwka" in url_str
    )
    has_dorcci = (
        "dorcci" in artist_str
        or "دورچی" in artist_str
        or "dorcci" in title_str
        or "دورچی" in title_str
    )
    return has_young_morvarid and has_dorcci


def _is_lithe_lychee_martini(track: Track) -> bool:
    title_str = (track.title or "").lower()
    artist_str = (track.artist or "").lower()
    url_str = (track.sourceUrl or "").lower()

    has_lychee_martini = (
        ("lychee" in title_str and "martini" in title_str)
        or "3644604352" in url_str
        or "7oqdfvu8muwzsrbpmxs1hs" in url_str
    )
    has_lithe = "lithe" in artist_str or "lithe" in title_str
    return has_lychee_martini and has_lithe


def _is_tlkhoon_havasam(track: Track) -> bool:
    if is_youtube_video(track):
        return False
    title_str = (track.title or "").lower()
    artist_str = (track.artist or "").lower()
    url_str = (track.sourceUrl or "").lower()
    track_id = (track.id or "").lower()

    clean_title = _clean_candidate_title(title_str).lower()
    has_havasam = (
        ("havasam" in title_str)
        or ("havasam" in clean_title)
        or ("حواسم" in title_str)
        or ("حواسم" in clean_title)
        or ("havasam" in url_str)
        or ("3279339531" in url_str)
        or ("3279339531" in track_id)
        or ("32xqkd" in url_str)
        or ("32xqkd" in track_id)
        or ("ak3klv7mwno" in url_str)
        or ("ak3klv7mwno" in track_id)
        or ("soundcloud.com/tlkhoon/havasam" in url_str)
    )
    has_artist = (
        ("tlkhoon" in artist_str)
        or ("talkhoon" in artist_str)
        or ("تلخون" in artist_str)
        or ("matin fattahi" in artist_str)
        or ("متین فتاحی" in artist_str)
        or ("tlkhoon" in title_str)
        or ("talkhoon" in title_str)
        or ("تلخون" in title_str)
        or ("tlkhoon" in url_str)
        or ("talkhoon" in url_str)
    )
    is_known_id = (
        ("3279339531" in url_str)
        or ("3279339531" in track_id)
        or ("32xqkd" in url_str)
        or ("32xqkd" in track_id)
        or ("ak3klv7mwno" in url_str)
        or ("ak3klv7mwno" in track_id)
        or ("soundcloud.com/tlkhoon/havasam" in url_str)
    )
    return (has_havasam and has_artist) or is_known_id


def _canonical_override(track: Track) -> Candidate | None:
    """اگر لینک قطعی و تاییدشده‌ای برای این ترک ثبت شده باشد، همان را برمی‌گرداند."""
    if is_youtube_video(track):
        return None
    if _is_sinazza_sex_drug(track):
        return Candidate(
            url="https://soundcloud.com/sinazza/sex-drug-6",
            title=track.title or "Sex Drug",
            uploader=track.artist or "Sinazza",
            duration_ms=track.durationMs,
            score=100.0,
            source="soundcloud",
        )
    if _is_sinazza_deja_vu(track):
        return Candidate(
            url="https://soundcloud.com/sinazza/deja-vu",
            title=track.title or "Deja Vu",
            uploader=track.artist or "Sinazza",
            duration_ms=track.durationMs,
            score=100.0,
            source="soundcloud",
        )
    if _is_dorcci_b_hessi(track):
        return Candidate(
            url="https://www.youtube.com/watch?v=P8Y8KwliBKo",
            title=track.title or "B HESSI",
            uploader=track.artist or "Dorcci",
            duration_ms=track.durationMs or 124000,
            score=100.0,
            source="youtube",
        )
    if _is_dorcci_addi(track):
        return Candidate(
            url="https://www.youtube.com/watch?v=tw9ZOCCkgvw",
            title=track.title or "ADDI",
            uploader=track.artist or "Dorcci",
            duration_ms=track.durationMs or 388_000,
            score=100.0,
            source="youtube",
        )
    if _is_dorcci_young_morvarid(track):
        return Candidate(
            url="https://www.youtube.com/watch?v=61Cz3eOdWKA",
            title=track.title or "YOUNG MORVARID",
            uploader=track.artist or "Dorcci",
            duration_ms=track.durationMs or 130_000,
            score=100.0,
            source="youtube",
        )
    if _is_lithe_lychee_martini(track):
        return Candidate(
            url="https://soundcloud.com/lithe9/lychee-martini",
            title=track.title or "Lychee Martini",
            uploader=track.artist or "Lithe",
            duration_ms=track.durationMs or 122000,
            score=100.0,
            source="soundcloud",
        )
    if _is_tlkhoon_havasam(track):
        if track.source == "soundcloud":
            return Candidate(
                url="https://soundcloud.com/tlkhoon/havasam",
                title=track.title or "Havasam",
                uploader=track.artist or "Tlkhoon",
                duration_ms=199_000,
                score=100.0,
                source="soundcloud",
            )
        return Candidate(
            url="https://music.youtube.com/watch?v=AK3KLv7MWno",
            title=track.title or "Havasam",
            uploader=track.artist or "Tlkhoon",
            duration_ms=199_000,
            score=100.0,
            source="youtube_music",
        )

    norm_artist = _normalize(_primary_artist(track.artist))
    norm_title = _normalize(_clean_candidate_title(_search_title(track.title)))
    url = CANONICAL_TRACK_OVERRIDES.get((norm_artist, norm_title))
    if not url:
        return None
    source = (
        "soundcloud"
        if "soundcloud.com" in url
        else "youtube_music"
        if "music.youtube.com" in url
        else "youtube"
    )
    return Candidate(
        url=url,
        title=track.title,
        uploader=track.artist,
        duration_ms=track.durationMs,
        score=100.0,
        source=source,
    )


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


def score_candidate(
    track: Track,
    title: str,
    uploader: str,
    duration_ms: int,
    candidate_album: str | None = None,
) -> float:
    """۰ تا ۱۰۰. مدت‌زمان مهم‌ترین سیگنال است چون جعل‌ناپذیرترین‌شان است."""
    clean_title = _clean_candidate_title(title)
    haystack = _tokens(f"{clean_title} {uploader}")
    if candidate_album:
        haystack |= _tokens(candidate_album)

    title_match = max(
        _overlap(_tokens(track.title), haystack),
        _overlap(_tokens(track.title), _tokens(clean_title)),
        _overlap(_tokens(track.title), _tokens(title)),
    )

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
    # بانس ترک رسمی با کانال یا آپلودکننده منطبق با هنرمند
    if uploader_is_artist:
        score += 8
    if uploader_is_artist and (
        _tokens(title) == _tokens(track.title) or _tokens(clean_title) == _tokens(track.title)
    ):
        score += 4

    has_album_match = False
    # تطابق متادیتای آلبوم: امتیاز مثبت برای آلبوم یکسان و جریمه برای آلبوم متناقض
    if track.album and candidate_album:
        album_tokens = _tokens(track.album)
        cand_album_tokens = _tokens(candidate_album)
        if album_tokens and cand_album_tokens:
            album_overlap = _overlap(album_tokens, cand_album_tokens)
            if album_overlap >= 0.5:
                score += 15
                has_album_match = True
            elif cand_album_tokens - album_tokens:
                score -= 10
    elif track.album and not candidate_album:
        # اگر آلبوم کاندیدا صریحاً ثبت نشده اما نام آلبوم در عنوان/آپلودکننده آمده
        album_tokens = _tokens(track.album)
        if album_tokens and _overlap(album_tokens, _tokens(f"{title} {uploader}")) >= 0.8:
            score += 10
            has_album_match = True

    # اگر عنوان ترک واژه‌های معتبر دارد ولی کاندیدا هیچ‌کدام از آن‌ها را ندارد،
    # این اثر قطعه‌ی دیگری است و نباید تنها به خاطر مدت زمان یکسان تایید شود
    track_title_tokens = _tokens(track.title)
    if track_title_tokens and title_match == 0.0:
        return 0.0

    # اگر هنرمند ترک مشخص است ولی کاندیدا هیچ اثری از هنرمند (یا آلبوم) در عنوان،
    # آپلودکننده یا متادیتا ندارد، این کاندیدا اثر هنرمند دیگری با نام مشابه است
    # و جریمه سنگین دریافت می‌کند تا هرگز از آستانه قبولی (MIN_SCORE) رد نشود.
    if primary_tokens and artist_match == 0.0 and not has_album_match:
        score -= 50.0

    # کاندیدایی که تطابق هنرمند یا آلبوم ندارد هرگز نباید به آستانه قطعیت (GOOD_ENOUGH) برسد
    if primary_tokens and artist_match < 0.3 and not has_album_match:
        score = min(score, 65.0)

    if track.durationMs and duration_ms:
        delta = abs(track.durationMs - duration_ms) / 1000
        # کاندیدِ کوتاه‌تر از ۶۰ ثانیه وقتی ترک کامل است هرگز سگمنتِ معتبر نیست (پیش‌نمایشِ فروشگاه، اینترو، کلیپ).
        if duration_ms < 60_000 and track.durationMs >= 120_000:
            return 0.0

        rel_delta = delta / (track.durationMs / 1000) if track.durationMs >= 30_000 else 0.0

        # گیت سخت‌گیرانه تطابق مدت‌زمان:
        # اگر انحراف مدت‌زمان بیش از ۵ ثانیه باشد و درصد انحراف نسبت به طول آهنگ بیش از ۳.۵٪ باشد
        # (مانند اختلاف ۳۰ ثانیه‌ای نسخه ۳:۴۹ نسبت به ۳:۱۹ که ۱۵٪ slowed است، یا نسخه‌های sped-up)،
        # کاندیدا دستکاری‌شده / نسخه اشتباه است و باید کاملاً رد صلاحیت شود (score = 0.0) تا سیستم
        # متوقف نشده و خودکار به سراغ منبع بعدی در کاتالوگ برود.
        if delta > 5.0 and rel_delta > 0.035:
            return 0.0

        if delta <= 2:
            score += 30
        elif delta <= 4:
            score += 18
        elif delta <= 5:
            score += 5
        else:
            score -= 20
            score = min(score, 60.0)
    elif not duration_ms:
        score -= 5

    low = f"{title} {uploader}".lower()
    # عبارت منفی فقط وقتی بد است که خودِ عنوانِ ترک آن کلمه را نداشته باشد
    track_low = track.title.lower()

    # کلمات دستکاری تمپو، بازنشر غیررسمی یا ادیت‌های سرعت رد صلاحیت قطعی دارند
    DISQUALIFYING_MODS = (
        "slowed", "sped up", "speed up", "nightcore", "slow reverb",
        "slowed reverb", "slowed down", "magical version", "tiktok edit", "distort"
    )
    for word in DISQUALIFYING_MODS:
        if _mentions(low, word) and not _mentions(track_low, word):
            return 0.0

    for word in NEGATIVE:
        if _mentions(low, word) and not _mentions(track_low, word):
            score -= 18
    for word in POSITIVE:
        if _mentions(low, word):
            score += 8
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


def _queries(track: Track, include_all_artists: bool = False) -> list[str]:
    """
    کوئری‌ها به‌ترتیبِ «دقیق ولی نه سخت‌گیر» تا «آخرین تیر».

    کوئریِ قدیمی همه‌ی هنرمندها را با هم می‌فرستاد و برای ترک‌های چندهنرمندی —
    که در فارسی یعنی تقریباً هر فیچرینگی — هیچ نتیجه‌ای برنمی‌گرداند، حتی وقتی
    خودِ ترک عیناً روی ساندکلاد بود. کوئریِ دوم برای وقتی است که نامِ هنرمند
    اصلاً در آن نسخه نمی‌آید (حسابِ فیچرینگ، املای متفاوت، خطِ فارسی در برابر
    فینگلیش)؛ چون هنرمند از کوئری می‌افتد، آستانه‌اش هم بالاتر است.
    """
    title = _search_title(track.title)
    clean_title = _clean_candidate_title(title)
    primary = _primary_artist(track.artist)
    queries = [f"{primary} - {title}".strip(" -"), f"{primary} {title}".strip()]
    if clean_title != title:
        queries.append(f"{primary} - {clean_title}".strip(" -"))
        queries.append(f"{primary} {clean_title}".strip())
    if track.album and _search_title(track.album).strip():
        clean_album = _search_title(track.album).strip()
        queries.append(f"{primary} - {clean_album} - {title}".strip(" -"))
        queries.append(f"{primary} {clean_album} {title}".strip(" -"))
        if clean_title != title:
            queries.append(f"{primary} - {clean_album} - {clean_title}".strip(" -"))
            queries.append(f"{primary} {clean_album} {clean_title}".strip(" -"))
    if include_all_artists:
        artists = [a.strip() for a in _ARTIST_SPLIT.split(track.artist) if a.strip()]
        for extra in artists[1:]:
            if extra and extra != primary:
                queries.append(f"{extra} - {title}".strip(" -"))
    queries.append(clean_title if clean_title != title else title)
    return list(dict.fromkeys(q for q in queries if q))


def _search_youtube_music(
    track: Track,
    min_score: float | None = MIN_SCORE,
    include_all_artists: bool = False,
    user_id: str = GUEST_ID,
) -> list[Candidate]:
    try:
        from .providers import youtube_music
        if not youtube_music.enabled():
            return []
    except Exception:
        return []

    found: list[Candidate] = []
    title_only_queries = {_search_title(track.title), _clean_candidate_title(_search_title(track.title))}
    for query in _queries(track, include_all_artists=include_all_artists):
        floor = (
            max(min_score or 0.0, TITLE_ONLY_MIN_SCORE)
            if query in title_only_queries and min_score is not None
            else min_score
        )

        try:
            # YouTube Music کاتالوگِ باز است و کلید نمی‌خواهد، پس `uid` به آن
            # نمی‌رسد؛ کوکیِ شخصی فقط در لایهٔ استخراجِ صدا لازم است.
            results = youtube_music.search(query, limit=CANDIDATES)
            for item in (results.tracks if hasattr(results, "tracks") else []):
                url = item.sourceUrl or (f"https://music.youtube.com/watch?v={item.id.removeprefix('ytm:track:')}" if item.id else "")
                if not url:
                    continue
                score = score_candidate(
                    track, item.title, item.artist, item.durationMs, candidate_album=getattr(item, "album", None)
                )
                if floor is not None and score < floor:
                    continue
                found.append(
                    Candidate(
                        url=url,
                        title=item.title,
                        uploader=item.artist,
                        duration_ms=item.durationMs,
                        score=score,
                        source="youtube_music",
                    )
                )
        except Exception as exc:
            log.warning("جستجوی YouTube Music برای «%s» خطا داد: %s", query, exc)

        if found:
            break

    return found


def _search_soundcloud(
    track: Track,
    min_score: float | None = MIN_SCORE,
    include_all_artists: bool = False,
    user_id: str = GUEST_ID,
) -> list[Candidate]:
    try:
        from .providers import soundcloud

        if not soundcloud.enabled():
            return []
    except Exception:
        return []

    found: list[Candidate] = []
    title_only_queries = {_search_title(track.title), _clean_candidate_title(_search_title(track.title))}
    for query in _queries(track, include_all_artists=include_all_artists):
        floor = (
            max(min_score or 0.0, TITLE_ONLY_MIN_SCORE)
            if query in title_only_queries and min_score is not None
            else min_score
        )

        try:
            entries = soundcloud.search_tracks(query, limit=CANDIDATES)
            for entry in entries:
                if not entry:
                    continue
                title = entry.get("title") or ""
                uploader = entry.get("artist") or entry.get("uploader") or ""
                duration_ms = int(float(entry.get("duration") or 0) * 1000)
                url = entry.get("webpage_url") or ""
                if not url:
                    continue

                score = score_candidate(
                    track, title, uploader, duration_ms, candidate_album=entry.get("album")
                )
                if floor is not None and score < floor:
                    continue
                found.append(
                    Candidate(
                        url=url,
                        title=title,
                        uploader=uploader,
                        duration_ms=duration_ms,
                        score=score,
                        source="soundcloud",
                    )
                )
        except Exception as exc:
            log.debug("جستجوی مستقیم SoundCloud برای «%s» ناموفق بود: %s", query, exc)

        # فقط در صورتی که کاندیدای قطعی (GOOD_ENOUGH) پیدا شده باشد حلقه متوقف شود؛
        # در غیر این صورت کوئری‌های بعدی برای یافتن ترک اصلی در کانال رسمی امتحان می‌شوند
        if any(c.score >= GOOD_ENOUGH for c in found):
            break

    found.sort(key=lambda c: c.score, reverse=True)
    return found


def _search_source(
    track: Track,
    source: str,
    min_score: float | None = MIN_SCORE,
    include_all_artists: bool = False,
    user_id: str = GUEST_ID,
) -> list[Candidate]:
    """`min_score=None` یعنی بدون آستانه — حالتِ `browse` که تصمیم با کاربر است."""
    if source == "youtube_music":
        return _search_youtube_music(
            track, min_score, include_all_artists=include_all_artists, user_id=user_id
        )
    if source == "soundcloud":
        sc_found = _search_soundcloud(
            track, min_score, include_all_artists=include_all_artists, user_id=user_id
        )
        if sc_found:
            return sc_found

    prefix = SEARCH_PREFIX.get(source)
    if not prefix:
        return []

    options = ydl.opts(
        user_id=user_id,
        skip_download=True,
        extract_flat="in_playlist",
        ignoreerrors=True,
    )

    found: list[Candidate] = []
    title_only_queries = {_search_title(track.title), _clean_candidate_title(_search_title(track.title))}
    for query in _queries(track, include_all_artists=include_all_artists):
        floor = (
            max(min_score or 0.0, TITLE_ONLY_MIN_SCORE)
            if query in title_only_queries and min_score is not None
            else min_score
        )

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
    track: Track,
    source: str,
    min_score: float | None = MIN_SCORE,
    include_all_artists: bool = False,
    user_id: str = GUEST_ID,
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
            try:
                return _search_source(
                    track,
                    source,
                    min_score,
                    include_all_artists=include_all_artists,
                    user_id=user_id,
                )
            except TypeError:
                return _search_source(track, source, min_score, user_id=user_id)
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


def _search_all_sources(
    track: Track,
    sources: Iterable[str] | None = None,
    include_all_artists: bool = False,
    user_id: str = GUEST_ID,
) -> list[Candidate]:
    found: list[Candidate] = []
    for source in AUDIO_SOURCES if sources is None else sources:
        found += _search_source_retrying(
            track, source, include_all_artists=include_all_artists, user_id=user_id
        )

        # منبع بعدی را فقط وقتی می‌زنیم که تا اینجا تطابق قانع‌کننده‌ای نداریم —
        # کاندیداهای دستکاری‌شده یا با اختلاف تمپو/طول سقف ۷۰ می‌گیرند و هرگز
        # باعث قطع زودهنگام نمی‌شوند، پس یوتیوب هم برای آن‌ها بررسی خواهد شد.
        if any(c.score >= GOOD_ENOUGH for c in found):
            break

    found.sort(key=lambda c: c.score, reverse=True)
    return found[:MAX_ATTEMPTS]


_mem_candidate_cache: dict[str, list[Candidate]] = {}


def _candidate_matches_metadata(track: Track, candidate: Candidate) -> bool:
    """
    بررسی انطباق کاندیدای کش‌شده در حافظه یا دیتابیس با متادیتای مرجع ترک.
    اگر مدت زمان ترک مشخص باشد، کاندیدایی که انحراف بیش از ۵ ثانیه و ۳.۵٪ دارد باطل است.
    """
    if track.durationMs >= 30_000 and candidate.duration_ms:
        delta = abs(track.durationMs - candidate.duration_ms) / 1000
        rel_delta = delta / (track.durationMs / 1000)
        if delta > 5.0 and rel_delta > 0.035:
            return False
    cand_low = candidate.title.lower()
    track_low = track.title.lower()
    for word in ("slowed", "sped up", "speed up", "nightcore", "distort"):
        if _mentions(cand_low, word) and not _mentions(track_low, word):
            return False
    return True


def invalidate_cache(track_id: str) -> None:
    """حذف کش حافظه و دیتابیس برای یک ترک (مثلاً وقتی کاندیدا نامعتبر بود)."""
    _mem_candidate_cache.pop(track_id, None)
    try:
        db.delete_resolved_candidates(track_id)
    except Exception:
        pass


def resolve(
    track: Track,
    user_id: str = GUEST_ID,
    use_cache: bool = False,
    sources: Iterable[str] | None = None,
) -> list[Candidate]:
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
    # ویدیوهای مستقل بخش Videos یوتیوب مستقیماً همان فایل صوتی ویدیو را دارند و نباید جایگزین شوند
    if is_youtube_video(track) and track.sourceUrl:
        return [
            Candidate(
                url=track.sourceUrl,
                title=track.title,
                uploader=track.artist,
                duration_ms=track.durationMs,
                score=100.0,
                source="youtube",
            )
        ]

    if override := _canonical_override(track):
        invalidate_cache(track.id)
        return [override]

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

    if use_cache:
        if track.id in _mem_candidate_cache:
            cached_candidates = _mem_candidate_cache[track.id]
            if cached_candidates and all(_candidate_matches_metadata(track, c) for c in cached_candidates):
                return cached_candidates
            invalidate_cache(track.id)
        try:
            cached_rows = db.get_resolved_candidates(track.id)
            if cached_rows is not None:
                candidates = [Candidate(**c) for c in cached_rows]
                if candidates and all(_candidate_matches_metadata(track, c) for c in candidates):
                    _mem_candidate_cache[track.id] = candidates
                    return candidates
                invalidate_cache(track.id)
        except Exception:
            pass

    found = _search_all_sources(track, sources=sources, user_id=user_id)
    if found and use_cache:
        _mem_candidate_cache[track.id] = found
        try:
            db.put_resolved_candidates(track.id, [asdict(c) for c in found])
        except Exception:
            pass

    return found


def resolve_fallback(
    track: Track,
    tried_sources: frozenset[str] = frozenset(),
    user_id: str = GUEST_ID,
) -> list[Candidate]:
    """
    فقط منبع‌هایی از AUDIO_SOURCES که هنوز امتحان نشده‌اند را جستجو می‌کند —
    برای وقتی کاندیدهای resolve() (لینکِ مستقیمِ یوتیوب/ساندکلاد، یا نتیجه‌ی
    زودهنگامِ «قانع‌کننده»ی یک منبع که مانع پرسیدن از بقیه شد) در عمل دانلود
    نشدند: DRM، گیتِ ضدربات، حذف‌شده. دوباره‌جستجوی همان منبع(ها) فقط وقت تلف
    می‌کند — نتیجه‌اش همان کاندیدهای از‌قبل‌شکست‌خورده خواهد بود.

    اگر همه‌ی منبع‌ها از قبل امتحان شده بودند، [] برمی‌گردد بدون هیچ جستجویی.
    """
    remaining = [s for s in AUDIO_SOURCES if s not in tried_sources]
    candidates = (
        _search_all_sources(
            track, remaining, include_all_artists=True, user_id=user_id
        )
        if remaining
        else []
    )
    if candidates and any(c.score >= GOOD_ENOUGH for c in candidates):
        try:
            _mem_candidate_cache[track.id] = candidates
            db.put_resolved_candidates(track.id, [asdict(c) for c in candidates])
        except Exception:
            pass
    return candidates


def browse(
    track: Track, source: str | None = None, user_id: str = GUEST_ID
) -> list[Candidate]:
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
    if override := _canonical_override(track):
        found.append(override)

    for name in sources:
        # همان تلاشِ دوباره‌ی `resolve`: خطای گذرای ساندکلاد نباید کاربری را که
        # برای انتخابِ دستی آمده بی‌نتیجه برگرداند
        found += _search_source_retrying(
            track, name, min_score=None, include_all_artists=True, user_id=user_id
        )

    # یکتاسازی بر اساس URL با حفظ اولویت
    seen_urls: set[str] = set()
    deduped: list[Candidate] = []
    for c in found:
        if c.url not in seen_urls:
            seen_urls.add(c.url)
            deduped.append(c)

    deduped.sort(key=lambda c: c.score, reverse=True)
    return deduped[:CANDIDATES]
