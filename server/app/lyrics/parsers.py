"""
پارسرهای متن: LRC خطی، LRC تقویت‌شده (Enhanced LRC) و TTML → مدلِ مشترکِ `Lyrics`.

هر Provider شکلِ خامِ خودش را دارد (LRC خطی، LRC کلمه‌ای، TTML) ولی همه‌ی
مصرف‌کننده‌ها یک چیز می‌خواهند: `Lyrics.lines`. اگر تبدیل را داخلِ هر Provider
بنویسیم، سه پیاده‌سازیِ متفاوت از یک قاعده‌ی واحد می‌شود — همان اشتباهی که
`matching.py` برای تطبیق جلویش را گرفت.

قواعدِ کلیِ این ماژول:

۱. هیچ استثنایی بیرون نمی‌زند. ورودیِ خراب → `None`، یا نتیجه‌ی جزئی از
   خط‌هایی که سالم پارس شدند. پارسر روی داده‌ی اینترنت کار می‌کند؛ یک فایلِ
   نیمه‌خراب نباید کلِ fetch را بیندازد.
۲. زمان همه‌جا میلی‌ثانیه‌ی صحیح (int) است — واحدِ `LyricLine.start_ms` و
   `LyricWord.start_ms`. کسرِ اعشاریِ LRC (صدم‌ثانیه) به ms تبدیل می‌شود.
۳. پارسِ ما هرگز `synced` را عوض نمی‌کند. Providerها همان رشته‌ی خامِ منبع را
   در `synced` می‌گذارند؛ این ماژول فقط `lines` را پر می‌کند.

⚠️ دروغِ رایج: TTML استانداردِ واحدی برای «کدام ریشه‌ی زمانی» ندارد. `ttp:tickRate`
و `ttp:frameRate` در خودِ سند می‌آیند و اگر نباشند مقدارِ پیش‌فرضِ spec لازم
می‌شود؛ اینجا پیش‌فرض‌های ساده‌ی مستندشده گذاشته شده و در گزارش «محتاجِ
راستی‌آزمایی با سندِ واقعی» ثبت شده است.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .models import LyricLine, LyricWord, Lyrics

# ---------------------------------------------------------------- زمان

# [mm:ss.xx] و [mm:ss:xx] و [mm:ss] — دقیقاً همان الگوی `src/lib/lrc.ts`
_LRC_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# متادیتای LRC. مقدار ممکن است خط جدید داشته باشد، پس `.` با DOTALL نه؛
# ولی `[ar:...]` تک‌خطی است و `$` کافی است.
_LRC_META = re.compile(r"^\[(ar|ti|al|length|offset):(.*)\]$", re.IGNORECASE)
# <mm:ss.xx> — تگِ کلمه در LRC تقویت‌شده
_WORD_TAG = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")

# زمانِ ساعتِ TTML: hh:mm:ss.fff ، mm:ss.fff ، و شکلِ فریمی hh:mm:ss:ff.sub
#
# ترتیبِ تطبیق مهم است: شکلِ فریمی یک کولونِ *اضافه* دارد (`ss:ff`) و شکلِ
# ساعتی یک نقطه دارد (`ss.fff`). الگوی فریمی اگر اول بیاید `00:00:12.500` را
# هم می‌گیرد و «۱۲» را فریم حساب می‌کند — یعنی ۵۰۰ms به‌جای ۱۲۵۰۰ms.
_TTML_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d+))?$")
_TTML_FRAMES = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}):(\d+)(?:\.(\d+))?$")
# زمانِ آفست: یک یا چند «عدد + واحد»، مثل `1500ms` یا `2m30s`.
# spec ترکیبِ واحدها را مجاز می‌داند و منابع واقعی از آن استفاده می‌کنند.
_TTML_OFFSET_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s|f|t)")
_TTML_OFFSET_UNITS = {"h", "m", "s", "ms", "f", "t"}

# namespaceها. با local-name تطبیق می‌دهیم چون پیشوندها در سندهای واقعی
# دلخواه‌اند و نامِ کاملِ namespace تنها چیزی است که ثابت می‌ماند.
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_TTM_METADATA = "http://www.w3.org/ns/ttml#metadata"
_TTP_PARAMETER = "http://www.w3.org/ns/ttml#parameter"

# DOCTYPE و ENTITY در XML هیچ مصرفِ مشروعی در متنِ آهنگ ندارند و فقط درِ
# حمله‌ی «billion laughs» و entity expansion هستند. کتابخانه‌ی استاندارد
# entity داخلی را بسط می‌دهد، پس قبل از پارس ردشان می‌کنیم.
_FORBIDDEN_XML = re.compile(r"<!\s*(doctype|entity)", re.IGNORECASE)

# سقفِ تعداد خط، تا یک سندِ متورم حافظه را نخورد
_MAX_LINES = 5000


def _frac_to_ms(frac: str | None) -> int:
    """
    کسرِ اعشاریِ LRC → ms.

    «صدم‌ثانیه» است نه دهم: `[00:01.5]` یعنی ۵۰۰ms نه ۵۰. پس به سه رقم
    راست‌چین پر می‌شود، عیناً همان کاری که `lrc.ts:tagTime` می‌کند.
    """
    if not frac:
        return 0
    return int(frac.ljust(3, "0")[:3])


def _lrc_tag_ms(match: re.Match[str]) -> int:
    minutes, seconds, frac = match.group(1), match.group(2), match.group(3)
    return int(minutes) * 60_000 + int(seconds) * 1_000 + _frac_to_ms(frac)


# ---------------------------------------------------------------- LRC


def _parse_offset(raw: str) -> int:
    """
    مقدارِ `[offset:...]` به ms. نامعتبر → ۰.

    ⚠️ **علامت، محتاجِ راستی‌آزمایی:** قراردادِ نوشتاریِ LRC می‌گوید
    «+ زمان را جلو می‌اندازد». اینجا `effective = tag - offset` گرفته شده،
    یعنی `offset:+500` متن را ۵۰۰ms **زودتر** نشان می‌دهد. بعضی پخش‌کننده‌ها
    عکسش را پیاده کرده‌اند. تا وقتی با یک فایلِ واقعیِ دارای offset سنجیده
    نشود، این یک انتخابِ مستندشده است نه یک قراردادِ تأییدشده.
    """
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return 0


def _lrc_lines(text: str, *, words: bool) -> list[LyricLine]:
    """هسته‌ی مشترکِ LRC خطی و تقویت‌شده."""
    offset = 0
    out: list[LyricLine] = []

    for raw in text.splitlines():
        row = raw.strip()
        if not row:
            continue

        if meta := _LRC_META.match(row):
            if meta.group(1).lower() == "offset":
                offset = _parse_offset(meta.group(2))
            continue

        tags = list(_LRC_TAG.finditer(row))
        if not tags:
            # خطِ بی‌تگ: متادیتای ناشناس یا متنِ آزاد. نادیده گرفته می‌شود،
            # چون «زمانِ نامعلوم» را نمی‌شود در خطِ زمان‌دار جا داد.
            continue

        body = _LRC_TAG.sub("", row).strip()
        parsed_words = _word_tags(body) if words else ()

        # یک خط می‌تواند چند تگِ زمانی داشته باشد (همان متن در چند لحظه).
        for tag in tags:
            start = max(0, _lrc_tag_ms(tag) - offset)
            out.append(
                LyricLine(
                    start_ms=start,
                    text=parsed_words_text(parsed_words) if parsed_words else body,
                    words=parsed_words,
                )
            )
            if len(out) >= _MAX_LINES:
                break
        if len(out) >= _MAX_LINES:
            break

    return out


def parsed_words_text(words: tuple[LyricWord, ...]) -> str:
    """متنِ کاملِ یک خط از روی کلمه‌هایش — همان چیزی که UI نمایش می‌دهد."""
    return "".join(w.text for w in words)


def _word_tags(body: str) -> tuple[LyricWord, ...]:
    """
    کلمه‌های زمان‌دارِ یک خط.

    قاعده‌ی `lrc.ts`: فاصله‌ی بین دو تگ به کلمه‌ی *قبلی* می‌چسبد تا گرادیانِ
    رنگ از روی فاصله هم طبیعی رد شود، و متنِ قبل از اولین تگ کلمه نیست و
    می‌افتد (چون زمان ندارد).
    """
    tags = list(_WORD_TAG.finditer(body))
    if not tags:
        return ()

    words: list[LyricWord] = []
    cursor = 0
    for tag in tags:
        gap = body[cursor : tag.start()]
        if words:
            words[-1] = LyricWord(
                start_ms=words[-1].start_ms, text=words[-1].text + gap, end_ms=None
            )
        words.append(LyricWord(start_ms=_lrc_tag_ms(tag), text=""))
        cursor = tag.end()
    words[-1] = LyricWord(
        start_ms=words[-1].start_ms, text=words[-1].text + body[cursor:].rstrip(), end_ms=None
    )

    if not any(w.text.strip() for w in words):
        return ()
    return tuple(words)


def _fill_line_indices(lines: list[LyricLine]) -> list[LyricLine]:
    """مرتب‌سازی بر اساس زمان و شماره‌گذاریِ صریح (`LyricLine.index`)."""
    lines.sort(key=lambda line: line.start_ms)
    return [
        LyricLine(
            start_ms=line.start_ms,
            text=line.text,
            end_ms=line.end_ms,
            words=line.words,
            index=i,
            role=line.role,
        )
        for i, line in enumerate(lines)
    ]


def _fill_word_ends(lines: list[LyricLine]) -> list[LyricLine]:
    """
    `end_ms` کلمه‌ها را پر کن.

    پارسر فقط شروعِ هر کلمه را می‌بیند (تگِ LRC همین را می‌دهد). پایانِ یک
    کلمه = شروعِ کلمه‌ی بعدی؛ و پایانِ کلمه‌ی آخر = شروعِ خطِ بعدی. برای خطِ
    آخر پایان نامعلوم می‌ماند (`None`) و UI از طولِ ترک استفاده می‌کند.
    """
    out: list[LyricLine] = []
    for i, line in enumerate(lines):
        if not line.words:
            out.append(line)
            continue
        next_start = lines[i + 1].start_ms if i + 1 < len(lines) else None
        filled: list[LyricWord] = []
        for j, word in enumerate(line.words):
            if j + 1 < len(line.words):
                end = line.words[j + 1].start_ms
            else:
                end = next_start
            filled.append(LyricWord(start_ms=word.start_ms, text=word.text, end_ms=end))
        out.append(
            LyricLine(
                start_ms=line.start_ms,
                text=line.text,
                end_ms=next_start,
                words=tuple(filled),
                index=line.index,
                role=line.role,
            )
        )
    return out


def parse_lrc(text: str | None) -> Lyrics | None:
    """
    LRC خطی → `Lyrics`.

    چند تگ در یک خط، متادیتای `[ar:] [ti:] [al:] [length:] [offset:]`.
    `offset` اعمال می‌شود. خطِ بی‌تگ نادیده می‌رود. هیچ تگِ زمانی = `None`.
    """
    if not text:
        return None
    try:
        lines = _fill_word_ends(_fill_line_indices(_lrc_lines(text, words=False)))
    except Exception:
        return None
    if not lines:
        return None
    return Lyrics(
        plain="\n".join(line.text for line in lines),
        synced=to_lrc(lines),
        format="lrc",
        sync_type="line",
        lines=tuple(lines),
    )


def parse_enhanced_lrc(text: str | None) -> Lyrics | None:
    """
    LRC تقویت‌شده → `Lyrics` با زمان‌بندیِ کلمه‌ای.

    اگر خط‌ها تگِ کلمه نداشته باشند، مثل LRC خطی رفتار می‌کند ولی
    `sync_type` را `line` می‌گذارد — نه `word`. برچسبِ اشتباه بدتر از نبودِ
    برچسب است: UI روی `sync_type` تصمیم می‌گیرد.
    """
    if not text:
        return None
    try:
        lines = _fill_word_ends(_fill_line_indices(_lrc_lines(text, words=True)))
    except Exception:
        return None
    if not lines:
        return None
    has_words = any(line.words for line in lines)
    return Lyrics(
        plain="\n".join(line.text for line in lines),
        synced=to_enhanced_lrc(lines) if has_words else to_lrc(lines),
        format="enhanced_lrc" if has_words else "lrc",
        sync_type="word" if has_words else "line",
        lines=tuple(lines),
    )


# ---------------------------------------------------------------- TTML


def _ttml_time(raw: str | None, ctx: "_TtmlClock") -> int | None:
    """یک عبارتِ زمانیِ TTML → ms. نامفهوم → `None`."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None

    if clock := _TTML_CLOCK.match(value):
        hours = int(clock.group(1) or 0)
        ms = hours * 3_600_000 + int(clock.group(2)) * 60_000 + int(clock.group(3)) * 1_000
        frac = clock.group(4)
        if frac:
            # کسرِ ثانیه: ۳ رقم = ms، کمتر = دهم/صدم ثانیه (راست‌چین)، بیشتر = کسرِ واقعی.
            ms += (
                int(frac.ljust(3, "0")[:3])
                if len(frac) <= 3
                else int(round(float(f"0.{frac}") * 1000))
            )
        return ms

    if frames := _TTML_FRAMES.match(value):
        hours = int(frames.group(1) or 0)
        ms = hours * 3_600_000 + int(frames.group(2)) * 60_000 + int(frames.group(3)) * 1_000
        return ms + ctx.frames_to_ms(int(frames.group(4)), frames.group(5))

    # `0s` یک زمانِ کاملاً معتبر است، پس بررسیِ None لازم است نه truthiness —
    # با `if offset := ...` خطِ شروع‌ازصفر بی‌صدا حذف می‌شد.
    return _parse_offset_time(value, ctx)


