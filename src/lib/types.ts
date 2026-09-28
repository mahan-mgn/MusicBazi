export type Source = 'apple' | 'deezer' | 'soundcloud' | 'spotify' | 'youtube'

export const SOURCE_LABEL: Record<Source, string> = {
  apple: 'Apple',
  deezer: 'Deezer',
  soundcloud: 'SoundCloud',
  spotify: 'Spotify',
  youtube: 'YouTube',
}

/** کیفیت‌های قابل انتخاب در هدر */
export type Quality = '128' | '192' | '320' | 'm4a' | 'opus' | 'flac' | 'original'

/**
 * دو دسته‌اند و در UI هم جدا نشان داده می‌شوند: بیت‌ریت mp3 (فقط عدد) و کدک
 * (اسم خودش). «اورجینال» یعنی هیچ ترنسکدی — همان چیزی که منبع داده.
 */
export const MP3_QUALITIES: { id: Quality; kbps: number }[] = [
  { id: '128', kbps: 128 },
  { id: '192', kbps: 192 },
  { id: '320', kbps: 320 },
]

export const CODEC_QUALITIES: { id: Quality; label: string }[] = [
  { id: 'm4a', label: 'm4a' },
  { id: 'opus', label: 'opus' },
  { id: 'flac', label: 'flac' },
]

export const QUALITIES: Quality[] = [
  ...MP3_QUALITIES.map((q) => q.id),
  ...CODEC_QUALITIES.map((q) => q.id),
  'original',
]

export interface Track {
  id: string
  title: string
  artist: string
  album?: string
  albumId?: string
  /**
   * هنرمندِ آلبوم — با `artist` فرق دارد وقتی ترک مهمان دارد. UI نشانش
   * نمی‌دهد، ولی موقع دانلود همراه ترک می‌رود تا تگِ آلبوم درست دربیاید و
   * پلیرها آلبوم را تکه‌تکه نبینند.
   */
  albumArtist?: string
  durationMs: number
  artworkUrl: string | null
  source: Source
  sourceUrl: string
  /** پری‌ویوی ۳۰ ثانیه‌ای؛ در مود ماک null است */
  previewUrl: string | null
  explicit?: boolean
  /**
   * متادیتای آلبومی — فقط برای تگ‌گذاری روی سرور.
   * UI نمایششان نمی‌دهد، ولی موقع ثبت دانلود همراه ترک می‌روند تا سرور
   * مجبور به lookup دوباره نشود.
   */
  trackNumber?: number
  discNumber?: number
  year?: number
  genre?: string
  /**
   * شناسه‌ی داخلیِ آرتیست (`sp:artist:…` و امثالش) — کلیدِ ناوبری به صفحه‌ی
   * آرتیست. نبودنش یعنی این پلتفرم صفحه‌ی آرتیست نمی‌دهد.
   */
  artistId?: string
  /** عکس پروفایل پلتفرمِ هنرمند */
  artistArtworkUrl?: string | null
  /**
   * حس‌وحالِ صوتیِ تحلیل‌شده بعد از دانلود — غمگین↔شاد و آرام↔پرشور، هرکدام
   * در [0, 1]. فقط ترک‌های کتابخانه دارندش؛ نتیجه‌ی جستجو که هنوز دانلود
   * نشده undefined است. شافل برای نپریدن ناگهانی بین حس‌وحال‌های ناهمخوان
   * از این دو استفاده می‌کند (`lib/shuffle.ts`).
   */
  valence?: number
  energy?: number
}

export interface Artist {
  id: string
  name: string
  artworkUrl: string | null
  source: Source
  sourceUrl: string
  subtitle: string
  /**
   * `user` یعنی این صفحه مالِ یک کاربرِ عادی است نه هنرمند — کسی که چیزی
   * منتشر نکرده و فقط پلی‌لیستِ عمومی دارد. قالبِ صفحه یکی است و فقط
   * برچسب‌هایش فرق می‌کنند. نبودنش یعنی هنرمند.
   */
  kind?: 'artist' | 'user'
  /** فقط وقتی پلتفرم صریح گفته حساب تأیید شده است — وگرنه بج جعلی نشان نده */
  verified?: boolean
}

