import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import BottomFadeScrim from './components/BottomFadeScrim'
import DownloadQueue from './components/DownloadQueue'
import Footer from './components/Footer'
import Header from './components/Header'
import Home from './components/Home'
import OfflineBar from './components/OfflineBar'
import { UpdateBanner } from './components/NativeHealth'
import MoodChat from './components/MoodChat'
import PlayerBar from './components/PlayerBar'
import SearchResults from './components/SearchResults'
import ServerSetup from './components/ServerSetup'
import SetupWizard from './components/SetupWizard'
import Shortcuts from './components/Shortcuts'
import TabBar, { type Tab } from './components/TabBar'
import { AlbumSkeleton, ArtistSkeleton, ResultsSkeleton } from './components/Skeletons'
import EmptyState from './components/EmptyState'
import { RetryIcon, WarnIcon } from './components/icons'
import TelegramLink from './components/TelegramLink'
import Toaster from './components/Toaster'
import { api, API_MODE } from './lib/api'
import { closeTopLayer } from './lib/back'
import { mountLiquidGlass, unmountLiquidGlass } from './lib/liquidGlass'
import { isArtistUrl, isUrl } from './lib/format'
import { onBackButton, onSharedText, onShortcut, takeShortcutRoute, type ShortcutRoute } from './lib/native'
import { useI18n } from './lib/i18n'
import { fetchSetupState } from './lib/setup'
import { isNativeApp, needsSetup } from './lib/server'
import { IntranetError } from './lib/types'
import { useNet } from './store/net'
import type {
  Album,
  AlbumDetail,
  Artist,
  ArtistDetail,
  Playlist,
  SearchResults as Results,
  Track,
} from './lib/types'
import { findBestJob, toPlayItem } from './lib/stream'
import { isDone, useDownloads } from './store/downloads'
import { usePlayer } from './store/player'
import { usePreview } from './lib/usePreview'
import { useRecent } from './store/recent'
import { useSearchHistory } from './store/searchHistory'
import { useSettings } from './store/settings'
import { useTelegram } from './store/telegram'
import { useToasts } from './store/toasts'

/*
 * صفحه‌هایی که فقط با یک کنشِ کاربر باز می‌شوند، جدا بسته‌بندی می‌شوند.
 *
 * سودش روی گوشی است نه دسکتاپ: بازِ کردنِ اپ یعنی تجزیه‌ی کلِ جاوااسکریپت
 * پیش از اولین نقاشی، و روی یک اندرویدِ میان‌رده این چند صد میلی‌ثانیه است.
 * صفحه‌ی خانه — تنها چیزی که همه‌ی کاربرها می‌بینند — دیگر منتظرِ کدِ شناسایی
 * صوتی و نمای کامل پخش و کتابخانه نمی‌ماند.
 *
 * تأخیرِ خودِ باز شدن ناچیز است: داخل اپ، این تکه‌ها روی حافظه‌ی خودِ گوشی‌اند
 * نه پشتِ شبکه — و در مرورگر هم سرویس‌ورکر از قبل کششان کرده.
 */
const AlbumView = lazy(() => import('./components/AlbumView'))
const ArtistView = lazy(() => import('./components/ArtistView'))
const Identify = lazy(() => import('./components/Identify'))
const LibraryView = lazy(() => import('./components/LibraryView'))
const StatsView = lazy(() => import('./components/StatsView'))

type View =
  | { kind: 'home' }
  | { kind: 'results'; query: string }
  | { kind: 'album'; ref: string; from?: string }
  | { kind: 'artist'; ref: string; from?: string }
  | { kind: 'library'; tab?: 'playlists' | 'liked' }
  | { kind: 'stats' }

function viewFromLocation(): View {
  const p = new URLSearchParams(location.search)
  const lib = p.get('library')
  if (lib === 'playlists') return { kind: 'library', tab: 'playlists' }
  if (lib === 'liked') return { kind: 'library', tab: 'liked' }
  if (p.has('library')) return { kind: 'library' }
  if (p.has('stats')) return { kind: 'stats' }
  const artist = p.get('artist')
  if (artist) return { kind: 'artist', ref: artist, from: p.get('q') ?? undefined }
  const url = p.get('url')
  if (url) return { kind: 'album', ref: url, from: p.get('q') ?? undefined }
  const q = p.get('q')
  if (q) return { kind: 'results', query: q }
  return { kind: 'home' }
}

