import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { dominantColor } from '../lib/artColor'
import { digits, safeFilename } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { trackDedupeKey } from '../lib/radio'
import { findBestJob, toPlayItem } from '../lib/stream'
import {
  SOURCE_LABEL,
  type Album,
  type Artist,
  type ArtistDetail,
  type Playlist,
  type Track,
} from '../lib/types'
import { isActive, isDone, useDownloads } from '../store/downloads'
import { usePlayer } from '../store/player'
import { useSettings } from '../store/settings'
import { useToasts } from '../store/toasts'
import ArtistTrackRow from './ArtistTrackRow'
import Artwork, { HeroBackdrop } from './Artwork'
import ClickSpark from './ClickSpark'
import EmptyState from './EmptyState'
import FollowButton from './FollowButton'
import SourceLogo from './logos'
import { Shelf } from './Shelf'
import { AlbumCard, ArtistCard, PlaylistRow } from './cards'
import {
  AlbumIcon,
  ArrowIcon,
  ArrowUpIcon,
  ChevronIcon,
  CloseIcon,
  DownloadIcon,
  GridIcon,
  HeadphonesIcon,
  InfoIcon,
  LinkIcon,
  ListIcon,
  OfflineIcon,
  PauseIcon,
  PlayIcon,
  SearchIcon,
  ShuffleIcon,
  SparkleIcon,
  Spinner,
  VerifiedBadgeIcon,
  ZipIcon,
} from './icons'

interface Props {
  artist: ArtistDetail
  playingId: string | null
  onTogglePlay: (track: Track) => void
  onOpenAlbum: (album: Album) => void
  onOpenPlaylist: (playlist: Playlist) => void
  onOpenArtist?: (artist: Artist) => void
  onBack: () => void
}

function albumKind(album: Album): 'album' | 'single' | 'ep' | 'compilation' {
  // نوع رسمیِ منبع بر حدس‌های فرانت مقدم است؛ برای کش‌های قدیمی که نوع ندارند
  // تعداد ترک و عنوان fallback می‌ماند.
  if (album.releaseType) return album.releaseType
  if (album.source === 'soundcloud' && album.trackCount > 0) {
    if (album.trackCount <= 1) return 'single'
    if (album.trackCount <= 6) return 'ep'
    return 'album'
  }
  if (album.trackCount === 1 || /single/i.test(album.title) || album.title.includes('تک‌آهنگ')) {
    return 'single'
  }
  if (/ep\b/i.test(album.title) || (album.trackCount >= 2 && album.trackCount <= 6)) return 'ep'
  return 'album'
}

function releaseLabel(
  album: Album,
  t: { typeAlbum: string; typeSong: string },
): string {
  const kind = albumKind(album)
  if (kind === 'single') return t.typeSong
  if (kind === 'ep') return 'EP'
  return t.typeAlbum
}

function titlesMatch(a: string, b: string): boolean {
  const left = a.trim().toLowerCase()
  const right = b.trim().toLowerCase()
  if (!left || !right) return false
  return left === right || left.includes(right) || right.includes(left)
}

function trackInAlbum(track: Track, album: Album): boolean {
  if (track.albumId && track.albumId === album.id) return true
  if (track.album && titlesMatch(track.album, album.title)) return true
  return titlesMatch(track.title, album.title)
}

/**
 * آخرین اثرِ منتشرشده: آلبوم اول دیسکوگرافی، مگر ترکِ تازه‌تری بیرون از آن باشد.
 *
 * ساندکلاد topTracks را محبوب می‌چیند نه تازه؛ تازه‌ترین همان اولِ دیسکوگرافی
 * است (آلبوم یا سینگلِ ساخته‌شده از ترکِ تکی). بقیهٔ پلتفرم‌ها هم آلبوم اول
 * می‌ماند مگر سالِ ترک صریحاً جدیدتر باشد.
 */
function pickLatestRelease(
  albums: Album[],
  tracks: Track[],
  source?: Album['source'],
): { kind: 'album'; album: Album } | { kind: 'track'; track: Track } | null {
  const album = albums[0]
  const track = tracks[0]
  if (!album && !track) return null
  if (!track) return { kind: 'album', album }
  if (!album) return { kind: 'track', track }
  // محبوب‌ترین ترکِ ساندکلاد آخرین انتشار نیست
  if (source === 'soundcloud') return { kind: 'album', album }
  if (trackInAlbum(track, album)) return { kind: 'album', album }

  const trackYear = track.year ?? 0
  const albumYear = album.year || 0
  if (trackYear && albumYear && trackYear > albumYear) return { kind: 'track', track }
  return { kind: 'album', album }
}

function ShelfTrackCard({
  track,
  playing,
  onPlay,
  playLabel,
  pauseLabel,
}: {
  track: Track
  playing: boolean
  onPlay: () => void
  playLabel: string
  pauseLabel: string
}) {
  return (
    <div className="w-36 shrink-0 snap-start overflow-hidden rounded-xl border border-line-soft bg-panel/60 p-2 text-start transition hover:border-line hover:bg-panel-2 sm:w-40">
      <div className="group/shelf relative aspect-square w-full overflow-hidden rounded-lg">
        <Artwork
          src={track.artworkUrl}
          alt={track.title}
          seed={track.albumId ?? track.id}
          className="size-full object-cover"
        />
        <button
          onClick={onPlay}
          className={`absolute inset-0 grid place-items-center bg-black/40 transition ${
            playing ? 'opacity-100' : 'opacity-100 sm:opacity-0 sm:hover:opacity-100 sm:focus:opacity-100'
          }`}
          aria-label={playing ? pauseLabel : playLabel}
        >
          <span className="grid size-8 place-items-center rounded-full bg-accent text-accent-fg shadow-lg">
            {playing ? <PauseIcon className="size-4" /> : <PlayIcon className="size-4 ms-0.5" />}
          </span>
        </button>
      </div>
      <p className="bidi mt-2 truncate text-xs font-medium text-fg">{track.title}</p>
      <p className="truncate text-[10px] text-muted">{track.album ?? track.artist}</p>
    </div>
  )
}

/** حداکثر چند آلبوم هم‌زمان از سرور بگیریم — تا روی ارائه‌دهنده هجوم نبریم */
const ALBUM_FETCH_CONCURRENCY = 4

