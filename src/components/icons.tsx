interface P {
  className?: string
}

const base = 'w-4 h-4'

export const DownloadIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M12 3v12m0 0 4-4m-4 4-4-4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" />
  </svg>
)

export const PlayIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M8 5.5v13l11-6.5-11-6.5Z" strokeLinejoin="round" />
  </svg>
)

export const PauseIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
    <rect x="7" y="5" width="3.5" height="14" rx="1" />
    <rect x="13.5" y="5" width="3.5" height="14" rx="1" />
  </svg>
)

/** «قبلی» — در RTL برمی‌گردد چون معنایش جهت‌دار است، نه شکلش */
export const PrevIcon = ({ className = base }: P) => (
  <svg
    viewBox="0 0 24 24"
    fill="currentColor"
    className={`${className} rtl:-scale-x-100`}
  >
    <path d="M9 12 18 6v12L9 12Z" />
    <rect x="5.5" y="6" width="2.2" height="12" rx="1" />
  </svg>
)

export const NextIcon = ({ className = base }: P) => (
  <svg
    viewBox="0 0 24 24"
    fill="currentColor"
    className={`${className} rtl:-scale-x-100`}
  >
    <path d="M15 12 6 18V6l9 6Z" />
    <rect x="16.3" y="6" width="2.2" height="12" rx="1" />
  </svg>
)

export const VolumeIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M4 9.5h3L11.5 6v12L7 14.5H4v-5Z" strokeLinejoin="round" />
    <path d="M15 9.5a3.5 3.5 0 0 1 0 5M17.5 7a7 7 0 0 1 0 10" strokeLinecap="round" />
  </svg>
)

export const MuteIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M4 9.5h3L11.5 6v12L7 14.5H4v-5Z" strokeLinejoin="round" />
    <path d="m15.5 10 4 4m0-4-4 4" strokeLinecap="round" />
  </svg>
)

export const ShuffleIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M3.4 7.4H7l9.6 9.2h4M18.1 14.1l2.5 2.5-2.5 2.5" />
    <path d="M3.4 16.6H7l2.8-2.7M13.9 10.1l2.7-2.7h4M18.1 4.9l2.5 2.5-2.5 2.5" />
  </svg>
)

export const RepeatIcon = ({ className = base, one = false }: P & { one?: boolean }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M8.6 7.6h6.8a4.4 4.4 0 0 1 0 8.8H8.6a4.4 4.4 0 0 1 0-8.8ZM13.5 5.7l1.9 1.9-1.9 1.9M10.5 14.5 8.6 16.4l1.9 1.9" />
    {one && (
      <text x="12" y="14.5" textAnchor="middle" fontSize="8" fontWeight="bold" fill="currentColor" stroke="none">
        1
      </text>
    )}
  </svg>
)

export const SearchIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={className}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" strokeLinecap="round" />
  </svg>
)

export const RetryIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M20 12a8 8 0 1 1-2.3-5.6" strokeLinecap="round" />
    <path d="M20 4v4h-4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export const CloseIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={className}>
    <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
  </svg>
)

export const CheckIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <path d="m5 12.5 4.5 4.5L19 7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

/**
 * تیکِ کشیده‌شده — همان شکلِ `CheckIcon` ولی مسیرش با `check-draw` از هیچ
 * درمی‌آید. برای لحظه‌ی «آماده شد»: چشم، کشیده‌شدنِ تیک را به‌عنوان تأیید
 * می‌خواند، نه ظاهرشدنِ ناگهانیِ یک آیکون.
 */
export const CheckDrawIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <path d="m5 12.5 4.5 4.5L19 7" strokeLinecap="round" strokeLinejoin="round" className="check-draw" />
  </svg>
)

/**
 * شورونِ «ادامه» — در RTL به چپ و در LTR به راست اشاره می‌کند.
 * برای استفاده‌های چرخشی (مثل جمع‌کردن پنل) flip را خاموش کن.
 */
export const ChevronIcon = ({ className = base, flip = true }: P & { flip?: boolean }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    className={`${className} ${flip ? 'ltr:-scale-x-100' : ''}`}
  >
    <path d="m15 6-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export const HeadphonesIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M4 15v-3a8 8 0 0 1 16 0v3" strokeLinecap="round" />
    <rect x="2.5" y="14" width="4.5" height="6.5" rx="2" />
    <rect x="17" y="14" width="4.5" height="6.5" rx="2" />
  </svg>
)