def _parse_offset_time(value: str, ctx: "_TtmlClock") -> int | None:
    """
    زمانِ آفستِ TTML → ms. تنها اگر *کلِ* رشته از «عدد+واحد» ساخته شده باشد
    قبول می‌شود، وگرنه `12.5` بی‌واحد هم به‌عنوان ثانیه خوانده می‌شد.
    """
    parts = list(_TTML_OFFSET_PART.finditer(value))
    if not parts or "".join(part.group(0) for part in parts) != value:
        return None

    total = 0.0
    for part in parts:
        amount, unit = float(part.group(1)), part.group(2)
        if unit == "h":
            total += amount * 3_600_000
        elif unit == "m":
            total += amount * 60_000
        elif unit == "s":
            total += amount * 1_000
        elif unit == "ms":
            total += amount
        elif unit == "f":
            total += ctx.frames_to_ms(int(amount), None)
        elif unit == "t":
            total += ctx.ticks_to_ms(int(amount))
    return int(round(total))


class _TtmlClock:
    """
    نرخ‌های زمانیِ سندِ TTML.

    همه‌ی این‌ها *اختیاری*‌اند و اگر در سند نباشند، spec پیش‌فرض‌هایی دارد که
    در عمل همه پیاده‌سازها با آن موافق نیستند. اینجا فقط مقداری گذاشته شده که
    برای سندهای متعارفِ متنِ آهنگ درست است؛ سندهای فریمی/تیکی نادرند و
    عددِ دقیقشان باید با سندِ واقعی سنجیده شود.
    """

    def __init__(self, root: ET.Element) -> None:
        self.frame_rate = self._float(root, f"{{{_TTP_PARAMETER}}}frameRate") or 25.0
        self.tick_rate = self._float(root, f"{{{_TTP_PARAMETER}}}tickRate")
        if self.tick_rate is None:
            multiplier = self._multiplier(root)
            self.tick_rate = self.frame_rate * multiplier

    @staticmethod
    def _float(root: ET.Element, name: str) -> float | None:
        raw = root.get(name)
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _multiplier(root: ET.Element) -> float:
        raw = root.get(f"{{{_TTP_PARAMETER}}}frameRateMultiplier")
        if not raw:
            return 1.0
        parts = raw.split()
        if len(parts) != 2:
            return 1.0
        try:
            numerator, denominator = int(parts[0]), int(parts[1])
        except ValueError:
            return 1.0
        return numerator / denominator if denominator else 1.0

    def frames_to_ms(self, frames: int, subframes: str | None) -> int:
        if self.frame_rate <= 0:
            return 0
        total = frames
        if subframes:
            total += float(f"0.{subframes}")
        return int(round(total * 1000 / self.frame_rate))

    def ticks_to_ms(self, ticks: int) -> int:
        if self.tick_rate <= 0:
            return 0
        return int(round(ticks * 1000 / self.tick_rate))


