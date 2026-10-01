import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { dominantColor } from '../lib/artColor'
import { usePopover } from '../lib/usePopover'
import { api, API_MODE } from '../lib/api'
import { bytes as fmtBytes, digits, fileExt, safeFilename } from '../lib/format'
import { useI18n } from '../lib/i18n'
import {
  filterItems,
  groupByAlbum,
  groupByArtist,
  libraryStats,
  sortGroups,
  sortItems,
  LIBRARY_SORTS,
  type LibrarySort,
} from '../lib/library'
import { pinnedBytes, supported as offlineSupported } from '../lib/offline'
import { readStored, readStoredAs, writeStored } from '../lib/storage'
import { SOURCE_LABEL, type LibraryItem, type LibraryPage, type Source } from '../lib/types'
import { useFavorites } from '../store/favorites'
import { useOffline } from '../store/offline'
import { usePlayer } from '../store/player'
import { UNDO_WINDOW_MS, useToasts } from '../store/toasts'
import { PlaylistPicker } from './AddToPlaylist'
import EmptyState from './EmptyState'
import { GroupCard, GroupHero, Mosaic, longDuration } from './LibraryCollections'
import AnimatedList from './AnimatedList'
import CountUp from './CountUp'
import { LibraryRow, RowHeader, toPlayItem } from './LibraryRow'
import SourceLogo from './logos'
import { SectionHead, Shelf, TrackTile } from './Shelf'
import PlaylistsView from './PlaylistsView'
import {
  AlbumIcon,
  ArtistIcon,
  CheckIcon,
  ChevronIcon,
  CloseIcon,
  GridIcon,
  HeartIcon,
  LibraryIcon,
  ListIcon,
  NextIcon,
  OfflineIcon,
  PlayIcon,
  PlaylistIcon,
  QueueIcon,
  SearchIcon,
  ShuffleIcon,
  SortIcon,
  Spinner,
  TrashIcon,
  ZipIcon,
} from './icons'

type Tab = 'tracks' | 'albums' | 'artists' | 'playlists'

const VIEW_KEY = 'library:view'
const SORT_KEY = 'library:sort'


const sortLabel = (sort: LibrarySort, t: ReturnType<typeof useI18n.getState>['t']): string =>
  ({
    recent: t.sortRecent,
    title: t.sortTitle,
    artist: t.sortArtist,
    size: t.sortSize,
    duration: t.sortDuration,
    plays: t.sortMostPlayed,
  })[sort]