export const PhoneIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <rect x="6.5" y="2.5" width="11" height="19" rx="2.5" />
    <path d="M10.5 18.5h3" strokeLinecap="round" />
  </svg>
)

export const SunIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19" strokeLinecap="round" />
  </svg>
)

export const MoonIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" strokeLinejoin="round" />
  </svg>
)

/** فلش «برو» — در RTL خودکار برمی‌گردد */
export const ArrowIcon = ({ className = base }: P) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.9"
    className={`${className} rtl:-scale-x-100`}
  >
    <path d="M5 12h13m0 0-5-5m5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

/** فلش عمودی با قابلیت چرخش ۱۸۰ درجه برای تغییر جهت سورت (BitChord Arrow Flip) */
export const ArrowUpIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <path d="M12 19V5m0 0-5 5m5-5 5 5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export const LinkIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M10 13.5a3.5 3.5 0 0 0 5 0l3-3a3.54 3.54 0 0 0-5-5l-1.2 1.2" strokeLinecap="round" />
    <path d="M14 10.5a3.5 3.5 0 0 0-5 0l-3 3a3.54 3.54 0 0 0 5 5l1.2-1.2" strokeLinecap="round" />
  </svg>
)

export const ZipIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className={className}>
    <rect x="3" y="4" width="18" height="4" rx="1.2" />
    <path d="M5 8v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8" />
    <path d="M11 12h2M11 15h2" strokeLinecap="round" />
  </svg>
)

export const HomeIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M4 10.2 12 4l8 6.2V19a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19z" strokeLinejoin="round" />
    <path d="M9.6 20.5v-6h4.8v6" strokeLinejoin="round" opacity="0.45" />
  </svg>
)

export const LibraryIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M4.6 4.8v14.4M9.2 4.8v14.4M13.8 4.8v14.4M17.2 5.6l3.4 13.3" />
  </svg>
)

export const TrashIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M4 7h16M10 4h4M9 7v12M15 7v12" strokeLinecap="round" />
    <path d="M6 7v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7" strokeLinecap="round" />
  </svg>
)

export const LyricsIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M9 18V6l10-2v12" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="6.5" cy="18" r="2.5" />
    <circle cx="16.5" cy="16" r="2.5" />
  </svg>
)

export const WarnIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M12 4.5 21 20H3l9-15.5Z" strokeLinejoin="round" />
    <path d="M12 10v4.5" strokeLinecap="round" />
    <circle cx="12" cy="17.2" r="0.9" fill="currentColor" stroke="none" />
  </svg>
)

/** «نسخه‌ی دیگر» — شاخه گرفتن از یک انتخاب به انتخابی دیگر */
export const SwapIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M4 8h13m0 0-3.5-3.5M17 8l-3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M20 16H7m0 0 3.5-3.5M7 16l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

/** صف پخش — چند خط لیست به‌علاوه‌ی مثلثِ پخش، مثل آیکون «بعدی در صف» یوتیوب */
export const QueueIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M3.5 6.5h11M3.5 12h11M3.5 17.5h6" strokeLinecap="round" />
    <path d="M16.5 12.3v6.4l5-3.2-5-3.2Z" strokeLinejoin="round" fill="currentColor" stroke="none" />
  </svg>
)

/** رادیوی خودکار — بدنه‌ی دستگاه، آنتن و دکمه‌ی بلندگو */
export const RadioIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M7 9.5 16 4M18 9.5l2-2" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="18.3" cy="6" r="0.9" fill="currentColor" stroke="none" />
    <rect x="3" y="9.5" width="18" height="11" rx="2" />
    <circle cx="8" cy="15" r="2.3" />
    <path d="M13.5 13.3h4M13.5 16.7h2.5" strokeLinecap="round" />
  </svg>
)

/** شافلِ هوشمند — یک ستاره‌ی درخشان، زبانِ بصریِ رایج برای «هوشمند/خودکار» */
export const SparkleIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className={className}>
    <path
      d="M12 3.5c.6 2.9 1.4 4.4 2.3 5.3.9.9 2.4 1.7 5.3 2.3-2.9.6-4.4 1.4-5.3 2.3-.9.9-1.7 2.4-2.3 5.3-.6-2.9-1.4-4.4-2.3-5.3-.9-.9-2.4-1.7-5.3-2.3 2.9-.6 4.4-1.4 5.3-2.3.9-.9 1.7-2.4 2.3-5.3Z"
      strokeLinejoin="round"
      fill="currentColor"
      fillOpacity="0.15"
    />
    <path d="M19 3.5v3M17.5 5h3" strokeLinecap="round" />
  </svg>
)

