"""مدل‌های داده — دقیقاً آینه‌ی src/lib/types.ts در فرانت."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Source = Literal["apple", "deezer", "soundcloud", "spotify", "youtube"]

# سه تا بیت‌ریت mp3، سه کدک مشخص، و «اورجینال» یعنی دست‌نخورده.
# کدک‌های بی‌اتلاف روی منبع باکیفیتِ لاسی فقط حجم اضافه می‌کنند — ولی انتخابش با کاربر است.
Quality = Literal["128", "192", "320", "m4a", "opus", "flac", "original"]

# `deferred` تنها وضعیتی است که خودش پیش نمی‌رود: یعنی کاربر دانلود را خواسته
# ولی اینترنتِ بین‌الملل قطع بوده. با برگشتنِ دسترسی خودکار به `queued` می‌رود.
# جایگزینِ رفتارِ قبلی است که همان درخواست را فوراً `error` می‌کرد و کاربر باید
# یادش می‌ماند بعداً دوباره بزند.
JobStatus = Literal[
    "queued", "searching", "downloading", "tagging", "ready", "error", "canceled", "deferred"
]


class Track(BaseModel):
    id: str
    title: str
    artist: str
    album: str | None = None
    albumId: str | None = None
    # هنرمندِ آلبوم، که با `artist` یکی نیست وقتی ترک مهمان دارد. پلیرها آلبوم را
    # با جفتِ (نامِ آلبوم، هنرمندِ آلبوم) گروه می‌کنند؛ بدون این فیلد، هر ترکِ
    # فیچردار یک آلبومِ جدا با همان نام می‌ساخت.
    albumArtist: str | None = None
    durationMs: int
    artworkUrl: str | None = None
    source: Source
    sourceUrl: str
    previewUrl: str | None = None
    explicit: bool = False
    # متادیتای آلبومی. UI به آن‌ها کاری ندارد، ولی بدونشان فایل خروجی تگِ ناقص
    # می‌گیرد و هر پلیر دیگری آلبوم را بی‌ترتیب و بی‌سال نشان می‌دهد.
    trackNumber: int | None = None
    discNumber: int | None = None
    year: int | None = None
    genre: str | None = None
    # آدرسِ صفحه‌ی این ترک در پلتفرمِ مبدأ — کلیدِ ناوبریِ فرانت به صفحه‌ی
    # آرتیست: از روی همین شناسه، URL صفحه‌ی آرتیست ساخته می‌شود
    artistId: str | None = None
    artistArtworkUrl: str | None = None
    # حس‌وحالِ صوتیِ تحلیل‌شده بعد از دانلود — غمگین↔شاد و آرام↔پرشور، هرکدام
    # در [0, 1]. فقط برای ترک‌های کتابخانه پر می‌شود؛ برای نتیجه‌ی جستجو که
    # هنوز دانلود نشده None است. شافلِ فرانت‌اند برای نپریدن ناگهانی بین
    # حس‌وحال‌های ناهمخوان از این دو استفاده می‌کند.
    valence: float | None = None
    energy: float | None = None


class Artist(BaseModel):
    id: str
    name: str
    artworkUrl: str | None = None
    source: Source
    sourceUrl: str
    subtitle: str
    # کاربرِ عادیِ پلتفرم هم صفحه دارد: کسی که هنرمند نیست و فقط پلی‌لیستِ
    # عمومی می‌سازد (اسپاتیفای، دیزر، ساندکلاد، یوتیوب). قالبِ صفحه‌اش همان
    # صفحه‌ی هنرمند است — فقط به‌جای دیسکوگرافی، پلی‌لیست دارد — و فرانت با
    # همین فیلد تصمیم می‌گیرد کدام برچسب را بگذارد.
    kind: Literal["artist", "user"] = "artist"
    # فقط وقتی پلتفرم صریح می‌گوید حساب تأیید شده است. ساندکلاد `verified`
    # می‌دهد؛ بقیه در API فعلی ندارند و False می‌مانند — فرانت بج جعلی نمی‌سازد.
    verified: bool = False


class Album(BaseModel):
    id: str
    title: str
    artist: str
    year: int
    artworkUrl: str | None = None
    trackCount: int
    source: Source
    sourceUrl: str
    # شناسه و آواتارِ آرتیستِ آلبوم از همان پلتفرم — فرانت با کلیک روی نام،
    # به صفحه‌ی آرتیستِ همین منبع می‌رود
    artistId: str | None = None
    artistArtworkUrl: str | None = None
    # دسته‌ی انتشار برای فیلتر دیسکوگرافی. دیزر در فهرست آلبوم تعداد ترک
    # نمی‌دهد و بدون این فیلد سینگل و آلبوم قاطی می‌شدند. نبودنش یعنی
    # کاتالوگ قدیمی / منبعی که نوع را نمی‌داند.
    releaseType: Literal["album", "single", "ep", "compilation"] | None = None
    releaseDate: str | None = None


class Playlist(BaseModel):
    id: str
    title: str
    owner: str
    trackCount: int
    artworkUrl: str | None = None
    source: Source
    sourceUrl: str


class AlbumDetail(Album):
    durationMs: int
    tracks: list[Track]

    @model_validator(mode="after")
    def _stamp_album_identity(self) -> "AlbumDetail":
        """
        چیزهایی که فقط سرِ آلبوم می‌داند را روی تک‌تک ترک‌ها می‌نشاند.

        هیچ سرویسی هنرمندِ آلبوم را روی خودِ ترک نمی‌دهد. اگر همین‌جا پخشش
        نکنیم، تگِ TPE2 هر فایل هنرمندِ همان ترک می‌شود و آلبومی که چند ترکش
        مهمان دارد، در پلیر به چند آلبومِ هم‌نام تکه‌تکه می‌شود.

        شرطش این است که واقعاً یک آلبوم باشد: پلی‌لیست و تک‌آهنگ هم در همین
        قالب برمی‌گردند و آنجا «هنرمندِ آلبوم» یعنی سازنده‌ی پلی‌لیست — که
        گذاشتنش روی ترک‌ها دروغ است. پس فقط وقتی می‌نشیند که همه‌ی ترک‌ها
        آلبومشان همین باشد.
        """
        if not self.tracks or any(t.album != self.title for t in self.tracks):
            return self

        # پلی‌لیست‌ها حتی اگر همه‌ی ترک‌هایشان هم‌نامِ پلی‌لیست باشند، آلبوم نیستند
        is_playlist = ":playlist:" in self.id and self.releaseType not in ("album", "ep", "compilation")
        if is_playlist:
            return self

        # کاورِ آلبوم باید روی همه‌ی ترک‌های آلبوم بنشیند — حتی ترکی که قبلاً
        # سینگل بوده و آرت‌ورکِ جداگانه داشته، در بسترِ آلبوم کاورِ آلبوم را می‌گیرد
        if self.artworkUrl:
            for t in self.tracks:
                t.artworkUrl = self.artworkUrl
        elif self.tracks and self.tracks[0].artworkUrl:
            self.artworkUrl = self.tracks[0].artworkUrl
            for t in self.tracks:
                t.artworkUrl = self.artworkUrl

        for t in self.tracks:
            if t.albumArtist is None and self.artist:
                t.albumArtist = self.artist
            # فقط شناسه‌ای که واقعاً آلبوم است: تک‌آهنگ و پلی‌لیست هم AlbumDetail
            # برمی‌گردند و شناسه‌شان به‌عنوان albumId، گروه‌بندیِ کتابخانه را
            # به‌هم می‌ریخت
            if t.albumId is None:
                t.albumId = self.id

        # شماره‌ی ترک را هر کاتالوگی نمی‌دهد — ساندکلاد و یوتیوب هیچ‌وقت.
        # ترتیبِ همین فهرست همان ترتیبی است که در خودِ پلتفرم دیده می‌شود، پس
        # وقتی هیچ ترکی شماره ندارد، جایگاهش شماره‌اش می‌شود. بدون آن فایل‌ها
        # بی‌TRCK می‌مانند و هر پلیری آلبوم را به میلِ خودش می‌چیند.
        if len(self.tracks) > 1 and all(t.trackNumber is None for t in self.tracks):
            for position, t in enumerate(self.tracks, start=1):
                t.trackNumber = position
        return self


class ArtistDetail(Artist):
    """صفحه‌ی هنرمند: چند ترک محبوب به‌علاوه‌ی دیسکوگرافی."""

    topTracks: list[Track] = Field(default_factory=list)
    albums: list[Album] = Field(default_factory=list)
    # فقط دیزر دارد (/artist/{id}/related,radio,playlists). بقیه‌ی پلتفرم‌ها
    # این سه فهرست را خالی می‌گذارند.
    related: list[Artist] = Field(default_factory=list)
    radio: list[Track] = Field(default_factory=list)
    playlists: list[Playlist] = Field(default_factory=list)
    # فقط ساندکلاد دارد — تبِ Likes و Reposts خودِ کاربر. بقیه‌ی پلتفرم‌ها این
    # دو فهرست را خالی می‌گذارند.
    likedTracks: list[Track] = Field(default_factory=list)
    repostedTracks: list[Track] = Field(default_factory=list)


class SearchResults(BaseModel):
    query: str
    # به‌ازای هر پلتفرم یک ردیف؛ یکتاسازی فقط درونِ هر منبع است
    artists: list[Artist] = Field(default_factory=list)
    tracks: list[Track] = Field(default_factory=list)
    albums: list[Album] = Field(default_factory=list)
    playlists: list[Playlist] = Field(default_factory=list)


class DownloadProgress(BaseModel):
    status: JobStatus
    percent: float = 0
    error: str | None = None
    fileUrl: str | None = None
    # همان فایل، ولی برای پخش در مرورگر: mime درست و بدون content-disposition
    streamUrl: str | None = None
    format: str | None = None
    # فایل سالم است ولی چیزی مشکوک بوده — مثلاً AcoustID ترک دیگری را شناخته
    warning: str | None = None
    # آدرس فایل .lrc اگر متنی پیدا شده باشد — هم‌زمان‌شده یا ساده (از Genius)
    lyricsUrl: str | None = None
    # تنظیمِ بلندی برای پخشِ هم‌تراز — همان چیزی که LibraryItem هم می‌دهد،
    # اینجا برای ترکی که همین الان دانلود شده و هنوز از کتابخانه خوانده نشده
    gainDb: float = 0.0


class TrackRef(BaseModel):
    """
    اشاره به یک ترک، به‌علاوه‌ی متادیتایی که فرانت از قبل دارد.

    متادیتا اختیاری است ولی فرستادنش یک lookup کامل را حذف می‌کند — و بدون آن،
    تگ‌های آلبومی (شماره، سال، ژانر) اصلاً به فایل نمی‌رسند.
    """

    trackId: str
    sourceUrl: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    albumId: str | None = None
    albumArtist: str | None = None
    durationMs: int | None = None
    artworkUrl: str | None = None
    trackNumber: int | None = None
    discNumber: int | None = None
    year: int | None = None
    genre: str | None = None
    source: str | None = None
    quality: str | None = None


class DownloadRequest(TrackRef):
    quality: Quality = "320"
    # کاربر خودش نسخه را انتخاب کرده — resolver دور زده می‌شود
    candidateUrl: str | None = None


class CandidateRequest(TrackRef):
    """درخواست دیدنِ نسخه‌های موجود، برای وقتی که انتخاب خودکار اشتباه بوده."""

    # نبودنش یعنی سریع‌ترین منبع. ساندکلاد فقط وقتی زده می‌شود که صریح خواسته شود
    source: str | None = None


class CandidateOption(BaseModel):
    """یک نسخه‌ی قابل دانلود، آن‌طور که برای انتخاب دستی نشان داده می‌شود."""

    url: str
    title: str
    uploader: str
    durationMs: int
    # همان امتیاز resolver — تا کاربر ببیند چرا این یکی انتخاب شده بود
    score: float
    source: Source


class DownloadAccepted(BaseModel):
    jobId: str
    # اگر همین ترک با همین کیفیت از قبل در کتابخانه بوده، دوباره دانلود نمی‌شود
    reused: bool = False


class LibraryItem(BaseModel):
    """یک فایل آماده روی دیسک. همان جاب موفق است، از زاویه‌ی کتابخانه."""

    jobId: str
    track: Track
    quality: Quality
    format: str | None = None
    bytes: int = 0
    fileUrl: str
    streamUrl: str
    lyricsUrl: str | None = None
    createdAt: float
    # چند دسی‌بل باید موقع پخش کم/زیاد شود تا این فایل هم‌ترازِ بقیه شنیده شود
    # (EBU R128، در `loudness.py` اندازه گرفته می‌شود). صفر یعنی یا اندازه‌گیری
    # خاموش بوده یا فایل از قبل روی هدف است.
    gainDb: float = 0.0
    # لایکِ کاربر — قلبِ کنارِ ردیف
    favorite: bool = False
    # چند بار این فایل پخش شده — برای مرتب‌سازیِ «بیشترین‌ها» در کتابخانه
    playCount: int = 0
    # آخرین باری که پخش شده — ردیفِ «اخیراً پخش‌شده»ی کتابخانه روی همین است.
    # None یعنی هرگز؛ مسیرهای غیرِکتابخانه (پلی‌لیست، split) این را ندارند.
    lastPlayedAt: float | None = None


# ---------- پخش‌ها و آمار ----------


class PlayEvent(BaseModel):
    """
    یک رویدادِ پخش از سمتِ فرانت.

    فرانت موقع شروعِ پخشِ یک ترکِ کتابخانه این را می‌فرستد. `seconds` اختیاری
    است: اگر فرانت موقع رد شدن از ترک، ثانیه‌های گوش‌شده را بفرستد دقیق‌تر
    می‌شود، ولی نبودنش هم مشکلی نیست — در آن صورت کلِ مدتِ ترک حساب می‌شود.
    """

    jobId: str
    seconds: int | None = None


class PlayRecord(BaseModel):
    """یک ردیف از تاریخچه‌ی پخش — همان چیزی که جدول plays نگه می‌دارد."""

    jobId: str
    trackId: str
    title: str
    artist: str
    album: str | None = None
    artworkUrl: str | None = None
    durationMs: int = 0
    seconds: int = 0
    playedAt: float


class TopTrack(BaseModel):
    trackId: str
    title: str
    artist: str
    album: str | None = None
    artworkUrl: str | None = None
    plays: int
    seconds: int
    lastAt: float


class TopArtist(BaseModel):
    artist: str
    plays: int
    seconds: int


class Stats(BaseModel):
    """آمارِ گوش‌دادن برای یک بازه — پیش‌فرض هفت روز."""

    plays: int
    seconds: int
    # چند ترکِ *متفاوت* گوش داده شده — از تعدادِ شمرده‌ی ردیف‌های پخش جداست:
    # یک آهنگِ ده‌بار پخش‌شده یک ترک است و ده پخش
    uniqueTracks: int = 0
    topTracks: list[TopTrack] = Field(default_factory=list)
    topArtists: list[TopArtist] = Field(default_factory=list)
    recent: list[PlayRecord] = Field(default_factory=list)


class DailyMix(BaseModel):
    """
    میکسِ روزانه — انتخابِ سرور از کتابخانه بر اساسِ سلیقه‌ی خودِ کاربر.

    `source` می‌گوید مرکزِ انتخاب از کجا آمده تا متنِ صفحه راست بگوید؛ وقتی
    هنوز نه لایکی هست نه پخشی، `none` است و فرانت کلاً سکشن را نشان نمی‌دهد.
    """

    source: Literal["favorites", "recent", "none"] = "none"
    items: list[LibraryItem] = Field(default_factory=list)


class LibraryPage(BaseModel):
    items: list[LibraryItem]
    total: int
    totalBytes: int


class SongInfo(BaseModel):
    """آهنگساز/تهیه‌کننده و بقیه‌ی جزئیاتی که فقط Genius می‌دهد — بات تلگرام استفاده می‌کند."""

    writers: list[str] = Field(default_factory=list)
    producers: list[str] = Field(default_factory=list)
    album: str | None = None
    releaseDate: str | None = None
    artworkUrl: str | None = None
    url: str | None = None


class VibeTurn(BaseModel):
    """
    یک نوبتِ گفتگو برای حافظه‌ی چندتوره — «نه، آروم‌تر» بدونِ این بی‌معناست.

    `role` عمداً str است نه Literal: یک تاریخچه‌ی خراب نباید کل درخواست را
    ۴۰۰/۴۲۲ کند. `_contents` نقش‌های مجاز را فیلتر می‌کند.
    """

    role: str
    text: str


class VibeRequest(BaseModel):
    """ورودیِ چت‌بات پیشنهاد پلی‌لیست. حداقل یکی از این دو باید پر باشد."""

    # پیامِ آزادِ کاربر — بدون آن یعنی کلیک روی یکی از چیپ‌های آماده
    message: str | None = None
    # کلیدِ یکی از VIBES (مثلاً "sad") — کلیک روی چیپ، بدون نیاز به تفسیر متن
    vibe: str | None = None
    # شناسه‌ی ترک‌هایی که فرانت قبلاً در همین گفتگو نشان داده — برای پرهیز از
    # تکرارِ همان آهنگ‌ها در پیشنهادِ بعدی. سقفِ ۲۰۰ با برشِ فرانت (۲۰۰ تا)
    # یکی است؛ اندپوینت بی‌احراز هویت است و نباید لیستِ بی‌نهایت بپذیرد.
    excludeIds: list[str] = Field(default_factory=list, max_length=200)
    # چند نوبتِ آخرِ همین گفتگو (فرانت کوتاهشان می‌کند). بدونش هر پیام از صفر
    # شروع می‌شود و «همین حال ولی ایرانی» کار نمی‌کرد.
    history: list[VibeTurn] = Field(default_factory=list, max_length=32)


class VibeReady(BaseModel):
    """ترکی که کاربر از قبل در کتابخانه دارد — پخشش دانلودِ دوباره نمی‌خواهد."""

    jobId: str
    streamUrl: str
    lyricsUrl: str | None = None
    gainDb: float | None = None


class VibeSuggestion(BaseModel):
    """پاسخ چت‌بات: یک حس‌وحالِ تشخیص‌داده‌شده به‌همراه پلی‌لیستِ پیشنهادی."""

    vibe: str
    label: str
    reply: str
    tracks: list[Track] = Field(default_factory=list)
    # «چرا این‌ها؟» — یک خطِ توضیح. None وقتی از مسیرِ کلیدواژه آمده و توضیحی نیست
    reason: str | None = None
    # شناسه‌ی ترک -> فایلِ آماده‌ی کتابخانه. کلیدهایش زیرمجموعه‌ی tracks است
    ready: dict[str, VibeReady] = Field(default_factory=dict)


class ZipRequest(BaseModel):
    jobIds: list[str]
    # نام فایل zip؛ معمولاً عنوان آلبوم
    name: str = "unstream"


class ZipReady(BaseModel):
    """آدرس دانلود آرشیو — خودِ فایل در درخواست بعدی می‌آید."""

    url: str
    bytes: int
    files: int


# ---------- شناسایی با فینگرپرینت ----------


class IdentifyMatch(BaseModel):
    """یک حدسِ AcoustID برای تکه‌صدای فرستاده‌شده."""

    title: str
    artist: str
    # اطمینانِ سرویس بین ۰ و ۱، یا None وقتی سرویس عددی نمی‌دهد (AudD).
    # ساختنِ یک «۱۰۰٪» الکی فقط اعتمادِ بی‌جا می‌سازد.
    score: float | None = None
    durationMs: int = 0


class IdentifyResult(BaseModel):
    matches: list[IdentifyMatch] = Field(default_factory=list)
    # همان حدسِ اول، جستجو شده در کاتالوگ‌ها — تا کاربر مستقیم دکمه‌ی دانلود
    # ببیند نه فقط یک اسم
    tracks: list[Track] = Field(default_factory=list)


# ---------- تکه‌کردنِ میکس ----------


class ChapterInfo(BaseModel):
    index: int
    # نامِ خامِ چپتر، همان‌طور که آپلودکننده نوشته
    title: str
    startMs: int
    endMs: int
    # حدسِ ما از روی همان نام — عنوان و (اگر «هنرمند - عنوان» بوده) هنرمند
    songTitle: str
    artist: str | None = None


class ChaptersInfo(BaseModel):
    url: str
    title: str
    uploader: str
    durationMs: int
    artworkUrl: str | None = None
    chapters: list[ChapterInfo] = Field(default_factory=list)


class SplitRequest(BaseModel):
    url: str
    quality: Quality = "320"
    # شماره‌ی چپترهای انتخاب‌شده؛ خالی یعنی همه
    indexes: list[int] = Field(default_factory=list)


class SplitStatus(BaseModel):
    taskId: str
    status: str
    percent: float = 0
    done: int = 0
    total: int = 0
    error: str | None = None
    # هر تکه‌ی بریده‌شده یک عضوِ کاملِ کتابخانه است
    items: list[LibraryItem] = Field(default_factory=list)


# ---------- پلی‌لیست‌های کاربر ----------


class PlaylistRule(BaseModel):
    """
    قانونِ یک پلی‌لیستِ هوشمند. همه‌ی فیلدها اختیاری‌اند؛ هرچه پر باشد فیلتر
    می‌شود. حس‌وحال از تحلیلِ صوتیِ `mood.py` می‌آید و فقط ترک‌های تحلیل‌شده
    را می‌بیند.
    """

    query: str | None = None
    valenceMin: float | None = None
    valenceMax: float | None = None
    energyMin: float | None = None
    energyMax: float | None = None
    sort: str = "recent"
    limit: int = 50


class UserPlaylist(BaseModel):
    id: str
    name: str
    # manual = فهرستِ دستی، smart = قانون
    kind: str
    rule: PlaylistRule | None = None
    trackCount: int = 0
    createdAt: float
    # کاورِ چند ترکِ اولش — کاشیِ فهرست با آن ساخته می‌شود
    artworkUrls: list[str] = Field(default_factory=list)


class UserPlaylistDetail(UserPlaylist):
    items: list[LibraryItem] = Field(default_factory=list)


class PlaylistCreate(BaseModel):
    name: str
    kind: str = "manual"
    rule: PlaylistRule | None = None
    # موقع ساخت می‌شود چند ترک را هم همان اول ریخت تویش
    jobIds: list[str] = Field(default_factory=list)


class PlaylistUpdate(BaseModel):
    name: str | None = None
    rule: PlaylistRule | None = None


class PlaylistItemsRequest(BaseModel):
    jobIds: list[str]


# ---------- فرستادن به بات تلگرام ----------


class TelegramStatus(BaseModel):
    """
    وضعیتی که دکمه‌ی «فرستادن به تلگرام» بر اساسش تصمیم می‌گیرد.

    «وصل نیست» و «بات بالا نیست» دو چیزِ متفاوت‌اند و کاربر باید بداند کدام —
    اولی با یک کد حل می‌شود، دومی با بالا آوردنِ سرویسِ بات.
    """

    connected: bool
    linked: bool
    chatTitle: str | None = None
    # شناسه‌ی چتِ وصل‌شده — وب برای دنبال‌کردنِ هنرمند به همین نیاز دارد؛ بدونش
    # نمی‌داند ردیفِ Follow را به کدام چت بچسباند.
    chatId: int | None = None
    botUsername: str | None = None


class TelegramPairing(BaseModel):
    code: str
    expiresIn: int
    # اگر نامِ بات را بدانیم، کاربر به‌جای تایپِ کد فقط لینک را می‌زند
    deepLink: str | None = None


class TelegramPairClaim(BaseModel):
    """از سمتِ بات می‌آید، وقتی کاربر کد را در چت فرستاد."""

    code: str
    chatId: int
    chatTitle: str


class TelegramSendRequest(BaseModel):
    """
    یک ترکِ تنها یا یک آلبوم/پلی‌لیستِ کامل.

    برای `album` فقط `ref` می‌آید (همان چیزی که `/api/album` می‌گیرد) نه فهرستِ
    ترک‌ها: بات خودش بازش می‌کند و ترک‌ها را ترتیبی می‌گیرد، پس فرستادنِ یک
    آلبومِ صدتایی هم یک درخواستِ کوچک است.
    """

    kind: Literal["track", "album"] = "track"
    track: TrackRef | None = None
    ref: str | None = None
    title: str
    quality: Quality = "320"
    # False یعنی فقط به تلگرام برود و اثری در کتابخانه نگذارد: فایل بعد از
    # آپلود پاک می‌شود و ردیفِ جاب هم حذف می‌شود. پیش‌فرضِ True رفتارِ قبلی است.
    keep: bool = True


class TelegramSend(BaseModel):
    id: str
    # pending | sending | done | error
    status: str
    error: str | None = None


class TelegramJob(BaseModel):
    """همان کار، به شکلی که بات از صف تحویل می‌گیرد."""

    id: str
    chatId: int
    kind: str
    quality: str
    title: str
    track: Track | None = None
    ref: str | None = None
    # False یعنی پس از ارسال، فایل و ردیفِ جاب پاک شوند — کتابخانه نباید ببیندش
    keep: bool = True


class TelegramJobResult(BaseModel):
    error: str | None = None


class Follow(BaseModel):
    """
    یک هنرمندِ دنبال‌شده برای اطلاعِ انتشارِ تازه — همان چیزی که `/follow` می‌سازد.

    مقصد همیشه چتِ وصل‌شده‌ی تلگرام است؛ `chatId` برای وقتی نگه داشته می‌شود که
    چند چت وصل شده بوده یا چت عوض شده باشد، تا دنبال‌شده‌های چتِ قدیمی به چتِ
    تازه سرازیر نشوند.
    """

    id: int
    chatId: int
    artistId: str
    artistName: str
    artistSourceUrl: str
    source: Source
    artworkUrl: str | None = None
    lastReleaseId: str | None = None
    lastReleaseTitle: str | None = None


class FollowRequest(BaseModel):
    """درخواستِ دنبال‌کردن — چه از وب، چه از بات."""

    artistId: str
    artistName: str
    artistSourceUrl: str
    source: Source
    artworkUrl: str | None = None
    lastReleaseId: str | None = None
    lastReleaseTitle: str | None = None


class FollowState(BaseModel):
    """
    وضعیتِ دنبال‌کردن — برای دکمه‌ی وب و برای جوابِ `/follow` بات.

    `created` فقط روی پاسخِ POST معنا دارد: True یعنی ردیفِ تازه ساخته شد،
    False یعنی این چت از قبل همین هنرمند را دنبال می‌کرد (کلیکِ دوباره خطا نیست).
    """

    followed: bool
    follow: Follow | None = None
    created: bool = False


class TelegramHeartbeat(BaseModel):
    username: str | None = None


# ---------- توزیعِ نسخه‌ی اندروید ----------


class ReleaseInfo(BaseModel):
    """
    آخرین APKِ منتشرشده روی همین سرور.

    `versionCode` عدد است چون مقایسه‌ی رشته‌ای «۱۰» را کوچک‌تر از «۹» می‌بیند و
    اپ برای همیشه بنرِ دروغین نشان می‌دهد. `apkUrl` خالی یعنی manifest هست ولی
    فایلش روی دیسک نیست — آن‌وقت بنر باید «خبر دارم ولی نمی‌دهم» باشد نه شکست.
    """

    versionCode: int
    versionName: str
    notes: str = ""
    apkUrl: str | None = None
    bytes: int = 0


class ClientError(BaseModel):
    """یک خطای سمتِ کاربر (WebView) — همان چیزی که هیچ لاگِ سروری ندارد."""

    kind: str = "error"
    message: str = ""
    stack: str = ""
    url: str = ""
    app: str = ""
    device: str = ""
