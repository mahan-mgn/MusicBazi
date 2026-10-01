"""
متن آهنگ از Genius — نیاز به کلید، فقط متن ساده می‌دهد (بدون هم‌زمان‌سازی).

API عمومیِ Genius خودِ متن را نمی‌دهد، فقط جستجو و لینک صفحه؛ متن باید از
HTML همان صفحه استخراج شود. به همین خاطر جایگزینِ LRCLIB است نه اولویت اول:
downloader.fetch_lyrics اول سراغ LRCLIB (بی‌کلید، هم‌زمان‌شده هم می‌دهد) می‌رود
و فقط وقتی چیزی پیدا نکرد نوبت به این می‌رسد.

بلاک‌کننده است: از همان جایی صدا زده می‌شود که LRCLIB زده می‌شود.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

from ..config import GENIUS_ACCESS_TOKEN, GENIUS_API, PROXY

_HEADERS = {"user-agent": "Mozilla/5.0 (compatible; MusicBazi/1.4)"}
_TIMEOUT = 8.0

_BLANK_RUN = re.compile(r"\n{3,}")
_WORDS = re.compile(r"\w+", re.UNICODE)

# جداکننده‌های اسمِ هنرمندِ چندنفره در کاتالوگ‌ها: «Tlkhoon, NoTsH»،
# «Tlkhoon & NoTsH»، «Sepehr Khalse x Sijal»، «… feat. …»
_ARTIST_SPLIT = re.compile(r"\s*(?:,|&|\+|/|؛|،|\bfeat\.?|\bft\.?|\bwith\b|\bx\b)\s*", re.IGNORECASE)

# آستانه‌ی شباهتِ عنوان وقتی کلمه‌ی مشترکی نیست. ۰٫۸ عمداً سخت‌گیر است:
# «mordi»↔«moordi» می‌شود ۰٫۹۱ ولی «mordi»↔«mahdi» می‌شود ۰٫۶.
_TITLE_RATIO = 0.8


@dataclass
class Lyrics:
    plain: str | None
    synced: None = None

    def __bool__(self) -> bool:
        return bool(self.plain)


@dataclass
class SongInfo:
    """آهنگساز/تهیه‌کننده و بقیه‌ی جزئیاتی که هیچ کاتالوگ دیگری نمی‌دهد."""

    writers: list[str]
    producers: list[str]
    album: str | None
    releaseDate: str | None
    artworkUrl: str | None
    url: str | None


def enabled() -> bool:
    return bool(GENIUS_ACCESS_TOKEN)


def _norm(text: str) -> set[str]:
    return set(_WORDS.findall((text or "").lower()))


def _primary(artist: str) -> str:
    """
    فقط هنرمندِ اول. جستجوی Genius با اسمِ چندنفره دست‌خالی برمی‌گردد.

    `q=«Ettefaghaye Bad Tlkhoon, NoTsH»` صفر نتیجه می‌دهد و `q=«Ettefaghaye
    Bad Tlkhoon»` همان ترک را — چون Genius دنبالِ عینِ رشته می‌گردد و اسمِ
    همکار (که هر کاتالوگی جور دیگری می‌نویسدش) به هیچ عنوانی نمی‌خورد.
    """
    parts = [p for p in _ARTIST_SPLIT.split(artist or "") if p.strip()]
    return parts[0].strip() if parts else (artist or "").strip()


def _close(want: str, got: str) -> bool:
    """
    دو عنوان یکی‌اند با املای متفاوت؟

    رومانیزه‌ی فارسی استاندارد ندارد: همان ترکی که اسپاتیفای «Mordi» صدایش
    می‌کند در Genius «Moordi» است. همپوشانیِ کلمه اینجا صفر است و بدون این،
    ترک متنِ موجودش را از دست می‌دهد.
    """
    left, right = " ".join(sorted(_norm(want))), " ".join(sorted(_norm(got)))
    if not left or not right:
        return False
    return difflib.SequenceMatcher(None, left, right).ratio() >= _TITLE_RATIO


def _best_hit(hits: list[dict], title: str, artist: str) -> dict | None:
    """
    همان انتخابِ بهترین نتیجه، ولی کل `result` را برمی‌گرداند نه فقط url —
    song_info به id/آرت‌ورک همین دیکشنری هم نیاز دارد.

    نتیجه‌ای که به هیچ‌کدام از دو سمت نخورَد رد می‌شود، حتی اگر تنها نتیجه باشد:
    جستجوی Genius هیچ‌وقت دست‌خالی برنمی‌گردد و برای ترکی که ندارد ده نتیجه‌ی
    بی‌ربط می‌دهد. قبول‌کردنِ اولینشان یعنی متنِ آهنگِ دیگری در فایل .lrc و
    کاور و تاریخِ آهنگِ دیگری روی کارتِ اطلاعات — و هر دو آن‌قدر معقول به نظر
    می‌رسند که کاربر دیر متوجه شود. نداشتن بهتر از اشتباه است.

    عنوانِ نزدیک (نه دقیق) فقط وقتی قبول می‌شود که اسمِ هنرمند خورده باشد:
    شباهتِ املایی به‌تنهایی سیگنالِ ضعیفی است، ولی کنارِ هنرمندِ درست دیگر
    آهنگِ کسِ دیگری نیست.
    """
    want_title, want_artist = _norm(title), _norm(artist)
    close_enough: dict | None = None
    for hit in hits:
        result = hit.get("result") or {}
        if not result.get("url") or result.get("lyrics_state") != "complete":
            continue
        got_title = _norm(result.get("title") or "")
        got_artist = _norm((result.get("primary_artist") or {}).get("name") or "")
        if want_artist and not (want_artist & got_artist):
            continue
        # تطابق کامل هر دو سمت لازم نیست — همپوشانیِ کلمات کافیست، چون Genius
        # اسم آهنگ را با پسوندهایی مثل «(Remastered)» برمی‌گرداند
        if not want_title or want_title & got_title:
            return result
        if close_enough is None and want_artist and _close(title, result.get("title") or ""):
            close_enough = result
    return close_enough


def _best_url(hits: list[dict], title: str, artist: str) -> str | None:
    hit = _best_hit(hits, title, artist)
    return hit.get("url") if hit else None


def _search(client: httpx.Client, query: str) -> list[dict]:
    res = client.get(
        f"{GENIUS_API}/search",
        params={"q": query},
        headers={"Authorization": f"Bearer {GENIUS_ACCESS_TOKEN}"},
    )
    if res.status_code != 200:
        return []
    return ((res.json().get("response") or {}).get("hits")) or []


def _find(client: httpx.Client, title: str, artist: str) -> dict | None:
    """
    بهترین نتیجه برای این ترک — اول با اسمِ کاملِ هنرمند، بعد فقط با اولی.

    درخواستِ دوم فقط وقتی زده می‌شود که اسم واقعاً چندنفره باشد و اولی چیزی
    پیدا نکرده باشد؛ برای ترکِ تک‌هنرمند دقیقاً همان یک درخواستِ قبلی است.
    فیلترِ `_best_hit` روی هر دو با اسمِ *کامل* اجرا می‌شود، پس ارزان‌تر شدنِ
    جستجو به معنیِ شل‌تر شدنِ پذیرش نیست.
    """
    queries = [f"{title} {artist}".strip()]
    if (primary := _primary(artist)) and primary != artist.strip():
        queries.append(f"{title} {primary}".strip())
    for query in queries:
        if hit := _best_hit(_search(client, query), title, artist):
            return hit
    return None


_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}


class _LyricsParser(HTMLParser):
    """
    فقط داخل `<div data-lyrics-container="true">` را جمع می‌کند — با دو ظرافت:

    ۱. این div خودش تگ‌های تودرتو دارد (مثلاً annotation)، پس یک پشته از
       تگ‌های باز نگه می‌داریم به‌جای اینکه با regex دنبال اولین `</div>`
       بگردیم — که با تودرتو بودن، متن را زودتر از موعد قطع می‌کرد.
    ۲. خودِ Genius داخل همین div یک بلوکِ رابط کاربری (مثلاً «۴ Contributors»
       و عنوانِ آهنگ) می‌گذارد که با `data-exclude-from-selection="true"`
       علامت خورده — همان چیزی که خودِ سایت هم موقع کپی‌کردن متن نادیده
       می‌گیرد. بدون این فیلتر، آن متن به‌عنوان خط اول لیریک ظاهر می‌شود.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, bool]] = []  # (تگ, داخل بلوکِ excluded است؟)
        self.chunks: list[str] = []

    def _excluded(self) -> bool:
        return any(excluded for _, excluded in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if not self._stack:
            if tag == "div" and attrs_dict.get("data-lyrics-container") == "true":
                self._stack.append((tag, False))
            return

        excluded = self._excluded() or attrs_dict.get("data-exclude-from-selection") == "true"
        if tag in _VOID_TAGS:
            if tag == "br" and not excluded:
                self.chunks.append("\n")
        else:
            self._stack.append((tag, excluded))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._stack and tag == "br" and not self._excluded():
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self._stack and not self._excluded():
            self.chunks.append(data)


def _extract(page_html: str) -> str | None:
    parser = _LyricsParser()
    try:
        parser.feed(page_html)
    except Exception:
        return None
    text = _BLANK_RUN.sub("\n\n", "".join(parser.chunks)).strip()
    return text or None


def fetch(title: str, artist: str, album: str | None, duration_ms: int) -> Lyrics | None:
    if not title or not GENIUS_ACCESS_TOKEN:
        return None

    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True, proxy=PROXY) as client:
            hit = _find(client, title, artist)
            if not hit:
                return None

            page = client.get(hit["url"])
            if page.status_code != 200:
                return None
    except Exception:
        return None

    text = _extract(page.text)
    return Lyrics(plain=text) if text else None