/** حبابِ گفتگو — دکمه‌ی باز/بستنِ چت‌بات وایب */
export const ChatIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path
      d="M4 5.5h16v10H9l-4 3.5v-3.5H4v-10Z"
      strokeLinejoin="round"
      strokeLinecap="round"
    />
    <path d="M8 9.5h8M8 12.5h5" strokeLinecap="round" />
  </svg>
)

export const Spinner = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" className={`${className} animate-spin`}>
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.2" opacity="0.25" />
    <path
      d="M21 12a9 9 0 0 0-9-9"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
    />
  </svg>
)

export const MicIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
  </svg>
)

/** سنجاقِ آفلاین — فلشِ دانلود روی یک دستگاه، نه ابر */
export const OfflineIcon = ({ className = base, filled = false }: P & { filled?: boolean }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <rect x="5" y="3" width="14" height="18" rx="2.5" fill={filled ? 'currentColor' : 'none'} opacity={filled ? 0.15 : 1} />
    <rect x="5" y="3" width="14" height="18" rx="2.5" />
    {filled ? (
      <path d="M8.5 12.5l2.5 2.5 4.5-5" strokeLinecap="round" strokeLinejoin="round" />
    ) : (
      <path d="M12 8v6m0 0 2.5-2.5M12 14l-2.5-2.5" strokeLinecap="round" strokeLinejoin="round" />
    )}
  </svg>
)

export const ScissorsIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <circle cx="6" cy="6" r="2.5" />
    <circle cx="6" cy="18" r="2.5" />
    <path d="M8 7.5 20 18M8 16.5 20 6" strokeLinecap="round" />
  </svg>
)

export const SlidersIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M5 4v6m0 4v6M12 4v10m0 4v2M19 4v2m0 4v10" strokeLinecap="round" />
    <circle cx="5" cy="12" r="2" />
    <circle cx="12" cy="16" r="2" />
    <circle cx="19" cy="8" r="2" />
  </svg>
)

export const TimerIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <circle cx="12" cy="13" r="8" />
    <path d="M12 9v4l2.5 2M9 2h6" strokeLinecap="round" />
  </svg>
)

export const PlaylistIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M4 6h11M4 10h11M4 14h7" strokeLinecap="round" />
    <circle cx="17" cy="16" r="3" />
    <path d="M20 16V7l-3 1" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export const PlusIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M12 5v14M5 12h14" strokeLinecap="round" />
  </svg>
)

export const GridIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <rect x="4" y="4" width="7" height="7" rx="1.6" />
    <rect x="13" y="4" width="7" height="7" rx="1.6" />
    <rect x="4" y="13" width="7" height="7" rx="1.6" />
    <rect x="13" y="13" width="7" height="7" rx="1.6" />
  </svg>
)

export const ListIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M9 6h11M9 12h11M9 18h11" strokeLinecap="round" />
    <circle cx="5" cy="6" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="5" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="5" cy="18" r="1.2" fill="currentColor" stroke="none" />
  </svg>
)

/** مرتب‌سازی — سه خطِ کوتاه‌شونده، قراردادِ آشنای «ترتیب» */
export const SortIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M4 7h13M4 12h9M4 17h5" strokeLinecap="round" />
    <path d="M18 11v9m0 0 2.5-2.5M18 20l-2.5-2.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export const ArtistIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <circle cx="12" cy="8" r="3.5" />
    <path d="M5 20a7 7 0 0 1 14 0" strokeLinecap="round" />
  </svg>
)

/** آلبوم — صفحه‌ی گرام، نه یک مربعِ دیگر که با کاور اشتباه شود */
export const AlbumIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="2.2" />
  </svg>
)

/**
 * نشانِ «همین الان دارد پخش می‌شود» — سه میله‌ی اکولایزر.
 *
 * وقتی مکث است میله‌ها می‌ایستند ولی محو نمی‌شوند: ردیف باید همچنان بگوید
 * «این همانی است که در نوارِ پخش است».
 */