export interface Album {
  id: string
  title: string
  artist: string
  year: number
  artworkUrl: string | null
  trackCount: number
  source: Source
  sourceUrl: string
  /** شناسه و آواتارِ آرتیستِ آلبوم از همان پلتفرم — کلیک روی نام به صفحه‌اش می‌رود */
  artistId?: string
  artistArtworkUrl?: string | null
  /**
   * دسته‌ی انتشار برای فیلتر دیسکوگرافی. دیزر در فهرست آلبوم تعداد ترک
   * نمی‌دهد؛ بدون این فیلد سینگل و آلبوم قاطی می‌شدند. نبودنش یعنی کش قدیمی.
   */
  releaseType?: 'album' | 'single' | 'ep' | 'compilation'
  releaseDate?: string | null
}

export interface Playlist {
  id: string
  title: string
  owner: string
  trackCount: number
  artworkUrl: string | null
  source: Source
  sourceUrl: string
}

export interface AlbumDetail extends Album {
  durationMs: number
  tracks: Track[]
}

/** صفحه‌ی هنرمند: چند ترک محبوب به‌علاوه‌ی دیسکوگرافی */
export interface ArtistDetail extends Artist {
  topTracks: Track[]
  albums: Album[]
  /**
   * پلی‌لیست‌های همین صفحه: برای کاربر تمامِ محتوایش، و برای هنرمند
   * پلی‌لیست‌هایی که پلتفرم دورش ساخته (دیزر) یا خودش منتشر کرده.
   */
  playlists: Playlist[]
  /** فقط ساندکلاد پر می‌کند — تبِ Likes/Reposts خودِ کاربر */
  likedTracks: Track[]
  repostedTracks: Track[]
  /**
   * هنرمندانِ مشابه — فقط دیزر دارد (`/artist/{id}/related`). بقیه‌ی پلتفرم‌ها
   * خالی می‌فرستند و بخشش رندر نمی‌شود.
   */
  related: Artist[]
  /** رادیوی هنرمند — فقط دیزر (`/artist/{id}/radio`). بقیه خالی. */
  radio?: Track[]
}

export interface SearchResults {
  query: string
  /** به‌ازای هر پلتفرم یک ردیف — همان هنرمند از اپل، دیزر، اسپاتیفای و ساندکلاد */
  artists: Artist[]
  tracks: Track[]
  albums: Album[]
  playlists: Playlist[]
}

/** چرخه‌ی عمر یک کار دانلود */
export type JobStatus =
  | 'queued'
  | 'searching'
  | 'downloading'
  | 'tagging'
  | 'ready'
  | 'error'
  | 'canceled'
  /**
   * منتظرِ برگشتنِ اینترنتِ بین‌الملل.
   *
   * تنها وضعیتی است که خودش جلو نمی‌رود و زمانِ ماندنش نامعلوم است — ممکن است
   * چند ساعت یا چند روز باشد. با برگشتنِ دسترسی، سرور خودش به `queued` می‌بردش
   * و بقیه‌ی چرخه مثل همیشه ادامه پیدا می‌کند.
   */
  | 'deferred'

export interface DownloadProgress {
  status: JobStatus
  /** ۰ تا ۱۰۰ — فقط در downloading معنادار است */
  percent: number
  /** پیام خطا در صورت status === 'error' */
  error?: string
  /** لینک فایل آماده در صورت status === 'ready' */
  fileUrl?: string
  /** همان فایل برای پخش در مرورگر — mime درست و بدون content-disposition */
  streamUrl?: string
  /** فرمت نهایی فایل، مثلاً mp3 */
  format?: string
  /** فایل سالم است ولی چیزی مشکوک بوده — مثلاً AcoustID ترک دیگری را شناخته */
  warning?: string
  /** فایل .lrc اگر متن هم‌زمان‌شده پیدا شده باشد */
  lyricsUrl?: string
  /** تنظیم بلندی برای پخشِ هم‌تراز (دسی‌بل) — صفر یعنی دست نزن */
  gainDb?: number
}