function pushView(view: View, replace = false) {
  const p = new URLSearchParams()
  if (view.kind === 'results') p.set('q', view.query)
  if (view.kind === 'library') p.set('library', view.tab ?? '1')
  if (view.kind === 'stats') p.set('stats', '1')
  if (view.kind === 'album' || view.kind === 'artist') {
    p.set(view.kind === 'album' ? 'url' : 'artist', view.ref)
    if (view.from) p.set('q', view.from)
  }
  const qs = p.toString()
  const url = qs ? `/?${qs}` : '/'
  if (replace) history.replaceState(null, '', url)
  else history.pushState(null, '', url)
}

/**
 * شکستِ بارگذاریِ صفحه‌ی جزئیات (آلبوم/هنرمند/نتایج) — قبلاً همان حالت به
 * اسکلتونِ ابدی ختم می‌شد چون شرطِ رندر فقط «داده نیست» را می‌دید. این،
 * خطا را با «تلاش دوباره» و راهِ فرار به خانه نشان می‌دهد.
 */
export function LoadFailed({
  text,
  onRetry,
  onHome,
}: {
  text: string
  onRetry: () => void
  onHome: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="mx-auto w-full max-w-md">
      <EmptyState icon={<WarnIcon className="size-5 text-warn" />} text={text} />
      <div className="mt-4 flex justify-center gap-3">
        <button
          onClick={onRetry}
          className="flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-accent-fg"
        >
          <RetryIcon className="size-4" />
          {t.retry}
        </button>
        <button
          onClick={onHome}
          className="rounded-full border border-line px-4 py-2 text-sm text-muted hover:text-fg"
        >
          {t.home}
        </button>
      </div>
    </div>
  )
}

