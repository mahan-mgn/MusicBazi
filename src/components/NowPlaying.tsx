import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { deriveHarmonics, dominantColor, fallbackTint, tidalBgColor } from '../lib/artColor'
import { engine } from '../lib/audioEngine'
import { digits } from '../lib/format'
import { useDialog } from '../lib/useDialog'
import { usePopover } from '../lib/usePopover'
import { useSheetDrag } from '../lib/useSheetDrag'
import { useCoverSwipe, type SwipeDir } from '../lib/useCoverSwipe'
import { COVER_VT } from '../lib/viewTransition'
import { useI18n } from '../lib/i18n'
import { parseLrc, type LyricLine } from '../lib/lrc'
import { haptic, share } from '../lib/native'
import { useFavorites } from '../store/favorites'
import { jobIdOf, usePlayer, type PlayItem } from '../store/player'
import { useRecent } from '../store/recent'
import { useSettings } from '../store/settings'
import { PlaylistPicker } from './AddToPlaylist'
import AudioSettings from './AudioSettings'
import Artwork, { artBlurUrl } from './Artwork'
import LikeHeart from './LikeHeart'
import LyricsPanel from './LyricsPanel'
import PlayPauseIcon from './PlayPauseIcon'
import QualitySelector from './QualitySelector'
import ThinSlider from './ThinSlider'
import {
  ChevronIcon,
  CloseIcon,
  DotsIcon,
  EqWaveIcon,
  LyricsQuoteIcon,
  MaximizeIcon,
  MenuLinesIcon,
  MinimizeIcon,
  NextIcon,
  PlusIcon,
  PrevIcon,
  RepeatIcon,
  ShareIcon,
  ShuffleIcon,
  Spinner,
  WarnIcon,
} from './icons'

type PanelView = 'cover' | 'lyrics' | 'queue'

type LyricsState =
  | { kind: 'loading' }
  | { kind: 'none' }
  | { kind: 'synced'; lines: LyricLine[] }
  | { kind: 'plain'; text: string }

/** تشخیص عنصر تمام‌صفحه به صورت Cross-Browser */
function getFullscreenElement(): Element | null {
  if (typeof document === 'undefined') return null
  const doc = document as unknown as {
    fullscreenElement?: Element | null
    webkitFullscreenElement?: Element | null
  }
  return doc.fullscreenElement || doc.webkitFullscreenElement || null
}

/** یک ردیف از صف پخش داخل نمای بزرگ */
function QueueRow({
  item,
  active,
  onPlay,
  onRemove,
}: {
  item: PlayItem
  active: boolean
  onPlay: () => void
  onRemove: () => void
}) {
  const { t } = useI18n()
  return (
    <div
      className={`group flex items-center gap-3 rounded-2xl px-3 py-2.5 transition duration-200 ${
        active
          ? 'bg-white/20 text-white shadow-sm ring-1 ring-white/25'
          : 'hover:bg-white/10 text-white/90'
      }`}
    >
      <button onClick={onPlay} className="flex min-w-0 flex-1 items-center gap-3.5 text-start cursor-pointer">
        <div className="relative shrink-0">
          <Artwork
            src={item.track.artworkUrl}
            alt={item.track.album ?? item.track.title}
            seed={item.track.albumId ?? item.track.id}
            className={`size-11 rounded-xl shadow-md ${active ? 'opacity-40' : ''}`}
          />
          {active && (
            <span aria-hidden className="absolute inset-0 grid place-items-center text-white">
              <EqWaveIcon className="size-4" />
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1 space-y-0.5">
          <p
            className={`bidi truncate text-sm sm:text-base ${
              active ? 'font-bold text-white' : 'font-semibold text-white/95'
            }`}
          >
            {item.track.title}
          </p>
          <p className="bidi truncate text-xs text-white/60">
            <bdi>{item.track.artist}</bdi>
          </p>
        </div>
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation()
          onRemove()
        }}
        aria-label={t.removeFromQueue}
        title={t.removeFromQueue}
        className="grid size-9 shrink-0 place-items-center rounded-full text-white/50 opacity-70 transition hover:bg-white/15 hover:text-white sm:opacity-0 sm:group-hover:opacity-100 cursor-pointer"
      >
        <CloseIcon className="size-4" />
      </button>
    </div>
  )
}

/** فرمت دقیق زمان به سبک TIDAL: همیشه حداقل دو رقم دقیقه (00:13 و 02:30) */
function fmtTidalDuration(seconds: number, lang: string): string {
  const total = Number.isFinite(seconds) ? Math.max(0, Math.round(seconds)) : 0
  const h = Math.floor(total / 3600)
  const m = Math.floor(total / 60) % 60
  const s = total % 60
  const text = h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return digits(text, lang)
}