def _local(tag: str) -> str:
    """نامِ محلیِ تگ/اتریبیوت، بدونِ namespace."""
    return tag.rpartition("}")[2]


def _attr(element: ET.Element, name: str) -> str | None:
    """اتریبیوت را با نامِ محلی پیدا کن — پیشوندِ namespace مهم نیست."""
    if name in element.attrib:
        return element.attrib[name]
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return None


def _span_ms(element: ET.Element, ctx: _TtmlClock) -> tuple[int | None, int | None]:
    """`begin`/`end`/`dur` یک عنصر را به (شروع، پایان) تبدیل کن."""
    begin = _ttml_time(_attr(element, "begin"), ctx)
    end = _ttml_time(_attr(element, "end"), ctx)
    if end is None:
        duration = _ttml_time(_attr(element, "dur"), ctx)
        if duration is not None and begin is not None:
            end = begin + duration
        elif duration is not None:
            end = duration
    return begin, end


def _element_text(element: ET.Element, *, strip: bool = True) -> str:
    """
    متنِ یک عنصر.

    `strip=False` برای `<span>` لازم است: فاصله‌ی انتهاییِ یک کلمه بخشی از
    آن کلمه است و اگر برداشته شود، `"one "` و `"two"` به هم می‌چسبند و
    LRC تقویت‌شده‌ی بازتولیدشده غلط می‌شود.
    """
    text = "".join(element.itertext())
    return text.strip() if strip else text