export default function App() {
  // در اپ نیتیو تا وقتی ندانیم سرور کجاست، هیچ‌کدام از صفحه‌ها معنا ندارند —
  // همه‌شان یک لیستِ خالی و یک toast خطا نشان می‌دادند
  const [setup, setSetup] = useState(needsSetup)
  /*
   * ویزاردِ راه‌اندازی برای مرورگر (اپ نیتیو `ServerSetup` را دارد).
   *
   * از سرور پرسیده می‌شود نه از localStorage: کلیدها روی سرورند و «آیا تنظیم
   * شده؟» را فقط خودش می‌داند. با همان پرسش، کاربری که از دستگاهِ دیگری یا
   * مرورگرِ دیگری می‌آید هم دوباره دروازه را می‌بیند — که برای یک نصبِ تازه
   * درست‌تر است تا این‌که کلیدها روی یک دستگاه گم شوند.
   */
  const [wizard, setWizard] = useState(false)
  const [view, setView] = useState<View>(viewFromLocation)
  const [results, setResults] = useState<Results | null>(null)
  const [album, setAlbum] = useState<AlbumDetail | null>(null)
  const [artist, setArtist] = useState<ArtistDetail | null>(null)

  const enrichedAlbum = useMemo(() => {
    if (!album) return null
    return {
      ...album,
      tracks: album.tracks.map((t) => ({
        ...t,
        album: t.album || album.title,
        albumId: t.albumId || album.id,
        artworkUrl: t.artworkUrl || album.artworkUrl,
        artistId: t.artistId || (t.artist === album.artist ? album.artistId : undefined),
        artistArtworkUrl: t.artistArtworkUrl || (t.artist === album.artist ? album.artistArtworkUrl : undefined),
      })),
    }
  }, [album])
  const [loading, setLoading] = useState(false)
  // «اسکلت ابدی» — لینکِ آلبومِ حذف‌شده (دیزر ۵۰۲ می‌دهد) یا قطعیِ شبکه،
  // داده را null می‌گذاشت و شرطِ رندر `loading || !data` تا ابد اسکلتون
  // نشان می‌داد: نه خطایی، نه راهِ برگشت. این، پیامِ خطا را نگه می‌دارد تا
  // ویوِ بدون‌داده بتواند EmptyStateِ «تلاش دوباره»دار نشان بدهد
  const [detailError, setDetailError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  // مودالِ شناسایی اینجا زندگی می‌کند نه در هدر، چون نتیجه‌اش همان ردیف‌های
  // ترک است و آن‌ها به پیش‌نمایشِ مشترکِ همین صفحه نیاز دارند
  const [identifying, setIdentifying] = useState(() =>
    new URLSearchParams(location.search).has('identify'),
  )
  const inflight = useRef<AbortController | null>(null)
  const preview = usePreview()
  const pushToast = useToasts((s) => s.push)
  const { t } = useI18n()

  const currentTrackId = usePlayer((s) => s.queue[s.index]?.track?.id)
  const isPlaying = usePlayer((s) => s.playing)
  const playingTrackId = isPlaying ? currentTrackId ?? null : null

  const handlePlayTrack = useCallback(
    (track: Track, contextTracks?: Track[]) => {
      preview.stop()
      if (currentTrackId === track.id) {
        usePlayer.getState().toggle()
        return
      }
      const tracks = contextTracks && contextTracks.length > 0 ? contextTracks : [track]
      const startIndex = Math.max(0, tracks.findIndex((t) => t.id === track.id))
      const quality = useSettings.getState().quality
      const readyJobs = useDownloads.getState().jobs.filter((j) => isDone(j.status))
      const items = tracks.map((t) => {
        const job = findBestJob(readyJobs, t.id, quality)
        return toPlayItem(t, job, quality)
      })
      usePlayer.getState().play(items, startIndex)
    },
    [currentTrackId, preview],
  )

  const navigate = useCallback(
    (next: View, { push = true, replace = false }: { push?: boolean; replace?: boolean } = {}) => {
      if (replace) pushView(next, true)
      else if (push) pushView(next)
      // `pushView` آدرس را از صفر می‌سازد و `?identify` را می‌اندازد؛ مودالِ
      // باز باید هم‌زمان بسته بماند وگرنه صفحه و آدرس از هم واگرا می‌شوند
      setIdentifying(false)
      setView(next)
    },
    [],
  )

  /*
   * دو مقصدِ ثابتِ ناوبری، یک بار ساخته می‌شوند.
   *
   * هدر این‌ها را به `PillNav` می‌دهد و آن‌جا تغییرِ هویتِ آرایه‌ی آیتم‌ها یعنی
   * ساختنِ دوباره‌ی انیمیشن‌ها؛ با تابعِ inline هر رندرِ اپ این کار تکرار می‌شد.
   */
  const goHome = useCallback(() => navigate({ kind: 'home' }), [navigate])
  const goLibrary = useCallback(() => navigate({ kind: 'library' }), [navigate])
  const goLiked = useCallback(() => navigate({ kind: 'library', tab: 'liked' }), [navigate])
  const goStats = useCallback(() => navigate({ kind: 'stats' }), [navigate])
  // هویتِ پایدار: تب‌بار memo است؛ با تابعِ inline هر رندرِ اپ prop عوض
  // می‌شد و memo بی‌اثر. منطق همان: سرچ‌بار در هدر است، با فوکوس باز می‌شود.
  const goSearch = useCallback(() => {
    // سرچ‌بار در هدر است و با فوکوس‌شدن خودش تاریخچه و پیشنهادها را باز می‌کند؛
    // بالا بردنِ صفحه لازم است چون هدر چسبان است ولی زیرش محتوا
    window.scrollTo({ top: 0, behavior: 'smooth' })
    document.querySelector<HTMLInputElement>('[data-search-input]')?.focus()
  }, [])

  /*
   * شناسایی هم مثلِ صفحه‌ها در آدرس می‌نشیند (`?identify=1`): قابلِ بوکمارک،
   * و «عقب»ِ مرورگر اول مودال را می‌بندد (popstate پایین همان را می‌خواند).
   */
  const openIdentify = useCallback(() => {
    setIdentifying(true)
    const p = new URLSearchParams(location.search)
    p.set('identify', '1')
    history.pushState(null, '', `/?${p}`)
  }, [])
  const closeIdentify = useCallback(() => {
    setIdentifying(false)
    const p = new URLSearchParams(location.search)
    if (p.has('identify')) {
      p.delete('identify')
      const qs = p.toString()
      history.replaceState(null, '', qs ? `/?${qs}` : '/')
    }
  }, [])

  useEffect(() => {
    const onPop = () => {
      setView(viewFromLocation())
      // مودالِ شناسایی هم بخشی از تاریخچه است: «عقب» باید اول درِ مودال را
      // ببندد، نه این‌که کلِ صفحه را عوض کند
      setIdentifying(new URLSearchParams(location.search).has('identify'))
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  /*
   * انکسارِ WebGL روی ناوبریِ شناور. ریشه = `.app-shell`؛ نوارِ ناوبری بچه‌ی
   * مستقیم آن است، همان‌طور که رندررِ شیشه لازم دارد. تا قبل از init یا در
   * هر شکستی، همان شیشه‌ی CSS روی صفحه است.
   *
   * refِ callback نه useEffect: ویوِ ویزارد/ستاپ زودهنگام return می‌کند و
   * شل بعداً متولد می‌شود؛ این‌جا mount دقیقاً لحظه‌ی ظاهرشدنِ شل اجرا می‌شود.
   */
  const shellRef = useCallback((el: HTMLDivElement | null) => {
    if (el) void mountLiquidGlass(el)
    else unmountLiquidGlass()
  }, [])

  /*
   * دروازه‌ی راه‌اندازی — فقط مرورگر، فقط مودِ http.
   *
   * اپ نیتیو `ServerSetup` را دارد که سؤالش چیز دیگری است («سرور کجاست؟»)، و
   * در مود دمو هیچ سروری نیست که بشود از کلید پرسید.
   *
   * `?setup=1` بازکردنِ اجباری است — برای وقتی که کاربر می‌خواهد کلیدها را
   * نگاه کند یا چیزی را درست کند.
   */
  useEffect(() => {
    if (API_MODE !== 'http' || isNativeApp()) return
    if (new URLSearchParams(location.search).has('setup')) {
      setWizard(true)
      return
    }
    let alive = true
    void fetchSetupState().then((s) => {
      // null یعنی به سرور نرسیدیم؛ «دروازه را باز نکن» درست‌تر از این است که
      // کاربرِ بدونِ اینترنت پشتِ یک صفحه‌ی تنظیماتِ بی‌نتیجه بماند
      if (alive && s && !s.done) setWizard(true)
    })
    return () => {
      alive = false
    }
  }, [])

  // بات هست یا نه — تا آن موقع دکمه‌های تلگرام اصلاً نشان داده نمی‌شوند، چون
  // دکمه‌ای که کلیکش حتماً به خطا می‌خورد بدتر از نبودنش است. با برگشتن به تب
  // دوباره می‌پرسیم: سرویسِ بات ممکن است بعد از باز شدنِ صفحه بالا آمده باشد و
  // بدون این، دکمه‌ها تا رفرشِ دستی پیدایشان نمی‌شد.
  useEffect(() => {
    const ask = () => void useTelegram.getState().refresh()
    ask()
    window.addEventListener('focus', ask)
    return () => window.removeEventListener('focus', ask)
  }, [])

  // «برو به کتابخانه»ی توستِ پایانِ دانلود. رویداد است نه ایمپورت، چون
  // فرستنده‌اش یک استورِ بی‌خبر از ناوبری است
  useEffect(() => {
    window.addEventListener('unstream:open-library', goLibrary)
    return () => window.removeEventListener('unstream:open-library', goLibrary)
  }, [goLibrary])

  // قلبِ نوارِ پخش → «لایک‌ها». همان الگوی رویداد: PlayerBar استوری است بی‌خبر
  // از ناوبری، پس به‌جای prop گرفتن، فقط اعلام می‌کند و App مسیر را عوض می‌کند
  useEffect(() => {
    window.addEventListener('unstream:open-liked', goLiked)
    return () => window.removeEventListener('unstream:open-liked', goLiked)
  }, [goLiked])

  /*
   * میان‌بُرهایِ لانچر (انگشت‌فشردِ آیکون اپ).
   *
   * دو حالت دارند و هر دو باید کار کنند: اپ *بسته* بوده (اینتنت زودتر از سوار
   * شدنِ رابط رسیده → `takeShortcutRoute`) یا *باز* بوده (رویدادِ `route`).
   * مثلِ اشتراک‌گذاری.
   *
   * مقصدها از همان رویدادهای داخلیِ خودِ کامپوننت‌ها رد می‌شوند — `search` را
   * SearchBar می‌گیرد، `resume` را PlayerBar. این‌جا فقط «کدام» تصمیم گرفته
   * می‌شود، نه «چطور».
   */
  useEffect(() => {
    const apply = (route: ShortcutRoute) => {
      if (!route) return
      if (route === 'search') {
        window.dispatchEvent(new Event('unstream:focus-search'))
      } else if (route === 'liked') {
        goLiked()
      } else {
        // resume: نوارِ پخش را باز می‌کند؛ اگر چیزی در صف نباشد همان خانه می‌ماند
        window.dispatchEvent(new Event('unstream:expand-player'))
      }
    }
    const off = onShortcut(apply)
    void takeShortcutRoute().then(apply)
    return off
  }, [goLiked])

  // بدون این، رفتن به یک آلبوم/هنرمند/نتیجه‌ی جدید همان اسکرولِ صفحه‌ی قبل را
  // نگه می‌داشت — انگار محتوا زیر پایت عوض شده، نه این‌که صفحه‌ی تازه باز شده
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [view])

  const remember = (
    kind: 'artist' | 'album',
    ref: string,
    title: string,
    subtitle: string,
    artworkUrl: string | null,
    id: string,
  ) => useRecent.getState().push({ kind, key: `${kind}:${id}`, title, subtitle, artworkUrl, seed: id, ref })

  // بارگذاری داده بر اساس ویو فعلی
  useEffect(() => {
    inflight.current?.abort()
    preview.stop()

    // خانه، کتابخانه و آمار هیچ‌کدام از این لایه داده نمی‌گیرند
    // (کتابخانه و آمار خودشان fetch می‌کنند چون فیلتر/بازه‌ی درون‌صفحه‌ای دارند)
    if (view.kind === 'home' || view.kind === 'library' || view.kind === 'stats') {
      setLoading(false)
      return
    }

    const ctrl = new AbortController()
    inflight.current = ctrl
    setLoading(true)
    setDetailError(null)

    // صفحه‌ای که واقعاً باز شده و داده‌اش آمده، ارزشِ «ادامه بده» دارد — نه
    // ref‌ای که کاربر تایپ کرده و ۴۰۴ گرفته
    const task =
      view.kind === 'results'
        ? api.search(view.query, ctrl.signal).then((r) => setResults(r))
        : view.kind === 'artist'
          ? api.getArtist(view.ref, ctrl.signal).then((a) => {
              setArtist(a)
              remember('artist', view.ref, a.name, '', a.artworkUrl, a.id)
            })
          : api.getAlbum(view.ref, ctrl.signal).then((a) => {
              setAlbum(a)
              remember('album', view.ref, a.title, a.artist, a.artworkUrl, a.id)
            })

    task
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        // داده‌ی ویوی قبلی باید برود؛ وگرنه بعد از یک درخواست ناموفق، نتیجه‌ی
        // جستجوی قبلی زیر عبارت جدید می‌ماند و انگار همان‌ها جوابِ این‌اند
        if (view.kind === 'results') setResults(null)
        else if (view.kind === 'artist') setArtist(null)
        else setAlbum(null)

        // «اینترنتِ بین‌الملل نیست و این صفحه هم کش نشده بود» خرابی نیست و
        // نباید قرمز نشان داده شود — کاری هم برای «تلاش دوباره» نمانده تا
        // شبکه برنگردد. نوارِ وضعیت همان لحظه بالا می‌آید و بقیه‌ی داستان را
        // می‌گوید.
        if (err instanceof IntranetError) {
          useNet.getState().noteIntranet()
          pushToast(t.intranetPageMissing, 'info')
          setDetailError(t.intranetPageMissing)
          return
        }
        const message = err instanceof Error ? err.message : t.fetchError
        pushToast(message, 'error')
        setDetailError(message)
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false)
      })

    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, reloadKey])

  /**
   * live=true یعنی حین تایپ (debounce شده از SearchBar): نباید تاریخچه ثبت
   * کند و نباید هر ضربه‌کلید یک ورودی جدید در تاریخچه‌ی مرورگر بگذارد —
   * فقط جابه‌جایی اول از یک ویوی غیرِنتایج به نتایج push می‌شود، بقیه replace.
   */
  const submit = (value: string, opts: { live?: boolean } = {}) => {
    if (isArtistUrl(value)) return navigate({ kind: 'artist', ref: value })
    if (isUrl(value)) return navigate({ kind: 'album', ref: value })

    if (!opts.live) {
      // فقط عبارت‌های واقعی جستجوِ صریح تاریخچه می‌شوند؛ نه هر مکثِ حین تایپ
      useSearchHistory.getState().add(value)
      return navigate({ kind: 'results', query: value })
    }

    const alreadyOnResults = view.kind === 'results'
    navigate(
      { kind: 'results', query: value },
      alreadyOnResults ? { replace: true } : { push: true },
    )
  }

  /** عبارت جستجویی که باید موقع «برگشت» به آن برگردیم */
  const searchOrigin = () =>
    view.kind === 'results' ? view.query : 'from' in view ? view.from : undefined

  const openAlbum = (a: Album) =>
    navigate({ kind: 'album', ref: a.sourceUrl || a.id, from: searchOrigin() })

  // پلی‌لیست هم همان قالبِ AlbumDetail را از بک‌اند می‌گیرد (resolve_ref آن را
  // می‌شناسد)، پس همان ویوی «album» را باز می‌کند — بدون این، کلیک روی پلی‌لیست
  // مستقیم به سایتِ منبع می‌رفت و از اپ بیرون می‌انداخت
  const openPlaylist = (p: Playlist) =>
    navigate({ kind: 'album', ref: p.sourceUrl || p.id, from: searchOrigin() })

  const openArtist = (a: Artist) =>
    navigate({ kind: 'artist', ref: a.id, from: searchOrigin() })

  /** صفحه‌ی آرتیست از روی شناسه‌ی خام — کلیک روی نامِ آرتیست در صفحه‌ی آلبوم/موزیک */
  const openArtistRef = (ref: string) =>
    navigate({ kind: 'artist', ref, from: searchOrigin() })

  const back = () => {
    if ((view.kind === 'album' || view.kind === 'artist') && view.from) {
      navigate({ kind: 'results', query: view.from })
    } else {
      history.back()
    }
  }

  // شنونده‌های ناوبری از نمای NowPlaying و مینی‌پلیر
  useEffect(() => {
    const onOpenArtist = (e: Event) => {
      const custom = e as CustomEvent<{ ref?: string }>
      const ref = custom.detail?.ref
      if (!ref) return
      if (ref.startsWith('http') || ref.includes(':artist:') || ref.includes(':user:')) {
        navigate({ kind: 'artist', ref, from: searchOrigin() })
      } else {
        submit(ref)
      }
    }

    const onOpenAlbum = (e: Event) => {
      const custom = e as CustomEvent<{ ref?: string }>
      const ref = custom.detail?.ref
      if (!ref) return
      if (ref.startsWith('http') || ref.includes(':album:') || ref.includes(':playlist:')) {
        navigate({ kind: 'album', ref, from: searchOrigin() })
      } else {
        submit(ref)
      }
    }

    window.addEventListener('unstream:open-artist', onOpenArtist)
    window.addEventListener('unstream:open-album', onOpenAlbum)
    return () => {
      window.removeEventListener('unstream:open-artist', onOpenArtist)
      window.removeEventListener('unstream:open-album', onOpenAlbum)
    }
  }, [navigate])

  /*
   * دکمه‌ی برگشتِ سخت‌افزاری.
   *
   * ترتیبِ اولویت همان چیزی است که کاربرِ اندروید انتظار دارد: اول لایه‌های
   * روی صفحه بسته می‌شوند (شیت، مودال، منو)، بعد ناوبریِ صفحه عقب می‌رود، و
   * فقط روی خانه است که برگشت یعنی «بگذار بروم» — آن هم با کوچک‌کردنِ اپ نه
   * بستنش، وگرنه پخشِ پس‌زمینه با یک ضربه‌ی حواس‌پرت قطع می‌شد.
   *
   * هندلر داخل ref می‌ماند تا شنونده‌ی نیتیو با هر ناوبری برداشته و دوباره
   * ثبت نشود؛ آن رفت‌وبرگشت روی پلِ Capacitor رایگان نیست.
   */
  const backHandler = useRef<() => boolean>(() => false)
  backHandler.current = () => {
    if (closeTopLayer()) return true
    if (view.kind !== 'home') {
      back()
      return true
    }
    return false
  }

  useEffect(() => onBackButton(() => backHandler.current()), [])

  /*
   * «اشتراک‌گذاری» از تلگرام یا مرورگر به آنستریم.
   *
   * متنِ اشتراک‌گذاری‌شده معمولاً لینکِ خالی نیست («این آهنگو گوش کن
   * https://...»)، پس اولین آدرسِ داخلش بیرون کشیده می‌شود. اگر آدرسی نبود،
   * همان متن به جستجو می‌رود — کسی که یک اسمِ آهنگ را share کرده هم منظوری
   * جز همین نداشته.
   */
  useEffect(
    () =>
      onSharedText((text) => {
        const link = text.match(/https?:\/\/\S+/)?.[0]
        const value = link ?? text.trim()
        if (value) submit(value)
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  // پیست کردن لینک در هر جای صفحه
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return
      const text = e.clipboardData?.getData('text')?.trim()
      if (text && isUrl(text)) {
        e.preventDefault()
        submit(text)
      }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  })

  const query = view.kind === 'results' ? view.query : searchOrigin() ?? ''

  /*
   * تبِ فعال از خودِ ویو درمی‌آید نه از یک state جدا: هر مسیرِ دیگری برای رسیدن
   * به کتابخانه (لینک، دکمه‌ی داخلِ خانه، برگشتِ مرورگر) وگرنه ناوبری را با
   * صفحه‌ای که واقعاً باز است ناهماهنگ می‌کرد.
   *
   * آلبوم و هنرمند زیرمجموعه‌ی همان جایی‌اند که از آن آمده‌اند؛ اگر از نتایج
   * آمده باشند «جستجو» تبِ فعالشان می‌ماند. هدر و تب‌بار هر دو از همین یک
   * محاسبه می‌خوانند تا نشود یکی «کتابخانه» را روشن نشان بدهد و آن یکی نه.
   */
  const tab: Tab =
    view.kind === 'library'
      ? 'library'
      : view.kind === 'stats'
        ? 'stats'
        : view.kind === 'results' || ('from' in view && view.from)
          ? 'search'
          : 'home'

  // بستن فقط وقتی معنا دارد که آدرسی از قبل هست؛ در اولین اجرا راهِ فرار
  // نباید باشد، چون پشتِ این صفحه چیزی جز خطا نیست
  if (setup) return <ServerSetup onDone={needsSetup() ? undefined : () => setSetup(false)} />

  // ویزاردِ راه‌اندازی. `onDone` صفحه را نمی‌بندد — خودِ ویزارد بعد از
  // ری‌استارت کل صفحه را رفرش می‌کند؛ این فقط برای حالتِ «دوباره باز کرده‌ام
  // و چیزی نمی‌خواهم عوض کنم» است.
  if (wizard)
    return (
      <SetupWizard
        onDone={() => {
          setWizard(false)
          const p = new URLSearchParams(location.search)
          p.delete('setup')
          const qs = p.toString()
          history.replaceState(null, '', qs ? `/?${qs}` : '/')
        }}
      />
    )

  return (
    <div ref={shellRef} className="app-shell flex flex-col">
      <Header
        onServer={() => setSetup(true)}
        onHome={goHome}
        onLibrary={goLibrary}
        onStats={goStats}
        onIdentify={openIdentify}
        active={tab}
        searchValue={query}
        searchLoading={loading && view.kind === 'results'}
        onSearch={(value, opts) => submit(value, opts)}
      />

      <OfflineBar />

      {/* بنرِ «نسخه‌ی تازه هست» — فقط روی اندروید و فقط وقتی سرور نسخه‌ی
          تازه‌تری از نصبِ فعلی اعلام کرده باشد */}
      <UpdateBanner />

      {/* 5xl نه 6xl: در ۱۴۴۰ پیکسل، ستونِ ۱۱۵۲ پیکسلی دو سویِ ردیف‌های آلبوم/
          هنرمند خلاِ مرده می‌ساخت؛ ۱۰۲۴ تراکمِ سالمی به ردیف‌ها می‌دهد */}
      <main className="px-safe mx-auto w-full max-w-5xl flex-1 pb-12">
        {view.kind === 'home' && (
          <Home
            onOpenRef={(kind, ref) => navigate({ kind, ref })}
            onOpenLibrary={goLibrary}
            onFocusSearch={goSearch}
            onSearch={(query) => submit(query)}
            onIdentify={openIdentify}
          />
        )}

        {/* خانه خودش سکشن‌های خودش را دارد؛ این جعبه فقط برای بقیه‌ی ویوهاست */}
        {view.kind !== 'home' && (
          <section
            key={
              view.kind === 'album'
                ? `album:${view.ref}`
                : view.kind === 'artist'
                  ? `artist:${view.ref}`
                  : view.kind === 'results'
                    ? `results:${view.query}`
                    : view.kind
            }
            className={`page-drill-in ${view.kind === 'library' ? 'pt-8' : 'mt-10'}`}
          >
            {/*
              یک Suspense برای هر سه ویو، نه سه‌تا: هر لحظه فقط یکی‌شان روی صفحه
              است. فالبکش همان اسکلتونی است که موقعِ آمدنِ داده هم نشان داده
              می‌شود، پس گذارِ «تکه‌ی کد» و «داده» به چشم یکی می‌آیند.
            */}
            <Suspense fallback={<ResultsSkeleton />}>
            {view.kind === 'library' && <LibraryView initialTab={view.tab} />}

            {view.kind === 'stats' && <StatsView />}

            {view.kind === 'results' &&
              (loading || !results ? (
                detailError ? (
                  <LoadFailed text={detailError} onRetry={() => setReloadKey((k) => k + 1)} onHome={goHome} />
                ) : (
                  <ResultsSkeleton />
                )
              ) : (
                <SearchResults
                  results={results}
                  playingId={playingTrackId}
                  onTogglePlay={(t) => handlePlayTrack(t, results.tracks)}
                  onOpenAlbum={openAlbum}
                  onOpenArtist={openArtist}
                  onOpenPlaylist={openPlaylist}
                />
              ))}

            {view.kind === 'album' &&
              (loading || !enrichedAlbum ? (
                detailError ? (
                  <LoadFailed text={detailError} onRetry={() => setReloadKey((k) => k + 1)} onHome={goHome} />
                ) : (
                  <AlbumSkeleton />
                )
              ) : (
                <AlbumView
                  album={enrichedAlbum}
                  playingId={playingTrackId}
                  onTogglePlay={(t) => handlePlayTrack(t, enrichedAlbum.tracks)}
                  onOpenAlbum={openAlbum}
                  onOpenArtist={openArtistRef}
                  onBack={back}
                />
              ))}

            {view.kind === 'artist' &&
              (loading || !artist ? (
                detailError ? (
                  <LoadFailed text={detailError} onRetry={() => setReloadKey((k) => k + 1)} onHome={goHome} />
                ) : (
                  <ArtistSkeleton />
                )
              ) : (
                <ArtistView
                  artist={artist}
                  playingId={playingTrackId}
                  onTogglePlay={(t) =>
                    handlePlayTrack(
                      t.artistArtworkUrl ? t : { ...t, artistArtworkUrl: artist.artworkUrl },
                      artist.topTracks.map((tr) => (tr.artistArtworkUrl ? tr : { ...tr, artistArtworkUrl: artist.artworkUrl })),
                    )
                  }
                  onOpenAlbum={openAlbum}
                  onOpenPlaylist={openPlaylist}
                  onOpenArtist={openArtist}
                  onBack={back}
                />
              ))}
            </Suspense>
          </section>
        )}
      </main>

      {identifying && (
        // مودالِ شناسایی فالبک ندارد: تا وقتی کدش نیامده، هیچی بهتر از یک
        // جعبه‌ی خالیِ چشمک‌زن است
        <Suspense fallback={null}>
          <Identify
            onClose={closeIdentify}
            playingId={playingTrackId}
            onTogglePlay={(t) => handlePlayTrack(t)}
          />
        </Suspense>
      )}

      <Footer />

      {/* شیدِ محوِ کف صفحه مطابق BottomFadeScrim در BitChord */}
      <BottomFadeScrim />

      <TabBar
        active={tab}
        onHome={goHome}
        onLibrary={goLibrary}
        onStats={goStats}
        onSearch={goSearch}
      />

      <TelegramLink />
      <Shortcuts />
      <DownloadQueue />
      <MoodChat />
      <PlayerBar />
      <Toaster />
    </div>
  )
}