export interface DownloadRequest {
  track: Track
  quality: Quality
  /** نسخه‌ای که کاربر خودش انتخاب کرده — resolver دور زده می‌شود */
  candidateUrl?: string
}

/** یک نسخه‌ی قابل دانلود، برای وقتی که انتخاب خودکار اشتباه بوده */
export interface CandidateOption {
  url: string
  title: string
  uploader: string
  durationMs: number
  /** همان امتیاز resolver — تا معلوم باشد چرا این یکی انتخاب شده بود */
  score: number
  source: Source
}

/** یک فایل آماده روی دیسک سرور */
export interface LibraryItem {
  jobId: string
  track: Track
  quality: Quality
  format?: string
  bytes: number
  fileUrl: string
  streamUrl: string
  lyricsUrl?: string
  /** ثانیه‌ی یونیکس */
  createdAt: number
  /**
   * چند دسی‌بل باید موقع پخش کم/زیاد شود تا این فایل هم‌ترازِ بقیه شنیده شود.
   * سرور با EBU R128 اندازه‌اش گرفته؛ صفر یعنی یا اندازه‌گیری خاموش بوده یا
   * فایل از قبل روی هدف است.
   */
  gainDb?: number
  /** لایکِ کاربر — قلبِ کنارِ ردیف */
  favorite?: boolean
  /** چند بار این فایل پخش شده */
  playCount?: number
  /** ثانیه‌ی یونیکسِ آخرین پخش — undefined یعنی هرگز پخش نشده */
  lastPlayedAt?: number
}

export interface LibraryPage {
  items: LibraryItem[]
  total: number
  totalBytes: number
}

/** یک ردیف از تاریخچه‌ی پخش */
export interface PlayRecord {
  jobId: string
  trackId: string
  title: string
  artist: string
  album?: string | null
  artworkUrl?: string | null
  durationMs: number
  seconds: number
  playedAt: number
}

export interface TopTrack {
  trackId: string
  title: string
  artist: string
  album?: string | null
  artworkUrl?: string | null
  plays: number
  seconds: number
  lastAt: number
}

export interface TopArtist {
  artist: string
  plays: number
  seconds: number
}

/** آمارِ گوش‌دادن برای یک بازه */
export interface Stats {
  plays: number
  seconds: number
  /** چند ترکِ متفاوت گوش داده شده */
  uniqueTracks: number
  topTracks: TopTrack[]
  topArtists: TopArtist[]
  recent: PlayRecord[]
}

/** میکسِ روزانه — انتخابِ سرور از کتابخانه بر اساسِ سلیقه‌ی خودِ کاربر */
export interface DailyMix {
  /** مرکزِ انتخاب از کجا آمده؛ `none` یعنی سیگنالی نیست */
  source: 'favorites' | 'recent' | 'none'
  items: LibraryItem[]
}

/** ورودیِ چت‌بات وایب — پیام آزاد، یا کلیدِ یک چیپِ آماده (بدون تفسیرِ متن) */
export interface VibeInput {
  message?: string
  vibe?: string
  /** شناسه‌ی ترک‌هایی که همین گفتگو قبلاً دیده — برای پرهیز از تکرار */
  excludeIds?: string[]
  /**
   * چند نوبتِ آخرِ گفتگو — تا «نه آروم‌تر» و «همین حال ولی ایرانی» معنا
   * داشته باشند. سرور خودش کوتاهشان می‌کند، ولی فرانت هم سقف می‌گذارد که
   * بدنه‌ی درخواست با طولِ گفتگو بزرگ نشود.
   */
  history?: VibeTurn[]
}

/** یک نوبتِ گفتگو برای حافظه‌ی چندتوره */
export interface VibeTurn {
  role: 'user' | 'model'
  text: string
}