def _ttml_paragraph(element: ET.Element, ctx: _TtmlClock, index: int) -> LyricLine | None:
    """یک `<p>` → یک `LyricLine`، با کلمه‌های `<span>` داخلش."""
    begin, end = _span_ms(element, ctx)
    if begin is None:
        return None

    words: list[LyricWord] = []
    for child in element:
        if _local(child.tag) != "span":
            continue
        child_begin, child_end = _span_ms(child, ctx)
        text = _element_text(child, strip=False)
        if child_begin is None or not text.strip():
            continue
        words.append(LyricWord(start_ms=child_begin, text=text, end_ms=child_end))

    text = _element_text(element)
    if not text and not words:
        return None

    return LyricLine(
        start_ms=begin,
        text=text,
        end_ms=end,
        words=tuple(words),
        index=index,
        role=_attr(element, "role"),
    )


def parse_ttml(text: str | None) -> Lyrics | None:
    """
    TTML → `Lyrics`. فقط کتابخانه‌ی استانداردِ XML.

    امنیت: DOCTYPE و ENTITY قبل از پارس رد می‌شوند (billion laughs / XXE).
    ورودیِ خراب → `None`. سندِ بی‌`<p>` زمان‌دار → `None`.

    پشتیبانی: clock-time، offset-time، tick، `<p>`/`<span>`،
    `begin`/`end`/`dur`، `xml:lang`، `ttm:role`، ترتیبِ خط در
    `LyricLine.index`، زبان در `Lyrics.language`.
    """
    if not text:
        return None
    if _FORBIDDEN_XML.search(text):
        return None

    try:
        root = ET.fromstring(text)
    except Exception:
        return None

    if _local(root.tag) != "tt":
        # بعضی منابع بدونِ ریشه‌ی `<tt>` یک `<body>` یا `<div>` تنها می‌دهند
        if _local(root.tag) not in ("body", "div"):
            return None

    ctx = _TtmlClock(root)
    language = _attr(root, "lang")

    lines: list[LyricLine] = []
    try:
        for element in root.iter():
            if _local(element.tag) != "p":
                continue
            line = _ttml_paragraph(element, ctx, len(lines))
            if line is None:
                continue
            # زبانِ سند از ریشه می‌آید؛ `xml:lang` روی خودِ خط فقط اگر ریشه
            # چیزی نگفته باشد استفاده می‌شود.
            if language is None and (line_lang := _attr(element, "lang")):
                language = line_lang
            lines.append(line)
            if len(lines) >= _MAX_LINES:
                break
    except Exception:
        # پارسِ جزئی بهتر از هیچ است: هر چه تا اینجا سالم بود برمی‌گردد.
        if not lines:
            return None

    if not lines:
        return None

    has_words = any(line.words for line in lines)
    return Lyrics(
        plain="\n".join(line.text for line in lines),
        format="ttml",
        sync_type="word" if has_words else "line",
        lines=tuple(lines),
        language=language,
    )