async function mapLimit<T, R>(
  items: T[],
  limit: number,
  fn: (item: T) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array(items.length)
  let next = 0
  async function worker() {
    while (next < items.length) {
      const i = next++
      results[i] = await fn(items[i])
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return results
}

/**
 * نمای پیشرفته‌ی صفحه‌ی هنرمند (Artist View):
 *
 * ۱. هدر سینمایی محیطی با رنگ غالب (dominantColor) و هاله‌ی نوری.
 * ۲. آواتار بزرگ برجسته، نشان تأیید (Verified Badge) و لوگوی پلتفرم.
 * ۳. نوار کنترل‌های کامل: پخش، شافل، دنبال‌کردن تلگرام، دانلود کامل و بسته‌بندی ZIP.
 * ۴. نوار چسبان (Sticky Bar) مینی‌پلیر هنگام اسکرول.
 * ۵. ردیف‌های محبوب‌ترین‌ها با رتبه‌بندی، اکولایزر متحرک و تاگل ۵ به ۱۰ آهنگ.
 * ۶. کارت ویژه «جدیدترین انتشار» (Latest Release Spotlight).
 * ۷. بخش اختصاصی «در کتابخانه شما» (In Your Library) برای پخش آفلاین قطعات دانلودشده.
 * ۸. فیلترهای دیسکوگرافی (همه / آلبوم‌ها / تک‌آهنگ‌ها)، سوییچ گرید/لیست و مرتب‌سازی.
 * ۹. جستجوی بلادرنگ در آثار هنرمند.
 * ۱۰. نمایش شلف‌های افقی مدرن برای بازنشرها و لایک‌های ساندکلاد.
 * ۱۱. مودال جامع «درباره هنرمند» و آمار تفصیلی.
 */
export default function ArtistView({
  artist,
  playingId,
  onTogglePlay,
  onOpenAlbum,
  onOpenPlaylist,
  onOpenArtist,
  onBack,
}: Props) {
  const [allTracks, setAllTracks] = useState<Track[] | null>(null)
  const [loadingAll, setLoadingAll] = useState(false)
  const [loadingPlayAll, setLoadingPlayAll] = useState(false)
  const [zipping, setZipping] = useState(false)
  const [tint, setTint] = useState<[number, number, number] | null>(null)
  const [isScrolledPast, setIsScrolledPast] = useState(false)
  const [showAllTopTracks, setShowAllTopTracks] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [discographyFilter, setDiscographyFilter] = useState<'all' | 'albums' | 'singles'>('all')
  const [discographyView, setDiscographyView] = useState<'grid' | 'list'>('grid')
  const [discographySort, setDiscographySort] = useState<'newest' | 'oldest'>('newest')
  const [showAboutModal, setShowAboutModal] = useState(false)

  const heroRef = useRef<HTMLDivElement>(null)
  const loadingPromiseRef = useRef<Promise<Track[]> | null>(null)
  const isMountedRef = useRef(true)
  const artistIdRef = useRef(artist.id)
  artistIdRef.current = artist.id

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  // با عوض شدن هنرمند، استیت صفحه‌ی قبلی نباید نشت کند — دیسکوگرافی لودشده،
  // جستجو، فیلتر و رنگ هیرو همه مالِ همان صفحه‌اند.
  useEffect(() => {
    setAllTracks(null)
    setLoadingAll(false)
    setLoadingPlayAll(false)
    setSearchQuery('')
    setShowAllTopTracks(false)
    setDiscographyFilter('all')
    setDiscographyView('grid')
    setDiscographySort('newest')
    setShowAboutModal(false)
    setTint(null)
    loadingPromiseRef.current = null
  }, [artist.id])

  const quality = useSettings((s) => s.quality)
  const { enqueueMany, jobs } = useDownloads()
  const { t, lang } = useI18n()
  const pushToast = useToasts((s) => s.push)

  const knownTracks = allTracks ?? artist.topTracks
  const knownIds = new Set(knownTracks.map((x) => x.id))
  const own = jobs.filter((j) => knownIds.has(j.track.id))
  const activeCount = own.filter((j) => isActive(j.status)).length
  const readyJobs = own.filter((j) => isDone(j.status))
  const hasMore = allTracks === null || readyJobs.length < allTracks.length

  const currentTrackId = usePlayer((s) => s.queue[s.index]?.track?.id)
  const currentTrack = usePlayer((s) => s.queue[s.index]?.track)
  const isPlaying = usePlayer((s) => s.playing)
  const queue = usePlayer((s) => s.queue)
  const play = usePlayer((s) => s.play)
  const activePlayingId = playingId ?? (isPlaying ? currentTrackId ?? null : null)

  // استخراج رنگ غالب عکس هنرمند برای گرادیان هیرو
  useEffect(() => {
    let cancelled = false
    void dominantColor(artist.artworkUrl).then((c) => {
      if (!cancelled) setTint(c)
    })
    return () => {
      cancelled = true
    }
  }, [artist.artworkUrl])

  const anyTint = tint ? tint.join(',') : '107,107,107'

  // رصد اسکرول هیرو برای نمایش نوار چسبان
  useEffect(() => {
    const el = heroRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        setIsScrolledPast(!entry.isIntersecting)
      },
      { threshold: 0.1 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // بستن مودال با کلید Escape
  useEffect(() => {
    if (!showAboutModal) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowAboutModal(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [showAboutModal])

  const topTrackItems = useMemo(
    () =>
      artist.topTracks.map((track) => {
        const job = findBestJob(readyJobs, track.id, quality)
        return toPlayItem(track, job, quality)
      }),
    [artist.topTracks, readyJobs, quality],
  )

  const isArtistTrackPlaying = useMemo(() => {
    if (!currentTrackId || !currentTrack) return false
    if (knownIds.has(currentTrackId)) return true
    if (currentTrack.artistId && currentTrack.artistId === artist.id) return true
    // اسم فقط وقتی که پلتفرم artistId نمی‌دهد (کش قدیمی). دو «فرهاد» روی دو
    // منبع نباید دکمه‌ی Pause را برای هم روشن کنند.
    if (currentTrack.artistId) return false
    const currentArtistName = (currentTrack.artist ?? '').trim().toLowerCase()
    const targetArtistName = (artist.name ?? '').trim().toLowerCase()
    return Boolean(currentArtistName && targetArtistName && currentArtistName === targetArtistName)
  }, [currentTrackId, currentTrack, knownIds, artist.id, artist.name])

  const isThisArtistInQueue = useMemo(() => {
    if (queue.length <= 1) return false
    const currentQTrack = queue[usePlayer.getState().index]?.track
    return Boolean(
      currentQTrack &&
        (knownIds.has(currentQTrack.id) ||
          (currentQTrack.artistId && currentQTrack.artistId === artist.id) ||
          (currentQTrack.artist && titlesMatch(currentQTrack.artist, artist.name))),
    )
  }, [queue, knownIds, artist.id, artist.name])

  const isThisArtistPlaying = isArtistTrackPlaying && isPlaying
  const isThisArtistCollectionPlaying = isThisArtistPlaying && isThisArtistInQueue

  const hasPlayable =
    (allTracks?.length ?? 0) > 0 ||
    artist.topTracks.length > 0 ||
    artist.albums.length > 0 ||
    artist.playlists.length > 0 ||
    (artist.likedTracks?.length ?? 0) > 0 ||
    (artist.repostedTracks?.length ?? 0) > 0 ||
    (artist.radio?.length ?? 0) > 0

  const canShuffle =
    (allTracks?.length ?? 0) > 1 ||
    artist.topTracks.length > 1 ||
    artist.albums.length > 0 ||
    artist.playlists.length > 0 ||
    (artist.likedTracks?.length ?? 0) > 1 ||
    (artist.repostedTracks?.length ?? 0) > 1 ||
    (artist.radio?.length ?? 0) > 1 ||
    (artist.topTracks.length +
      (artist.likedTracks?.length ?? 0) +
      (artist.repostedTracks?.length ?? 0) +
      (artist.radio?.length ?? 0)) > 1

  // پیش‌گرم‌سازی ۳ ترک برتر در پس‌زمینه برای شروع پخش فوری
  useEffect(() => {
    const tracksToWarm = artist.topTracks.slice(0, 3)
    if (!tracksToWarm.length) return

    const timers: ReturnType<typeof setTimeout>[] = []
    tracksToWarm.forEach((track, i) => {
      const alreadyDownloaded = jobs.some((j) => j.track.id === track.id && isDone(j.status))
      if (alreadyDownloaded) return

      const timer = setTimeout(() => {
        void api.prefetchStream?.(track)
      }, i * 600)
      timers.push(timer)
    })

    return () => {
      timers.forEach((t) => clearTimeout(t))
    }
  }, [artist.id, artist.topTracks, jobs])

  const handleTopTrackToggle = useCallback(
    (track: Track) => {
      if (onTogglePlay) {
        onTogglePlay(track)
      } else if (currentTrackId === track.id) {
        usePlayer.getState().toggle()
      } else {
        const idx = artist.topTracks.findIndex((t) => t.id === track.id)
        play(topTrackItems, Math.max(0, idx))
      }
    },
    [artist.topTracks, topTrackItems, currentTrackId, play, onTogglePlay],
  )

  const loadDiscography = useCallback(async (): Promise<Track[]> => {
    if (allTracks) return allTracks
    if (loadingPromiseRef.current) return loadingPromiseRef.current

    const sessionArtistId = artist.id
    let promise!: Promise<Track[]>
    promise = (async () => {
      setLoadingAll(true)
      try {
        const seenIds = new Set<string>()
        const seenKeys = new Set<string>()
        const deduped: Track[] = []

        function addTrack(track: Track) {
          if (!track || !track.id) return
          if (seenIds.has(track.id)) return
          const key = trackDedupeKey(track, artist.name)
          if (seenKeys.has(key)) return
          seenIds.add(track.id)
          seenKeys.add(key)
          deduped.push(track)
        }

        // ۱. برترین‌ها / ویدیوها / آپلودهای هنرمند
        for (const track of artist.topTracks) addTrack(track)

        // ۲. ترک‌های لایک‌شده توسط هنرمند (ساندکلاد)
        for (const track of artist.likedTracks ?? []) addTrack(track)

        // ۳. ترک‌های بازنشرشده توسط هنرمند (ساندکلاد)
        for (const track of artist.repostedTracks ?? []) addTrack(track)

        // ۴. رادیوی هنرمند (دیزر)
        for (const track of artist.radio ?? []) addTrack(track)

        // ۵. آلبوم‌ها و پلی‌لیست‌های هنرمند
        const rawSources: (Album | Playlist)[] = [
          ...artist.albums,
          ...artist.playlists,
        ]

        const albumsToFetch: (Album | Playlist)[] = []
        for (const item of rawSources) {
          // برای ساندکلاد: سینگل‌های دیسکوگرافی خودشان شناسه ترک دارند
          // و نیازی به درخواست اضافی و سنگین api.getAlbum برای هر تک‌آهنگ نیست
          if (item.source === 'soundcloud' && item.id.startsWith('sc:track:') && 'artist' in item) {
            const known =
              artist.topTracks.find((t) => t.id === item.id) ??
              artist.likedTracks?.find((t) => t.id === item.id) ??
              artist.repostedTracks?.find((t) => t.id === item.id)
            addTrack({
              id: item.id,
              title: item.title,
              artist: item.artist,
              album: item.title,
              durationMs: known?.durationMs ?? 0,
              artworkUrl: item.artworkUrl,
              source: 'soundcloud',
              sourceUrl: item.sourceUrl,
              previewUrl: null,
              year: item.year,
              artistId: item.artistId,
            })
          } else {
            albumsToFetch.push(item)
          }
        }

        // سقف حداکثر ۳۰ آلبوم با اولویت آلبوم‌های کامل برای جلوگیری از Rate Limit
        const sortedAlbums = [...albumsToFetch]
          .sort((a, b) => {
            const aCount = 'trackCount' in a ? a.trackCount : 0
            const bCount = 'trackCount' in b ? b.trackCount : 0
            if (aCount > 1 && bCount <= 1) return -1
            if (bCount > 1 && aCount <= 1) return 1
            return 0
          })
          .slice(0, 30)

        const details = await mapLimit(sortedAlbums, ALBUM_FETCH_CONCURRENCY, (item) =>
          api.getAlbum(item.sourceUrl || item.id).catch(() => null),
        )

        for (const detail of details) {
          if (!detail) continue
          for (const track of detail.tracks) addTrack(track)
        }

        // پاسخِ در پروازِ هنرمند قبلی نباید صفحه‌ی فعلی را پر کند
        if (isMountedRef.current && sessionArtistId === artistIdRef.current) {
          setAllTracks(deduped)
        }
        return deduped
      } finally {
        if (isMountedRef.current && sessionArtistId === artistIdRef.current) {
          setLoadingAll(false)
        }
        if (loadingPromiseRef.current === promise) {
          loadingPromiseRef.current = null
        }
      }
    })()

    loadingPromiseRef.current = promise
    return promise
  }, [allTracks, artist.albums, artist.id, artist.likedTracks, artist.name, artist.playlists, artist.radio, artist.repostedTracks, artist.topTracks])

  const playArtistDiscography = useCallback(
    async (shuffleMode: boolean) => {
      const currentQuality = useSettings.getState().quality
      const allReadyJobs = jobs.filter((j) => isDone(j.status))

      // تنظیم قطعی شافل بر اساس خواسته‌ی کاربر (Play All: خاموش، Shuffle: روشن)
      usePlayer.getState().setShuffle(shuffleMode)

      // ۱. اگر کل دیسکوگرافی قبلاً لود شده: فوراً همه‌چیز را پخش کن
      if (allTracks && allTracks.length > 0) {
        const items = allTracks.map((t) =>
          toPlayItem(t, findBestJob(allReadyJobs, t.id, currentQuality), currentQuality),
        )
        const idx = shuffleMode ? Math.floor(Math.random() * items.length) : 0
        play(items, idx)
        return
      }

      // ۲. جمع‌آوری تمام ترک‌های در دسترس فوری در همین لحظه روی صفحه
      const seenIds = new Set<string>()
      const seenKeys = new Set<string>()
      const initialTracks: Track[] = []

      function addImmediate(track: Track | null | undefined) {
        if (!track || !track.id) return
        if (seenIds.has(track.id)) return
        const key = trackDedupeKey(track, artist.name)
        if (seenKeys.has(key)) return
        seenIds.add(track.id)
        seenKeys.add(key)
        initialTracks.push(track)
      }

      for (const t of artist.topTracks) addImmediate(t)

      // سینگل‌های ساندکلاد که بدون درخواست اضافی در artist.albums حضور دارند
      for (const item of artist.albums) {
        if (item.source === 'soundcloud' && item.id.startsWith('sc:track:') && 'artist' in item) {
          const known =
            artist.topTracks.find((t) => t.id === item.id) ??
            artist.likedTracks?.find((t) => t.id === item.id) ??
            artist.repostedTracks?.find((t) => t.id === item.id)
          addImmediate({
            id: item.id,
            title: item.title,
            artist: item.artist,
            album: item.title,
            durationMs: known?.durationMs ?? 0,
            artworkUrl: item.artworkUrl,
            source: 'soundcloud',
            sourceUrl: item.sourceUrl,
            previewUrl: null,
            year: item.year,
            artistId: item.artistId,
          })
        }
      }

      for (const t of artist.likedTracks ?? []) addImmediate(t)
      for (const t of artist.repostedTracks ?? []) addImmediate(t)
      for (const t of artist.radio ?? []) addImmediate(t)

      if (initialTracks.length > 0) {
        const initialItems = initialTracks.map((t) =>
          toPlayItem(t, findBestJob(allReadyJobs, t.id, currentQuality), currentQuality),
        )
        const idx = shuffleMode ? Math.floor(Math.random() * initialItems.length) : 0
        play(initialItems, idx)

        // گسترش پس‌زمینه صف به سایر آلبوم‌های دیسکوگرافی
        const sessionArtistId = artist.id
        const sessionArtistName = (artist.name ?? '').trim().toLowerCase()
        const initialIds = new Set(initialTracks.map((t) => t.id))
        const initialKeysSet = new Set(initialTracks.map((t) => trackDedupeKey(t, artist.name)))
        try {
          const fullTracks = await loadDiscography()

          // بررسی اینکه کاربر وسط لودینگ آهنگ آرتیست دیگری را نزده باشد
          const currentQ = usePlayer.getState().queue
          const activeTrack = currentQ[usePlayer.getState().index]?.track
          const isStillThisArtist =
            activeTrack &&
            (initialIds.has(activeTrack.id) ||
              activeTrack.artistId === sessionArtistId ||
              (activeTrack.artist && titlesMatch(activeTrack.artist, artist.name)) ||
              (!activeTrack.artistId &&
                (activeTrack.artist ?? '').trim().toLowerCase() === sessionArtistName))

          if (isStillThisArtist) {
            const remainingTracks = fullTracks.filter(
              (t) => !initialIds.has(t.id) && !initialKeysSet.has(trackDedupeKey(t, artist.name)),
            )

            if (remainingTracks.length > 0) {
              const remainingItems = remainingTracks.map((t) =>
                toPlayItem(t, findBestJob(allReadyJobs, t.id, currentQuality), currentQuality),
              )
              usePlayer.getState().enqueue(remainingItems)
            }
          }
        } catch {
          // اگر لود بقیه آلبوم‌ها خطا داد، آهنگ‌های اولیه بدون وقفه ادامه می‌یابند
        }
        return
      }

      // ۳. حالتی که هنرمند هیچ ترک اولیه‌ای ندارد و فقط آلبوم دارد
      setLoadingPlayAll(true)
      try {
        const fullTracks = await loadDiscography()
        if (fullTracks.length > 0) {
          const items = fullTracks.map((t) =>
            toPlayItem(t, findBestJob(allReadyJobs, t.id, currentQuality), currentQuality),
          )
          const idx = shuffleMode ? Math.floor(Math.random() * items.length) : 0
          play(items, idx)
        }
      } catch {
        pushToast(t.fetchError, 'error')
      } finally {
        if (isMountedRef.current) {
          setLoadingPlayAll(false)
        }
      }
    },
    [allTracks, artist, jobs, play, loadDiscography, pushToast, t],
  )

  const handlePlayAll = useCallback(() => {
    if (isThisArtistCollectionPlaying) {
      usePlayer.getState().pause()
    } else if (isArtistTrackPlaying && isThisArtistInQueue) {
      usePlayer.getState().toggle()
    } else {
      void playArtistDiscography(false)
    }
  }, [isThisArtistCollectionPlaying, isArtistTrackPlaying, isThisArtistInQueue, playArtistDiscography])

  const handleShufflePlay = useCallback(() => {
    void playArtistDiscography(true)
  }, [playArtistDiscography])

  const copyArtistLink = async () => {
    const url = artist.sourceUrl || window.location.href
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url)
      } else {
        const ta = document.createElement('textarea')
        ta.value = url
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        ta.remove()
      }
      pushToast(t.linkCopied, 'info')
    } catch {
      // fallback
    }
  }

  // قطعات این هنرمند که در دستگاه ذخیره شده و آماده پخش آفلاین‌اند
  const downloadedArtistJobs = useMemo(() => {
    const artistNameLower = (artist.name ?? '').toLowerCase().trim()
    return jobs.filter((j) => {
      if (!isDone(j.status)) return false
      if (knownIds.has(j.track.id)) return true
      // Once a track has an artist id, trust that identity instead of its
      // display name. Names collide frequently across providers and would
      // otherwise leak another artist's offline tracks into this page.
      if (j.track.artistId) return j.track.artistId === artist.id
      if (j.track.source !== artist.source) return false
      const jobArtist = (j.track?.artist ?? '').toLowerCase().trim()
      return jobArtist === artistNameLower
    })
  }, [jobs, knownIds, artist.id, artist.name, artist.source])

  const offlinePlayItems = useMemo(
    () => downloadedArtistJobs.map((j) => toPlayItem(j.track, j, quality)),
    [downloadedArtistJobs, quality],
  )

  const handlePlayOffline = useCallback(() => {
    if (!offlinePlayItems.length) return
    play(offlinePlayItems, 0)
  }, [play, offlinePlayItems])

  const handlePlayOfflineTrack = useCallback(
    (idx: number) => {
      if (!offlinePlayItems.length) return
      const target = offlinePlayItems[idx]
      if (currentTrackId === target.track.id) {
        usePlayer.getState().toggle()
      } else {
        play(offlinePlayItems, idx)
      }
    },
    [play, offlinePlayItems, currentTrackId],
  )

  const isUser = artist.kind === 'user'
  const isVerified = Boolean(artist.verified)
  const relatedArtists = artist.related ?? []
  const radioTracks = artist.radio ?? []
  const hasAnything =
    artist.topTracks.length > 0 ||
    artist.albums.length > 0 ||
    artist.playlists.length > 0 ||
    (artist.likedTracks?.length ?? 0) > 0 ||
    (artist.repostedTracks?.length ?? 0) > 0 ||
    relatedArtists.length > 0 ||
    radioTracks.length > 0
  const topTracksTitle = artist.source === 'soundcloud' ? t.topTracks : t.popularSongs

  async function downloadAll() {
    const tracks = await loadDiscography()
    if (!tracks.length) return
    enqueueMany(tracks, quality, { title: artist.name, artworkUrl: artist.artworkUrl })
  }

  async function downloadZip() {
    setZipping(true)
    try {
      const url = await api.zip(
        readyJobs.map((j) => ({ trackId: j.track.id, quality: j.quality })),
        safeFilename(artist.name),
      )
      if (!url) {
        pushToast(t.mockNoFile, 'info')
        return
      }
      location.href = url
    } catch {
      pushToast(t.toastZipFailed, 'error')
    } finally {
      setZipping(false)
    }
  }

  const latestRelease = useMemo(
    () => pickLatestRelease(artist.albums, artist.topTracks, artist.source),
    [artist.albums, artist.topTracks, artist.source],
  )

  const isLatestTrackPlaying =
    latestRelease?.kind === 'track' &&
    activePlayingId === latestRelease.track.id

  // فیلتر و مرتب‌سازی دیسکوگرافی
  const processedAlbums = useMemo(() => {
    let list = [...artist.albums]
    if (discographyFilter === 'albums') {
      list = list.filter((a) => {
        const kind = albumKind(a)
        return kind === 'album' || kind === 'compilation'
      })
    } else if (discographyFilter === 'singles') {
      list = list.filter((a) => {
        const kind = albumKind(a)
        return kind === 'single' || kind === 'ep'
      })
    }

    // بک‌اند با تاریخ کامل مرتب کرده؛ فقط وقتی سال فرق دارد جابه‌جا کن تا
    // شش سینگلِ یک سال ترتیب دلبخواه نگیرند. reverse پایدار همان ترتیب
    // ورودی را برای سال برابر نگه می‌دارد.
    if (discographySort === 'oldest') {
      const indexed = list.map((album, i) => ({ album, i }))
      indexed.sort((a, b) => {
        const yearA = a.album.year || 0
        const yearB = b.album.year || 0
        if (yearA !== yearB) return yearA - yearB
        return b.i - a.i
      })
      list = indexed.map((x) => x.album)
    }

    return list
  }, [artist.albums, discographyFilter, discographySort])

  // فیلتر جستجوی بلادرنگ در آثار با نرمال‌سازی نویسه‌های فارسی/عربی
  const cleanQ = searchQuery.trim().toLowerCase().replace(/[‌\s]+/g, ' ')
  const matchesSearch = useCallback(
    (text?: string | null) => {
      if (!cleanQ) return true
      if (!text) return false
      const norm = text.toLowerCase().replace(/[‌\s]+/g, ' ')
      if (norm.includes(cleanQ)) return true
      const arNorm = norm.replace(/ي/g, 'ی').replace(/ك/g, 'ک')
      const arQ = cleanQ.replace(/ي/g, 'ی').replace(/ك/g, 'ک')
      return arNorm.includes(arQ)
    },
    [cleanQ],
  )

  const filteredTopTracks = useMemo(() => {
    if (!cleanQ) return artist.topTracks
    return artist.topTracks.filter(
      (t) => matchesSearch(t.title) || matchesSearch(t.album),
    )
  }, [artist.topTracks, cleanQ, matchesSearch])

  const filteredAlbums = useMemo(() => {
    if (!cleanQ) return processedAlbums
    return processedAlbums.filter(
      (a) => matchesSearch(a.title) || matchesSearch(String(a.year)),
    )
  }, [processedAlbums, cleanQ, matchesSearch])

  const filteredPlaylists = useMemo(() => {
    if (!cleanQ) return artist.playlists
    return artist.playlists.filter((p) => matchesSearch(p.title))
  }, [artist.playlists, cleanQ, matchesSearch])

  const filteredReposted = useMemo(() => {
    const list = artist.repostedTracks ?? []
    if (!cleanQ) return list
    return list.filter(
      (t) => matchesSearch(t.title) || matchesSearch(t.album),
    )
  }, [artist.repostedTracks, cleanQ, matchesSearch])

  const filteredLiked = useMemo(() => {
    const list = artist.likedTracks ?? []
    if (!cleanQ) return list
    return list.filter(
      (t) => matchesSearch(t.title) || matchesSearch(t.album),
    )
  }, [artist.likedTracks, cleanQ, matchesSearch])

  const filteredDownloadedJobs = useMemo(() => {
    if (!cleanQ) return downloadedArtistJobs
    return downloadedArtistJobs.filter(
      (j) => matchesSearch(j.track.title) || matchesSearch(j.track.album),
    )
  }, [downloadedArtistJobs, cleanQ, matchesSearch])

  const displayedTopTracks = showAllTopTracks
    ? filteredTopTracks
    : filteredTopTracks.slice(0, 5)

  const hasAnySearchResult =
    filteredTopTracks.length > 0 ||
    filteredAlbums.length > 0 ||
    filteredPlaylists.length > 0 ||
    filteredReposted.length > 0 ||
    filteredLiked.length > 0 ||
    filteredDownloadedJobs.length > 0

  return (
    <div className="rise pb-8">
      {/* دکمه‌ی بازگشت */}
      <div className="mb-2 px-1 pt-1 sm:px-2">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 py-1 text-xs text-muted transition hover:text-fg"
        >
          <ArrowIcon className="size-3.5 -scale-x-100 rtl:scale-x-100" />
          <span>{t.backToResults}</span>
        </button>
      </div>

      {/* ─── هیرو: بک‌دراپ محیطی تمام‌عرض با فِید نرم به پس‌زمینه ─── */}
      <div
        ref={heroRef}
        className="relative -mx-2 -mt-2 mb-6 overflow-hidden rounded-3xl p-5 sm:-mx-4 sm:p-7 md:p-8"
        style={{
          background: `
            radial-gradient(ellipse 90% 70% at 50% -10%, rgb(${anyTint} / 0.45), transparent 75%),
            linear-gradient(to bottom, rgb(${anyTint} / 0.18) 0%, transparent 100%)
          `,
        }}
      >
        {/* لایه‌ی محوِ تصویر پس‌زمینه با ماسک نرم */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10 opacity-60 blur-3xl"
          style={{
            maskImage: 'linear-gradient(to bottom, black 30%, transparent 100%)',
            WebkitMaskImage: 'linear-gradient(to bottom, black 30%, transparent 100%)',
          }}
        >
          <HeroBackdrop src={artist.artworkUrl} seed={artist.id} />
        </div>

        <div className="relative flex flex-col gap-6 sm:flex-row sm:items-end sm:gap-8">
          {/* بخش آواتار دایره‌ای بزرگ با هاله‌ی نوری */}
          <div className="group/avatar relative shrink-0 self-center sm:self-auto">
            {/* هاله‌ی درخشان رنگ کاور */}
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 rounded-full opacity-60 blur-2xl transition-opacity duration-500 group-hover/avatar:opacity-85"
              style={{ background: `rgb(${anyTint} / 0.75)` }}
            />

            {/* تصویر گرد هنرمند با حاشیه‌ی شیشه‌ای */}
            <div className="relative z-10 overflow-hidden rounded-full border-2 border-white/20 bg-panel shadow-2xl shadow-black/80 transition-transform duration-300 group-hover/avatar:scale-[1.03]">
              <Artwork
                src={artist.artworkUrl}
                alt={artist.name}
                seed={artist.id}
                rounded="rounded-full"
                className="size-36 object-cover sm:size-44 md:size-52"
              />
              {/* برق شیشه‌ای */}
              <div className="pointer-events-none absolute inset-0 rounded-full bg-gradient-to-tr from-white/15 via-transparent to-white/5 opacity-70" />
            </div>
          </div>

          {/* متادیتای هنرمند */}
          <div className="min-w-0 flex-1 text-center sm:text-start">
            {/* ردیف بج‌های شیشه‌ای */}
            <div className="mb-2.5 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
              {isUser ? (
                <span className="glass-chip inline-flex items-center gap-1.5 rounded-full border border-white/15 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white shadow-sm">
                  <span>{t.typeUser}</span>
                </span>
              ) : isVerified ? (
                <span className="glass-chip inline-flex items-center gap-1.5 rounded-full border border-white/15 px-3 py-1 text-[11px] font-bold text-white shadow-sm">
                  <VerifiedBadgeIcon className="size-3.5 text-accent" />
                  <span>{t.verifiedArtist}</span>
                </span>
              ) : (
                <span className="glass-chip inline-flex items-center gap-1.5 rounded-full border border-white/15 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white shadow-sm">
                  <span>{t.typeArtist}</span>
                </span>
              )}

              {artist.source && (
                <span className="glass-chip inline-flex items-center gap-1.5 rounded-full border border-white/15 px-2.5 py-0.5 text-[10px] font-medium text-white/90 shadow-sm">
                  <SourceLogo source={artist.source} className="size-3" />
                  <span>{SOURCE_LABEL[artist.source]}</span>
                </span>
              )}

              {artist.albums.length > 0 && (
                <span className="glass-chip inline-flex items-center gap-1 rounded-full border border-white/15 px-2.5 py-0.5 text-[10px] font-semibold text-white/90 shadow-sm">
                  <AlbumIcon className="size-3 text-accent" />
                  <span>{t.albumCount(artist.albums.length)}</span>
                </span>
              )}

              <span className="glass-chip inline-flex items-center gap-1 rounded-full border border-white/15 px-2 py-0.5 text-[10px] font-semibold text-accent/95 shadow-sm">
                <HeadphonesIcon className="size-3" />
                <span>{quality.toUpperCase()}</span>
              </span>
            </div>

            {/* نام هنرمند */}
            <h1 className="bidi-hero relative z-10 w-full text-2xl font-black leading-[1.18] [word-break:break-word] [text-wrap:balance] drop-shadow-[0_2px_12px_rgb(0_0_0/0.7)] text-center sm:text-start sm:text-4xl md:text-5xl">
              {artist.name}
            </h1>

            {/* خط جزئیات و آمار آثار */}
            <div className="relative z-10 mt-3 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-sm text-muted drop-shadow-[0_1px_6px_rgb(0_0_0/0.6)] sm:justify-start">
              {artist.subtitle && <span>{digits(artist.subtitle, lang)}</span>}

              {artist.topTracks.length > 0 && (
                <>
                  {artist.subtitle && <span aria-hidden className="text-muted-2">·</span>}
                  <span>
                    {t.trackCount(artist.topTracks.length)} {topTracksTitle}
                  </span>
                </>
              )}

              {artist.albums.length > 0 && (
                <>
                  <span aria-hidden className="text-muted-2">·</span>
                  <span>{t.albumCount(artist.albums.length)}</span>
                </>
              )}

              {isUser && artist.playlists.length > 0 && (
                <>
                  <span aria-hidden className="text-muted-2">·</span>
                  <span>{t.playlistsCount(artist.playlists.length)}</span>
                </>
              )}
            </div>

            {/* اکشن‌بار منسجم در هیرو */}
            <div className="mt-6 flex flex-wrap items-center justify-center gap-3 sm:justify-start">
              {/* دکمه بزرگ پخش اصلی */}
              {hasPlayable && (
                <ClickSpark>
                  <button
                    onClick={handlePlayAll}
                    disabled={loadingPlayAll}
                    aria-label={isThisArtistCollectionPlaying ? t.pause : t.playAll}
                    title={isThisArtistCollectionPlaying ? t.pause : t.playAll}
                    className="grid size-14 place-items-center rounded-full bg-accent text-accent-fg shadow-xl shadow-accent/25 transition enabled:hover:scale-105 enabled:active:scale-95 disabled:opacity-75"
                  >
                    {loadingPlayAll ? (
                      <Spinner className="size-6 text-accent-fg" />
                    ) : isThisArtistCollectionPlaying ? (
                      <PauseIcon className="size-6" />
                    ) : (
                      <PlayIcon className="size-6 ms-0.5" />
                    )}
                  </button>
                </ClickSpark>
              )}

              {/* دکمه شافل */}
              {canShuffle && (
                <button
                  onClick={handleShufflePlay}
                  aria-label={t.shufflePlay}
                  title={t.shufflePlay}
                  className="grid size-11 place-items-center rounded-full border border-white/15 bg-white/5 text-fg backdrop-blur-md transition hover:border-accent/40 hover:bg-white/10 hover:text-accent active:scale-95"
                >
                  <ShuffleIcon className="size-5" />
                </button>
              )}

              {/* دکمه دنبال کردن تلگرام */}
              {!isUser && <FollowButton artist={artist} />}

              {/* دکمه دانلود دیسکوگرافی کامل */}
              {hasAnything && (activeCount > 0 || loadingAll || hasMore) && (
                <ClickSpark className="flex-1 sm:flex-none">
                  <button
                    onClick={downloadAll}
                    disabled={loadingAll || activeCount > 0}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-accent px-5 py-3 text-sm font-bold text-accent-fg shadow-lg shadow-accent/20 transition enabled:hover:brightness-110 disabled:opacity-60 active:scale-95 sm:w-auto"
                  >
                    {loadingAll ? (
                      <>
                        <Spinner className="size-4" />
                        <span>{t.loadingAlbums}</span>
                      </>
                    ) : activeCount > 0 ? (
                      <>
                        <Spinner className="size-4" />
                        <span>{t.ofTotal(readyJobs.length, readyJobs.length + activeCount)}</span>
                      </>
                    ) : (
                      <>
                        <DownloadIcon className="size-4" />
                        <span>{t.downloadAll}</span>
                      </>
                    )}
                  </button>
                </ClickSpark>
              )}

              {/* دانلود فایل ZIP */}
              {readyJobs.length > 0 && (
                <button
                  onClick={downloadZip}
                  disabled={zipping}
                  title={t.zipTitle}
                  className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-4 py-2.5 text-sm font-medium text-fg backdrop-blur-md transition hover:border-white/30 hover:bg-white/10 disabled:opacity-45"
                >
                  {zipping ? <Spinner className="size-4" /> : <ZipIcon className="size-4" />}
                  <span>{t.zip(readyJobs.length)}</span>
                </button>
              )}

              {/* کپی لینک هنرمند */}
              <button
                onClick={copyArtistLink}
                title={t.copyLink}
                aria-label={t.copyLink}
                className="grid size-11 place-items-center rounded-full border border-white/15 bg-white/5 text-muted backdrop-blur-md transition hover:border-white/30 hover:bg-white/10 hover:text-fg active:scale-95"
              >
                <LinkIcon className="size-4" />
              </button>

              {/* اطلاعات و آمار هنرمند */}
              <button
                onClick={() => setShowAboutModal(true)}
                title={t.aboutArtist}
                aria-label={t.aboutArtist}
                className="grid size-11 place-items-center rounded-full border border-white/15 bg-white/5 text-muted backdrop-blur-md transition hover:border-white/30 hover:bg-white/10 hover:text-fg active:scale-95"
              >
                <InfoIcon className="size-4" />
              </button>

              {/* باز کردن در پلتفرم اصلی */}
              {artist.sourceUrl && (
                <a
                  href={artist.sourceUrl}
                  target="_blank"
                  rel="noreferrer"
                  title={t.openSource}
                  aria-label={t.openSource}
                  className="grid size-11 place-items-center rounded-full border border-white/15 bg-white/5 text-muted backdrop-blur-md transition hover:border-white/30 hover:bg-white/10 hover:text-fg active:scale-95"
                >
                  <SourceLogo source={artist.source} className="size-4" />
                </a>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ─── نوار چسبان: نمایش کنترل‌ها و مینی‌پلیر هنگام اسکرول ─── */}
      {isScrolledPast && (
        <div className="glass-bar sticky top-[calc(3.5rem+env(safe-area-inset-top,0px))] z-20 mb-4 flex items-center justify-between gap-3 rounded-2xl border-b border-line-soft px-3 py-2.5 shadow-lg sm:px-4">
          <div className="flex min-w-0 items-center gap-3">
            <Artwork
              src={artist.artworkUrl}
              alt=""
              seed={artist.id}
              className="size-9 shrink-0 shadow-sm"
              rounded="rounded-full"
            />
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <p className="bidi truncate text-xs font-bold text-fg sm:text-sm">{artist.name}</p>
                {isVerified && <VerifiedBadgeIcon className="size-3.5 shrink-0 text-accent" />}
              </div>
              <p className="bidi truncate text-[11px] text-muted">
                {artist.albums.length
                  ? t.albumCount(artist.albums.length)
                  : isUser && artist.playlists.length
                    ? t.playlistsCount(artist.playlists.length)
                    : digits(artist.subtitle, lang)}
              </p>
            </div>
            {hasPlayable && (
              <button
                onClick={handlePlayAll}
                disabled={loadingPlayAll}
                aria-label={isThisArtistCollectionPlaying ? t.pause : t.playAll}
                title={isThisArtistCollectionPlaying ? t.pause : t.playAll}
                className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-accent-fg shadow-sm transition hover:scale-105 active:scale-95 disabled:opacity-75"
              >
                {loadingPlayAll ? (
                  <Spinner className="size-4 text-accent-fg" />
                ) : isThisArtistCollectionPlaying ? (
                  <PauseIcon className="size-4" />
                ) : (
                  <PlayIcon className="size-4 ms-0.5" />
                )}
              </button>
            )}
          </div>

          <div className="flex items-center gap-2">
            {!isUser && <FollowButton artist={artist} />}
          </div>
        </div>
      )}

      {/* ─── فیلد جستجوی سریع در آثار هنرمند (فاز ۵) ─── */}
      <div className="mb-6 px-1">
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute start-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setSearchQuery('')
            }}
            placeholder={t.searchArtistWorks(artist.name)}
            className="w-full rounded-2xl border border-line bg-panel/60 py-2.5 pe-9 ps-10 text-xs text-fg placeholder:text-muted transition focus:border-accent focus:bg-panel focus:outline-none"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              aria-label={t.clearSearch}
              className="absolute end-3 top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded-full text-muted hover:text-fg"
            >
              <CloseIcon className="size-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* ─── محتوای صفحه ─── */}
      <div className="space-y-10">
        {!hasAnything && (
          <EmptyState
            bordered={false}
            icon={<HeadphonesIcon className="size-5" />}
            text={isUser ? t.userNotFound : t.artistNotFound}
          />
        )}

        {/* پیام عدم تطابق در جستجو */}
        {cleanQ && !hasAnySearchResult && (
          <EmptyState
            bordered={false}
            icon={<SearchIcon className="size-5" />}
            text={t.noWorksFound(searchQuery)}
          />
        )}

        {/* ─── فاز ۴: بخش قطعات در کتابخانه محلی و پخش آفلاین ─── */}
        {filteredDownloadedJobs.length > 0 && (
          <section className="relative overflow-hidden rounded-2xl border border-accent/25 bg-gradient-to-br from-accent/15 via-panel/80 to-panel/40 p-4 sm:p-5 shadow-sm">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <div className="grid size-11 shrink-0 place-items-center rounded-xl border border-accent/30 bg-accent/20 text-accent shadow-sm">
                  <OfflineIcon className="size-5" filled />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-bold text-fg sm:text-base">
                      {t.inYourLibrary}
                    </h3>
                    <span className="rounded-full bg-accent/20 px-2 py-0.5 text-[11px] font-bold text-accent">
                      {digits(filteredDownloadedJobs.length, lang)}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted">
                    {t.offlineReadyDesc(filteredDownloadedJobs.length)}
                  </p>
                </div>
              </div>

              <button
                onClick={handlePlayOffline}
                className="inline-flex items-center justify-center gap-2 rounded-full bg-accent px-4 py-2.5 text-xs font-bold text-accent-fg shadow-md shadow-accent/20 transition hover:brightness-110 active:scale-95 sm:w-auto"
              >
                <PlayIcon className="size-3.5 fill-current" />
                <span>{t.playOffline}</span>
              </button>
            </div>

            {/* شلف افقی قطعات دانلودشده */}
            <div className="mt-4 border-t border-line-soft/60 pt-3">
              <Shelf>
                {filteredDownloadedJobs.map((job, idx) => {
                  const isItemPlaying = isPlaying && currentTrackId === job.track.id
                  return (
                    <div
                      key={job.id}
                      className="group/offline relative w-32 shrink-0 snap-start overflow-hidden rounded-xl border border-line-soft/60 bg-panel/60 p-2 text-start transition hover:border-accent/40 hover:bg-panel-2"
                    >
                      <div className="relative aspect-square w-full overflow-hidden rounded-lg">
                        <Artwork
                          src={job.track.artworkUrl}
                          alt={job.track.title}
                          seed={job.track.albumId ?? job.track.id}
                          className="size-full object-cover"
                        />
                        <button
                          onClick={() => handlePlayOfflineTrack(idx)}
                          className={`absolute inset-0 grid place-items-center bg-black/45 transition ${
                            isItemPlaying
                              ? 'opacity-100'
                              : 'opacity-0 group-hover/offline:opacity-100'
                          }`}
                          aria-label={isItemPlaying ? t.pause : t.playTrack(job.track.title)}
                        >
                          <span className="grid size-8 place-items-center rounded-full bg-accent text-accent-fg shadow-lg">
                            {isItemPlaying ? (
                              <PauseIcon className="size-4" />
                            ) : (
                              <PlayIcon className="size-4 ms-0.5" />
                            )}
                          </span>
                        </button>
                      </div>
                      <p className="bidi mt-2 truncate text-xs font-medium text-fg">
                        {job.track.title}
                      </p>
                      <p className="truncate text-[10px] text-muted">
                        {job.track.album ?? job.track.artist}
                      </p>
                    </div>
                  )
                })}
              </Shelf>
            </div>
          </section>
        )}

        {/* ─── فاز ۳: کارت ویژه «جدیدترین انتشار» (Latest Release Spotlight) ─── */}
        {latestRelease && !cleanQ && (
          <div className="relative overflow-hidden rounded-2xl border border-line-soft bg-panel/40 p-4 transition hover:border-muted-2/60 sm:p-5">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:gap-6">
              <button
                type="button"
                onClick={() => {
                  if (latestRelease.kind === 'album') {
                    onOpenAlbum(latestRelease.album)
                  } else {
                    handleTopTrackToggle(latestRelease.track)
                  }
                }}
                aria-label={
                  latestRelease.kind === 'album'
                    ? t.viewRelease
                    : isLatestTrackPlaying
                      ? t.pause
                      : t.playTrack(latestRelease.track.title)
                }
                className="group/spotlight relative size-24 shrink-0 overflow-hidden rounded-xl border border-white/10 shadow-lg shadow-black/40 text-start transition hover:scale-[1.02] sm:size-28"
              >
                <Artwork
                  src={
                    latestRelease.kind === 'album'
                      ? latestRelease.album.artworkUrl
                      : latestRelease.track.artworkUrl
                  }
                  alt={
                    latestRelease.kind === 'album'
                      ? latestRelease.album.title
                      : latestRelease.track.title
                  }
                  seed={
                    latestRelease.kind === 'album'
                      ? latestRelease.album.id
                      : latestRelease.track.id
                  }
                  className="size-full object-cover"
                />
                <span
                  className={`absolute inset-0 grid place-items-center bg-black/45 transition-opacity ${
                    isLatestTrackPlaying
                      ? 'opacity-100'
                      : 'opacity-0 group-hover/spotlight:opacity-100'
                  }`}
                >
                  <span className="grid size-9 place-items-center rounded-full bg-accent text-accent-fg shadow-lg">
                    {latestRelease.kind === 'album' ? (
                      <ArrowIcon className="size-4 -scale-x-100 rtl:scale-x-100" />
                    ) : isLatestTrackPlaying ? (
                      <PauseIcon className="size-4" />
                    ) : (
                      <PlayIcon className="size-4 ms-0.5" />
                    )}
                  </span>
                </span>
              </button>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1 rounded-full bg-accent/15 px-2.5 py-0.5 text-[10px] font-bold text-accent">
                    <SparkleIcon className="size-3" />
                    <span>{t.latestRelease}</span>
                  </span>
                  <span className="text-xs text-muted">
                    {latestRelease.kind === 'album'
                      ? releaseLabel(latestRelease.album, t)
                      : t.typeSong}
                  </span>
                  {(latestRelease.kind === 'album'
                    ? latestRelease.album.year
                    : latestRelease.track.year) ? (
                    <span className="text-xs text-muted">
                      ·{' '}
                      {digits(
                        latestRelease.kind === 'album'
                          ? latestRelease.album.year
                          : (latestRelease.track.year ?? ''),
                        lang,
                      )}
                    </span>
                  ) : null}
                </div>
                <h3
                  onClick={() => {
                    if (latestRelease.kind === 'album') {
                      onOpenAlbum(latestRelease.album)
                    } else {
                      handleTopTrackToggle(latestRelease.track)
                    }
                  }}
                  className="bidi mt-1.5 cursor-pointer truncate text-base font-bold text-fg transition-colors hover:text-accent sm:text-lg"
                >
                  {latestRelease.kind === 'album'
                    ? latestRelease.album.title
                    : latestRelease.track.title}
                </h3>
                <p className="mt-0.5 text-xs text-muted">
                  {latestRelease.kind === 'album'
                    ? t.trackCount(latestRelease.album.trackCount)
                    : latestRelease.track.artist}
                </p>
              </div>
              <button
                onClick={() => {
                  if (latestRelease.kind === 'album') {
                    onOpenAlbum(latestRelease.album)
                  } else {
                    handleTopTrackToggle(latestRelease.track)
                  }
                }}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-full border border-line bg-panel px-4 py-2.5 text-xs font-semibold text-fg transition hover:border-muted-2 hover:bg-panel-2 active:scale-95"
              >
                <span>
                  {latestRelease.kind === 'album'
                    ? t.viewRelease
                    : isLatestTrackPlaying
                      ? t.pause
                      : t.play}
                </span>
                {latestRelease.kind === 'album' ? (
                  <ArrowIcon className="size-3 -scale-x-100 rtl:scale-x-100" />
                ) : isLatestTrackPlaying ? (
                  <PauseIcon className="size-3" />
                ) : (
                  <PlayIcon className="size-3" />
                )}
              </button>
            </div>
          </div>
        )}

        {/* ─── بخش قطعات محبوب (Top Tracks) با رتبه‌بندی و هدر ستون‌ها ─── */}
        {filteredTopTracks.length > 0 && (
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-fg sm:text-lg">
                {topTracksTitle}
              </h2>
              <span className="text-xs font-semibold text-muted-2">
                ({digits(filteredTopTracks.length, lang)})
              </span>
            </div>

            {/* هدر ستون‌های جدول در دسکتاپ */}
            <div className="hidden items-center gap-2 border-b border-line-soft px-2.5 pb-2 text-[11px] font-semibold text-muted-2 sm:gap-3 md:flex">
              <span className="w-7 shrink-0 text-center">{t.tableHeaderNumber}</span>
              <span className="w-10 shrink-0" />
              <span className="min-w-0 flex-1 md:flex-initial md:w-[38%] lg:w-[42%]">{t.tableHeaderTitle}</span>
              <span className="hidden min-w-0 md:block md:w-[26%] lg:w-[28%]">{t.typeAlbum}</span>
              <span className="hidden w-12 shrink-0 text-center md:inline">{t.tableHeaderDuration}</span>
              <span className="ms-auto w-24 pe-2 text-end">{t.tableHeaderActions}</span>
            </div>

            {/* لیست قطعات برتر */}
            <div className="space-y-1">
              {displayedTopTracks.map((track, idx) => (
                <ArtistTrackRow
                  key={track.id}
                  track={track}
                  index={idx + 1}
                  playingId={activePlayingId}
                  onTogglePlay={handleTopTrackToggle}
                  onOpenAlbum={onOpenAlbum}
                  artistAlbums={artist.albums}
                />
              ))}
            </div>

            {/* دکمه‌ی نمایش بیشتر در زیر لیست */}
            {filteredTopTracks.length > 5 && !cleanQ && (
              <div className="pt-2 text-center">
                <button
                  onClick={() => setShowAllTopTracks((v) => !v)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-line px-4 py-2 text-xs font-semibold text-fg transition hover:border-muted-2 hover:bg-panel-2 active:scale-95"
                >
                  <span>
                    {showAllTopTracks
                      ? t.showLess
                      : t.showMoreSongs(filteredTopTracks.length)}
                  </span>
                  <ChevronIcon
                    className={`size-3 transition-transform duration-200 ${
                      showAllTopTracks ? 'rotate-90' : '-rotate-90'
                    }`}
                    flip={false}
                  />
                </button>
              </div>
            )}
          </section>
        )}

        {/* ─── بخش دیسکوگرافی با فیلترها و مرتب‌سازی (فاز ۳) ─── */}
        {artist.albums.length > 0 && (
          <section className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-fg sm:text-lg">
                  {t.discography}
                </h2>
                <span className="text-xs font-semibold text-muted-2">
                  ({digits(filteredAlbums.length, lang)})
                </span>
              </div>

              {/* نوار ابزار فیلتر و تغییر نما */}
              <div className="flex flex-wrap items-center gap-2">
                {/* چیپ‌های فیلتر: همه / آلبوم‌ها / سینگل‌ها */}
                <div className="flex items-center rounded-lg border border-line bg-panel/60 p-0.5 text-xs">
                  <button
                    onClick={() => setDiscographyFilter('all')}
                    className={`rounded-md px-2.5 py-1 transition ${
                      discographyFilter === 'all'
                        ? 'bg-accent text-accent-fg font-bold'
                        : 'text-muted hover:text-fg'
                    }`}
                  >
                    {t.allReleases}
                  </button>
                  <button
                    onClick={() => setDiscographyFilter('albums')}
                    className={`rounded-md px-2.5 py-1 transition ${
                      discographyFilter === 'albums'
                        ? 'bg-accent text-accent-fg font-bold'
                        : 'text-muted hover:text-fg'
                    }`}
                  >
                    {t.albums}
                  </button>
                  <button
                    onClick={() => setDiscographyFilter('singles')}
                    className={`rounded-md px-2.5 py-1 transition ${
                      discographyFilter === 'singles'
                        ? 'bg-accent text-accent-fg font-bold'
                        : 'text-muted hover:text-fg'
                    }`}
                  >
                    {t.singlesAndEps}
                  </button>
                </div>

                {/* مرتب‌سازی سال: جدیدترین / قدیمی‌ترین با انیمیشن چرخش فلش (BitChord Arrow Flip) */}
                <button
                  onClick={() =>
                    setDiscographySort((s) => (s === 'newest' ? 'oldest' : 'newest'))
                  }
                  title={discographySort === 'newest' ? t.sortNewest : t.sortOldest}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-panel/60 px-2.5 py-1.5 text-xs text-muted hover:border-muted-2 hover:text-fg transition cursor-pointer"
                >
                  <ArrowUpIcon
                    className={`size-3.5 transition-transform duration-200 ease-out ${
                      discographySort === 'oldest' ? 'rotate-180' : 'rotate-0'
                    }`}
                  />
                  <span>{discographySort === 'newest' ? t.sortNewest : t.sortOldest}</span>
                </button>

                {/* سوییچ گرید / لیست */}
                <div className="flex items-center rounded-lg border border-line bg-panel/60 p-0.5">
                  <button
                    onClick={() => setDiscographyView('grid')}
                    title={t.viewGrid}
                    aria-label={t.viewGrid}
                    className={`grid size-7 place-items-center rounded-md transition ${
                      discographyView === 'grid'
                        ? 'bg-white/10 text-fg'
                        : 'text-muted hover:text-fg'
                    }`}
                  >
                    <GridIcon className="size-3.5" />
                  </button>
                  <button
                    onClick={() => setDiscographyView('list')}
                    title={t.viewList}
                    aria-label={t.viewList}
                    className={`grid size-7 place-items-center rounded-md transition ${
                      discographyView === 'list'
                        ? 'bg-white/10 text-fg'
                        : 'text-muted hover:text-fg'
                    }`}
                  >
                    <ListIcon className="size-3.5" />
                  </button>
                </div>
              </div>
            </div>

            {/* محتوای دیسکوگرافی بر اساس نمای انتخابی */}
            {filteredAlbums.length === 0 ? (
              <div className="rounded-2xl border border-line-soft bg-panel/30 p-8 text-center text-xs text-muted">
                <p>
                  {discographyFilter === 'albums'
                    ? 'هیچ آلبومی برای این هنرمند در دسترس نیست.'
                    : discographyFilter === 'singles'
                      ? 'هیچ تک‌آهنگ یا EP برای این هنرمند در دسترس نیست.'
                      : t.noWorksFound(searchQuery)}
                </p>
                {discographyFilter !== 'all' && (
                  <button
                    onClick={() => setDiscographyFilter('all')}
                    className="mt-3 inline-flex items-center gap-1 rounded-full border border-line bg-panel px-3.5 py-1.5 text-xs font-semibold text-fg transition hover:border-accent hover:text-accent"
                  >
                    <span>{t.allReleases}</span>
                  </button>
                )}
              </div>
            ) : discographyView === 'grid' ? (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                {filteredAlbums.map((album) => (
                  <AlbumCard
                    key={album.id}
                    album={album}
                    onOpen={() => onOpenAlbum(album)}
                  />
                ))}
              </div>
            ) : (
              <div className="space-y-1">
                {filteredAlbums.map((album) => (
                  <button
                    key={album.id}
                    onClick={() => onOpenAlbum(album)}
                    className="group flex w-full items-center gap-3 rounded-xl border border-transparent p-2 text-start transition hover:border-line hover:bg-panel-2"
                  >
                    <Artwork
                      src={album.artworkUrl}
                      alt={album.title}
                      seed={album.id}
                      rounded="rounded-lg"
                      className="size-12 shrink-0 object-cover shadow-sm"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="bidi truncate text-sm font-bold text-fg group-hover:text-accent transition-colors">
                        {album.title}
                      </p>
                      <p className="mt-0.5 text-xs text-muted">
                        {releaseLabel(album, t)}
                        {album.year ? ` · ${digits(album.year, lang)}` : ''}
                        {album.trackCount > 0 ? ` · ${t.trackCount(album.trackCount)}` : ''}
                      </p>
                    </div>
                    <ArrowIcon className="size-4 shrink-0 text-muted transition group-hover:translate-x-1 rtl:group-hover:-translate-x-1 group-hover:text-fg" />
                  </button>
                ))}
              </div>
            )}
          </section>
        )}

        {/* ─── بخش پلی‌لیست‌ها ─── */}
        {filteredPlaylists.length > 0 && (
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-fg sm:text-lg">
                {t.playlists}
              </h2>
              <span className="text-xs font-semibold text-muted-2">
                ({digits(filteredPlaylists.length, lang)})
              </span>
            </div>

            <div className="space-y-0.5">
              {filteredPlaylists.map((playlist) => (
                <PlaylistRow
                  key={playlist.id}
                  playlist={playlist}
                  onOpen={() => onOpenPlaylist(playlist)}
                />
              ))}
            </div>
          </section>
        )}

        {/* ─── فاز ۶: ترک‌های بازنشر شده (ساندکلاد) به صورت شلف افقی ─── */}
        {filteredReposted.length > 0 && (
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-fg sm:text-lg">
                {t.reposted}
              </h2>
              <span className="text-xs font-semibold text-muted-2">
                ({digits(filteredReposted.length, lang)})
              </span>
            </div>

            <Shelf>
              {filteredReposted.map((track) => (
                <ShelfTrackCard
                  key={track.id}
                  track={track}
                  playing={isPlaying && currentTrackId === track.id}
                  playLabel={t.playTrack(track.title)}
                  pauseLabel={t.pause}
                  onPlay={() => {
                    if (currentTrackId === track.id) {
                      usePlayer.getState().toggle()
                    } else {
                      const idx = filteredReposted.findIndex((x) => x.id === track.id)
                      const items = filteredReposted.map((x) =>
                        toPlayItem(x, findBestJob(readyJobs, x.id, quality), quality),
                      )
                      play(items, Math.max(0, idx))
                    }
                  }}
                />
              ))}
            </Shelf>
          </section>
        )}

        {/* ─── فاز ۶: ترک‌های لایک شده (ساندکلاد) به صورت شلف افقی ─── */}
        {filteredLiked.length > 0 && (
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-fg sm:text-lg">
                {t.liked}
              </h2>
              <span className="text-xs font-semibold text-muted-2">
                ({digits(filteredLiked.length, lang)})
              </span>
            </div>

            <Shelf>
              {filteredLiked.map((track) => (
                <ShelfTrackCard
                  key={track.id}
                  track={track}
                  playing={isPlaying && currentTrackId === track.id}
                  playLabel={t.playTrack(track.title)}
                  pauseLabel={t.pause}
                  onPlay={() => {
                    if (currentTrackId === track.id) {
                      usePlayer.getState().toggle()
                    } else {
                      const idx = filteredLiked.findIndex((x) => x.id === track.id)
                      const items = filteredLiked.map((x) =>
                        toPlayItem(x, findBestJob(readyJobs, x.id, quality), quality),
                      )
                      play(items, Math.max(0, idx))
                    }
                  }}
                />
              ))}
            </Shelf>
          </section>
        )}

        {radioTracks.length > 0 && !cleanQ && (
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-fg sm:text-lg">{t.artistRadio}</h2>
              <span className="text-xs font-semibold text-muted-2">
                ({digits(radioTracks.length, lang)})
              </span>
            </div>
            <Shelf>
              {radioTracks.map((track, idx) => (
                <ShelfTrackCard
                  key={track.id}
                  track={track}
                  playing={isPlaying && currentTrackId === track.id}
                  playLabel={t.playTrack(track.title)}
                  pauseLabel={t.pause}
                  onPlay={() => {
                    if (currentTrackId === track.id) {
                      usePlayer.getState().toggle()
                    } else {
                      const items = radioTracks.map((x) =>
                        toPlayItem(x, findBestJob(readyJobs, x.id, quality), quality),
                      )
                      play(items, idx)
                    }
                  }}
                />
              ))}
            </Shelf>
          </section>
        )}

        {relatedArtists.length > 0 && !cleanQ && (
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-fg sm:text-lg">{t.relatedArtists}</h2>
              <span className="text-xs font-semibold text-muted-2">
                ({digits(relatedArtists.length, lang)})
              </span>
            </div>
            <Shelf>
              {relatedArtists.map((related) => (
                <div key={related.id} className="w-28 shrink-0 snap-start sm:w-32">
                  <ArtistCard
                    artist={related}
                    onOpen={() => onOpenArtist?.(related)}
                  />
                </div>
              ))}
            </Shelf>
          </section>
        )}
      </div>

      {/* ─── فاز ۷: مودال جامع «درباره هنرمند» (About the Artist Modal) ─── */}
      {showAboutModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="about-artist-title"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md"
          onClick={() => setShowAboutModal(false)}
        >
          <div
            className="relative w-full max-w-md overflow-hidden rounded-3xl border border-line-soft bg-panel p-6 shadow-2xl rise"
            onClick={(e) => e.stopPropagation()}
          >
            {/* دکمه بستن */}
            <button
              onClick={() => setShowAboutModal(false)}
              className="absolute end-4 top-4 grid size-8 place-items-center rounded-full border border-line bg-panel-2 text-muted hover:text-fg transition"
              aria-label={t.collapse}
            >
              <CloseIcon className="size-4" />
            </button>

            {/* آواتار و نام */}
            <div className="flex flex-col items-center text-center">
              <div className="relative size-28 overflow-hidden rounded-full border-2 border-white/20 shadow-xl">
                <Artwork
                  src={artist.artworkUrl}
                  alt={artist.name}
                  seed={artist.id}
                  rounded="rounded-full"
                  className="size-full object-cover"
                />
              </div>

              <div className="mt-4 flex items-center gap-1.5">
                <h3 id="about-artist-title" className="text-xl font-black text-fg">
                  {artist.name}
                </h3>
                {isVerified && <VerifiedBadgeIcon className="size-4 text-accent" />}
              </div>

              {artist.subtitle && (
                <p className="mt-1 text-xs text-muted">
                  {digits(artist.subtitle, lang)}
                </p>
              )}
            </div>

            {/* گرید آمار و اطلاعات متناسب با نوع هنرمند و پلتفرم */}
            <div className="mt-6 grid grid-cols-2 gap-3">
              {isUser ? (
                <div className="rounded-2xl border border-line-soft bg-panel-2/60 p-3 text-center">
                  <span className="text-xs text-muted">{t.playlists}</span>
                  <p className="mt-1 text-base font-bold text-fg">
                    {digits(artist.playlists.length, lang)}
                  </p>
                </div>
              ) : (
                <div className="rounded-2xl border border-line-soft bg-panel-2/60 p-3 text-center">
                  <span className="text-xs text-muted">{t.albums}</span>
                  <p className="mt-1 text-base font-bold text-fg">
                    {digits(artist.albums.length, lang)}
                  </p>
                </div>
              )}

              {artist.topTracks.length > 0 && (
                <div className="rounded-2xl border border-line-soft bg-panel-2/60 p-3 text-center">
                  <span className="text-xs text-muted">{topTracksTitle}</span>
                  <p className="mt-1 text-base font-bold text-fg">
                    {digits(artist.topTracks.length, lang)}
                  </p>
                </div>
              )}

              {(artist.likedTracks?.length ?? 0) > 0 && (
                <div className="rounded-2xl border border-line-soft bg-panel-2/60 p-3 text-center">
                  <span className="text-xs text-muted">{t.liked}</span>
                  <p className="mt-1 text-base font-bold text-fg">
                    {digits(artist.likedTracks?.length ?? 0, lang)}
                  </p>
                </div>
              )}

              {(artist.repostedTracks?.length ?? 0) > 0 && (
                <div className="rounded-2xl border border-line-soft bg-panel-2/60 p-3 text-center">
                  <span className="text-xs text-muted">{t.reposted}</span>
                  <p className="mt-1 text-base font-bold text-fg">
                    {digits(artist.repostedTracks?.length ?? 0, lang)}
                  </p>
                </div>
              )}

              {relatedArtists.length > 0 && (
                <div className="rounded-2xl border border-line-soft bg-panel-2/60 p-3 text-center">
                  <span className="text-xs text-muted">{t.relatedArtists}</span>
                  <p className="mt-1 text-base font-bold text-fg">
                    {digits(relatedArtists.length, lang)}
                  </p>
                </div>
              )}

              {radioTracks.length > 0 && (
                <div className="rounded-2xl border border-line-soft bg-panel-2/60 p-3 text-center">
                  <span className="text-xs text-muted">{t.artistRadio}</span>
                  <p className="mt-1 text-base font-bold text-fg">
                    {digits(radioTracks.length, lang)}
                  </p>
                </div>
              )}

              <div className="rounded-2xl border border-line-soft bg-panel-2/60 p-3 text-center">
                <span className="text-xs text-muted">{t.inYourLibrary}</span>
                <p className="mt-1 text-base font-bold text-accent">
                  {digits(downloadedArtistJobs.length, lang)}
                </p>
              </div>

              <div className="rounded-2xl border border-line-soft bg-panel-2/60 p-3 text-center">
                <span className="text-xs text-muted">{t.quality}</span>
                <p className="mt-1 text-base font-bold text-fg">
                  {quality.toUpperCase()}
                </p>
              </div>
            </div>

            {/* لینک به پلتفرم منبع */}
            {artist.sourceUrl && (
              <div className="mt-6 pt-4 border-t border-line-soft flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <SourceLogo source={artist.source} className="size-4" />
                  <span className="text-xs font-medium text-muted">
                    {SOURCE_LABEL[artist.source]}
                  </span>
                </div>

                <a
                  href={artist.sourceUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-bold text-accent hover:underline"
                >
                  <span>{t.openSource}</span>
                  <ArrowIcon className="size-3 -scale-x-100 rtl:scale-x-100" />
                </a>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
