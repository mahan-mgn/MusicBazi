"""
چت‌بات پیشنهاد پلی‌لیست بر اساس حال‌وهوا («وایب»).

مسیر تشخیص: اول Gemini (اگر UNSTREAM_GEMINI_API_KEY تنظیم شده)، وگرنه نگاشتِ
کلیدواژه‌ایِ فارسیِ زیر. هر دو مسیر یک شکل خروجی می‌دهند: یک وایبِ شناخته‌شده، یک
پاسخِ همدلانه‌ی فارسی، و چند پیشنهادِ (عنوان، هنرمند).

بعد از تشخیصِ وایب، build_playlist اول سراغِ پلی‌لیست‌های واقعیِ خودِ پلتفرم‌ها
می‌رود (دیزر/اسپاتیفای — همان چیزی که کاربر روی خودِ آن پلتفرم پیدا می‌کرد)، نه
ساختنِ یک لیستِ تک‌ترکی. فقط وقتی هیچ پلی‌لیستِ مناسبی پیدا نشد (پلتفرم قطع،
جستجوی خالی) به روشِ قدیمی برمی‌گردد: هر (عنوان، هنرمند) را در catalog.search
جستجو می‌کند — همان الگویی که رادیوی خودکار در فرانت (lib/radio.ts) استفاده
می‌کند. هیچ‌کدام از حس‌وحالِ عددیِ valence/energy استفاده نمی‌کنند چون آن دو فقط
برای ترک‌های از قبل دانلودشده موجودند (mood.py).

هر مسیر بی‌صدا شکست می‌خورد: بدون کلید، خطای شبکه/JSON، یا پلتفرمِ قطع، همیشه
یک پله پایین‌تر می‌افتد و هیچ‌وقت استثنا پرت نمی‌کند — چت نباید با یک قطعیِ گذرا
از کار بیفتد.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass

import httpx

from . import catalog
from .config import GEMINI_API_KEY, GEMINI_API_URL, GEMINI_MODEL
from .models import AlbumDetail, Playlist, SearchResults, Track, VibeReady, VibeRequest, VibeSuggestion
from .providers import deezer, spotify

log = logging.getLogger(__name__)

# LLM محلیِ تشخیصِ حال‌وهوا؛ کوتاه‌تر از HTTP_TIMEOUT عمومی چون این یک فراخوانیِ
# تکی است، نه یک زنجیره‌ی provider که ذاتاً کند است
LLM_TIMEOUT = 20.0

# سقفِ نهاییِ پلی‌لیست — با MAX_TRACKSِ فرانت (MoodChat.tsx) یکی است؛ اگر
# سرور بیشتر از فرانت بفرستد، اضافه‌ها دور ریخته می‌شوند و فقط پهنای باند
# جستجو هدر رفته. اگر فرانت بیشتر بفرستد، لیستِ کاربر کوتاه‌تر از حد می‌شود.
MAX_TRACKS = 8

# از استخرِ کنسرویِ هر وایب، هر بار همین تعداد به‌طور تصادفی انتخاب می‌شود —
# بدونش کلیک‌های پیاپیِ روی یک چیپ همیشه همان پلی‌لیست را می‌دادند
PICKS_PER_SUGGESTION = 10


@dataclass(frozen=True)
class VibeDef:
    label: str
    keywords: tuple[str, ...]
    reply: str
    picks: tuple[tuple[str, str], ...]


# شش وایبِ آماده — هم چیپ‌های فرانت روی همین کلیدها می‌زنند، هم LLM موظف است
# یکی از همین‌ها را برگرداند، هم کلیدواژه‌ها همین‌جا زندگی می‌کنند
VIBES: dict[str, VibeDef] = {
    "sad": VibeDef(
        label="😢 غمگین",
        keywords=("ناراحت", "غمگین", "غم", "حالم بده", "دلتنگ", "گریه", "افسرده", "بغض", "دپرس"),
        reply="می‌دونم حس بدی داری. این چندتا رو گذاشتم برات — بذار کنارت باشن.",
        picks=(
            ("گریه نکن", "شادمهر عقیلی"),
            ("بی قرار", "محسن یگانه"),
            ("بزن بارون", "فریدون فروغی"),
            ("چتر", "معین"),
            ("جمعه", "فرهاد مهراد"),
            ("مرد تنها", "فرهاد مهراد"),
            ("خداحافظ", "معین"),
            ("Someone Like You", "Adele"),
            ("Fix You", "Coldplay"),
            ("Say Something", "A Great Big World"),
            ("Skinny Love", "Bon Iver"),
            ("Hurt", "Johnny Cash"),
            ("Everybody Hurts", "R.E.M."),
            ("The Sound of Silence", "Simon & Garfunkel"),
            ("Yesterday", "The Beatles"),
        ),
    ),
    "happy": VibeDef(
        label="😊 شاد",
        keywords=("شاد", "خوشحال", "خوبم", "هیجان زده", "سرحال", "شادی"),
        reply="عالیه! بزن بریم با یه پلی‌لیست شاد.",
        picks=(
            ("شاد باش", "بنیامین بهادری"),
            ("بزن برقص", "شادمهر عقیلی"),
            ("قند عسل", "ماکان بند"),
            ("دیوونه", "بنیامین بهادری"),
            ("Happy", "Pharrell Williams"),
            ("Can't Stop the Feeling", "Justin Timberlake"),
            ("Good as Hell", "Lizzo"),
            ("Walking on Sunshine", "Katrina and the Waves"),
            ("I Gotta Feeling", "The Black Eyed Peas"),
            ("Dancing Queen", "ABBA"),
            ("Best Day of My Life", "American Authors"),
            ("Three Little Birds", "Bob Marley"),
            ("September", "Earth, Wind & Fire"),
            ("I Wanna Dance with Somebody", "Whitney Houston"),
        ),
    ),
    "energetic": VibeDef(
        label="🔥 پرانرژی",
        keywords=("پرانرژی", "انرژی", "ورزش", "باشگاه", "هیجان", "تمرین"),
        reply="بریم رو دور تند! این‌ها انرژیت رو می‌برن بالا.",
        picks=(
            ("Eye of the Tiger", "Survivor"),
            ("Uptown Funk", "Mark Ronson"),
            ("Don't Stop Me Now", "Queen"),
            ("Blinding Lights", "The Weeknd"),
            ("بزن برقص", "شادمهر عقیلی"),
            ("قند عسل", "ماکان بند"),
            ("دیوونه", "بنیامین بهادری"),
            ("جیگر", "احسان خواجه امیری"),
            ("Thunderstruck", "AC/DC"),
            ("Stronger", "Kanye West"),
            ("Levitating", "Dua Lipa"),
            ("Physical", "Dua Lipa"),
            ("Titanium", "David Guetta"),
        ),
    ),
    "calm": VibeDef(
        label="😌 آرام",
        keywords=("آروم", "آرامش", "ریلکس", "استرس", "خسته", "خواب", "سکوت"),
        reply="باشه، بریم رو یه ریتم آروم. نفس عمیق بکش.",
        picks=(
            ("Weightless", "Marconi Union"),
            ("River Flows in You", "Yiruma"),
            ("Holocene", "Bon Iver"),
            ("Clair de Lune", "Claude Debussy"),
            ("آروم جانم", "محسن چاوشی"),
            ("نفس", "همایون شجریان"),
            ("پرستو", "علیرضا قربانی"),
            ("باران", "کیهان کلهر"),
            ("Gymnopédie No. 1", "Erik Satie"),
            ("Watermark", "Enya"),
            ("The Night We Met", "Lord Huron"),
            ("Breathe Me", "Sia"),
        ),
    ),
    "romantic": VibeDef(
        label="❤️ عاشقانه",
        keywords=("عاشق", "عشق", "دلبر", "دلتنگتم", "دوستت دارم", "عاشقانه"),
        reply="چه حس قشنگی. این‌ها رو برای همین حال‌وهوا گذاشتم.",
        picks=(
            ("Perfect", "Ed Sheeran"),
            ("All of Me", "John Legend"),
            ("Thinking Out Loud", "Ed Sheeran"),
            ("At Last", "Etta James"),
            ("عاشقتم", "بنیامین بهادری"),
            ("تو خودتی", "احسان خواجه امیری"),
            ("دلبر", "همایون شجریان"),
            ("بی تو", "شادمهر عقیلی"),
            ("Can't Help Falling in Love", "Elvis Presley"),
            ("La Vie en Rose", "Edith Piaf"),
            ("Just the Way You Are", "Bruno Mars"),
            ("A Thousand Years", "Christina Perri"),
        ),
    ),
    "angry": VibeDef(
        label="😤 عصبانی",
        keywords=("عصبانی", "عصبانیت", "خشمگین", "کفری", "خشم"),
        reply="بریزش بیرون. این‌ها همون شدتی رو دارن که الان لازم داری.",
        picks=(
            ("Break Stuff", "Limp Bizkit"),
            ("Killing In the Name", "Rage Against the Machine"),
            ("Bulls on Parade", "Rage Against the Machine"),
            ("Smells Like Teen Spirit", "Nirvana"),
            ("Chop Suey!", "System of a Down"),
            ("Numb", "Linkin Park"),
            ("In the End", "Linkin Park"),
            ("Duality", "Slipknot"),
            ("Bodies", "Drowning Pool"),
            ("Given Up", "Linkin Park"),
            ("Freak on a Leash", "Korn"),
            ("Du Hast", "Rammstein"),
        ),
    ),
    "nostalgic": VibeDef(
        label="📼 نوستالژیک",
        keywords=("نوستالژی", "خاطره", "خاطرات", "یاد قدیما", "دلم برای قدیم تنگ شده", "دلتنگ گذشته"),
        reply="بریم سراغ خاطره‌ها. این‌ها می‌برنت به قدیما.",
        picks=(
            ("جمعه", "فرهاد مهراد"),
            ("مرد تنها", "فرهاد مهراد"),
            ("بی تو", "شادمهر عقیلی"),
            ("دلبر", "همایون شجریان"),
            ("In My Life", "The Beatles"),
            ("The Way We Were", "Barbra Streisand"),
            ("Photograph", "Ed Sheeran"),
            ("Summer of '69", "Bryan Adams"),
            ("Vincent", "Don McLean"),
            ("Landslide", "Fleetwood Mac"),
            ("Yesterday Once More", "Carpenters"),
        ),
    ),
    "focus": VibeDef(
        label="🎯 تمرکز",
        keywords=("تمرکز", "مطالعه", "درس خوندن", "کار دارم", "پروژه", "کنکور", "امتحان"),
        reply="باشه، یه پس‌زمینه‌ی بی‌کلام می‌ذارم که حواس‌پرتت نکنه.",
        picks=(
            ("River Flows in You", "Yiruma"),
            ("Clair de Lune", "Claude Debussy"),
            ("Gymnopédie No. 1", "Erik Satie"),
            ("Weightless", "Marconi Union"),
            ("Nuvole Bianche", "Ludovico Einaudi"),
            ("Divenire", "Ludovico Einaudi"),
            ("Comptine d'un autre été", "Yann Tiersen"),
            ("Spiegel im Spiegel", "Arvo Pärt"),
            ("باران", "کیهان کلهر"),
            ("نفس", "همایون شجریان"),
        ),
    ),
    "heartbreak": VibeDef(
        label="💔 دلشکسته",
        keywords=("دلشکسته", "شکست عشقی", "جدا شدیم", "ترکم کرد", "دلم شکست", "بهم زدیم"),
        reply="سخته... این آهنگ‌ها دقیقاً همون حسو دارن.",
        picks=(
            ("Someone Like You", "Adele"),
            ("When We Were Young", "Adele"),
            ("All Too Well", "Taylor Swift"),
            ("Back to December", "Taylor Swift"),
            ("Someone You Loved", "Lewis Capaldi"),
            ("Jar of Hearts", "Christina Perri"),
            ("Nothing Compares 2 U", "Sinéad O'Connor"),
            ("Skinny Love", "Bon Iver"),
            ("Say Something", "A Great Big World"),
            ("بی تو", "شادمهر عقیلی"),
            ("خداحافظ", "معین"),
        ),
    ),
}

# وقتی نه چیپی زده شده نه کلیدواژه‌ای تشخیص داده شد — چت هیچ‌وقت نباید دست‌خالی بماند
DISCOVER = VibeDef(
    label="🎵 پیشنهادی",
    keywords=(),
    reply="دقیق نفهمیدم چه حالی داری، ولی این‌ها رو این روزها خیلی‌ها گوش می‌دن.",
    picks=(
        ("Blinding Lights", "The Weeknd"),
        ("بی تو", "شادمهر عقیلی"),
        ("Perfect", "Ed Sheeran"),
        ("قند عسل", "ماکان بند"),
        ("Someone Like You", "Adele"),
        ("Happy", "Pharrell Williams"),
        ("Levitating", "Dua Lipa"),
        ("جمعه", "فرهاد مهراد"),
        ("Uptown Funk", "Mark Ronson"),
        ("Dancing Queen", "ABBA"),
    ),
)


# عبارت‌های جستجوی پلی‌لیست به‌ازای هر وایب — یک انگلیسی (پوششِ بهتر روی هر دو
# پلتفرم) و یک فارسی. کلیدها همان کلیدهای VIBES‌اند به‌علاوه‌ی "discover".
PLAYLIST_QUERIES: dict[str, tuple[str, str]] = {
    "sad": ("sad songs", "غمگین"),
    "happy": ("feel good hits", "شاد"),
    "energetic": ("workout motivation", "پرانرژی"),
    "calm": ("chill relax", "آرام"),
    "romantic": ("love songs", "عاشقانه"),
    "angry": ("rage metal", "خشمگین"),
    "nostalgic": ("throwback hits", "نوستالژی"),
    "focus": ("focus instrumental", "تمرکز و مطالعه"),
    "heartbreak": ("breakup songs", "دلشکسته"),
    "discover": ("today's top hits", "پلی لیست محبوب"),
}

# هر بار این تعداد پلی‌لیستِ واقعی قاطی می‌شود — هم تنوعِ پلتفرم هم طولِ پلی‌لیست
PLAYLIST_COUNT = 3
# از هر پلی‌لیستِ انتخاب‌شده همین تعداد ترکِ تصادفی برداشته می‌شود؛ کل پلی‌لیستِ
# صدتایی را نمی‌گیریم — فقط یک نمونه‌ی نماینده
TRACKS_PER_PLAYLIST = 6
# پلی‌لیستِ خیلی‌کوتاه معمولاً خالی یا بی‌ربط است (مثلاً پلی‌لیستِ شخصیِ یک‌ترکه)
MIN_PLAYLIST_TRACKS = 3


@dataclass
class VibeResult:
    vibe: str
    label: str
    reply: str
    picks: list[tuple[str, str]]
    # «چرا این‌ها؟» — فقط مسیرِ LLM آن را دارد؛ مسیرِ کلیدواژه توضیحی نمی‌سازد
    reason: str | None = None


def _sample_picks(pool: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    """
    زیرمجموعه‌ی تصادفی از استخرِ یک وایب — همان چیپ که دوباره زده شود، پلی‌لیستِ
    یکسان ندهد. استخر کوچک‌تر از سهمیه بود یعنی همه‌اش برمی‌گردد.
    """
    if len(pool) <= PICKS_PER_SUGGESTION:
        return list(pool)
    return random.sample(pool, PICKS_PER_SUGGESTION)


def detect_from_keywords(text: str) -> str | None:
    """اولین وایبی که یکی از کلیدواژه‌هایش زیرمجموعه‌ی متن است، یا None."""
    normalized = text.strip()
    if not normalized:
        return None
    for key, definition in VIBES.items():
        if any(kw in normalized for kw in definition.keywords):
            return key
    return None


# --------- قیدهای صریح: «قدیمی»، «ایرانی/فارسی» ---------
#
# وایب («غمگین») یک محورِ حس‌وحال است. درخواست‌های واقعی گاهی یک محورِ دومِ
# مستقل هم دارند — دوره یا زبان («یک پلی‌لیست غمگین از آهنگ‌های قدیمی
# ایرانی»). detect_from_keywords/Gemini فقط محورِ اول را می‌فهمند؛ این بخش
# محورِ دوم را از همان متن جدا می‌خواند تا هم استخرِ کنسروی هم جستجوی
# پلی‌لیستِ واقعی بر اساسش محدود شوند.

OLD_KEYWORDS = ("قدیمی", "قدیم", "کلاسیک", "دهه شصت", "دهه هفتاد")
PERSIAN_KEYWORDS = ("ایرانی", "فارسی", "پرشین")

# هنرمندانِ کلاسیکِ پاپِ فارسی — پیش از دورانِ پاپِ مدرنِ داخلی/تهرانجلسی.
# لیست عمداً کوتاه است: فقط اسم‌هایی که مطمئنیم واقعاً «قدیمی»‌اند، چون
# لیستِ کوتاهِ درست بهتر از لیستِ بلندِ نامطمئن است.
OLD_PERSIAN_ARTISTS = frozenset(
    {
        "فرهاد مهراد",
        "معین",
        "داریوش",
        "گوگوش",
        "ابی",
        "ویگن",
        "عارف",
        "حبیب",
        "فریدون فروغی",
        "کورش یغمایی",
        "هایده",
        "مهستی",
    }
)

_PERSIAN_SCRIPT = re.compile(r"[؀-ۿ]")


@dataclass(frozen=True)
class Qualifiers:
    old: bool = False
    persian_only: bool = False


def detect_qualifiers(text: str, history: list[VibeTurn] | None = None) -> Qualifiers:
    """
    قیدهای دوره/زبان را از متنِ کاربر می‌خواند — مستقل از تشخیصِ خودِ وایب.

    تاریخچه هم اسکن می‌شود (فقط نوبت‌های user): «غمگینِ ایرانیِ قدیمی» و بعد
    «نه آروم‌تر» — قیدِ اول در پیامِ جاری نیست ولی هنوز پابرجاست. بدونِ این،
    حافظه فقط در LLM اثر می‌کرد و فیلترِ پلی‌لیست‌ها بی‌قید می‌شد.
    """
    parts = [text.strip()] + [t.text for t in (history or [])[-HISTORY_TURNS:] if t.role == "user"]
    normalized = " ".join(parts)
    return Qualifiers(
        old=any(kw in normalized for kw in OLD_KEYWORDS),
        persian_only=any(kw in normalized for kw in PERSIAN_KEYWORDS),
    )


def _is_persian(artist: str) -> bool:
    return bool(_PERSIAN_SCRIPT.search(artist))


def _filter_picks(picks: list[tuple[str, str]], qualifiers: Qualifiers) -> list[tuple[str, str]]:
    """
    پیشنهادها را طبق قیدهای صریحِ کاربر محدود می‌کند. هر لایه فقط وقتی اعمال
    می‌شود که نتیجه‌ی غیرخالی بدهد — قیدِ سخت‌گیرانه‌تر نباید چت را دست‌خالی
    بگذارد، فقط باید تا جای ممکن دقیق‌تر کند.
    """
    if qualifiers.old:
        old = [p for p in picks if p[1] in OLD_PERSIAN_ARTISTS]
        if old:
            return old
    if qualifiers.persian_only:
        persian = [p for p in picks if _is_persian(p[1])]
        if persian:
            return persian
    return picks


def _describe_qualifiers(qualifiers: Qualifiers) -> str:
    if qualifiers.old and qualifiers.persian_only:
        return " از قدیمی‌های ایرونی برات گذاشتم."
    if qualifiers.old:
        return " از قدیمی‌ترها برات گذاشتم."
    if qualifiers.persian_only:
        return " همه‌شون ایرونی‌ان."
    return ""


# --------- تشخیصِ حال‌وهوا با Gemini (Google AI Studio) ---------

# سقفِ نوبت‌هایی که از تاریخچه به مدل داده می‌شود. بیشتر از این فقط توکن
# می‌سوزاند؛ «دو پیامِ آخر» تقریباً همه‌ی ارجاع‌های محاوره‌ای را پوشش می‌دهد.
HISTORY_TURNS = 6


def _response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "vibe": {"type": "string", "enum": list(VIBES)},
            "reply": {"type": "string"},
            "reason": {"type": "string"},
            "picks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "artist": {"type": "string"}},
                    "required": ["title", "artist"],
                },
            },
        },
        "required": ["vibe", "reply", "reason", "picks"],
    }


def _parse_llm_json(raw: str) -> VibeResult | None:
    """
    پاسخِ Gemini را به VibeResult تبدیل می‌کند؛ هر انحرافی از قرارداد (وایبِ
    ناشناس، picks خالی، آیتمِ بدشکل) کل پاسخ را رد می‌کند — نیمه‌معتبر بی‌فایده
    است، مسیر کلیدواژه‌ای جایگزینِ کاملی دارد.

    regexِ `{.*}` می‌ماند با وجودِ responseSchema: مدل‌های قدیمی‌تر یا پاسخِ
    سانسور‌شده ممکن است هنوز متنِ آزاد یا ```json بدهند، و این یک‌هزینه‌ای است که
    هر دو حالت را می‌پوشاند.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    vibe = data.get("vibe")
    reply = data.get("reply")
    picks = data.get("picks")
    if vibe not in VIBES or not isinstance(reply, str) or not reply.strip():
        return None
    if not isinstance(picks, list) or not picks:
        return None

    cleaned: list[tuple[str, str]] = [
        (pick["title"].strip(), pick["artist"].strip())
        for pick in picks
        if isinstance(pick, dict)
        and all(isinstance(pick.get(p), str) and pick[p].strip() for p in ("title", "artist"))
    ]
    if not cleaned:
        return None

    # reason اختیاریِ عمداً-سست است: schema آن را required می‌کند ولی مدل‌های
    # قدیمی‌تر ممکن است حذفش کنند — نبودنش نباید کل پاسخِ خوب را باطل کند.
    reason = data.get("reason")
    return VibeResult(
        vibe=vibe,
        label=VIBES[vibe].label,
        reply=reply.strip(),
        picks=cleaned,
        reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
    )


def library_digest() -> str | None:
    """
    خلاصه‌ی یک‌خطیِ سلیقه‌ی کاربر از کتابخانه‌ی خودش — برای system prompt.

    چرا این‌جا نه جستجوی مستقیمِ کتابخانه: پیشنهاد باید از کاتالوگ بیرون بیاید
    (چت برای «چیزی که نداری» است)، ولی دانستنِ اینکه کاربر چه می‌پسندد کیفیتِ
    انتخاب را عوض می‌کند. سه سیگنال کافی است: هنرمندانِ لایک‌شده، مرکزِ حسیِ
    لایک‌ها، و حجمِ کتابخانه. همه از همین dbِ محلی، بدونِ شبکه.
    """
    from . import db

    favorites = db.favorite_jobs()
    if not favorites:
        return None
    artists: dict[str, int] = {}
    centers: list[tuple[float, float]] = []
    for row in favorites[:40]:
        try:
            track = Track.model_validate_json(row["track_json"])
        except Exception:  # noqa: BLE001 — ردیفِ خراب نباید چت را بخواباند
            continue
        artists[track.artist] = artists.get(track.artist, 0) + 1
        if row["valence"] is not None and row["energy"] is not None:
            centers.append((float(row["valence"]), float(row["energy"])))
    top = sorted(artists.items(), key=lambda kv: -kv[1])[:6]
    parts = [f"User's liked artists: {', '.join(a for a, _ in top)}"]
    if centers:
        v = sum(c[0] for c in centers) / len(centers)
        e = sum(c[1] for c in centers) / len(centers)
        parts.append(f"Their taste sits at valence {v:.2f}, energy {e:.2f} (0-1)")
    parts.append(f"Library size: {len(favorites)} liked tracks")
    return " | ".join(parts)


def _contents(req: VibeRequest, text: str) -> list[dict]:
    """
    تاریخچه‌ی گفتگو + پیامِ جاری به شکلِ contentsِ Gemini.

    نقش‌ها همان role‌های خودِ APIاند (user/model)؛ نوبتِ خالی حذف می‌شود تا یک
    پیامِ بی‌محتوا (مثلاً چیپی که برچسبش خالی شده) تاریخچه را شلوغ نکند.
    """
    contents = [
        {"role": turn.role, "parts": [{"text": turn.text[:500]}]}
        for turn in req.history[-HISTORY_TURNS:]
        if turn.role in ("user", "model") and turn.text.strip()
    ]
    contents.append({"role": "user", "parts": [{"text": text}]})
    return contents


async def _call_llm(client: httpx.AsyncClient, req: VibeRequest, text: str) -> VibeResult | None:
    """
    تشخیصِ حال‌وهوا با Gemini — بی‌صدا None برمی‌گرداند اگر کلید نباشد، شبکه
    بیفتد، یا پاسخ معتبر نباشد. suggest() در آن صورت به کلیدواژه می‌افتد.
    """
    if not GEMINI_API_KEY:
        return None

    known = ", ".join(VIBES.keys())
    system = (
        "You are the mood-playlist bot of a Persian music app. You read a short "
        "mood message in Persian or English (possibly a follow-up like 'no, "
        "calmer' or 'same but Iranian') and respond with STRICT JSON only — no "
        "prose, no markdown fences. Shape: "
        '{"vibe": one of [' + known + "], "
        '"reply": a short warm Persian reply (1-2 sentences, matches the mood), '
        '"reason": one short Persian sentence saying WHY these songs fit this '
        "user specifically, "
        '"picks": [{"title": ..., "artist": ...}, ...]}. '
        "picks must be 8 REAL, well-known songs that genuinely fit the mood — "
        "never invent a song. Default to a mix of Persian and international "
        "songs, but the message may also state an explicit constraint beyond "
        "the mood — a language/origin (e.g. only Iranian/Persian songs), an "
        "era (e.g. old/classic vs. new), a decade, a genre, or a specific "
        "artist. When it does, every single pick MUST strictly satisfy that "
        "constraint instead of the default mix: a request for 'a sad playlist "
        "of old Iranian songs' must return ONLY real, well-known CLASSIC "
        "Persian songs (e.g. Farhad Mehrad, Dariush, Googoosh, Ebi, Vigen, "
        "Hayedeh) — no international songs and no modern Persian pop. "
        "Use the conversation history to resolve follow-ups: 'no'/'بازم'/"
        "'آروم‌تر' refer to the previous turn. "
        "If a taste profile is provided below, lean toward that taste but never "
        "repeat songs the user already owns — suggest what they don't have yet."
    )
    digest = await asyncio.to_thread(library_digest)
    if digest:
        system += "\n\nTaste profile: " + digest

    try:
        res = await client.post(
            GEMINI_API_URL.format(model=GEMINI_MODEL),
            # هدر، نه ?key= در آدرس: کلید در query-logها می‌ماند
            headers={"x-goog-api-key": GEMINI_API_KEY, "content-type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": _contents(req, text),
                "generationConfig": {
                    "temperature": 0.7,
                    # 1024 جواب نمی‌داد: فارسی گران‌توکن است و 8 تا picks +
                    # reply + reason از سقف رد می‌شد → JSON نصفه → fallbackِ
                    # بی‌صدا. نشانه‌ی همان حالت: finishReason=MAX_TOKENS
                    "maxOutputTokens": 4096,
                    # gemini-3.6-flash با thinkingِ پیش‌فرض ۸۱۰ توکن فکر
                    # می‌کند و ~۱۶ ثانیه طول می‌کشد — روی شبکه‌ی کند از
                    # LLM_TIMEOUT رد می‌شود و چت بی‌صدا به کلیدواژه می‌افتد.
                    # low: ۲.۷ ثانیه، همان کیفیتِ انتخاب
                    "thinkingConfig": {"thinkingLevel": "low"},
                    "responseMimeType": "application/json",
                    "responseSchema": _response_schema(),
                },
            },
            timeout=LLM_TIMEOUT,
        )
        res.raise_for_status()
        body = res.json()
        # دو حالتِ «۲۰۰ ولی بی‌پاسخ» مخصوصِ Gemini است و هر دو باید به
        # کلیدواژه برگردند، نه اینکه کل چت بمیرد:
        #   promptFeedback.blockReason — متن‌های خشم/غم گاهی سانسور می‌خورند
        #   candidates خالی یا finishReason=MAX_TOKENS — JSON نصفه
        blocked = (body.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            log.info("gemini blocked the mood message (%s), keyword fallback", blocked)
            return None
        candidate = (body.get("candidates") or [{}])[0]
        if candidate.get("finishReason") == "MAX_TOKENS":
            log.warning("gemini answer hit maxOutputTokens, keyword fallback")
        parts = (candidate.get("content") or {}).get("parts") or []
        raw = "".join(p.get("text", "") for p in parts)
        return _parse_llm_json(raw)
    except Exception:  # noqa: BLE001 — قراردادِ بی‌صدا: چت نباید با قطعیِ گذرا بمیرد
        log.warning("gemini vibe call failed", exc_info=True)
        return None


async def suggest(client: httpx.AsyncClient, req: VibeRequest) -> VibeResult:
    """
    تصمیمِ نهایی: Gemini (حتی برای کلیکِ چیپ) > کلیدواژه > پیش‌فرضِ عمومی.

    چیپ قبلاً LLM را دور می‌زد و همیشه همان ریپلایِ ثابت را می‌داد؛ حالا برچسبِ
    چیپ به‌عنوانِ پیام به مدل می‌رود تا انتخاب‌ها با تاریخچه و سلیقه قاطی شوند.
    مسیرِ کلیدواژه دست‌نخورده می‌ماند: بدونِ کلید، چیپ همان رفتارِ همیشگی است.
    """
    text = (req.message or "").strip()
    if not text and req.vibe and req.vibe in VIBES:
        text = VIBES[req.vibe].label

    if text and (result := await _call_llm(client, req, text)):
        return result

    # چیپِ صریح حتی وقتی LLM جواب نمی‌دهد نباید به «حدسِ متن» تبدیل شود:
    # کاربر دقیقاً همان وایب را خواسته
    if req.vibe and req.vibe in VIBES:
        definition = VIBES[req.vibe]
        return VibeResult(
            vibe=req.vibe, label=definition.label, reply=definition.reply, picks=_sample_picks(definition.picks)
        )

    if text and (key := detect_from_keywords(text)):
        definition = VIBES[key]
        return VibeResult(
            vibe=key,
            label=definition.label,
            reply=definition.reply,
            picks=_sample_picks(definition.picks),
        )

    return VibeResult(
        vibe="discover", label=DISCOVER.label, reply=DISCOVER.reply, picks=_sample_picks(DISCOVER.picks)
    )


def _dedupe_key(track: Track) -> tuple[str, str]:
    return (track.title.strip().lower(), track.artist.strip().lower())


async def resolve_tracks(
    client: httpx.AsyncClient, picks: list[tuple[str, str]], exclude: set[str] = frozenset()
) -> list[Track]:
    """
    هر (عنوان، هنرمند) را در کاتالوگ جستجو می‌کند و اولین نتیجه را برمی‌دارد.
    شکستِ یک جستجو (provider افتاده، چیزی پیدا نشد) بقیه را خراب نمی‌کند —
    فقط همان یکی از پلی‌لیست جا می‌ماند.

    `exclude` شناسه‌ی ترک‌هایی است که فرانت قبلاً در همین گفتگو نشان داده —
    تضمینِ سخت‌افزاریِ «بدون تکرار» فقط اینجاست: چه پیشنهاد از استخرِ تصادفی
    بیاید چه از Gemini، اگر به همان ترکِ قبلی برسد همین‌جا حذف می‌شود.
    """
    results = await asyncio.gather(
        *(catalog.search(client, f"{title} {artist}") for title, artist in picks),
        return_exceptions=True,
    )

    seen: set[tuple[str, str]] = set()
    tracks: list[Track] = []
    for outcome in results:
        if not isinstance(outcome, SearchResults) or not outcome.tracks:
            continue
        track = outcome.tracks[0]
        if track.id in exclude:
            continue
        key = _dedupe_key(track)
        if key in seen:
            continue
        seen.add(key)
        tracks.append(track)
        if len(tracks) >= MAX_TRACKS:
            break

    return tracks


async def _search_playlists(
    client: httpx.AsyncClient, vibe_key: str, qualifiers: Qualifiers = Qualifiers()
) -> list[Playlist]:
    """
    پلی‌لیست‌های واقعیِ کاربرها/پلتفرم‌ها برای این وایب — چند عبارتِ جستجو، چند
    پلتفرم، موازی. شکستِ یکی بقیه را خراب نمی‌کند؛ اسپاتیفای بدون کلید همیشه
    خودش خالی برمی‌گرداند (spotify.search_playlists).

    وقتی کاربر صریحاً «قدیمی» خواسته، عبارتِ فارسی با همان کلمه تقویت می‌شود.
    وقتی صریحاً «ایرانی/فارسی» خواسته، عبارتِ انگلیسی اصلاً جستجو نمی‌شود —
    آن عبارت تقریباً همیشه پلی‌لیستِ بین‌المللی برمی‌گرداند، همان چیزی که
    کاربر گفته نمی‌خواهد.
    """
    en_query, fa_query = PLAYLIST_QUERIES.get(vibe_key, PLAYLIST_QUERIES["discover"])
    if qualifiers.old:
        fa_query = f"قدیمی {fa_query}"

    searches = [deezer.search_playlists(client, fa_query)]
    if not qualifiers.persian_only:
        searches += [
            deezer.search_playlists(client, en_query),
            spotify.search_playlists(client, en_query),
        ]

    results = await asyncio.gather(*searches, return_exceptions=True)

    playlists: list[Playlist] = []
    for outcome in results:
        if isinstance(outcome, list):
            playlists += outcome
    return playlists


def _pick_playlists(candidates: list[Playlist]) -> list[Playlist]:
    """
    از میانِ پلی‌لیست‌های پیداشده، حداکثر PLAYLIST_COUNT تا را با تناوب بینِ
    منبع‌ها انتخاب می‌کند — تا وقتی دیزر و اسپاتیفای هر دو جواب داده باشند، هر
    دو در پلی‌لیستِ نهایی نماینده داشته باشند، نه اینکه یکی همه‌جا را بگیرد.
    """
    unique: dict[str, Playlist] = {}
    for p in candidates:
        if p.trackCount >= MIN_PLAYLIST_TRACKS:
            unique.setdefault(p.id, p)

    by_source: dict[str, list[Playlist]] = {}
    for p in unique.values():
        by_source.setdefault(p.source, []).append(p)
    for group in by_source.values():
        random.shuffle(group)

    picked: list[Playlist] = []
    sources = list(by_source)
    while len(picked) < PLAYLIST_COUNT and sources:
        for source in list(sources):
            group = by_source[source]
            if not group:
                sources.remove(source)
                continue
            picked.append(group.pop())
            if len(picked) >= PLAYLIST_COUNT:
                break

    return picked


async def _tracks_from_playlists(
    client: httpx.AsyncClient, playlists: list[Playlist], exclude: set[str]
) -> list[Track]:
    """
    هر پلی‌لیستِ انتخاب‌شده را کامل می‌گیرد (catalog.resolve_ref، هم دیزر هم
    اسپاتیفای را می‌شناسد) و از هرکدام یک زیرمجموعه‌ی تصادفیِ کوچک برمی‌دارد —
    نه کلِ پلی‌لیست را، که می‌تواند صدها ترک باشد.
    """
    details = await asyncio.gather(
        *(catalog.resolve_ref(client, p.sourceUrl or p.id) for p in playlists),
        return_exceptions=True,
    )

    pool: list[Track] = []
    for detail in details:
        if not isinstance(detail, AlbumDetail) or not detail.tracks:
            continue
        candidates = [t for t in detail.tracks if t.id not in exclude]
        random.shuffle(candidates)
        pool += candidates[:TRACKS_PER_PLAYLIST]

    random.shuffle(pool)
    seen: set[tuple[str, str]] = set()
    tracks: list[Track] = []
    for track in pool:
        key = _dedupe_key(track)
        if key in seen:
            continue
        seen.add(key)
        tracks.append(track)
        if len(tracks) >= MAX_TRACKS:
            break

    return tracks


def _describe_playlists(playlists: list[Playlist]) -> str:
    # یک پلی‌لیست ممکن است از چند پلتفرم به‌عنوانِ یکیِ همان‌نام بیاید — تکرارِ
    # «آهنگ های قدیمی با وایب غمگین» ×۳ در جوابِ چت زشت است
    names: list[str] = []
    for p in playlists:
        if p.title and p.title not in names:
            names.append(p.title)
    return f" این‌ها رو از پلی‌لیستِ {'، '.join(f'«{n}»' for n in names)} آوردم." if names else ""


def _owned_files(tracks: list[Track]) -> dict[str, VibeReady]:
    """
    کدام ترک‌های پیشنهادی از قبل در کتابخانه‌اند — با فایلِ آماده، نه با
    «بازدانلودِ همان چیز».

    چرا روی دیسک چک نمی‌شود (مثلِ مسیرِ /api/mix که Path.exists() می‌زند):
    این‌جا فقط می‌خواهیم به فرانت بگوییم «این یکی را داری، استریمش کن»؛ اگر
    فایل رفته باشد، استریم ۴۰۴ می‌دهد و فرانت همان ترک را مثلِ بقیه دانلود
    می‌کند — یک round-trip در حالتِ نادر، در برابرِ یک exists() به‌ازای هر ترک
    در هر درخواستِ چت.
    """
    from . import db, jobs, loudness

    owned = db.owned_refs([t.id for t in tracks])
    out: dict[str, VibeReady] = {}
    for track_id, row in owned.items():
        out[track_id] = VibeReady(
            jobId=row["id"],
            streamUrl=jobs.stream_url(row["id"]),
            lyricsUrl=jobs.lyrics_url(row["id"]) if row["lyrics_path"] else None,
            gainDb=loudness.gain_db(row["loudness"], row["peak"]),
        )
    return out


async def build_playlist(client: httpx.AsyncClient, req: VibeRequest) -> VibeSuggestion:
    """
    نقطه‌ی ورودیِ کاملِ چت‌بات: تشخیصِ وایب، بعد تلاش برای پلی‌لیستِ واقعیِ
    پلتفرم‌ها، و فقط اگر چیزی پیدا نشد برگشت به لیستِ تک‌ترکیِ قدیمی — چت
    هیچ‌وقت دست‌خالی نمی‌ماند.

    قیدهای صریحِ متن («قدیمی»، «ایرانی/فارسی» — detect_qualifiers) هم روی
    جستجوی پلی‌لیستِ واقعی هم روی استخرِ کنسروی اعمال می‌شوند، تا درخواستِ
    ترکیبی («غمگینِ قدیمیِ ایرانی») واقعاً همان را برگرداند، نه فقط وایبِ کلی.
    """
    result = await suggest(client, req)
    qualifiers = detect_qualifiers(req.message or "", req.history)
    exclude = set(req.excludeIds)

    candidates = await _search_playlists(client, result.vibe, qualifiers)
    chosen = _pick_playlists(candidates)

    reply = result.reply + _describe_qualifiers(qualifiers)
    tracks: list[Track] = []
    if chosen:
        tracks = await _tracks_from_playlists(client, chosen, exclude)
        if tracks:
            reply += _describe_playlists(chosen)

    if not tracks:
        tracks = await resolve_tracks(client, _filter_picks(result.picks, qualifiers), exclude)

    owned = await asyncio.to_thread(_owned_files, tracks)
    return VibeSuggestion(
        vibe=result.vibe, label=result.label, reply=reply, tracks=tracks, reason=result.reason, ready=owned
    )