def _names(entries: list[dict] | None) -> list[str]:
    return [n for e in (entries or []) if (n := e.get("name"))]


def song_info(title: str, artist: str) -> SongInfo | None:
    """
    آهنگساز/تهیه‌کننده/آلبوم/تاریخ انتشار/کاور — از `/songs/{id}`، نه از
    `/search` که این فیلدها را ندارد.

    `description` عمداً گرفته نمی‌شود: فرمتش (rich text/DOM) بدون یک
    parser جدا قابل‌اتکا استخراج نمی‌شود و ارزشش را برای این کار ندارد.
    """
    if not title or not GENIUS_ACCESS_TOKEN:
        return None

    auth = {"Authorization": f"Bearer {GENIUS_ACCESS_TOKEN}"}
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True, proxy=PROXY) as client:
            hit = _find(client, title, artist)
            if not hit or not hit.get("id"):
                return None

            detail = client.get(
                f"{GENIUS_API}/songs/{hit['id']}", params={"text_format": "plain"}, headers=auth
            )
            if detail.status_code != 200:
                return None
            song = ((detail.json().get("response") or {}).get("song")) or {}
    except Exception:
        return None

    return SongInfo(
        writers=_names(song.get("writer_artists")),
        producers=_names(song.get("producer_artists")),
        album=(song.get("album") or {}).get("name"),
        releaseDate=song.get("release_date_for_display") or song.get("release_date"),
        artworkUrl=song.get("song_art_image_url") or hit.get("song_art_image_url"),
        url=hit.get("url"),
    )