export const EqualizerIcon = ({ className = base, animate = true }: P & { animate?: boolean }) => (
  <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
    {[
      { x: 4, delay: '0s', h: 10 },
      { x: 10, delay: '0.35s', h: 16 },
      { x: 16, delay: '0.7s', h: 7 },
    ].map((bar) => (
      <rect
        key={bar.x}
        x={bar.x}
        y={20 - bar.h}
        width="4"
        height={bar.h}
        rx="1.5"
        className={animate ? 'wave-bar' : undefined}
        style={animate ? { animationDelay: bar.delay, animationDuration: '1.1s' } : undefined}
      />
    ))}
  </svg>
)

/** منوی «بیشتر» — سه نقطه‌ی افقی، همان قراردادِ همه‌جایی */
export const DotsIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
    <circle cx="5.5" cy="12" r="1.7" />
    <circle cx="12" cy="12" r="1.7" />
    <circle cx="18.5" cy="12" r="1.7" />
  </svg>
)

/**
 * مارکِ رسمیِ تلگرام (simple-icons، CC0).
 *
 * برخلافِ لوگوهای `logos.tsx` که رنگِ برندشان را نگه می‌دارند، این یکی عمداً
 * `currentColor` است: دکمه‌اش کنارِ پخش و دانلود و متن می‌نشیند و آبیِ تلگرام
 * وسطِ آن‌ها یک وصله بود. هواپیما «سوراخِ» دایره است، پس رنگِ پس‌زمینه از تویش
 * می‌زند بیرون و در هر دو تم درست درمی‌آید.
 */
export const TelegramIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z" />
  </svg>
)

export const KeyboardIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <rect x="2" y="6" width="20" height="12" rx="2" />
    <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8" strokeLinecap="round" />
  </svg>
)

/** نمودارِ آمار — سه میله‌ی ساده، همان که تبِ «آمار» می‌خواهد */
export const StatsIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M5 20v-6M12 20V7M19 20v-9" strokeLinecap="round" />
  </svg>
)

/** قلبِ علاقه‌مندی — تناسبات ارگانیک بیت‌کورد و اپل موزیک */
export const HeartIcon = ({ className = base, filled = false }: P & { filled?: boolean }) => (
  <svg
    viewBox="0 0 24 24"
    fill={filled ? 'currentColor' : 'none'}
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden="true"
  >
    <path d="M12 20C12 20 3.2 14.6 3.2 8.9A4.5 4.5 0 0 1 12 7.4a4.5 4.5 0 0 1 8.8 1.5C20.8 14.6 12 20 12 20Z" />
  </svg>
)

/** باتری با خطِ مورب — «چیزی اینجا محدود است»، برای ردیفِ بهینه‌سازیِ باتری */
export const BatteryIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <rect x="2.5" y="8" width="15" height="8" rx="2" />
    <path d="M20.5 11v2" strokeLinecap="round" />
    <path d="M6 8.5v7" strokeLinecap="round" />
  </svg>
)

/** تمام‌صفحه (ورود به حالت سینمایی/کامل) */
export const MaximizeIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

/** خروج از تمام‌صفحه */
export const MinimizeIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

/** نشان تأیید هنرمند — ستاره‌ی دندانه‌دار با تیک در مرکز */
export const VerifiedBadgeIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
    <path d="m8.6 22.5-1.9-3.2-3.6-.8.4-3.7-2.5-2.8 2.5-2.8-.4-3.7 3.6-.8 1.9-3.2 3.4 1.5 3.4-1.5 1.9 3.2 3.6.8-.4 3.7 2.5 2.8-2.5 2.8.4 3.7-3.6.8-1.9 3.2-3.4-1.5-3.4 1.5zm2.1-7.2 6-6-1.4-1.4-4.6 4.6-2.2-2.2-1.4 1.4 3.6 3.6z" />
  </svg>
)

/** آیکون اطلاعات / درباره */
export const InfoIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8h.01M12 12v4" strokeLinecap="round" />
  </svg>
)

/** دیسک گرامافون وینیل */
export const VinylIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className} aria-hidden="true">
    <circle cx="12" cy="12" r="9.5" />
    <circle cx="12" cy="12" r="6.5" strokeDasharray="3 3" opacity="0.6" />
    <circle cx="12" cy="12" r="3.5" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
  </svg>
)

/** کاور ساده آلبوم */
export const CoverIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className} aria-hidden="true">
    <rect x="3" y="3" width="18" height="18" rx="3.5" />
    <circle cx="12" cy="12" r="3.5" opacity="0.7" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
  </svg>
)