/** اسکرابر پیشرفت مویی با تامب کپسولی و نشان کیفیت صدا به سبک تایدال */
function NowPlayingSeekBar({
  total,
  seek,
}: {
  total: number
  seek: (val: number) => void
}) {
  const position = usePlayer((s) => s.position)
  const { quality } = useSettings()
  const { t, lang } = useI18n()
  const [qualityMenuOpen, setQualityMenuOpen] = useState(false)
  const [scrubPosition, setScrubPosition] = useState<number | null>(null)

  const currentPos = scrubPosition !== null ? scrubPosition : Math.min(position, total)
  const progressPct = total > 0 ? Math.min(100, Math.max(0, (currentPos / total) * 100)) : 0

  const qualityLabel = useMemo(() => {
    if (quality === 'flac' || quality === 'original') return '24-BIT 44.1KHZ FLAC'
    if (quality === '320') return '320 KBPS AAC'
    if (quality === '192') return 'HIGH • 192 KBPS'
    if (quality === '128') return 'NORMAL • 128 KBPS'
    return `${String(quality).toUpperCase()} QUALITY`
  }, [quality])

  return (
    <div className="w-full space-y-2 select-none" dir="ltr">
      <div className="relative w-full">
        <ThinSlider
          value={currentPos}
          max={total || 1}
          onChange={setScrubPosition}
          onChangeFinished={(val) => {
            setScrubPosition(null)
            seek(val)
          }}
          enableHapticTick
          trackHeight="h-[3px]"
          label={t.seekBar}
          className="w-full"
        />
        {/* تامب کپسولی عمودی سفید مشخصه TIDAL با مهار لبه‌ها */}
        <div
          className="pointer-events-none absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2 h-4 rounded-full bg-white shadow-md transition-transform"
          style={{ left: `clamp(4px, ${progressPct}%, calc(100% - 4px))` }}
        />
      </div>

      <div className="flex items-center justify-between text-xs font-mono font-medium tabular-nums text-white/60 px-0.5">
        <span>{fmtTidalDuration(currentPos, lang)}</span>

        <div className="relative inline-flex items-center">
          <button
            onClick={() => setQualityMenuOpen((v) => !v)}
            aria-haspopup="dialog"
            aria-expanded={qualityMenuOpen}
            aria-label={t.qualityMenu}
            title={t.qualityMenu}
            className="group/q inline-flex items-center text-[11px] font-bold font-mono tracking-widest uppercase text-white/55 hover:text-white transition cursor-pointer"
          >
            <span>{qualityLabel}</span>
          </button>

          <QualitySelector
            open={qualityMenuOpen}
            onClose={() => setQualityMenuOpen(false)}
          />
        </div>

        <span>{fmtTidalDuration(total, lang)}</span>
      </div>
    </div>
  )
}

/**
 * صفحه Now Playing بازطراحی‌شده دقیقاً مطابق پلتفرم TIDAL
 * ویژگی‌ها:
 *  - پس‌زمینه یکپارچه و عمیق همرنگ کاور موزیک (TIDAL Immersive Tint)
 *  - نشان‌های حروف اول نام هنرمندان در هدر (Artist Initials Badges)
 *  - نشان محتوای صریح ([E] Explicit Badge) کنار عنوان ترک
 *  - دکمه بزرگ (+) برای افزودن سریع به پلی‌لیست
 *  - نشان کیفیت صوتی تایدال در مرکز اسکرابر (24-BIT 44.1KHZ FLAC)
 *  - دکمه‌های ترانسپورت ۵گانه با آیکون پخش/توقف توپر و بدون کادر گرد
 *  - فوتر ۳ دکمه‌ای دایره‌ای (صف پخش، اشتراک‌گذاری، منوی بیشتر) و عنوان «Playing from»
 */
// کش عکس پروفایل هنرمندان در سطح ماژول برای جلوگیری از درخواست‌های تکراری
const artistAvatarCache = new Map<string, string | null>()