/** ترکی که از قبل در کتابخانه است — پخشش دانلودِ دوباره نمی‌خواهد */
export interface VibeReady {
  jobId: string
  streamUrl: string
  lyricsUrl?: string
  gainDb?: number
}

/** پاسخِ چت‌بات: یک حس‌وحالِ تشخیص‌داده‌شده به‌همراه پلی‌لیستِ پیشنهادی */
export interface VibeSuggestion {
  vibe: string
  label: string
  reply: string
  tracks: Track[]
  /** «چرا این‌ها؟» — فقط وقتی مدل جواب داده هست */
  reason?: string | null
  /** شناسه‌ی ترک -> فایلِ آماده‌ی کتابخانه */
  ready?: Record<string, VibeReady>
}

/** یک حدسِ شناساییِ صوتی */
export interface IdentifyMatch {
  title: string
  artist: string
  /** اطمینانِ سرویس بین ۰ و ۱، یا null وقتی سرویس عددی نمی‌دهد */
  score: number | null
  durationMs: number
}

/**
 * شناسایی روی این سرور تنظیم نشده.
 *
 * جدا از «چیزی پیدا نشد» است و پیامش را خودِ سرور می‌دهد — چون فقط سرور
 * می‌داند کدام تکه کم است (`fpcalc`، کلید AcoustID، یا توکنِ AudD) و همان
 * جمله تنها چیزی است که به کاربر می‌گوید بعدش چه کند.
 */
export class IdentifyUnavailable extends Error {}

/**
 * سرور سالم است ولی اینترنتِ بین‌الملل قطع است، و این درخواست بدون آن جواب
 * ندارد — چیزی که خواستی نه در کش هست نه روی دیسک.
 *
 * جدا از `Error`ِ معمولی است چون کارِ کاربر با آن فرق دارد: «دوباره امتحان کن»
 * بی‌فایده است تا وقتی شبکه برنگردد، و UI به‌جای پیامِ خطا باید حالتِ اینترانت
 * را نشان بدهد. سرور با کد ۵۰۳ علامتش می‌دهد.
 */
export class IntranetError extends Error {}

export interface IdentifyResult {
  matches: IdentifyMatch[]
  /** همان حدسِ اول، جستجو شده در کاتالوگ‌ها — آماده‌ی دانلود */
  tracks: Track[]
}

/** یک چپترِ ویدیو، به‌علاوه‌ی حدسِ سرور از هنرمند و عنوانش */
export interface ChapterInfo {
  index: number
  title: string
  startMs: number
  endMs: number
  songTitle: string
  artist?: string | null
}

export interface ChaptersInfo {
  url: string
  title: string
  uploader: string
  durationMs: number
  artworkUrl: string | null
  chapters: ChapterInfo[]
}

/** پیشرفتِ تکه‌کردنِ یک میکس — با polling خوانده می‌شود، نه SSE */
export interface SplitStatus {
  taskId: string
  status: 'queued' | 'downloading' | 'cutting' | 'done' | 'error'
  percent: number
  done: number
  total: number
  error?: string | null
  items: LibraryItem[]
}

/**
 * قانونِ یک پلی‌لیستِ هوشمند. هرچه پر باشد فیلتر می‌شود؛ حس‌وحال از تحلیلِ
 * صوتیِ سرور می‌آید و فقط ترک‌های تحلیل‌شده را می‌بیند.
 */
export interface PlaylistRule {
  query?: string | null
  valenceMin?: number | null
  valenceMax?: number | null
  energyMin?: number | null
  energyMax?: number | null
  sort?: string
  limit?: number
}

export type PlaylistKind = 'manual' | 'smart'

/** پلی‌لیستِ خودِ کاربر — روی کتابخانه، نه روی کاتالوگ‌های بیرونی */
export interface UserPlaylist {
  id: string
  name: string
  kind: PlaylistKind
  rule?: PlaylistRule | null
  trackCount: number
  createdAt: number
  /** کاورِ چند ترکِ اول — کاشیِ فهرست با همین ساخته می‌شود */
  artworkUrls: string[]
}