/** موج فرکانسی صوتی / ویژوالایزر */
export const WaveformIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className={className} aria-hidden="true">
    <path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 11v2" />
  </svg>
)

/** الماس نشان کیفیت استودیویی / لاس‌لس (Lossless Audio Diamond) */
export const QualityDiamondIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M6 3h12l4 7-10 11L2 10l4-7z" />
    <path d="M2 10h20M12 21 8 10 12 3l4 7-4 11" opacity="0.7" />
  </svg>
)

/** حباب نقل‌قول متن ترانه به سبک اپل موزیک و بیت‌کورد */
export const LyricsQuoteIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M6 3.5h12q3 0 3 3V15q0 3-3 3h-8l-4 3v-3q-3 0-3-3V6.5q0-3 3-3Z" />
    <path
      fill="currentColor"
      stroke="none"
      d="M7.6 8h3v3.1q0 2.1-2.5 2.6l-.6-1.4q1.2-.3 1.2-1.3h-1.1V8Zm5.2 0h3v3.1q0 2.1-2.5 2.6l-.6-1.4q1.2-.3 1.2-1.3h-1.1V8Z"
    />
  </svg>
)

/** بلندگوی کم‌صدا (Volume Down) */
export const VolumeDownIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className} aria-hidden="true">
    <path d="M4 9.5h3L11.5 6v12L7 14.5H4v-5Z" strokeLinejoin="round" />
    <path d="M15 10a3 3 0 0 1 0 4" strokeLinecap="round" />
  </svg>
)

/** بلندگوی پرصدا (Volume Up) */
export const VolumeUpIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={className} aria-hidden="true">
    <path d="M4 9.5h3L11.5 6v12L7 14.5H4v-5Z" strokeLinejoin="round" />
    <path d="M15 8.5a5 5 0 0 1 0 7M18 6a8.5 8.5 0 0 1 0 12" strokeLinecap="round" />
  </svg>
)

/** اینفینیتی / اتوپلی (Infinity / Autoplay) با انحنای متقارن بیت‌کورد */
export const InfinityIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M12 12C10.1 9.1 8.7 8 7.1 8a4 4 0 0 0 0 8c1.6 0 3-1.1 4.9-4 1.9-2.9 3.3-4 4.9-4a4 4 0 0 1 0 8c-1.6 0-3-1.1-4.9-4Z" />
  </svg>
)

/** میله‌های اکولایزر برای ترک در حال پخش در صف */
export const EqWaveIcon = ({ className = '' }: P) => (
  <span aria-hidden className={`inline-flex items-end gap-[2px] h-3.5 ${className}`}>
    <span className="eq-bar w-[2.5px] rounded-full bg-current" style={{ height: '60%' }} />
    <span className="eq-bar w-[2.5px] rounded-full bg-current" style={{ height: '100%' }} />
    <span className="eq-bar w-[2.5px] rounded-full bg-current" style={{ height: '40%' }} />
  </span>
)

/** سنجاق / پونز پین کردن (BitChord Pin) */
export const PinIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <circle cx="13" cy="8.4" r="3.4" />
    <path d="m10.8 10.8-5.2 8.8" />
  </svg>
)

/** بج دالبی اتموس (Dolby Atmos) برای صدای فراگیر و کیفیت استودیویی */
export const DolbyAtmosBadge = ({ className = 'w-5 h-3' }: P) => (
  <svg viewBox="0 0 109 77" fill="currentColor" className={className} aria-label="Dolby Atmos">
    <path
      fillRule="evenodd"
      d="M0 0v76.6h109V0H0zm12.9 10h12.4c12.9 0 23.6 12.9 23.6 28.2 0 15.7-10.7 28.4-23.6 28.4H12.9V10zm70.8 0h12.5v56.6H83.7C70.8 66.6 60 53.9 60 38.2c0-15.3 10.8-28.2 23.7-28.2z"
    />
  </svg>
)

export const EyeIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
)

export const EyeOffIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61M2 2l20 20" />
  </svg>
)