export default function NowPlaying({
  onClose,
  initialTint,
}: {
  onClose: () => void
  initialTint?: [number, number, number] | null
}) {
  const {
    queue,
    index,
    playing,
    duration,
    repeat,
    shuffle,
    failed,
    radio,
    radioLoading,
    toggle,
    next,
    prev,
    seek,
    cycleRepeat,
    toggleShuffle,
    play,
    drop,
  } = usePlayer()
  const { t, lang } = useI18n()
  const [closing, setClosing] = useState(false)
  const [panel, setPanel] = useState<PanelView>('cover')
  const [lyrics, setLyrics] = useState<LyricsState>({ kind: 'loading' })
  const [playlistPickerOpen, setPlaylistPickerOpen] = useState(false)
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)

  const playlistPickerBox = usePopover<HTMLDivElement>(playlistPickerOpen, () =>
    setPlaylistPickerOpen(false),
  )
  const moreMenuBox = usePopover<HTMLDivElement>(moreMenuOpen, () =>
    setMoreMenuOpen(false),
  )

  // تشخیص اندازه‌ی دسکتاپ به صورت واکنشی
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(min-width: 1024px)').matches : false,
  )

  // تشخیص حالت افقی در گوشی‌ها (Landscape) برای چیدمان متناسب دو ستونه
  const [isLandscape, setIsLandscape] = useState(() =>
    typeof window !== 'undefined'
      ? window.matchMedia('(orientation: landscape) and (max-height: 550px)').matches
      : false,
  )

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia('(min-width: 1024px)')
    const onChange = (e: MediaQueryListEvent | MediaQueryList) => setIsDesktop(e.matches)
    if (mq.addEventListener) {
      mq.addEventListener('change', onChange)
      return () => mq.removeEventListener('change', onChange)
    } else {
      mq.addListener(onChange)
      return () => mq.removeListener(onChange)
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia('(orientation: landscape) and (max-height: 550px)')
    const onChange = (e: MediaQueryListEvent | MediaQueryList) => setIsLandscape(e.matches)
    if (mq.addEventListener) {
      mq.addEventListener('change', onChange)
      return () => mq.removeEventListener('change', onChange)
    } else {
      mq.addListener(onChange)
      return () => mq.removeListener(onChange)
    }
  }, [])

  // وضعیت تمام‌صفحه مرورگر
  const [isFullscreen, setIsFullscreen] = useState(() => Boolean(getFullscreenElement()))

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(Boolean(getFullscreenElement()))
    document.addEventListener('fullscreenchange', onFsChange)
    document.addEventListener('webkitfullscreenchange', onFsChange)
    return () => {
      document.removeEventListener('fullscreenchange', onFsChange)
      document.removeEventListener('webkitfullscreenchange', onFsChange)
    }
  }, [])

  const toggleFullscreen = () => {
    const doc = document as unknown as {
      exitFullscreen?: () => Promise<void>
      webkitExitFullscreen?: () => Promise<void>
    }
    const docEl = document.documentElement as unknown as {
      requestFullscreen?: () => Promise<void>
      webkitRequestFullscreen?: () => Promise<void>
    }
    if (!getFullscreenElement()) {
      const requestFs = docEl.requestFullscreen || docEl.webkitRequestFullscreen
      void requestFs?.call(docEl)?.catch(() => {})
    } else {
      const exitFs = doc.exitFullscreen || doc.webkitExitFullscreen
      void exitFs?.call(doc)?.catch(() => {})
    }
  }

  const withTap = (run: () => void) => () => {
    haptic.tap()
    run()
  }

  const dismiss = () => {
    if (closing) return
    if (getFullscreenElement()) {
      const doc = document as unknown as {
        exitFullscreen?: () => Promise<void>
        webkitExitFullscreen?: () => Promise<void>
      }
      const exitFs = doc.exitFullscreen || doc.webkitExitFullscreen
      void exitFs?.call(doc)?.catch(() => {})
    }
    const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      onClose()
      return
    }
    setClosing(true)
    window.setTimeout(onClose, 290)
  }

  const onPhone = typeof window !== 'undefined' && !window.matchMedia('(min-width: 640px)').matches
  const drag = useSheetDrag({ onClose, enabled: onPhone })
  const dialog = useDialog<HTMLDivElement>(true, dismiss)

  const item = queue[index]

  // ناوبری به صفحه خواننده و آلبوم
  const handleArtistClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    dismiss()
    const ref = item?.track.artistId || item?.track.artist
    if (ref) {
      window.dispatchEvent(new CustomEvent('musicbazi:open-artist', { detail: { ref } }))
    }
  }

  const handleAlbumClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    dismiss()
    const ref = item?.track.albumId || item?.track.album
    if (ref) {
      window.dispatchEvent(new CustomEvent('musicbazi:open-album', { detail: { ref } }))
    }
  }

  const swipeEnabled = panel === 'cover' && queue.length > 1
  const swipe = useCoverSwipe({
    enabled: swipeEnabled,
    onSwipe: (dir: SwipeDir) => {
      if (dir === 'next') next()
      else play(queue, (index - 1 + queue.length) % queue.length)
    },
  })

  const peekItem = item
    ? swipe.dir === 'prev'
      ? queue[index - 1] ?? (repeat === 'all' ? queue[queue.length - 1] : null)
      : queue[index + 1] ?? (repeat === 'all' || radio ? queue[0] : null)
    : null

  // خروج از تمام‌صفحه در unmount
  useEffect(() => {
    return () => {
      if (getFullscreenElement()) {
        const doc = document as unknown as {
          exitFullscreen?: () => Promise<void>
          webkitExitFullscreen?: () => Promise<void>
        }
        const exitFs = doc.exitFullscreen || doc.webkitExitFullscreen
        void exitFs?.call(doc)?.catch(() => {})
      }
    }
  }, [])

  // قلب لایک
  const jobId = item ? jobIdOf(item) : null
  const favorite = useFavorites((s) => (jobId ? Boolean(s.items[jobId]) : false))
  const toggleFavorite = useFavorites((s) => s.toggle)

  // رنگ‌های استخراج‌شده از کاور به سبک TIDAL — دریافت رنگ اولیه از PlayerBar برای حذف پرش رنگ
  const [tint, setTint] = useState<[number, number, number] | null>(initialTint ?? null)
  useEffect(() => {
    let cancelled = false
    void dominantColor(item?.track.artworkUrl ?? null).then((c) => {
      if (!cancelled) setTint(c)
    })
    return () => {
      cancelled = true
    }
  }, [item?.track.artworkUrl])

  // واکشی متن ترانه
  useEffect(() => {
    if (panel !== 'lyrics') return
    if (!item?.lyricsUrl) {
      setLyrics({ kind: 'none' })
      return
    }
    setLyrics({ kind: 'loading' })
    let cancelled = false
    fetch(item.lyricsUrl)
      .then((r) => (r.ok ? r.text() : Promise.reject()))
      .then((raw) => {
        if (cancelled) return
        const lines = parseLrc(raw)
        if (lines.length > 0) setLyrics({ kind: 'synced', lines })
        else if (raw.trim()) setLyrics({ kind: 'plain', text: raw.trim() })
        else setLyrics({ kind: 'none' })
      })
      .catch(() => {
        if (!cancelled) setLyrics({ kind: 'none' })
      })
    return () => {
      cancelled = true
    }
  }, [panel, item?.lyricsUrl])

  useEffect(() => {
    if (!item) onClose()
  }, [item, onClose])

  if (!item) return null

  const { track } = item
  const total = duration || track.durationMs / 1000

  const repeatLabel =
    repeat === 'one' ? t.repeatOne : repeat === 'all' ? t.repeatAll : t.repeatOff

  // عنوان مبدأ پخش
  const originCaption = radio
    ? t.radio
    : track.album
      ? track.album
      : t.nowPlayingView

  // پس‌زمینهٔ بلورشده‌ی کاور — بلور سمت سرور یا خود تصویر کاور
  const bgBlur = artBlurUrl(track.artworkUrl)
  const [bgBlurFailed, setBgBlurFailed] = useState<string | null>(null)
  const bgSrc = bgBlur && bgBlurFailed !== track.artworkUrl ? bgBlur : track.artworkUrl

  // رنگ پس‌زمینه اختصاصی TIDAL و هارمونیک‌های اتمسفری نوری با فالبک پایدار از روی شناسه
  const effectiveTint = tint ?? fallbackTint(track.albumId ?? track.id)
  const tidalBg = tidalBgColor(effectiveTint)
  const harmonics = useMemo(() => deriveHarmonics(effectiveTint), [effectiveTint])

  // توکن‌های هنرمندان برای نمایش دکمه‌های پروفایل هنرمندان
  const artistTokens = useMemo(
    () =>
      (track.artist || '')
        .split(/\s*[,&/]\s*|\s+\b(?:feat\.?|ft\.?)\b\s+/i)
        .map((s) => s.trim())
        .filter(Boolean),
    [track.artist],
  )

  // عکس‌های پروفایل پلتفرم هنرمندان
  const [artistAvatars, setArtistAvatars] = useState<Record<string, string | null>>({})

  useEffect(() => {
    let cancelled = false

    artistTokens.slice(0, 3).forEach((art, idx) => {
      const ref = idx === 0 && track.artistId ? track.artistId : art

      // ۱. اگر ترک خودش عکس پروفایل دارد
      if (idx === 0 && track.artistArtworkUrl) {
        artistAvatarCache.set(ref, track.artistArtworkUrl)
        setArtistAvatars((prev) =>
          prev[ref] === track.artistArtworkUrl ? prev : { ...prev, [ref]: track.artistArtworkUrl! },
        )
        return
      }

      // ۲. اگر قبلاً در کش موجود است
      if (artistAvatarCache.has(ref)) {
        const cached = artistAvatarCache.get(ref) ?? null
        setArtistAvatars((prev) => (prev[ref] === cached ? prev : { ...prev, [ref]: cached }))
        return
      }

      // ۳. بررسی سوابق اخیر
      const recent = useRecent
        .getState()
        .items.find(
          (it) =>
            it.kind === 'artist' &&
            (it.ref === ref || it.title.trim().toLowerCase() === art.trim().toLowerCase()) &&
            it.artworkUrl,
        )
      if (recent?.artworkUrl) {
        artistAvatarCache.set(ref, recent.artworkUrl)
        setArtistAvatars((prev) => ({ ...prev, [ref]: recent.artworkUrl }))
        return
      }

      // ۴. واکشی آنلاین از سرور
      if (idx === 0 && track.artistId) {
        api.getArtist(track.artistId)
          .then((detail) => {
            if (cancelled) return
            const url = detail.artworkUrl ?? null
            artistAvatarCache.set(ref, url)
            setArtistAvatars((prev) => ({ ...prev, [ref]: url }))
          })
          .catch(() => {
            if (cancelled) return
            artistAvatarCache.set(ref, null)
          })
      } else {
        api.search(art)
          .then((res) => {
            if (cancelled) return
            const hit =
              res.artists.find((a) => a.name.trim().toLowerCase() === art.trim().toLowerCase()) ??
              res.artists[0]
            const url = hit?.artworkUrl ?? null
            artistAvatarCache.set(ref, url)
            setArtistAvatars((prev) => ({ ...prev, [ref]: url }))
          })
          .catch(() => {
            if (cancelled) return
            artistAvatarCache.set(ref, null)
          })
      }
    })

    return () => {
      cancelled = true
    }
  }, [track.id, track.artist, track.artistId, track.artistArtworkUrl, artistTokens])

  // اشتراک‌گذاری
  const handleShare = () => {
    void share({
      title: track.title,
      text: `${track.title} - ${track.artist}`,
      url: track.sourceUrl || (typeof window !== 'undefined' ? window.location.href : ''),
    })
  }

  // ۱. کاور آلبوم به سبک TIDAL
  const renderCover = (sizeClass: string) => {
    return (
      <div
        ref={swipe.cover}
        className={`relative aspect-square select-none max-h-full ${sizeClass} ${
          swipeEnabled ? 'cursor-grab touch-pan-y active:cursor-grabbing' : ''
        }`}
      >
        {/* کاور پیش‌نمایش موقع سوایپ */}
        {swipe.dir && peekItem && (
          <div ref={swipe.peek} aria-hidden className="absolute inset-0 scale-90 opacity-0 z-20">
            <Artwork
              src={peekItem.track.artworkUrl}
              alt=""
              seed={peekItem.track.albumId ?? peekItem.track.id}
              rounded="rounded-xl sm:rounded-2xl"
              className="size-full shadow-2xl shadow-black/80 ring-1 ring-white/10"
            />
          </div>
        )}

        {/* کاور اصلی تایدال با گوشه‌های گرد نرم و سایه عمیق ۶۰ پیکسلی */}
        <div className="relative z-10 size-full">
          <Artwork
            src={track.artworkUrl}
            alt={track.album ?? track.title}
            seed={track.albumId ?? track.id}
            transitionName={COVER_VT}
            rounded="rounded-xl sm:rounded-2xl"
            className="size-full shadow-[0_24px_60px_-10px_rgba(0,0,0,0.85)] object-cover"
          />
        </div>
      </div>
    )
  }

  // ۲. مشخصات و متادیتای ترک به سبک TIDAL همراه با نشان [E] و دکمه (+)
  const renderTrackInfo = () => (
    <div className="flex items-center justify-between w-full gap-3 pt-2">
      <div className="min-w-0 flex-1 space-y-1 text-start">
        <div className="flex items-center gap-2">
          <p
            className="bidi truncate text-2xl sm:text-3xl font-extrabold tracking-tight text-white"
            title={track.title}
          >
            {track.title}
          </p>
          {track.explicit && (
            <span
              title="Explicit"
              className="inline-grid size-5 shrink-0 place-items-center rounded bg-white text-black text-[11px] font-black leading-none uppercase shadow-sm"
            >
              E
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-2 text-sm sm:text-base text-white/70">
          {failed ? (
            <p className="inline-flex items-center gap-1.5 text-danger font-medium">
              <WarnIcon className="size-4" />
              {t.playFailed}
            </p>
          ) : (
            <button
              onClick={handleArtistClick}
              title={t.goToArtist(track.artist)}
              className="bidi text-white/80 transition hover:text-white hover:underline underline-offset-4 font-semibold"
            >
              <bdi>{track.artist}</bdi>
            </button>
          )}
        </div>

        {radioLoading && (
          <p className="inline-flex items-center gap-1.5 text-xs text-white/60">
            <Spinner className="size-3 text-white" />
            {t.radioFinding}
          </p>
        )}
      </div>

      {/* دکمه بزرگ (+) برای افزودن به پلی‌لیست در سمت راست عنوان */}
      <div ref={playlistPickerBox} className="relative shrink-0">
        <button
          onClick={() => setPlaylistPickerOpen((v) => !v)}
          aria-label={t.playlistAdd}
          title={t.playlistAdd}
          className="grid size-11 place-items-center rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition cursor-pointer"
        >
          <PlusIcon className="size-7" />
        </button>
        {playlistPickerOpen && (
          <div
            role="menu"
            className="absolute end-0 bottom-full mb-2 z-50 w-60 rounded-2xl bg-black/90 p-2.5 shadow-2xl backdrop-blur-xl border border-white/15"
          >
            <PlaylistPicker
              jobIds={jobId ? [jobId] : []}
              onDone={() => setPlaylistPickerOpen(false)}
            />
          </div>
        )}
      </div>
    </div>
  )

  // ۳. کنترل‌های ترانسپورت پنج‌گانه به سبک TIDAL با دکمه پخش بدون کادر دایره‌ای
  const renderTransportRow = () => (
    <div className="flex items-center justify-between w-full max-w-sm mx-auto px-2 py-1">
      {/* شافل */}
      <button
        onClick={toggleShuffle}
        aria-label={t.shuffle}
        aria-pressed={shuffle}
        title={t.shuffle}
        className={`grid size-11 place-items-center transition active:scale-90 cursor-pointer ${
          shuffle ? 'text-white' : 'text-white/40 hover:text-white'
        }`}
      >
        <ShuffleIcon className="size-5 sm:size-6" />
      </button>

      {/* قبلی */}
      <button
        onClick={withTap(prev)}
        aria-label={t.prevTrack}
        title={t.prevTrack}
        className="grid size-12 place-items-center text-white hover:text-white/80 active:scale-90 transition cursor-pointer"
      >
        <PrevIcon className="size-7 sm:size-8" />
      </button>

      {/* دکمه مرکزی پخش / مکث بدون پس‌زمینه دایره‌ای سفید (آیکون خالص تایدال) */}
      <button
        onClick={withTap(toggle)}
        aria-label={playing ? t.pause : t.play}
        title={playing ? t.pause : t.play}
        className="grid size-16 place-items-center text-white hover:scale-105 active:scale-95 transition cursor-pointer"
      >
        {radioLoading ? (
          <Spinner className="size-10 sm:size-12 text-white" />
        ) : (
          <PlayPauseIcon playing={playing} className="size-10 sm:size-12 text-white" />
        )}
      </button>

      {/* بعدی */}
      <button
        onClick={withTap(next)}
        aria-label={t.nextTrack}
        title={t.nextTrack}
        className="grid size-12 place-items-center text-white hover:text-white/80 active:scale-90 transition cursor-pointer"
      >
        <NextIcon className="size-7 sm:size-8" />
      </button>

      {/* تکرار */}
      <button
        onClick={cycleRepeat}
        aria-label={repeatLabel}
        title={repeatLabel}
        className={`grid size-11 place-items-center transition active:scale-90 cursor-pointer ${
          repeat === 'off' ? 'text-white/40 hover:text-white' : 'text-white'
        }`}
      >
        <RepeatIcon className="size-5 sm:size-6" one={repeat === 'one'} />
      </button>
    </div>
  )

  // ۴. فوتر پایینی شامل دکمه‌های دایره‌ای صف، مبدأ پخش، اشتراک‌گذاری و منوی بیشتر
  const renderFooterRow = () => (
    <div className="flex items-center justify-between w-full pt-1">
      {/* دکمه دایره‌ای صف پخش (Queue / Hamburger) */}
      <button
        onClick={() => setPanel((v) => (v === 'queue' ? 'cover' : 'queue'))}
        aria-label={t.upNext}
        aria-pressed={panel === 'queue'}
        title={t.upNext}
        className={`grid size-12 place-items-center rounded-full transition active:scale-95 cursor-pointer ${
          panel === 'queue'
            ? 'bg-white/30 text-white'
            : 'bg-white/10 text-white/80 hover:bg-white/20 hover:text-white'
        }`}
      >
        <MenuLinesIcon className="size-5" />
      </button>

      {/* مرکز: متن «Playing from» و نام آلبوم یا پلی‌لیست */}
      <div className="flex flex-col items-center justify-center text-center px-2 min-w-0 flex-1">
        <span className="text-[11px] font-medium text-white/50 tracking-wide">
          {lang === 'fa' ? 'در حال پخش از' : 'Playing from'}
        </span>
        <button
          onClick={handleAlbumClick}
          title={originCaption}
          className="bidi truncate text-xs sm:text-sm font-bold text-white hover:underline transition max-w-[160px] sm:max-w-[240px]"
        >
          <bdi>{originCaption}</bdi>
        </button>
      </div>

      {/* دکمه‌های دایره‌ای سمت راست: اشتراک‌گذاری و منوی بیشتر */}
      <div className="flex items-center gap-2 sm:gap-2.5">
        <button
          onClick={handleShare}
          aria-label={lang === 'fa' ? 'اشتراک‌گذاری' : 'Share'}
          title={lang === 'fa' ? 'اشتراک‌گذاری' : 'Share'}
          className="grid size-12 place-items-center rounded-full bg-white/10 text-white/80 hover:bg-white/20 hover:text-white transition active:scale-95 cursor-pointer"
        >
          <ShareIcon className="size-5" />
        </button>

        <div ref={moreMenuBox} className="relative">
          <button
            onClick={() => setMoreMenuOpen((v) => !v)}
            aria-label={t.moreMenu}
            aria-expanded={moreMenuOpen}
            title={t.moreMenu}
            className="grid size-12 place-items-center rounded-full bg-white/10 text-white/80 hover:bg-white/20 hover:text-white transition active:scale-95 cursor-pointer"
          >
            <DotsIcon className="size-5" />
          </button>

          {moreMenuOpen && (
            <div
              role="menu"
              className="absolute end-0 bottom-full mb-2 z-50 w-52 rounded-2xl bg-black/90 p-2 shadow-2xl backdrop-blur-xl border border-white/15 space-y-1"
            >
              {jobId && (
                <button
                  onClick={() => {
                    void toggleFavorite(jobId)
                    setMoreMenuOpen(false)
                  }}
                  className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs font-semibold text-white/90 hover:bg-white/15 transition cursor-pointer"
                >
                  <LikeHeart
                    liked={favorite}
                    onToggle={() => void toggleFavorite(jobId)}
                    ariaLabel={favorite ? t.favoriteRemove : t.favoriteAdd}
                    iconClassName="size-4"
                  />
                  <span>{favorite ? t.favoriteRemove : t.favoriteAdd}</span>
                </button>
              )}

              {item.lyricsUrl && (
                <button
                  onClick={() => {
                    setPanel((v) => (v === 'lyrics' ? 'cover' : 'lyrics'))
                    setMoreMenuOpen(false)
                  }}
                  aria-label={t.lyrics}
                  aria-pressed={panel === 'lyrics'}
                  className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs font-semibold text-white/90 hover:bg-white/15 transition cursor-pointer"
                >
                  <LyricsQuoteIcon className="size-4 text-white/70" />
                  <span>{t.lyrics}</span>
                </button>
              )}

              <div className="px-3 py-1 border-t border-white/10">
                <AudioSettings />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )

  // ۵. محتوای لیریکس
  const renderLyricsContent = () =>
    lyrics.kind === 'synced' ? (
      <LyricsPanel lines={lyrics.lines} position={engine.currentTime()} trackEnd={total} onSeek={seek} />
    ) : (
      <div className="scroll-pane no-scrollbar h-full w-full overflow-y-auto px-4 sm:px-8 py-10">
        {lyrics.kind === 'loading' ? (
          <div className="grid h-full place-items-center text-white/70">
            <Spinner className="size-8 text-white" />
          </div>
        ) : lyrics.kind === 'none' ? (
          <div className="grid h-full place-items-center px-4 text-center text-lg font-bold text-white/50">
            {t.lyricsUnavailable}
          </div>
        ) : (
          <p className="bidi whitespace-pre-line text-2xl sm:text-3xl lg:text-4xl leading-snug sm:leading-tight font-extrabold text-white/90">
            {lyrics.text}
          </p>
        )}
      </div>
    )

  // ۶. محتوای صف پخش
  const renderQueueContent = () => {
    const clearText = lang === 'fa' ? 'پاک کردن صف' : 'Clear queue'
    const tracksCountText = lang === 'fa' ? `${queue.length} آهنگ در صف` : `${queue.length} tracks in queue`
    const upcomingCount = queue.length - 1

    return (
      <div className="h-full w-full flex flex-col overflow-hidden">
        <div className="flex shrink-0 items-center justify-between pb-3 px-2 border-b border-white/10">
          <div>
            <h3 className="text-base font-bold text-white">{t.upNext}</h3>
            <p className="text-xs text-white/50 font-medium">{tracksCountText}</p>
          </div>
          {upcomingCount > 0 && (
            <button
              onClick={() => {
                const toRemove = queue.filter((_, i) => i !== index)
                for (const qItem of toRemove) {
                  drop(qItem.id)
                }
              }}
              className="rounded-full bg-white/10 px-3.5 py-1 text-xs font-semibold text-white/80 hover:text-white hover:bg-white/20 transition cursor-pointer"
            >
              {clearText}
            </button>
          )}
        </div>

        <div className="scroll-pane no-scrollbar flex-1 overflow-y-auto space-y-3 py-3 px-1">
          <div className="space-y-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-white/40 px-2">
              {t.nowPlayingView}
            </span>
            <QueueRow
              key={queue[index].id}
              item={queue[index]}
              active={true}
              onPlay={() => play(queue, index)}
              onRemove={() => drop(queue[index].id)}
            />
          </div>

          {upcomingCount > 0 ? (
            <div className="space-y-1 pt-1">
              <span className="text-[11px] font-bold uppercase tracking-wider text-white/40 px-2">
                {t.upNext} ({upcomingCount})
              </span>
              <div className="space-y-1.5">
                {queue.map((qItem, i) => {
                  if (i === index) return null
                  return (
                    <QueueRow
                      key={qItem.id}
                      item={qItem}
                      active={false}
                      onPlay={() => play(queue, i)}
                      onRemove={() => drop(qItem.id)}
                    />
                  )
                })}
              </div>
            </div>
          ) : (
            <div className="py-8 text-center text-xs text-white/40 font-medium">
              {lang === 'fa' ? 'ترک دیگری در صف نیست' : 'No upcoming tracks'}
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50">
      {/* لایه پشت شیت با پس‌زمینه تیره */}
      <div
        aria-hidden
        ref={drag.backdrop}
        onClick={dismiss}
        className={`absolute inset-0 bg-black/85 cursor-pointer ${closing ? 'np-backdrop-out' : 'np-backdrop-in'}`}
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label={t.nowPlayingView}
        tabIndex={-1}
        ref={(node) => {
          drag.sheet.current = node
          dialog.current = node
        }}
        onClick={(e) => e.stopPropagation()}
        onAnimationEnd={(e) => {
          if (closing && e.target === e.currentTarget) onClose()
        }}
        style={{
          backgroundColor: tidalBg,
          transition: 'background-color 0.8s ease',
        }}
        className={`absolute inset-0 flex flex-col overflow-hidden text-white p-4 sm:p-6 pb-[calc(1.25rem+var(--safe-b))] pt-[calc(0.75rem+var(--safe-t))] ps-[calc(1rem+var(--safe-l))] pe-[calc(1rem+var(--safe-r))] ${
          closing ? 'np-sheet-out' : 'np-sheet-in'
        }`}
      >
        {/* ============================================================== */}
        {/* لایهٔ پس‌زمینهٔ پویا و زنده از کاور آرت‌ورک و گرادیان هارمونیک     */}
        {/* ============================================================== */}
        <span aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
          {bgSrc && (
            <img
              key={bgSrc}
              src={bgSrc}
              alt=""
              onError={() => setBgBlurFailed(track.artworkUrl)}
              className="absolute inset-0 size-full scale-125 object-cover opacity-50 saturate-150 blur-3xl transition-opacity duration-700"
            />
          )}

          {/* اتمسفر نوری زنده (Living Mesh Aurora) با پالت هارمونیک */}
          <span
            className="absolute inset-0 transition-all duration-700"
            style={{
              background: `radial-gradient(ellipse 85% 65% at 50% 15%, rgb(${harmonics.dominant.join(' ')} / 0.5), transparent 75%), radial-gradient(ellipse 70% 55% at 85% 85%, rgb(${harmonics.secondary.join(' ')} / 0.38), transparent 65%), radial-gradient(ellipse 60% 50% at 15% 75%, rgb(${harmonics.accent.join(' ')} / 0.28), transparent 60%)`,
            }}
          />

          {/* لایهٔ گرادیان تیره برای تضمین خوانایی متون و کنترل‌ها به سبک TIDAL */}
          <span className="absolute inset-0 bg-black/55" />
          <span className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/85 via-black/40 to-transparent" />
          <span className="absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-black/60 to-transparent" />
        </span>

        {/* ============================================================== */}
        {/* نوار بالای پلیر به سبک TIDAL                                    */}
        {/* ============================================================== */}
        <div
          ref={drag.handle}
          className="relative flex shrink-0 items-center justify-between z-20 h-12 mb-1 sm:mb-2 select-none touch-none"
        >
          {/* سمت چپ: در نمای کاور عکس پروفایل پلتفرم هنرمندان؛ در نمای لیریکس یا صف تامبنیل آلبوم */}
          <div className="flex items-center gap-2">
            {panel === 'cover' ? (
              <div className="flex items-center -space-x-1.5 rtl:space-x-reverse">
                {artistTokens.slice(0, 3).map((art, idx) => {
                  const ref = idx === 0 && track.artistId ? track.artistId : art
                  const avatarUrl =
                    artistAvatars[ref] ?? (idx === 0 ? track.artistArtworkUrl ?? null : null)
                  return (
                    <button
                      key={idx}
                      onClick={(e) => {
                        e.stopPropagation()
                        dismiss()
                        window.dispatchEvent(
                          new CustomEvent('musicbazi:open-artist', { detail: { ref } }),
                        )
                      }}
                      title={art}
                      style={{ zIndex: 10 - idx }}
                      className="relative grid size-9 sm:size-10 place-items-center rounded-full bg-white/10 text-xs font-bold text-white ring-2 ring-black/30 hover:bg-white/20 transition cursor-pointer overflow-hidden shadow-sm"
                    >
                      <Artwork
                        src={avatarUrl}
                        alt={art}
                        seed={ref}
                        rounded="rounded-full"
                        className="size-full object-cover"
                      />
                    </button>
                  )
                })}
              </div>
            ) : (
              <button
                onClick={() => setPanel('cover')}
                aria-label={track.title}
                title="بازگشت به کاور"
                className="shrink-0 size-10 sm:size-11 rounded-lg overflow-hidden shadow-md ring-1 ring-white/15 transition hover:scale-105 active:scale-95 cursor-pointer"
              >
                <Artwork
                  src={track.artworkUrl}
                  alt={track.title}
                  seed={track.albumId ?? track.id}
                  rounded="rounded-lg"
                  className="size-full object-cover"
                />
              </button>
            )}
          </div>

          {/* سمت راست: دکمه کپسولی لیریکس در بالا راست به سبک TIDAL + دکمه‌های بستن و تمام‌صفحه */}
          <div className="flex items-center gap-1.5 sm:gap-2">
            {item.lyricsUrl && (
              <button
                onClick={() => setPanel((v) => (v === 'lyrics' ? 'cover' : 'lyrics'))}
                aria-label={t.lyrics}
                aria-pressed={panel === 'lyrics'}
                title={t.lyrics}
                className={`rounded-full px-5 py-1.5 text-sm transition active:scale-95 cursor-pointer shadow-sm ${
                  panel === 'lyrics'
                    ? 'bg-white text-black font-extrabold shadow-md'
                    : 'bg-white/15 hover:bg-white/25 text-white font-bold'
                }`}
              >
                Lyrics
              </button>
            )}

            <button
              onClick={withTap(dismiss)}
              aria-label={t.minimizePlayer}
              title={t.minimizePlayer}
              className="grid size-10 place-items-center rounded-2xl bg-white/10 text-white/80 transition-all duration-150 hover:bg-white/20 hover:text-white active:scale-90 active:bg-white/25 cursor-pointer"
            >
              <ChevronIcon className="size-5 -rotate-90 transition-transform duration-150" flip={false} />
            </button>

            {/* دکمه تمام‌صفحه (دسکتاپ) */}
            <button
              onClick={toggleFullscreen}
              aria-label={isFullscreen ? t.exitFullscreen : t.fullscreen}
              title={isFullscreen ? t.exitFullscreen : t.fullscreen}
              className="hidden sm:grid size-10 place-items-center rounded-2xl bg-white/10 text-white/80 hover:bg-white/20 hover:text-white transition cursor-pointer"
            >
              {isFullscreen ? <MinimizeIcon className="size-4" /> : <MaximizeIcon className="size-4" />}
            </button>
          </div>
        </div>

        {/* ============================================================== */}
        {/* ۱. نمای دسکتاپ و نمایشگرهای عریض و افقی (Landscape & Desktop)   */}
        {/* ============================================================== */}
        {isDesktop || isLandscape ? (
          <div className="relative min-h-0 flex-1 flex flex-col justify-center z-10 py-1 sm:py-2">
            <div className={`w-full max-w-6xl xl:max-w-7xl mx-auto flex-1 min-h-0 grid grid-cols-12 ${isLandscape ? 'gap-4' : 'gap-8 xl:gap-14'} items-center px-4 sm:px-8`}>
              {/* ستون چپ: استیج کاور آلبوم */}
              <div className="col-span-5 flex flex-col items-center justify-center space-y-3">
                <div className="flex items-center justify-center w-full">
                  {renderCover(isLandscape ? 'w-full max-h-[65vh] max-w-[min(65vh,290px)]' : 'w-full max-w-[340px] sm:max-w-[390px] xl:max-w-[430px]')}
                </div>
              </div>

              {/* ستون راست: کنترل‌ها در حالت کاور، یا پنل کامل لیریکس/صف */}
              <div className="col-span-7 flex flex-col h-full max-h-[85vh] justify-center">
                {panel === 'cover' ? (
                  <div className={`w-full max-w-xl mx-auto ${isLandscape ? 'space-y-2.5' : 'space-y-6'}`}>
                    {renderTrackInfo()}
                    <NowPlayingSeekBar total={total} seek={seek} />
                    {renderTransportRow()}
                    {renderFooterRow()}
                  </div>
                ) : (
                  <div className="flex flex-col h-full overflow-hidden w-full">
                    <div className="relative flex-1 min-h-0 w-full overflow-hidden">
                      {panel === 'lyrics' ? renderLyricsContent() : renderQueueContent()}
                    </div>
                    <div className="shrink-0 pt-3 border-t border-white/10">
                      {renderFooterRow()}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* ============================================================== */
          /* ۲. نمای موبایل (<lg) دقیقاً مطابق TIDAL                        */
          /* ============================================================== */
          <div className="relative min-h-0 flex-1 flex flex-col z-10 justify-between">
            {panel === 'cover' ? (
              <>
                {/* استیج مرکزی: کاور آلبوم */}
                <div className="relative flex min-h-0 flex-1 items-center justify-center py-1 sm:py-2 my-auto overflow-hidden">
                  <div className="flex items-center justify-center w-full max-h-full">
                    {renderCover('w-full max-h-[35vh] sm:max-h-[40vh] max-w-[min(35vh,320px)] sm:max-w-[min(40vh,380px)]')}
                  </div>
                </div>

                {/* کنترل‌های پایین تایدال */}
                <div className="relative shrink-0 space-y-4 max-w-md mx-auto w-full pt-2 pb-1">
                  {renderTrackInfo()}
                  <NowPlayingSeekBar total={total} seek={seek} />
                  {renderTransportRow()}
                  {renderFooterRow()}
                </div>
              </>
            ) : (
              /* در نمای لیریکس یا صف: تمام‌صفحه و فراگیر با فوتر در پایین (Images 4 & 5) */
              <>
                <div className="relative flex min-h-0 flex-1 overflow-hidden w-full max-w-2xl mx-auto py-2">
                  {panel === 'lyrics' ? renderLyricsContent() : renderQueueContent()}
                </div>

                <div className="relative shrink-0 max-w-md mx-auto w-full pt-2 pb-1">
                  {renderFooterRow()}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