export interface UserPlaylistDetail extends UserPlaylist {
  items: LibraryItem[]
}

/**
 * قرارداد لایه‌ی داده. مود ماک و مود HTTP هر دو این را پیاده می‌کنند،
 * پس UI هیچ‌وقت نمی‌داند دیتا از کجا می‌آید.
 */
/**
 * وضعیتِ دسترسی به اینترنتِ بین‌الملل، از دیدِ سرور.
 *
 * `navigator.onLine` این را نمی‌داند: موقعِ قطعیِ بین‌الملل، وای‌فای وصل است،
 * سرورِ خانگی جواب می‌دهد و از دیدِ مرورگر همه‌چیز عادی است. تنها جایی که
 * می‌شود واقعاً فهمید، خودِ سرور است.
 */
export interface NetStatus {
  /** آیا کاتالوگ‌ها و منابعِ صوتی در دسترس‌اند */
  online: boolean
  /** زمانِ آخرین بررسیِ واقعی (اپاکِ ثانیه‌ای). صفر یعنی هنوز بررسی نشده. */
  checkedAt: number
  /** آدرس‌هایی که در آخرین بررسی جواب دادند */
  reachable: string[]
  /** همه‌ی آدرس‌هایی که امتحان می‌شوند */
  probes: string[]
}