/** انتخابِ ترتیب — منوی کوچکِ خودش، چون پنج چیپِ کنارِ هم کلِ نوار را می‌خورد */
function SortMenu({ value, onChange }: { value: LibrarySort; onChange: (s: LibrarySort) => void }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const box = usePopover<HTMLDivElement>(open, () => setOpen(false))

  return (
    <div ref={box} className="relative shrink-0">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={t.sortBy}
        className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1.5 text-[11px] text-muted transition hover:text-fg cursor-pointer"
      >
        <SortIcon className={`size-3.5 transition-colors duration-200 ${open ? 'text-accent' : ''}`} />
        <span className="hidden sm:inline">{sortLabel(value, t)}</span>
        <ChevronIcon className={`size-3 text-muted-2 transition-transform duration-200 ease-out ${open ? 'rotate-180' : 'rotate-0'}`} />
      </button>

      {open && (
        <div
          role="menu"
          className="sheet-in absolute end-0 z-40 mt-1 w-44 rounded-xl border border-line bg-panel p-1.5 shadow-xl"
        >
          <p className="px-2.5 py-1 text-[10px] uppercase tracking-wide text-muted-2">{t.sortBy}</p>
          {LIBRARY_SORTS.map((option) => (
            <button
              key={option}
              role="menuitemradio"
              aria-checked={option === value}
              onClick={() => {
                onChange(option)
                setOpen(false)
              }}
              className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-start text-xs transition hover:bg-panel-2 ${
                option === value ? 'text-accent' : 'text-muted hover:text-fg'
              }`}
            >
              <CheckIcon className={`size-3.5 shrink-0 ${option === value ? '' : 'opacity-0'}`} />
              {sortLabel(option, t)}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** «افزودن به پلی‌لیست» برای چند ترک با هم — نوارِ انتخاب از این استفاده می‌کند */
function BulkPlaylist({ jobIds }: { jobIds: string[] }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const box = usePopover<HTMLDivElement>(open, () => setOpen(false))

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={t.playlistAdd}
        className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1.5 text-[11px] text-muted transition hover:text-fg"
      >
        <PlaylistIcon className="size-3.5" />
        <span className="hidden sm:inline">{t.playlistAdd}</span>
      </button>
      {open && (
        <div
          role="menu"
          className="sheet-in absolute end-0 z-40 mt-1 w-52 rounded-xl border border-line bg-panel p-1.5 shadow-xl"
        >
          <PlaylistPicker jobIds={jobIds} onDone={() => setOpen(false)} />
        </div>
      )}
    </div>
  )
}

export default function LibraryView({ initialTab }: { initialTab?: 'playlists' | 'liked' }) {
  const [page, setPage] = useState<LibraryPage | null>(null)
  const [loading, setLoading] = useState(true)
  /** فهرستِ لایک‌شده‌ها از `/api/favorites` — فقط وقتی چیپش روشن شود واکشی می‌شود */
  const [favItems, setFavItems] = useState<LibraryItem[] | null>(null)
  const [query, setQuery] = useState('')
  const [supported, setSupported] = useState(true)
  // «لایک‌ها» تبِ مستقل نیست: همان تبِ ترک‌ها با فیلترِ onlyFavs روشن
  const [tab, setTab] = useState<Tab>(initialTab === 'playlists' ? 'playlists' : 'tracks')
  const [onlyOffline, setOnlyOffline] = useState(false)
  /** فقط لایک‌شده‌ها — داده از `/api/favorites` می‌آید، جستجویش محلی است */
  const [onlyFavs, setOnlyFavs] = useState(false)
  /*
   * «لایک‌ها» تبِ مستقل نیست: همان تبِ ترک‌ها با فیلترِ onlyFavs.
   * دو راهِ ورود: دیپ‌لینک/تاریخچه (?library=liked) که از prop می‌آید، و
   * کلیکِ زنده روی قلبِ نوارِ پخش که رویداد است — چون در کلیکِ دوم مقدارِ
   * prop عوض نمی‌شود ('liked' بود، 'liked' می‌ماند) و افکت دوباره اجرا
   * نمی‌شد، ولی رویداد همیشه می‌رسد.
   */
  useEffect(() => {
    if (initialTab === 'liked') {
      setTab('tracks')
      setOnlyFavs(true)
    }
  }, [initialTab])
  useEffect(() => {
    const open = () => {
      setTab('tracks')
      setOnlyFavs(true)
    }
    window.addEventListener('musicbazi:open-liked', open)
    return () => window.removeEventListener('musicbazi:open-liked', open)
  }, [])
  const [unreachable, setUnreachable] = useState(false)
  const [selectedSource, setSelectedSource] = useState<Source | null>(null)
  const [onlyLossless, setOnlyLossless] = useState(false)
  const [onlyUnplayed, setOnlyUnplayed] = useState(false)
  const [sort, setSort] = useState<LibrarySort>(
    () => readStoredAs<LibrarySort>(SORT_KEY, 'recent'),
  )
  const [view, setView] = useState<'list' | 'grid'>(
    () => (readStored(VIEW_KEY) === 'grid' ? 'grid' : 'list'),
  )
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [selectMode, setSelectMode] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [zipping, setZipping] = useState(false)
  const heroRef = useRef<HTMLDivElement>(null)
  const [isScrolledPast, setIsScrolledPast] = useState(false)

  useEffect(() => {
    const el = heroRef.current
    if (!el) return

    const onScroll = () => {
      const rect = el.getBoundingClientRect()
      setIsScrolledPast(rect.bottom <= 60)
    }

    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()

    let observer: IntersectionObserver | null = null
    if (typeof IntersectionObserver !== 'undefined') {
      observer = new IntersectionObserver(
        ([entry]) => {
          setIsScrolledPast(!entry.isIntersecting)
        },
        { threshold: 0.1 },
      )
      observer.observe(el)
    }

    return () => {
      window.removeEventListener('scroll', onScroll)
      observer?.disconnect()
    }
  }, [])
  /*
   * ردیف‌هایی که «پاک شده‌اند» ولی هنوز نه.
   *
   * حذف از کتابخانه یعنی حذفِ فایل از دیسکِ سرور — بی‌بازگشت. تا امروز راهِ
   * جبرانش فقط دانلودِ دوباره بود، و مودالِ «مطمئنی؟» هم چاره نیست: کسی که
   * مطمئن است را هر بار کند می‌کند و کسی که اشتباه می‌زند معمولاً همان را هم
   * بی‌فکر تأیید می‌کند.
   *
   * پس مثل جی‌میل: ردیف همان لحظه از لیست می‌رود، ولی درخواستِ واقعی چند
   * ثانیه صبر می‌کند. تا وقتی توستِ «واگرد» روی صفحه است، هیچ‌چیز واقعاً پاک
   * نشده.
   */
  const [pendingRemoval, setPendingRemoval] = useState<Set<string>>(new Set())
  /** تایمرهای درحال‌انتظار — با ترکِ صفحه باید *اجرا* شوند، نه لغو */
  const commits = useRef(new Map<number, () => void>())
  const removalSeq = useRef(0)
  const inflight = useRef<AbortController | null>(null)
  const { t, lang } = useI18n()
  const pushToast = useToasts((s) => s.push)
  const pinnedItems = useOffline((s) => s.items)

  const load = useCallback(
    async (q: string) => {
      inflight.current?.abort()
      const ctrl = new AbortController()
      inflight.current = ctrl
      setLoading(true)
      try {
        const result = await api.library(q, ctrl.signal)
        if (ctrl.signal.aborted) return
        setSupported(result !== null)
        setUnreachable(false)
        setPage(result)
        if (result) {
          useFavorites.getState().hydrate(
            result.items.map((x) => x.jobId),
            result.items.map((x) => Boolean(x.favorite)),
          )
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        // قطعیِ شبکه خطا نیست — همان چیزی است که سنجاق‌ها برایش ساخته شده‌اند.
        // ولی خطای خودِ سرور (۵۰۰) هست و نباید زیر پیامِ «آفلاینی» پنهان شود؛
        // `fetch` فقط برای شکستِ شبکه TypeError پرت می‌کند.
        if (!navigator.onLine || err instanceof TypeError) {
          setUnreachable(true)
        } else {
          pushToast(t.fetchError, 'error')
        }
      } finally {
        if (!ctrl.signal.aborted) setLoading(false)
      }
    },
    [pushToast, t],
  )

  // تایپ کردن نباید به ازای هر حرف یک درخواست بزند
  useEffect(() => {
    const timer = setTimeout(() => void load(query), query ? 300 : 0)
    return () => clearTimeout(timer)
  }, [query, load])

  useEffect(() => () => inflight.current?.abort(), [])

  // کشِ مرورگر ممکن است بین دو بازدید چیزی را دور انداخته باشد
  useEffect(() => {
    void useOffline.getState().sync()
  }, [])

  useEffect(() => {
    writeStored(SORT_KEY, sort)
  }, [sort])

  useEffect(() => {
    writeStored(VIEW_KEY, view)
  }, [view])

  // گروهِ بازمانده از تبِ قبلی در تبِ جدید معنایی ندارد — و انتخابی که
  // ردیف‌هایش دیگر روی صفحه نیستند، انتخابِ نامرئی است
  useEffect(() => {
    setOpenKey(null)
    setSelected(new Set())
  }, [tab])

  useEffect(() => {
    setSelected(new Set())
  }, [openKey])

  // «مطمئنی؟» نباید تا ابد روی دکمه بماند
  useEffect(() => {
    if (!confirmDelete) return
    const timer = setTimeout(() => setConfirmDelete(false), 4_000)
    return () => clearTimeout(timer)
  }, [confirmDelete])

  useEffect(() => {
    setConfirmDelete(false)
  }, [selected])

  /** ردیف‌ها را از حالت (و از صف پخش و آفلاین) بردار */
  const forget = useCallback((removed: LibraryItem[]) => {
    const gone = new Set(removed.map((x) => x.jobId))
    for (const item of removed) {
      usePlayer.getState().drop(item.jobId)
      void useOffline.getState().unpin(item)
    }
    setPage((prev) =>
      prev
        ? {
            ...prev,
            items: prev.items.filter((x) => !gone.has(x.jobId)),
            total: Math.max(0, prev.total - removed.length),
            totalBytes: Math.max(0, prev.totalBytes - removed.reduce((s, x) => s + x.bytes, 0)),
          }
        : prev,
    )
    setSelected((prev) => {
      const next = new Set(prev)
      for (const id of gone) next.delete(id)
      return next
    })
  }, [])

  /**
   * حذفِ قابلِ واگرد: ردیف‌ها فوراً از لیست می‌روند، درخواستِ واقعی بعد از
   * مهلتِ توست می‌رود.
   */
  const scheduleRemoval = useCallback(
    (items: LibraryItem[], message: string) => {
      if (!items.length) return
      const ids = items.map((x) => x.jobId)
      const key = ++removalSeq.current

      setPendingRemoval((prev) => new Set([...prev, ...ids]))

      /** ردیف‌ها را از حالتِ «منتظرِ حذف» دربیاور — یا برمی‌گردند یا رفته‌اند */
      const unhide = () =>
        setPendingRemoval((prev) => {
          const rest = new Set(prev)
          for (const id of ids) rest.delete(id)
          return rest
        })

      const stopTimer = () => {
        window.clearTimeout(timer)
        commits.current.delete(key)
      }

      /** واگرد: هیچ درخواستی نرفته، ردیف‌ها سرِ جایشان برمی‌گردند */
      const undo = () => {
        stopTimer()
        unhide()
      }

      const commit = async () => {
        stopTimer()
        const results = await Promise.allSettled(ids.map((id) => api.removeFromLibrary(id)))
        const done = items.filter((_, i) => results[i].status === 'fulfilled')
        /*
         * ترتیب مهم است: اول `forget` که ردیف‌ها را از خودِ داده بیرون
         * می‌برد، بعد برداشتنِ پرده. برعکسش یعنی یک فریم که ردیف‌های
         * پاک‌شده دوباره ظاهر می‌شوند و بعد می‌روند. هر دو در یک تیک‌اند،
         * پس ری‌اکت یک‌جا رندرشان می‌کند.
         *
         * پاک‌کردنِ سنجاقِ آفلاین و بیرون‌کشیدن از صفِ پخش هم تا همین لحظه
         * عقب افتاده‌اند: با واگرد نباید فایلِ آفلاین از دست رفته باشد.
         */
        if (done.length) forget(done)
        unhide()
        if (done.length < ids.length) pushToast(t.libraryRemoveFailed, 'error')
      }

      const timer = window.setTimeout(() => void commit(), UNDO_WINDOW_MS)
      commits.current.set(key, () => void commit())

      pushToast(message, 'info', { label: t.undo, run: undo })
    },
    [forget, pushToast, t],
  )

  /*
   * ترکِ صفحه (یا بستنِ اپ) نباید حذف را بی‌سروصدا لغو کند: کاربر «پاک شد»
   * دیده و واگرد نزده، پس تصمیمش همان بوده.
   */
  useEffect(
    () => () => {
      for (const run of commits.current.values()) run()
    },
    [],
  )

  async function zipSelected(items: LibraryItem[]) {
    setZipping(true)
    try {
      const url = await api.zip(
        items.map((x) => ({ trackId: x.track.id, quality: x.quality, jobId: x.jobId })),
        safeFilename(t.library),
      )
      if (!url) {
        pushToast(t.mockNoFile, 'info')
        return
      }
      // ناوبری به URL، نه fetch: دانلود بومی و بدون نگه‌داشتن آرشیو در حافظه
      location.href = url
    } catch {
      pushToast(t.toastZipFailed, 'error')
    } finally {
      setZipping(false)
    }
  }

  const pinnedList = useMemo(() => Object.values(pinnedItems), [pinnedItems])

  /**
   * سه منبعِ داده، یک خروجی:
   *
   * - سرور در دسترس نیست → همان سنجاق‌ها (چیزی که واقعاً روی این دستگاه پخش می‌شود)
   * - چیپِ لایک‌ها روشن است → فهرستِ `/api/favorites`
   * - وگرنه → صفحه‌ی کتابخانه، با فیلترِ اختیاریِ «فقط آفلاین»
   *
   * فیلترِ لایک روی استورِ خوش‌بینانه هم اعمال می‌شود: قلبی که همین الان از
   * جای دیگری برداشته شده نباید تا واکشیِ بعدی اینجا بماند.
   */
  const favMap = useFavorites((s) => s.items)

  // لایک‌شده‌ها فقط وقتی لازم‌اند که چیپشان روشن باشد. وابستگی به `version`
  // یعنی قلبی که حین روشن بودنِ چیپ از جای دیگری برداشته شد، واکشیِ دوباره
  // بزند — ولی هیدریتِ کتابخانه (که نسخه را بالا نمی‌برد) نه.
  const favVersion = useFavorites((s) => s.version)
  useEffect(() => {
    if (!onlyFavs) return
    const ctrl = new AbortController()
    api
      .favorites(ctrl.signal)
      .then((rows) => {
        if (!ctrl.signal.aborted) setFavItems(rows ?? [])
      })
      .catch(() => {})
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onlyFavs, favVersion])

  const items = useMemo(() => {
    let base: LibraryItem[]
    if (unreachable) {
      base = filterItems(pinnedList, query)
      if (onlyFavs) base = base.filter((item) => favMap[item.jobId])
    } else if (onlyFavs) {
      base = favItems === null ? [] : filterItems(favItems, query).filter((item) => favMap[item.jobId])
    } else {
      base = (page?.items ?? []).filter((item) => !onlyOffline || pinnedItems[item.jobId])
    }
    if (selectedSource) {
      base = base.filter((item) => item.track.source === selectedSource)
    }
    if (onlyLossless) {
      base = base.filter(
        (item) =>
          item.quality === 'flac' ||
          fileExt(item.format).toLowerCase() === 'flac' ||
          Boolean(item.format?.toLowerCase().includes('flac')),
      )
    }
    if (onlyUnplayed) {
      base = base.filter((item) => (item.playCount ?? 0) === 0 && !item.lastPlayedAt)
    }
    // ردیف‌هایی که منتظرِ حذف‌اند از همین‌جا کنار می‌روند، پس گروه‌بندی، آمار،
    // صفِ پخش و انتخاب همه یک‌جا و بدونِ شرطِ تکراری با هم هماهنگ می‌مانند
    return sortItems(
      pendingRemoval.size ? base.filter((item) => !pendingRemoval.has(item.jobId)) : base,
      sort,
    )
  }, [
    unreachable,
    pinnedList,
    query,
    page,
    onlyOffline,
    onlyFavs,
    favItems,
    favMap,
    pinnedItems,
    selectedSource,
    onlyLossless,
    onlyUnplayed,
    sort,
    pendingRemoval,
  ])

  const albums = useMemo(() => sortGroups(groupByAlbum(items), sort), [items, sort])
  const artists = useMemo(() => sortGroups(groupByArtist(items), sort), [items, sort])
  const stats = useMemo(() => libraryStats(items), [items])
  const covers = useMemo(
    () => [...new Set(items.map((x) => x.track.artworkUrl).filter((u): u is string => Boolean(u)))].slice(0, 4),
    [items],
  )

  /*
   * ردیف‌های «اخیراً» و قفسه‌های هوشمند — از همان `items` ساخته می‌شوند، نه با درخواستِ جدا.
   *
   * کمتر از چهار کاشی، ردیف معنایی ندارد: اسکرول افقی روی چهار آیتمِ کوتاه‌تر
   * از عرضِ صفحه فقط فضا می‌گیرد. برای همین هر ردیف زیرِ همان سقف می‌رود.
   */
  const recentlyPlayed = useMemo(
    () =>
      items
        .filter((x) => x.lastPlayedAt)
        .sort((a, b) => (b.lastPlayedAt ?? 0) - (a.lastPlayedAt ?? 0))
        .slice(0, 12),
    [items],
  )
  const recentlyAdded = useMemo(() => sortItems(items, 'recent').slice(0, 12), [items])
  const topPlayed = useMemo(
    () =>
      items
        .filter((x) => (x.playCount ?? 0) > 0)
        .sort((a, b) => (b.playCount ?? 0) - (a.playCount ?? 0) || b.createdAt - a.createdAt)
        .slice(0, 12),
    [items],
  )
  const highEnergy = useMemo(
    () =>
      items
        .filter((x) => typeof x.track.energy === 'number' && x.track.energy >= 0.6)
        .sort((a, b) => (b.track.energy ?? 0) - (a.track.energy ?? 0))
        .slice(0, 12),
    [items],
  )
  const calm = useMemo(
    () =>
      items
        .filter((x) => typeof x.track.energy === 'number' && x.track.energy <= 0.4)
        .sort((a, b) => (a.track.energy ?? 0) - (b.track.energy ?? 0))
        .slice(0, 12),
    [items],
  )
  const playedQueue = useMemo(() => recentlyPlayed.map(toPlayItem), [recentlyPlayed])
  const addedQueue = useMemo(() => recentlyAdded.map(toPlayItem), [recentlyAdded])
  const topPlayedQueue = useMemo(() => topPlayed.map(toPlayItem), [topPlayed])
  const highEnergyQueue = useMemo(() => highEnergy.map(toPlayItem), [highEnergy])
  const calmQueue = useMemo(() => calm.map(toPlayItem), [calm])

  /*
   * هاله‌های سرصفحه رنگِ کاورِ اول را می‌گیرند — همان کاری که پخش‌کننده با
   * کاورِ ترکِ فعلی می‌کند. بدونِ کاور (یا کاورِ بی‌CORS) null می‌ماند و
   * هاله‌های accentِ پیش‌فرض سرِ جایشان‌اند.
   */
  const [tint, setTint] = useState<[number, number, number] | null>(null)
  const cover0 = covers[0] ?? null
  useEffect(() => {
    let cancelled = false
    setTint(null)
    void dominantColor(cover0).then((c) => {
      if (!cancelled) setTint(c)
    })
    return () => {
      cancelled = true
    }
  }, [cover0])

  if (!supported || API_MODE !== 'http') {
    return <EmptyState icon={<LibraryIcon className="size-5" />} text={t.libraryUnavailable} />
  }

  const openGroup =
    openKey === null
      ? null
      : (tab === 'albums' ? albums : artists).find((g) => g.key === openKey) ?? null

  // ردیف‌هایی که همین حالا روی صفحه‌اند — هم صفِ پخش‌اند هم دامنه‌ی انتخاب.
  // `queue` باید memo باشد: با memo بودنِ ردیف‌ها، آرایه‌ی نو در هر رندر همه
  // را از نو می‌راند و memo بی‌اثر می‌شد. امضای `jobId`ها ملاک است نه
  // خودِ آرایه: لایک‌زدنِ یک ردیف، آرایه‌ی items را از نو می‌سازد ولی صف
  // عوض نشده و هیچ ردیفی نباید به‌خاطرِ یک قلبِ بی‌ربط رندر شود
  const visible = openGroup ? openGroup.items : items
  const visibleSig = visible.map((x) => x.jobId).join('|')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const queue = useMemo(() => visible.map(toPlayItem), [visibleSig])
  const selectedItems = visible.filter((x) => selected.has(x.jobId))
  const selecting = selectMode
  const allSelected = visible.length > 0 && selectedItems.length === visible.length

  const playAll = () => {
    if (queue.length) usePlayer.getState().play(queue, 0)
  }
  const shuffleAll = () => {
    if (!queue.length) return
    const player = usePlayer.getState()
    if (!player.shuffle) player.toggleShuffle()
    player.play(queue, Math.floor(Math.random() * queue.length))
  }

  const toggleSelect = useCallback(
    (jobId: string) =>
      setSelected((prev) => {
        const next = new Set(prev)
        if (next.has(jobId)) next.delete(jobId)
        else next.add(jobId)
        return next
      }),
    [],
  )

  const removeOne = useCallback(
    (item: LibraryItem) => scheduleRemoval([item], t.libraryRemoved(item.track.title)),
    [scheduleRemoval, t],
  )

  const openGroupCard = useCallback((key: string) => setOpenKey(key), [])

  const tabs: { id: Tab; label: string; icon: React.ReactNode; count?: number }[] = [
    { id: 'tracks', label: t.libraryTracksTab, icon: <ListIcon className="size-3.5" />, count: stats.tracks },
    { id: 'albums', label: t.libraryAlbumsTab, icon: <AlbumIcon className="size-3.5" />, count: stats.albums },
    { id: 'artists', label: t.libraryArtistsTab, icon: <ArtistIcon className="size-3.5" />, count: stats.artists },
    { id: 'playlists', label: t.myPlaylists, icon: <PlaylistIcon className="size-3.5" /> },
  ]

  const rows = (list: LibraryItem[]) =>
    list.map((item, i) => (
      <LibraryRow
        key={item.jobId}
        item={item}
        queue={queue}
        index={i}
        number={i + 1}
        onRemove={removeOne}
        selectable={selecting}
        selected={selected.has(item.jobId)}
        onToggleSelect={toggleSelect}
      />
    ))

  // در حالتِ لایک‌ها، واکشیِ فهرست ممکن است هنوز تمام نشده باشد؛ `items` خالیِ
  // ناشی از آن «کتابخانه خالی» نیست و اسپینر خودش می‌گوید که هنوز می‌آید
  const listLoading = loading || (onlyFavs && favItems === null)
  const hasFilter = Boolean(query || selectedSource || onlyLossless || onlyUnplayed)

  const emptyTracks = (
    <EmptyState
      bordered={false}
      icon={
        onlyFavs ? <HeartIcon className="size-5" /> : hasFilter ? <SearchIcon className="size-5" /> : <LibraryIcon className="size-5" />
      }
      text={
        onlyFavs
          ? hasFilter
            ? t.libraryNoMatch
            : t.favoritesEmpty
          : hasFilter
            ? t.libraryNoMatch
            : t.libraryEmpty
      }
    />
  )

  return (
    <div className="rise space-y-4">
      {/* ---------- سرصفحه ---------- */}
      <div
        ref={heroRef}
        className="relative overflow-hidden rounded-2xl border border-line-soft bg-panel/50 p-4 sm:p-5"
      >
        <span
          aria-hidden
          className={`pointer-events-none absolute -top-24 end-0 size-64 rounded-full blur-3xl ${
            tint ? '' : 'bg-accent/10'
          }`}
          style={tint ? { background: `rgba(${tint[0]}, ${tint[1]}, ${tint[2]}, 0.18)` } : undefined}
        />
        <span
          aria-hidden
          className={`pointer-events-none absolute -bottom-28 start-10 size-56 rounded-full blur-3xl ${
            tint ? '' : 'bg-accent-2/10'
          }`}
          style={tint ? { background: `rgba(${tint[0]}, ${tint[1]}, ${tint[2]}, 0.12)` } : undefined}
        />

        <div className="relative flex items-center gap-4">
          <Mosaic
            urls={covers}
            seed="library"
            alt={t.library}
            className="size-20 shrink-0 shadow-xl shadow-black/30 sm:size-24"
            rounded="rounded-xl"
          />

          <div className="min-w-0 flex-1">
            <p className="text-[11px] uppercase tracking-wide text-muted-2">{t.librarySubtitle}</p>
            <h1 className="truncate text-2xl font-black sm:text-3xl">{t.library}</h1>
            <p className="mt-0.5 truncate text-xs text-muted">
              {unreachable
                ? t.offlineSummary(pinnedList.length, fmtBytes(pinnedBytes(pinnedList), lang))
                : `${t.libraryStats(stats.tracks, stats.artists, stats.albums)} · ${longDuration(
                    stats.durationMs,
                    t,
                  )} · ${fmtBytes(stats.bytes, lang)}`}
            </p>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                onClick={playAll}
                disabled={!queue.length}
                className="inline-flex items-center gap-1.5 rounded-full bg-accent px-4 py-1.5 text-xs font-semibold text-accent-fg transition enabled:hover:brightness-110 disabled:opacity-40"
              >
                <PlayIcon className="size-3.5" />
                {t.playAll}
              </button>
              <button
                onClick={shuffleAll}
                disabled={!queue.length}
                className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-xs text-muted transition enabled:hover:text-fg disabled:opacity-40"
              >
                <ShuffleIcon className="size-3.5" />
                {t.shuffle}
              </button>
              <button
                onClick={() => setOnlyFavs((v) => !v)}
                aria-pressed={onlyFavs}
                title={t.favoritesOnly}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition ${
                  onlyFavs
                    ? 'border-danger bg-danger/10 font-semibold text-danger'
                    : 'border-line text-muted hover:text-fg'
                }`}
              >
                <HeartIcon className="size-3.5" filled={onlyFavs} />
                {t.favoritesOnly}
              </button>

              {offlineSupported() && !unreachable && (
                <button
                  onClick={() => setOnlyOffline((v) => !v)}
                  aria-pressed={onlyOffline}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition ${
                    onlyOffline
                      ? 'border-accent bg-accent font-semibold text-accent-fg'
                      : 'border-line text-muted hover:text-fg'
                  }`}
                >
                  <OfflineIcon className="size-3.5" filled={onlyOffline} />
                  {t.offlineOnly}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ---------- تب‌ها و ابزار ---------- */}
      {/* top-header به‌جای top-14: در حالت PWA ارتفاعِ واقعیِ هدر شاملِ نوار
          وضعیت هم می‌شود و با عددِ ثابت، تب‌ها زیرِ هدر گم می‌شدند */}
      <div className="glass-bar top-header sticky z-20 space-y-2 rounded-2xl border border-line-soft p-2">
        {/* نوار فشرده سرصفحه هنگام اسکرول به پایین */}
        <div
          className={`grid transition-all duration-300 ease-out ${
            isScrolledPast
              ? 'grid-rows-[1fr] opacity-100 pb-2 mb-1 border-b border-line-soft/60'
              : 'grid-rows-[0fr] opacity-0 pointer-events-none'
          }`}
        >
          <div className="overflow-hidden">
            <div className="flex items-center justify-between gap-3 px-1">
              <div className="flex min-w-0 items-center gap-2.5">
                <Mosaic
                  urls={covers}
                  seed="library"
                  alt={t.library}
                  className="size-8 shrink-0 shadow-sm"
                  rounded="rounded-lg"
                />
                <div className="min-w-0">
                  <h2 className="bidi truncate text-xs font-bold text-fg">
                    {openGroup ? openGroup.title : t.library}
                  </h2>
                  <p className="bidi truncate text-[10px] text-muted">
                    {unreachable
                      ? t.offlineSummary(pinnedList.length, fmtBytes(pinnedBytes(pinnedList), lang))
                      : `${digits(visible.length, lang)} ${t.libraryTracksTab}`}
                  </p>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-1.5">
                <button
                  onClick={playAll}
                  disabled={!queue.length}
                  title={t.playAll}
                  aria-label={t.playAll}
                  className="inline-flex items-center gap-1 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold text-accent-fg transition enabled:hover:brightness-110 disabled:opacity-40"
                >
                  <PlayIcon className="size-3" />
                  <span className="hidden sm:inline">{t.playAll}</span>
                </button>
                <button
                  onClick={shuffleAll}
                  disabled={!queue.length}
                  title={t.shuffle}
                  aria-label={t.shuffle}
                  className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-1 text-[11px] text-muted transition enabled:hover:text-fg disabled:opacity-40"
                >
                  <ShuffleIcon className="size-3" />
                  <span className="hidden sm:inline">{t.shuffle}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="no-scrollbar -mx-1 flex items-center gap-1.5 overflow-x-auto px-1">
          {tabs.map((item) => (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              aria-current={tab === item.id ? 'page' : undefined}
              className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition ${
                tab === item.id
                  ? 'bg-accent font-semibold text-accent-fg'
                  : 'bg-panel-2/60 text-muted hover:text-fg'
              }`}
            >
              {item.icon}
              {item.label}
              {item.count !== undefined && (
                <span className={tab === item.id ? 'opacity-70' : 'text-muted-2'}>
                  {/* شمارنده بالا می‌رود؛ فرمت از بیرون می‌آید تا در فارسی
                      ارقام فارسی بمانند مثل بقیه‌ی عددهای اپ */}
                  <CountUp value={item.count} format={(n) => digits(n, lang)} />
                </span>
              )}
            </button>
          ))}
        </div>

        {tab !== 'playlists' &&
          (selecting ? (
            <div className="flex flex-wrap items-center gap-2 px-1">
              <button
                onClick={() =>
                  setSelected(allSelected ? new Set() : new Set(visible.map((x) => x.jobId)))
                }
                className="inline-flex items-center gap-1.5 text-xs text-muted transition hover:text-fg"
              >
                <span
                  className={`grid size-4 place-items-center rounded border transition ${
                    allSelected ? 'border-accent bg-accent text-accent-fg' : 'border-line text-transparent'
                  }`}
                >
                  <CheckIcon className="size-3" />
                </span>
                {selected.size ? t.selectedCount(selected.size) : t.selectAll}
              </button>

              <span className="flex-1" />

              <button
                onClick={() => usePlayer.getState().play(selectedItems.map(toPlayItem), 0)}
                disabled={!selected.size}
                title={t.selectionPlay}
                aria-label={t.selectionPlay}
                className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1.5 text-[11px] text-muted transition enabled:hover:text-fg disabled:opacity-40"
              >
                <PlayIcon className="size-3.5" />
                <span className="hidden sm:inline">{t.selectionPlay}</span>
              </button>

              <button
                onClick={() => {
                  const toPlay = selectedItems.map(toPlayItem)
                  usePlayer.getState().playNext(toPlay)
                  pushToast(t.selectionPlayNextAdded(selectedItems.length), 'info')
                }}
                disabled={!selected.size}
                title={t.selectionPlayNext}
                aria-label={t.selectionPlayNext}
                className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1.5 text-[11px] text-muted transition enabled:hover:text-fg disabled:opacity-40"
              >
                <NextIcon className="size-3.5" />
                <span className="hidden sm:inline">{t.selectionPlayNext}</span>
              </button>

              <button
                onClick={() => {
                  const toPlay = selectedItems.map(toPlayItem)
                  usePlayer.getState().enqueue(toPlay)
                  pushToast(t.selectionEnqueued(selectedItems.length), 'info')
                }}
                disabled={!selected.size}
                title={t.selectionAddToQueue}
                aria-label={t.selectionAddToQueue}
                className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1.5 text-[11px] text-muted transition enabled:hover:text-fg disabled:opacity-40"
              >
                <QueueIcon className="size-3.5" />
                <span className="hidden sm:inline">{t.selectionAddToQueue}</span>
              </button>

              {selected.size > 0 && <BulkPlaylist jobIds={selectedItems.map((x) => x.jobId)} />}

              <button
                onClick={() => void zipSelected(selectedItems)}
                disabled={zipping || !selected.size}
                title={t.zipTitle}
                className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1.5 text-[11px] text-muted transition enabled:hover:text-fg disabled:opacity-40"
              >
                {zipping ? <Spinner className="size-3.5" /> : <ZipIcon className="size-3.5" />}
                {t.zip(selected.size)}
              </button>

              {/* حذفِ دسته‌جمعی دو کلیک می‌خواهد: کلیکِ اول فقط دکمه را باز و
                  قرمز می‌کند. یک لغزشِ انگشت نباید بیست فایل را ببرد */}
              <button
                onClick={() => {
                  if (!confirmDelete) {
                    setConfirmDelete(true)
                    return
                  }
                  scheduleRemoval(selectedItems, t.selectionDeleted(selectedItems.length))
                }}
                disabled={!selected.size}
                title={t.selectionDelete}
                aria-label={t.selectionDelete}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[11px] transition disabled:opacity-40 ${
                  confirmDelete
                    ? 'border-danger bg-danger/10 font-semibold text-danger'
                    : 'border-line text-muted enabled:hover:border-danger enabled:hover:text-danger'
                }`}
              >
                <TrashIcon className="size-3.5" />
                {confirmDelete && t.selectionDelete}
              </button>

              <button
                onClick={() => {
                  setSelectMode(false)
                  setSelected(new Set())
                }}
                title={t.selectionClear}
                aria-label={t.selectionClear}
                className="grid size-8 place-items-center rounded-full text-muted-2 transition hover:bg-panel-2 hover:text-fg sm:size-7"
              >
                <CloseIcon className="size-3.5" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="flex min-w-32 flex-1 items-center gap-2 rounded-full border border-line bg-panel px-3 py-1.5">
                <SearchIcon className="size-3.5 shrink-0 text-muted-2" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t.librarySearch}
                  aria-label={t.librarySearch}
                  className="bidi-auto w-full bg-transparent text-xs outline-none placeholder:text-muted-2"
                />
                {loading && <Spinner className="size-3.5 shrink-0 text-muted-2" />}
              </div>

              <SortMenu value={sort} onChange={setSort} />

              {tab === 'tracks' && (
                <div className="flex shrink-0 items-center rounded-full border border-line p-0.5">
                  {(
                    [
                      ['list', t.viewList, <ListIcon key="l" className="size-3.5" />],
                      ['grid', t.viewGrid, <GridIcon key="g" className="size-3.5" />],
                    ] as const
                  ).map(([id, label, icon]) => (
                    <button
                      key={id}
                      onClick={() => setView(id)}
                      aria-pressed={view === id}
                      aria-label={label}
                      title={label}
                      className={`grid size-7 place-items-center rounded-full transition sm:size-6 ${
                        view === id ? 'bg-panel-2 text-fg' : 'text-muted-2 hover:text-fg'
                      }`}
                    >
                      {icon}
                    </button>
                  ))}
                </div>
              )}

              <button
                onClick={() => setSelectMode(true)}
                title={t.selectToggle}
                aria-label={t.selectToggle}
                className="grid size-8 shrink-0 place-items-center rounded-full border border-line text-muted-2 transition hover:text-fg sm:size-7"
              >
                <CheckIcon className="size-3.5" />
              </button>
            </div>
          ))}

        {/* نوار چیپ‌های فیلتر سریع (منبع، Lossless، پخش‌نشده) */}
        {tab !== 'playlists' && !selecting && (
          <div className="no-scrollbar -mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pt-1.5 border-t border-line-soft/60">
            <button
              type="button"
              onClick={() => {
                setSelectedSource(null)
                setOnlyLossless(false)
                setOnlyUnplayed(false)
                setOnlyFavs(false)
                setOnlyOffline(false)
              }}
              className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[11px] transition ${
                !selectedSource && !onlyLossless && !onlyUnplayed && !onlyFavs && !onlyOffline
                  ? 'bg-accent/15 font-semibold text-accent'
                  : 'text-muted hover:text-fg'
              }`}
            >
              {t.filterAll}
            </button>

            <button
              type="button"
              onClick={() => setOnlyFavs((v) => !v)}
              className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition ${
                onlyFavs
                  ? 'border-like bg-like font-semibold text-white'
                  : 'border-line text-muted hover:text-fg'
              }`}
            >
              <HeartIcon className="size-3" filled={onlyFavs} />
              <span>{t.favoritesOnly}</span>
            </button>

            {offlineSupported() && !unreachable && (
              <button
                type="button"
                onClick={() => setOnlyOffline((v) => !v)}
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition ${
                  onlyOffline
                    ? 'border-accent bg-accent font-semibold text-accent-fg'
                    : 'border-line text-muted hover:text-fg'
                }`}
              >
                <OfflineIcon className="size-3" filled={onlyOffline} />
                <span>{t.offlineOnly}</span>
              </button>
            )}

            {(['spotify', 'youtube', 'soundcloud', 'deezer', 'apple'] as const).map((source) => (
              <button
                key={source}
                type="button"
                onClick={() => setSelectedSource((cur) => (cur === source ? null : source))}
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition ${
                  selectedSource === source
                    ? 'border-accent/50 bg-accent/15 font-semibold text-accent'
                    : 'border-line text-muted hover:text-fg'
                }`}
              >
                <SourceLogo source={source} className="size-3" />
                <span>{SOURCE_LABEL[source]}</span>
              </button>
            ))}

            <button
              type="button"
              onClick={() => setOnlyLossless((v) => !v)}
              className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition ${
                onlyLossless
                  ? 'border-accent/50 bg-accent/15 font-semibold text-accent'
                  : 'border-line text-muted hover:text-fg'
              }`}
            >
              {t.filterLossless}
            </button>

            <button
              type="button"
              onClick={() => setOnlyUnplayed((v) => !v)}
              className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition ${
                onlyUnplayed
                  ? 'border-accent/50 bg-accent/15 font-semibold text-accent'
                  : 'border-line text-muted hover:text-fg'
              }`}
            >
              {t.filterUnplayed}
            </button>
          </div>
        )}
      </div>

      {/* ---------- ردیف‌های «اخیراً» و قفسه‌های هوشمند ---------- */}
      {/* فقط در تبِ آهنگ‌ها و فقط وقتی هیچ فیلتری روشن نیست: با جستجو یا
          «فقط لایک‌ها» یا فیلترهای سریع این ردیف‌ها مزاحم‌اند نه میان‌بُر */}
      {tab === 'tracks' && !query && !onlyFavs && !onlyOffline && !unreachable && !selectedSource && !onlyLossless && !onlyUnplayed && (
        <div className="space-y-5">
          {recentlyPlayed.length >= 4 && (
            <section className="rise">
              <SectionHead title={t.libraryRecentlyPlayed} hint={t.libraryRecentlyPlayedHint} />
              <Shelf>
                {recentlyPlayed.map((item, i) => (
                  <TrackTile key={item.jobId} item={item} queue={playedQueue} index={i} />
                ))}
              </Shelf>
            </section>
          )}

          {topPlayed.length >= 4 && (
            <section className="rise" style={{ animationDelay: '50ms' }}>
              <SectionHead title={t.libraryTopPlayed} hint={t.libraryTopPlayedHint} />
              <Shelf>
                {topPlayed.map((item, i) => (
                  <TrackTile key={item.jobId} item={item} queue={topPlayedQueue} index={i} />
                ))}
              </Shelf>
            </section>
          )}

          {highEnergy.length >= 4 && (
            <section className="rise" style={{ animationDelay: '80ms' }}>
              <SectionHead title={t.libraryHighEnergy} hint={t.libraryHighEnergyHint} />
              <Shelf>
                {highEnergy.map((item, i) => (
                  <TrackTile key={item.jobId} item={item} queue={highEnergyQueue} index={i} />
                ))}
              </Shelf>
            </section>
          )}

          {calm.length >= 4 && (
            <section className="rise" style={{ animationDelay: '100ms' }}>
              <SectionHead title={t.libraryCalm} hint={t.libraryCalmHint} />
              <Shelf>
                {calm.map((item, i) => (
                  <TrackTile key={item.jobId} item={item} queue={calmQueue} index={i} />
                ))}
              </Shelf>
            </section>
          )}

          {recentlyAdded.length >= 4 && (
            <section className="rise" style={{ animationDelay: '120ms' }}>
              <SectionHead title={t.recentlyDownloaded} hint={t.recentlyDownloadedHint} />
              <Shelf>
                {recentlyAdded.map((item, i) => (
                  <TrackTile key={item.jobId} item={item} queue={addedQueue} index={i} />
                ))}
              </Shelf>
            </section>
          )}
        </div>
      )}

      {/* ---------- محتوا ---------- */}
      {/* بدونِ overflow-hidden: منویِ «⋯» ردیف‌های آخر وگرنه از پایینِ همین
          جعبه بریده می‌شد */}
      <div className="rounded-2xl border border-line-soft bg-panel/50">
        {unreachable && (
          <p className="rounded-t-2xl border-b border-line-soft bg-accent-dim px-4 py-2 text-[11px] text-accent">
            {t.offlineBanner}
          </p>
        )}

        {tab === 'playlists' && (
          <div className="p-4">
            <PlaylistsView
              onOpenLiked={() => {
                setTab('tracks')
                setOnlyFavs(true)
              }}
            />
          </div>
        )}

        {tab === 'tracks' &&
          (listLoading && items.length === 0 ? (
            <div className="flex justify-center py-12">
              <Spinner className="size-5 text-muted-2" />
            </div>
          ) : items.length === 0 ? (
            emptyTracks
          ) : view === 'grid' ? (
            <div className="grid grid-cols-2 gap-1 p-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
              {items.map((item, i) => (
                <TrackTile key={item.jobId} item={item} queue={queue} index={i} className="w-full" />
              ))}
            </div>
          ) : (
            <div className="p-2">
              <RowHeader />
              <AnimatedList className="space-y-0.5">{rows(items)}</AnimatedList>
            </div>
          ))}

        {(tab === 'albums' || tab === 'artists') &&
          (listLoading && items.length === 0 ? (
            <div className="flex justify-center py-12">
              <Spinner className="size-5 text-muted-2" />
            </div>
          ) : openGroup ? (
            <>
              <GroupHero group={openGroup} round={tab === 'artists'} onBack={() => setOpenKey(null)} />
              <AnimatedList className="space-y-0.5 p-2">{rows(openGroup.items)}</AnimatedList>
            </>
          ) : (tab === 'albums' ? albums : artists).length === 0 && !loading ? (
            <EmptyState
              bordered={false}
              icon={
                tab === 'albums' ? <AlbumIcon className="size-5" /> : <ArtistIcon className="size-5" />
              }
              text={
                query
                  ? t.libraryNoMatch
                  : tab === 'albums'
                    ? t.libraryNoAlbums
                    : t.libraryNoArtists
              }
            />
          ) : (
            <div className="grid grid-cols-2 gap-1 p-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
              {(tab === 'albums' ? albums : artists).map((group) => (
                <GroupCard
                  key={group.key}
                  group={group}
                  round={tab === 'artists'}
                  onOpen={openGroupCard}
                />
              ))}
            </div>
          ))}
      </div>
    </div>
  )
}