/** نشان امواج صوتی بیت‌کورد (BitChord Audio Waves Mark) */
export const BitChordWaveLogo = ({ className = 'w-6 h-4' }: P) => (
  <svg viewBox="0 0 730 484" fill="currentColor" className={className} aria-hidden="true">
    <path d="M6.7 317C20.2 294.2 49.7 286.6 72.4 300.2c165.2 98.1 437.7 107.1 595.4 59.2 25.3-7.7 52.1 6.6 59.8 32 7.7 25.3-6.6 52.1-32 59.8-181 55-482 44.3-672.1-68.5C0.7 369.1-6.8 339.7 6.7 317Zm71.1-162.1c11.6-18.8 36.2-24.8 55-13.2 137.8 84.7 347.7 109.2 510.7 59.8 21.1-6.4 43.4 5.5 49.9 26.6 6.4 21.1-5.5 43.4-26.6 49.8-186.1 56.5-417.5 29.1-575.7-68.1-18.8-11.6-24.7-36.2-13.3-54.9Zm62.7-139.6c9.2-15 28.9-19.8 43.9-10.6 120.3 73.5 271.8 90.1 450.2 49.4 17.2-3.9 34.3 6.9 38.2 24.1 3.9 17.2-6.8 34.3-24 38.2-195.2 44.6-362.7 25.4-497.8-57.1-15-9.2-19.8-28.9-10.5-44Z" />
  </svg>
)

/** نماد اشتراک‌گذاری (TIDAL Share) */
export const ShareIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <circle cx="18" cy="5" r="3" />
    <circle cx="6" cy="12" r="3" />
    <circle cx="18" cy="19" r="3" />
    <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
    <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
  </svg>
)

/** نماد سه خط افقی صف پخش (TIDAL Queue Menu) */
export const MenuLinesIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className={className} aria-hidden="true">
    <line x1="4" y1="7" x2="20" y2="7" />
    <line x1="4" y1="12" x2="20" y2="12" />
    <line x1="4" y1="17" x2="20" y2="17" />
  </svg>
)

/** نماد دوربین و لنز برای تغییر حالت و ویژوالایزر (TIDAL Camera/Visualizer) */
export const CameraLensIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={className} aria-hidden="true">
    <rect x="3" y="3" width="18" height="18" rx="6" />
    <circle cx="12" cy="12" r="4.2" strokeWidth="1.8" />
    <circle cx="16.5" cy="7.5" r="1.2" fill="currentColor" stroke="none" />
  </svg>
)

/** نماد دکمه شناور همگام‌سازی لیریکس (TIDAL Lyrics Sync / Auto-scroll) */
export const SyncLyricsIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
    <path d="M3 3v5h5" />
    <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
    <path d="M16 21h5v-5" />
    <circle cx="12" cy="12" r="1.5" fill="currentColor" />
  </svg>
)



/**
 * نت‌های چنگ به هم پیوسته (Instrumental)
 * برگرفته از BitChordIcons.MusicNote برای بخش‌های بی‌کلام لیریکس
 */
export const InstrumentalIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path fill="currentColor" stroke="none" d="M4.2 17.7a2.9 2.5 0 1 1 5.8 0 2.9 2.5 0 0 1-5.8 0ZM14.2 15.9a2.9 2.5 0 1 1 5.8 0 2.9 2.5 0 0 1-5.8 0Z" />
    <path d="M10 17.7V6.7M20 15.9V4.9M10 6.7l10-1.8" />
  </svg>
)

/**
 * قطب‌نمای کاوش (Explore Compass)
 * برگرفته از BitChordIcons.Explore برای کشف موسیقی و پیشنهادها
 */
export const ExploreIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <circle cx="12" cy="12" r="8.6" />
    <polygon points="15.4,8.6 13.6,13.6 8.6,15.4 10.4,10.4" fill="currentColor" fillOpacity="0.2" stroke="currentColor" />
  </svg>
)

/**
 * سرعت‌سنج / گیج عملکرد و پینگ سرور (Performance Gauge)
 * برگرفته از BitChordIcons.Performance
 */
export const PerformanceGaugeIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d="M4.1 16.8a8.4 8.4 0 1 1 15.8 0" />
    <path d="m12 15.8 4.7-6.5" />
    <circle cx="12" cy="16.9" r="1.1" fill="currentColor" />
    <path d="M5.4 19.5h13.2" />
  </svg>
)

/**
 * ساعت انتظار صف دانلود (Clock / Pending)
 * برگرفته از BitChordIcons.Clock
 */
export const ClockPendingIcon = ({ className = base }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <circle cx="12" cy="12" r="8.6" />
    <polyline points="12,7.4 12,12 15.4,13.8" />
  </svg>
)