export interface MusicApi {
  search(query: string, signal?: AbortSignal): Promise<SearchResults>
  /**
   * وضعیتِ اینترنتِ بین‌الملل. null یعنی این لایه سروری ندارد که بپرسد (مود دمو).
   *
   * `recheck` یعنی همین حالا پروب بزن — برای دکمه‌ی «دوباره امتحان کن»، وقتی
   * کاربر می‌داند اینترنتش برگشته و نباید تا دورِ بعدیِ حلقه منتظر بماند.
   */
  netStatus(recheck?: boolean, signal?: AbortSignal): Promise<NetStatus | null>
  /** ورودی می‌تواند id داخلی یا لینک اپل‌موزیک/اسپاتیفای/دیزر باشد */
  getAlbum(idOrUrl: string, signal?: AbortSignal): Promise<AlbumDetail>
  /** ورودی id داخلی هنرمند یا لینک اپل‌موزیک/دیزر */
  getArtist(idOrUrl: string, signal?: AbortSignal): Promise<ArtistDetail>
  /**
   * کتابخانه‌ی محلی — فایل‌هایی که قبلاً دانلود شده‌اند و هنوز روی دیسک سرورند.
   * null یعنی این لایه کتابخانه ندارد (مود دمو).
   */
  library(query: string, signal?: AbortSignal): Promise<LibraryPage | null>
  /** حذف کامل یک مورد از کتابخانه: فایل و ردیفش */
  removeFromLibrary(jobId: string): Promise<void>
  /** لایک/برداشتنِ لایک یک ترکِ کتابخانه */
  toggleFavorite(jobId: string, favorite: boolean): Promise<void>
  /** ثبتِ یک رویدادِ پخش — فرانت موقع شروعِ پخشِ ترکِ کتابخانه صدا می‌زند */
  recordPlay(jobId: string, seconds?: number): Promise<void>
  /** آمارِ گوش‌دادن برای یک بازه (روز). null یعنی این لایه آمار ندارد (مود دمو). */
  stats(days?: number, signal?: AbortSignal): Promise<Stats | null>
  /** ترک‌های لایک‌شده. null یعنی این لایه کتابخانه ندارد (مود دمو). */
  favorites(signal?: AbortSignal): Promise<LibraryItem[] | null>
  /** میکسِ روزانه. `source === 'none'` یعنی سیگنالی برای پیشنهاد نیست. */
  dailyMix(signal?: AbortSignal): Promise<DailyMix | null>
  /**
   * شروع دانلود. onProgress تا رسیدن به وضعیت نهایی صدا زده می‌شود.
   * تابع برگشتی، کار را کنسل می‌کند.
   */
  download(req: DownloadRequest, onProgress: (p: DownloadProgress) => void): () => void
  /**
   * نسخه‌های موجود برای یک ترک.
   *
   * `source` را ندهی یعنی سریع‌ترین منبع؛ ساندکلاد فقط با درخواست صریح زده
   * می‌شود چون جستجویش حدود صد ثانیه طول می‌کشد.
   * null یعنی این لایه پشتیبانی نمی‌کند (مود دمو).
   */
  candidates(track: Track, source?: Source): Promise<CandidateOption[] | null>
  /**
   * ZIP را روی سرور می‌سازد و آدرس دانلودش را برمی‌گرداند.
   *
   * عمداً URL برمی‌گرداند نه Blob: پاسخی که content-disposition دارد را مرورگر
   * مستقیم به‌عنوان دانلود می‌قاپد و fetch هیچ بدنه‌ای نمی‌بیند.
   * null یعنی پشتیبانی نمی‌شود (مود دمو).
   *
   * ورودی جفتِ (ترک، کیفیت) است نه فقط ترک: هر کیفیت فایل جداگانه‌ای روی سرور
   * دارد و با شناسه‌ی تنها معلوم نبود کدام نسخه باید بسته‌بندی شود.
   */
  zip(items: ZipItem[], name: string): Promise<string | null>
  /** چت‌بات پیشنهاد پلی‌لیست بر اساس حال‌وهوا — پیام آزاد یا کلیدِ یک چیپ */
  vibeSuggest(input: VibeInput, signal?: AbortSignal): Promise<VibeSuggestion>
  /**
   * شناساییِ یک تکه صدا/ویدیو از روی صدایش.
   * اگر این لایه (یا این سرور) شناسایی نداشته باشد `IdentifyUnavailable` پرت
   * می‌کند — که با نتیجه‌ی خالی («نشناختم») یکی نیست.
   */
  identify(file: Blob, filename: string, signal?: AbortSignal): Promise<IdentifyResult>
  /**
   * چپترهای یک لینک — برای تکه‌کردنِ میکس‌های بلند.
   * null یعنی پشتیبانی نمی‌شود؛ آرایه‌ی خالیِ chapters یعنی این لینک چپتر ندارد.
   */
  chapters(url: string, signal?: AbortSignal): Promise<ChaptersInfo | null>
  /** شروعِ تکه‌کردن؛ وضعیتش بعداً با splitStatus خوانده می‌شود */
  split(url: string, quality: Quality, indexes: number[]): Promise<SplitStatus | null>
  splitStatus(taskId: string): Promise<SplitStatus | null>
  /** پلی‌لیست‌های کاربر. null یعنی این لایه پلی‌لیست ندارد (مود دمو). */
  playlists(signal?: AbortSignal): Promise<UserPlaylist[] | null>
  playlist(id: string, signal?: AbortSignal): Promise<UserPlaylistDetail | null>
  createPlaylist(input: {
    name: string
    kind?: PlaylistKind
    rule?: PlaylistRule
    jobIds?: string[]
  }): Promise<UserPlaylist | null>
  renamePlaylist(id: string, name: string): Promise<void>
  updatePlaylistRule(id: string, rule: PlaylistRule): Promise<void>
  deletePlaylist(id: string): Promise<void>
  addToPlaylist(id: string, jobIds: string[]): Promise<number>
  removeFromPlaylist(id: string, jobId: string): Promise<void>
  /**
   * وضعیتِ بات تلگرام. null یعنی این لایه بات ندارد (مود دمو) — که با «بات
   * بالا نیست» یکی نیست و در UI هم دکمه‌ای نشان داده نمی‌شود.
   */
  telegramStatus(signal?: AbortSignal): Promise<TelegramStatus | null>
  /** کدِ وصل‌کردنِ یک چت به این نصب */
  telegramPair(): Promise<TelegramPairing>
  telegramUnlink(): Promise<void>
  /** یک ترک یا یک آلبومِ کامل را در صفِ بات می‌گذارد */
  telegramSend(req: TelegramSendRequest): Promise<TelegramSend>
  /** پیگیریِ همان ارسال تا وقتی بات کارش تمام شود */
  telegramSendStatus(id: string): Promise<TelegramSend>
  /** هنرمندهای دنبال‌شده‌ی یک چت (بدون chatId: همه) */
  follows(chatId?: number, signal?: AbortSignal): Promise<Follow[]>
  /** وضعیتِ دکمه‌ی Follow روی صفحه‌ی هنرمند */
  followState(chatId: number, artistId: string, signal?: AbortSignal): Promise<FollowState>
  follow(chatId: number, req: FollowRequest): Promise<FollowState>
  unfollow(chatId: number, artistId: string): Promise<void>
  /** پری‌فچ فایل استریم برای ترک بعدی صف در پس‌زمینه */
  prefetchStream?(track: Track): Promise<void>
}