# ---------------------------------------------------------------- سریال‌سازی


def _stamp(ms: int) -> str:
    """
    ms → `mm:ss.cc`.

    ⚠️ **اتلافِ عمدی:** LRC فقط صدم‌ثانیه دارد، پس `ms` به نزدیک‌ترین صدم
    گرد می‌شود و حداکثر ۵ms از دست می‌رود. این گردکردن در یک‌جا انجام
    می‌شود و carry را خودش مدیریت می‌کند (۱۵۰۰ms → `00:01.50` نه `00:00.150`).
    """
    total_centis = round(max(0, ms) / 10)
    minutes, remainder = divmod(total_centis, 6_000)
    seconds, centis = divmod(remainder, 100)
    return f"{minutes:02d}:{seconds:02d}.{centis:02d}"


def to_lrc(lines: tuple[LyricLine, ...] | list[LyricLine]) -> str:
    """خط‌ها → LRC خطی. همان قالبی که `src/lib/lrc.ts` می‌خواند."""
    return "\n".join(f"[{_stamp(line.start_ms)}]{line.text}" for line in lines)


def to_enhanced_lrc(lines: tuple[LyricLine, ...] | list[LyricLine]) -> str:
    """
    خط‌ها → LRC تقویت‌شده (`[line]<word>text<word>text`).

    خطی که کلمه ندارد ساده می‌ماند — نه تگِ خالی، نه از دست رفتنِ خط. برای
    رفت‌وبرگشتِ کاملِ زمان‌بندیِ کلمه‌ای باید هر کلمه `start_ms` داشته باشد
    که همیشه دارد؛ `end_ms` در LRC جا نمی‌شود و هنگام خواندن دوباره از
    شروعِ کلمه‌ی بعدی ساخته می‌شود.
    """
    out: list[str] = []
    for line in lines:
        if not line.words:
            out.append(f"[{_stamp(line.start_ms)}]{line.text}")
            continue
        body = "".join(f"<{_stamp(word.start_ms)}>{word.text}" for word in line.words)
        out.append(f"[{_stamp(line.start_ms)}]{body}")
    return "\n".join(out)