/**
 * وضعیتِ اتصالِ وب به بات تلگرام.
 *
 * `connected` و `linked` دو چیزِ متفاوت‌اند و کاربر باید بداند کدام لنگ است:
 * اولی یعنی سرویسِ بات اصلاً بالا نیست، دومی یعنی بالاست ولی هنوز نمی‌داند
 * فایل را به کدام چت بفرستد.
 */
export interface TelegramStatus {
  connected: boolean
  linked: boolean
  chatTitle: string | null
  /** شناسه‌ی چتِ وصل‌شده — ردیفِ Follow به همین می‌چسبد */
  chatId: number | null
  botUsername: string | null
}

export interface TelegramPairing {
  code: string
  /** ثانیه */
  expiresIn: number
  /** لینکی که تلگرام را باز می‌کند و خودش کد را می‌فرستد */
  deepLink: string | null
}

export type TelegramSendStatus = 'pending' | 'sending' | 'done' | 'error'

export interface TelegramSend {
  id: string
  status: TelegramSendStatus
  error: string | null
}

/** یک ترکِ تنها، یا یک آلبوم/پلی‌لیستِ کامل با همان مرجعی که getAlbum می‌گیرد */
export type TelegramSendRequest =
  | { kind: 'track'; track: Track; quality: Quality; keep?: boolean }
  | { kind: 'album'; ref: string; title: string; quality: Quality; keep?: boolean }

/** یک هنرمندِ دنبال‌شده — همان چیزی که بات هر ۳۰ دقیقه چک می‌کند */
export interface Follow {
  id: number
  chatId: number
  artistId: string
  artistName: string
  artistSourceUrl: string
  source: Source
  artworkUrl: string | null
  lastReleaseId: string | null
  lastReleaseTitle: string | null
}

/** بدنه‌ی درخواستِ دنبال‌کردن — seedِ آخرین انتشار از صفحه‌ی هنرمند می‌آید */
export type FollowRequest = Omit<Follow, 'id' | 'chatId'>

export interface FollowState {
  followed: boolean
  follow: Follow | null
  /** فقط روی پاسخِ follow معنا دارد: ردیفِ تازه ساخته شد؟ */
  created: boolean
}

/** یک ترکِ آماده در یک کیفیت مشخص — واحد بسته‌بندی ZIP */
export interface ZipItem {
  trackId: string
  quality: Quality
  /**
   * شناسه‌ی جابِ سرور، وقتی صدازننده از قبل داردش (ردیف‌های کتابخانه).
   *
   * بدونِ این، لایه‌ی HTTP مجبور بود از نگاشتِ درون‌حافظه‌ایِ (ترک، کیفیت) →
   * jobId استفاده کند؛ آن نگاشت فقط با دانلود در همین بازدید پر می‌شود، پس
   * ZIP گرفتن از کتابخانه بعد از یک رفرشِ ساده هیچ‌وقت کار نمی‌کرد.
   */
  jobId?: string
}
