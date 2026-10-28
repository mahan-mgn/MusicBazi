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
import { RetryIcon, Spinner, WarnIcon } from './components/icons'
import TelegramLink from './components/TelegramLink'
import Toaster from './components/Toaster'
import { api, API_MODE } from './lib/api'
import { token } from './lib/auth'
import { closeTopLayer } from './lib/back'
import { onIdentityChange } from './lib/identity'
import { mountLiquidGlass, unmountLiquidGlass } from './lib/liquidGlass'
import { isArtistUrl, isUrl } from './lib/format'
import { onBackButton, onSharedText, onShortcut, takeShortcutRoute, type ShortcutRoute } from './lib/native'
import { useI18n } from './lib/i18n'
import { fetchSetupState } from './lib/setup'
import { needsSetup } from './lib/server'
import { IntranetError } from './lib/types'
import { useNet } from './store/net'
import type {
  Album,
  AlbumDetail,
  Artist,
  ArtistDetail,
  Playlist,
  SearchResults as Results,
  Source,
  Track,
  ArtistDiscographyContext,
} from './lib/types'
import { findBestJob, toPlayItem } from './lib/stream'
import { tracksFromSelectedDiscography } from './lib/artistDiscography'
import { pageCache } from './lib/pageCache'
import { pageThemeVars } from './lib/pageTheme'
import { pageThemeSourceOf, useArtworkTheme } from './lib/useArtworkTheme'
import { isDone, useDownloads } from './store/downloads'
import { usePlayer } from './store/player'
import { usePreview } from './lib/usePreview'
import { usePullToRefresh } from './lib/usePullToRefresh'
import { useRecent } from './store/recent'
import { useSearchHistory } from './store/searchHistory'
import { useSettings } from './store/settings'
import { useAuth } from './store/auth'
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
const LoginView = lazy(() => import('./components/LoginView'))
const ProfileView = lazy(() => import('./components/ProfileView'))
const SettingsView = lazy(() => import('./components/SettingsView'))
const StatsView = lazy(() => import('./components/StatsView'))

type View =
  | { kind: 'home' }
  /*
   * `fresh` یعنی «این ویو از یک *جستجوی تازه* آمده، نه از برگشتن به صفحه».
   *
   * تفکیکش لازم است چون هر دو یک `query` دارند: برگشت از آلبوم یا دکمه‌ی
   * مرورگر باید از کش بیاید (بدونِ اسکلتون و بدونِ درخواست)، ولی تایپِ همان
   * عبارت در نوار جستجو یعنی «جوابِ تازه می‌خواهم» و باید واکشی کند.
   * عمداً در URL ذخیره نمی‌شود: `popstate` همان برگشتن است، پس نباید تازه کند.
   */
  | { kind: 'results'; query: string; fresh?: boolean }
  | { kind: 'album'; ref: string; from?: string; artistDiscography?: ArtistDiscographyContext }
  | { kind: 'artist'; ref: string; from?: string }
  | { kind: 'library'; tab?: 'playlists' | 'liked' }
  | { kind: 'stats' }
  | { kind: 'settings' }
  | { kind: 'profile' }

/*
 * هویتِ داده‌ی هر ویو.
 *
 * کلید، همان چیزی است که کش و پرشِ اسکلتون را ممکن می‌کند: بدونِ آن نمی‌شود
 * فهمید «همان صفحه است» یا «صفحه‌ی تازه». `ref` جداست چون کلید پیشوندِ نوع
 * دارد ولی درخواست باید شناسه‌ی خام بگیرد.
 */
interface ActiveKey {
  kind: 'results' | 'artist' | 'album'
  key: string
  ref: string
}

function detailKeyOf(view: View): ActiveKey | null {
  if (view.kind === 'results') return { kind: 'results', key: `results:${view.query}`, ref: view.query }
  if (view.kind === 'artist') return { kind: 'artist', key: `artist:${view.ref}`, ref: view.ref }
  if (view.kind === 'album') return { kind: 'album', key: `album:${view.ref}`, ref: view.ref }
  return null
}

/** داده‌ی یک ویو، همراه با کلیدِ همان داده */
type Loaded =
  | { key: string; kind: 'results'; data: Results }
  | { key: string; kind: 'artist'; data: ArtistDetail }
  | { key: string; kind: 'album'; data: AlbumDetail }

/**
 * داده‌ای که همین حالا باید رندر شود.
 *
 * اگر کلیدِ حالتِ فعلی با ویو نخواند (یعنی ناوبری تازه انجام شده و افکت هنوز
 * نرسیده)، به کش برمی‌گردیم. بدونِ این، یک فریم داده‌ی ویوی *قبلی* روی صفحه‌ی
 * تازه دیده می‌شد — همان «زیرِ پایم عوض شد» که اسکلتون جلویش را می‌گیرد.
 */
function shownDetail(active: ActiveKey | null, detail: Loaded | null): Loaded | null {
  if (!active) return null
  if (detail?.key === active.key) return detail
  if (active.kind === 'results') {
    const data = pageCache.results.read(active.key)
    return data === undefined ? null : { key: active.key, kind: 'results', data }
  }
  if (active.kind === 'artist') {
    const data = pageCache.artist.read(active.key)
    return data === undefined ? null : { key: active.key, kind: 'artist', data }
  }
  const data = pageCache.album.read(active.key)
  return data === undefined ? null : { key: active.key, kind: 'album', data }
}

/** آیا برای این ویو چیزی در کش هست — یعنی شکستِ بعدی نباید صفحه را خالی کند */
function isCached(active: ActiveKey): boolean {
  if (active.kind === 'results') return pageCache.results.read(active.key) !== undefined
  if (active.kind === 'artist') return pageCache.artist.read(active.key) !== undefined
  return pageCache.album.read(active.key) !== undefined
}

function viewFromLocation(): View {
  const p = new URLSearchParams(location.search)
  const lib = p.get('library')
  if (lib === 'playlists') return { kind: 'library', tab: 'playlists' }
  if (lib === 'liked') return { kind: 'library', tab: 'liked' }
  if (p.has('library')) return { kind: 'library' }
  if (p.has('stats')) return { kind: 'stats' }
  if (p.has('settings')) return { kind: 'settings' }
  if (p.has('profile')) return { kind: 'profile' }
  const artist = p.get('artist')
  if (artist) return { kind: 'artist', ref: artist, from: p.get('q') ?? undefined }
  const url = p.get('url')
  if (url) {
    const artistRef = p.get('discArtist')
    const releasesParam = p.get('discReleases')
    const discSource = p.get('discSource')
    let artistDiscography: ArtistDiscographyContext | undefined
    if (artistRef && releasesParam) {
      try {
        const releases = JSON.parse(releasesParam) as ArtistDiscographyContext['releases']
        const source = ['apple', 'deezer', 'soundcloud', 'spotify', 'youtube', 'youtube_music'].includes(discSource ?? '')
          ? (discSource as Source)
          : undefined
        if (Array.isArray(releases) && releases.every((r) => r && typeof r.id === 'string' && typeof r.title === 'string')) {
          artistDiscography = { artistRef, source, releases }
        }
      } catch {
        // Ignore malformed optional navigation context and keep standard album playback.
      }
    }
    return { kind: 'album', ref: url, from: p.get('q') ?? undefined, artistDiscography }
  }
  const q = p.get('q')
  if (q) return { kind: 'results', query: q }
  return { kind: 'home' }
}

function pushView(view: View, replace = false) {
  const p = new URLSearchParams()
  if (view.kind === 'results') p.set('q', view.query)
  if (view.kind === 'library') p.set('library', view.tab ?? '1')
  if (view.kind === 'stats') p.set('stats', '1')
  if (view.kind === 'settings') p.set('settings', '1')
  if (view.kind === 'profile') p.set('profile', '1')
  if (view.kind === 'album' || view.kind === 'artist') {
    p.set(view.kind === 'album' ? 'url' : 'artist', view.ref)
    if (view.from) p.set('q', view.from)
    if (view.kind === 'album' && view.artistDiscography) {
      p.set('discArtist', view.artistDiscography.artistRef)
      if (view.artistDiscography.source) p.set('discSource', view.artistDiscography.source)
      p.set('discReleases', JSON.stringify(view.artistDiscography.releases))
    }
  }
  const qs = p.toString()
  const url = qs ? `/?${qs}` : '/'
  if (replace) history.replaceState(null, '', url)
  else history.pushState(null, '', url)
}

/**
 * «رفرشِ پشتیبانِ بازگشت از گوگل» یک بار در هر نشستِ مرورگر.
 *
 * اگر آن یک‌شات هدر برود، رفرشِ کامل آخرین راه است؛ ولی بدونِ این پرچم، هر
 * بار که `/auth/me` جواب ندهد می‌تواند به حلقه‌ی بی‌پایان تبدیل شود. `session`
 * (نه `local`) چون مرزِ درست همین نشستِ تب است.
 */
const RELOAD_BACKSTOP = 'auth:reloaded'

function takeReloadBackstop(): boolean {
  try {
    if (sessionStorage.getItem(RELOAD_BACKSTOP)) return false
    sessionStorage.setItem(RELOAD_BACKSTOP, '1')
    return true
  } catch {
    // بدونِ storage نمی‌شود حلقه را مهار کرد، پس اصلاً رفرش نمی‌کنیم
    return false
  }
}

/** ورود موفق یعنی دیگر به پشتیبان نیازی نیست؛ نشستِ بعدی حقِ خودش را دارد. */
function releaseReloadBackstop(): void {
  try {
    sessionStorage.removeItem(RELOAD_BACKSTOP)
  } catch {
    // بی‌اهمیت — نهایتش این است که یک رفرشِ اضافه در نشستِ بعد مهار شود
  }
}


const artistDiscographyRequests = new Map<string, Promise<Track[]>>()
const completeArtistDiscographies = new Map<string, Promise<Track[]>>()

function discographyContextKey(context: ArtistDiscographyContext): string {
  return `${context.source ?? ''}:${context.artistRef}:${context.releases.map((release) => release.id).join(',')}`
}

function fetchArtistDiscography(context: ArtistDiscographyContext): Promise<Track[]> {
  const key = discographyContextKey(context)
  const cached = artistDiscographyRequests.get(key)
  if (cached) return cached
  const request = api.getArtistDiscography(context.artistRef).catch((error) => {
    artistDiscographyRequests.delete(key)
    throw error
  })
  artistDiscographyRequests.set(key, request)
  return request
}

async function fetchDiscographyReleaseTracks(
  context: ArtistDiscographyContext,
  selectedTrackId: string,
): Promise<Track[]> {
  const tracks = await fetchCompleteArtistDiscography(context)
  return tracksFromSelectedDiscography(tracks, context.releases, selectedTrackId, context.source)
}

function fetchCompleteArtistDiscography(context: ArtistDiscographyContext): Promise<Track[]> {
  const key = discographyContextKey(context)
  const cached = completeArtistDiscographies.get(key)
  if (cached) return cached

  const request = (async () => {
    let tracks: Track[] = []
    try {
      tracks = await fetchArtistDiscography(context)
    } catch {
      // Fill missing releases individually below.
    }

    const releaseIds = new Set(context.releases.map((release) => release.id))
    const releaseNames = new Map(
      context.releases.map((release) => [release.title.trim().toLocaleLowerCase(), release.id]),
    )
    const releaseIdForTrack = (track: Track) => {
      if (context.source && track.source !== context.source) return undefined
      return (
        (track.source === 'soundcloud' && releaseIds.has(track.id) ? track.id : undefined) ??
        (track.albumId && releaseIds.has(track.albumId) ? track.albumId : undefined) ??
        (track.album ? releaseNames.get(track.album.trim().toLocaleLowerCase()) : undefined)
      )
    }
    if (context.source) tracks = tracks.filter((track) => track.source === context.source)
    const releaseTrackIds = new Map<string, Set<string>>()
    for (const track of tracks) {
      const releaseId = releaseIdForTrack(track)
      if (releaseId) {
        const ids = releaseTrackIds.get(releaseId) ?? new Set<string>()
        ids.add(track.id)
        releaseTrackIds.set(releaseId, ids)
      }
    }

    const required = context.releases.filter(
      (release) => (releaseTrackIds.get(release.id)?.size ?? 0) < Math.max(1, release.trackCount ?? 0),
    )
    if (required.length) {
      const requiredIds = new Set(required.map((release) => release.id))
      const details: Array<Track[]> = new Array(required.length)
      let nextIndex = 0
      const worker = async () => {
        while (nextIndex < required.length) {
          const index = nextIndex++
          try {
            const detail = await api.getAlbum(required[index].id)
            details[index] = context.source && detail.source !== context.source
              ? []
              : detail.tracks.filter((track) => !context.source || track.source === context.source)
          } catch {
            details[index] = []
          }
        }
      }
      await Promise.all(Array.from({ length: Math.min(4, required.length) }, worker))
      tracks = tracks.filter((track) => !requiredIds.has(releaseIdForTrack(track) ?? ''))
      const seen = new Set(tracks.map((track) => track.id))
      for (const releaseTracks of details) {
        for (const track of releaseTracks) {
          if (track.id && !seen.has(track.id)) {
            seen.add(track.id)
            tracks.push(track)
          }
        }
      }
    }

    return tracks
  })().catch((error) => {
    completeArtistDiscographies.delete(key)
    throw error
  })
  completeArtistDiscographies.set(key, request)
  return request
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

  /*
   * صفحه‌ی ورود و پروفایل.
   *
   * ورود اختیاری است، پس `loginOpen` یک لایه است نه گیت: هر وقت کاربر خواست
   * باز می‌شود و با Escape یا «بدون حساب» بسته می‌شود. پروفایل مثل تنظیمات
   * یک ویو است چون آدرس‌پذیر است و دکمه‌ی برگشتِ مرورگر سرِ جایش می‌آوردش.
   *
   * `?login=1` هم خوانده می‌شود چون بازگشت از گوگل با همان پارامتر می‌آید.
   */
  const [loginOpen, setLoginOpen] = useState(() => new URLSearchParams(location.search).has('login'))
  const [view, setView] = useState<View>(viewFromLocation)

  /*
   * «داده‌ی این صفحه دیگر مالِ من نیست».
   *
   * خانه، کتابخانه و آمار داده‌شان را با افکتِ `[]` یک بار از سرور می‌گیرند و
   * کتابخانه، میکسِ روزانه و علاقه‌مندی‌ها همه به حساب گره خورده‌اند. بعدِ
   * ورود، بدونِ این شمارنده همان کتابخانه‌ی مهمان روی صفحه می‌ماند تا کاربر
   * خودش رفرش کند — همان چیزی که گزارش شد.
   *
   * رفرشِ کاملِ سند این را حل می‌کرد ولی پخش را می‌کشت (نوارِ پخش بخشی از
   * همین سند است). با شمارنده، فقط بخشِ صفحه از نو سوار می‌شود: افکت‌هایش
   * دوباره اجرا می‌شوند و داده‌ی تازه می‌آید، ولی صفِ پخش و صدای در حالِ
   * پخش دست‌نخورده می‌مانند.
   */
  const [identityEpoch, setIdentityEpoch] = useState(0)
  useEffect(() => onIdentityChange(() => setIdentityEpoch((n) => n + 1)), [identityEpoch])

  /*
   * یک حالت برای هر سه صفحه‌ی داده‌دار، به‌جای سه `useState` جدا.
   *
   * هر بار داده همراه کلیدش ذخیره می‌شود، پس موقعِ ناوبری می‌شود فهمید این
   * داده مالِ *همین* صفحه است یا صفحه‌ی قبلی — و آن‌چه رندر می‌شود همیشه با
   * ویوی فعلی می‌خواند (پایین‌تر: `shownDetail`).
   */
  const [detail, setDetail] = useState<Loaded | null>(null)

  const active = detailKeyOf(view)
  /*
   * `shown` ممُو می‌شود چون `active` با هر رندر یک شیءِ تازه است ولی هویتش
   * عوض نشده. بدونِ آن، هر رندرِ اپ (هر تیکِ پخش) داده‌ی کش‌شده را از نو
   * می‌ساخت و لیستِ نتیجه‌ها را بی‌دلیل از نو رندر می‌کرد.
   */
  const shown = useMemo(
    () => shownDetail(active, detail),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [active?.key, active?.kind, detail],
  )
  const results = shown?.kind === 'results' ? shown.data : null
  const artist = shown?.kind === 'artist' ? shown.data : null
  const album = shown?.kind === 'album' ? shown.data : null

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

  /*
   * تمِ پس‌زمینه‌ی تمام‌صفحه.
   *
   * این‌جا حساب می‌شود و نه داخلِ خودِ ویو، چون لایه‌ی پس‌زمینه در شل و بیرونِ
   * `<main>` می‌نشیند: ریشه‌ی ویو داخلِ ستونِ `max-w-5xl` است و هر پس‌زمینه‌ای
   * که بگیرد ستون‌های کناری را نمی‌پوشاند. App خودش همین حالا `artist` و
   * `enrichedAlbum` را دارد و همان‌ها را به ویوها می‌دهد، پس تم مشتق از همان
   * داده است — بدونِ storeِ جهانی و بدونِ خطرِ نشتِ رنگِ صفحه‌ی قبلی.
   *
   * `useArtworkTheme` روی مسیرِ گرم (`peekArtworkColor`) رنگ را سنکرون می‌دهد،
   * پس بازگشتِ دوباره به یک صفحه فریمِ خاکستری ندارد.
   */
  const themed = pageThemeSourceOf(view, artist, enrichedAlbum)
  const shellTheme = useArtworkTheme(themed?.src ?? null, themed?.seed ?? '')
  const shellTint = useMemo(() => pageThemeVars(shellTheme), [shellTheme])

  const [loading, setLoading] = useState(false)
  /*
   * «نتیجه‌های تازه در راه است» — جدا از `loading`.
   *
   * `loading` فقط وقتی روشن می‌شود که صفحه چیزی برای نشان‌دادن ندارد (وگرنه
   * اسکلتون روی محتوای درست می‌افتاد). ولی سرِ جستجوی تازه، کاربر باید بفهمد
   * درخواستش در جریان است حتی وقتی نتایجِ کش‌شده‌ی همان عبارت روی صفحه است —
   * وگرنه تا آمدنِ جواب، صفحه بی‌واکنش به‌نظر می‌رسد. فقط اسپینرِ نوار جستجو
   * را روشن می‌کند، نه اسکلتونِ صفحه.
   */
  const [searching, setSearching] = useState(false)
  // «اسکلت ابدی» — لینکِ آلبومِ حذف‌شده (دیزر ۵۰۲ می‌دهد) یا قطعیِ شبکه،
  // داده را null می‌گذاشت و شرطِ رندر `loading || !data` تا ابد اسکلتون
  // نشان می‌داد: نه خطایی، نه راهِ برگشت. این، پیامِ خطا را نگه می‌دارد تا
  // ویوِ بدون‌داده بتواند EmptyStateِ «تلاش دوباره»دار نشان بدهد
  const [detailError, setDetailError] = useState<string | null>(null)
  /*
   * `reloadKey` از یک کنشِ *صریح* می‌آید (pull-to-refresh یا «تلاش دوباره»)
   * و به همین دلیل از افکتِ خودکار جدا نگه داشته می‌شود: ناوبریِ معمولی هم
   * افکت را اجرا می‌کند، ولی نه به‌عنوان درخواستِ کاربر.
   */
  const [reloadKey, setReloadKey] = useState(0)
  /** مقدارِ `reloadKey` در آخرین اجرای افکت — تا «صریح» را از «ناوبری» جدا کنیم */
  const seenReload = useRef(reloadKey)
  /** درخواستِ نمایشِ داده — فقط برای این‌که نتیجه‌اش روی ویوی رفته اعمال نشود */
  const pageAbort = useRef<AbortController | null>(null)

  // مودالِ شناسایی اینجا زندگی می‌کند نه در هدر، چون نتیجه‌اش همان ردیف‌های
  // ترک است و آن‌ها به پیش‌نمایشِ مشترکِ همین صفحه نیاز دارند
  const [identifying, setIdentifying] = useState(() =>
    new URLSearchParams(location.search).has('identify'),
  )
  const preview = usePreview()
  const pushToast = useToasts((s) => s.push)

  const currentTrackId = usePlayer((s) => s.queue[s.index]?.track?.id)
  const isPlaying = usePlayer((s) => s.playing)
  const playingTrackId = isPlaying ? currentTrackId ?? null : null

  const handlePlayTrack = useCallback(
    (track: Track, contextTracks?: Track[], artistDiscography?: ArtistDiscographyContext) => {
      preview.stop()
      const tracks = contextTracks && contextTracks.length > 0 ? contextTracks : [track]
      const startIndex = Math.max(0, tracks.findIndex((t) => t.id === track.id))
      const player = usePlayer.getState()
      if (artistDiscography) player.setShuffle(false)
      if (currentTrackId === track.id) {
        player.toggle()
      } else {
        const quality = useSettings.getState().quality
        const readyJobs = useDownloads.getState().jobs.filter((j) => isDone(j.status))
        const items = tracks.map((t) => {
          const job = findBestJob(readyJobs, t.id, quality, t)
          return toPlayItem(t, job, quality)
        })
        player.play(items, startIndex)
      }

      if (artistDiscography) {
        void fetchDiscographyReleaseTracks(artistDiscography, track.id).then((remainingTracks) => {
          if (!remainingTracks.length) return
          const activeTrackId = usePlayer.getState().queue[usePlayer.getState().index]?.track.id
          const activeIndex = remainingTracks.findIndex((item) => item.id === activeTrackId)
          if (activeIndex < 0) return

          const quality = useSettings.getState().quality
          const readyJobs = useDownloads.getState().jobs.filter((job) => isDone(job.status))
          const items = remainingTracks.slice(activeIndex).map((item) => {
            const job = findBestJob(readyJobs, item.id, quality, item)
            return toPlayItem(item, job, quality)
          })
          usePlayer.getState().replaceQueue(items, 0)
        }).catch(() => {})
      }
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
  const goSettings = useCallback(() => navigate({ kind: 'settings' }), [navigate])
  const goProfile = useCallback(() => navigate({ kind: 'profile' }), [navigate])
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
      setWizard(new URLSearchParams(location.search).has('setup'))
      setLoginOpen(new URLSearchParams(location.search).has('login'))
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  /*
   * بازگشت از گوگل.
   *
   * توکن در `#auth=...` می‌آید نه در query: fragment به سرور نمی‌رود، پس در
   * لاگِ nginx و در `Referer` نمی‌نشیند. بلافاصله بعدِ خواندن پاک می‌شود تا در
   * نوار آدرس نماند و با رفرش دوباره خرج نشود.
   *
   * این‌جا **منتظرِ نتیجه** می‌مانیم (برخلافِ `void`ِ قبلی): این یک‌شات است و
   * اگر پروفایل نیامد، باید بفهمیم تا پشتیبانِ پایین‌تر عمل کند. خودِ استور
   * داخلش یک تلاشِ دوباره می‌کند.
   */
  useEffect(() => {
    const match = /auth=([^&]+)/.exec(location.hash)
    if (!match) return
    const value = decodeURIComponent(match[1])
    history.replaceState(null, '', location.pathname + location.search)
    if (!value) return
    void useAuth.getState().adoptToken(value).then((ok) => {
      if (ok) {
        releaseReloadBackstop()
        return
      }
      /*
       * پشتیبانِ آخر.
       *
       * توکن نشسته ولی پروفایلش نیامده — یعنی مسیرِ یک‌شاتِ بازگشت هدر رفته
       * و تا رفرشِ دستی `user` خالی می‌ماند. یک رفرشِ کامل همان چیزی است که
       * کاربر را نجات می‌دهد: بوتِ بعدی دوباره `/auth/me` را می‌پرسد و این‌بار
       * جواب می‌گیرد. (خودِ هش پیش از این پاک شده، پس بعدِ رفرش این افکت اصلاً
       * اجرا نمی‌شود؛ پرچم برای همان حالتِ نامحتملِ باقی‌ماندنِ هش است.)
       */
      if (!takeReloadBackstop()) return
      location.reload()
    })
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
   * دروازه‌ی راه‌اندازی — فقط در مودِ http.
   *
   * در اپ نیتیو تا وقتی سرور مشخص نشده (`needsSetup`) ابتدا ServerSetup پاسخ داده می‌شود.
   * پس از اتصال یا در مرورگر، اگر ستاپ هنوز کامل نباشد یا `?setup=1` در آدرس باشد،
   * ویزارد باز می‌شود.
   *
   * **وابسته به `user?.id`:** ستاپ حالا personal است، پس پاسخِ سرور برای هر
   * حساب فرق دارد. اثر باید بعدِ ثبت‌نام یا ورودِ گوگل دوباره اجرا شود — وگرنه
   * کاربرِ تازه همان `done`ِ مهمان را می‌دید و ویزاردش هرگز باز نمی‌شد.
   */
  const userId = useAuth((s) => s.user?.id ?? null)
  useEffect(() => {
    if (API_MODE !== 'http' || needsSetup()) return
    if (new URLSearchParams(location.search).has('setup')) {
      setWizard(true)
      return
    }
    // ویزاردِ بازِ کاربر را با هر رندر دوباره باز نکن؛ بستنش تصمیمِ کاربر است
    if (wizard) return
    let alive = true
    void fetchSetupState().then((s) => {
      // null یعنی به سرور نرسیدیم؛ «دروازه را باز نکن» درست‌تر از این است که
      // کاربرِ بدونِ اینترنت پشتِ یک صفحه‌ی تنظیماتِ بی‌نتیجه بماند
      if (alive && s && !s.done) setWizard(true)
    })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  /*
   * پروفایلِ ذخیره‌شده و راه‌های ورود.
   *
   * هر دو در پس‌زمینه‌اند و هیچ‌کدام رندر را بلوکه نمی‌کنند: توکن از
   * `localStorage` می‌آید (همگام) و واسط کاربری همان‌جا با پروفایلِ خالی رسم
   * می‌شود. منتظر ماندن یعنی کاربرِ آفلاین تا تایم‌اوت یک صفحه‌ی سفید ببیند.
   *
   * `providers` تا رسیدنش `google: false` است، پس دکمه‌ی گوگل یک لحظه غیرفعال
   * دیده می‌شود و بعد روشن — بهتر از دکمه‌ای که هست و کار نمی‌کند.
   */
  useEffect(() => {
    void useAuth.getState().refresh()
    void api
      .authProviders()
      .then((p) => useAuth.setState({ providers: p }))
      .catch(() => {
        // سرور قدیمی یا مود دمو: گوگل نیست، حساب محلی هست
      })
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

  /*
   * همان الگوی تلگرام، برای حساب کاربری.
   *
   * hydrationِ حساب فقط یک بار سرِ بوت (`[]`) اجرا می‌شد؛ بعد از آن اگر توکن
   * نشسته بود ولی پروفایلش نیامده بود، هیچ‌چیز دوباره تلاش نمی‌کرد و تا رفرشِ
   * دستی تاپ‌بار «مهمان» می‌ماند. برگشتن به تب (یا زنده شدن از bfcache) دقیقاً
   * همان لحظه‌ای است که شبکه و تمرکزِ کاربر برگشته‌اند.
   */
  useEffect(() => {
    const again = () => {
      const state = useAuth.getState()
      if (token() && !state.user && !state.loading) void state.refresh()
    }
    window.addEventListener('focus', again)
    window.addEventListener('pageshow', again)
    document.addEventListener('visibilitychange', again)
    return () => {
      window.removeEventListener('focus', again)
      window.removeEventListener('pageshow', again)
      document.removeEventListener('visibilitychange', again)
    }
  }, [])


  // «برو به کتابخانه»ی توستِ پایانِ دانلود. رویداد است نه ایمپورت، چون
  // فرستنده‌اش یک استورِ بی‌خبر از ناوبری است
  useEffect(() => {
    window.addEventListener('musicbazi:open-library', goLibrary)
    return () => window.removeEventListener('musicbazi:open-library', goLibrary)
  }, [goLibrary])

  // قلبِ نوارِ پخش → «لایک‌ها». همان الگوی رویداد: PlayerBar استوری است بی‌خبر
  // از ناوبری، پس به‌جای prop گرفتن، فقط اعلام می‌کند و App مسیر را عوض می‌کند
  useEffect(() => {
    window.addEventListener('musicbazi:open-liked', goLiked)
    return () => window.removeEventListener('musicbazi:open-liked', goLiked)
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
        window.dispatchEvent(new Event('musicbazi:focus-search'))
      } else if (route === 'liked') {
        goLiked()
      } else {
        // resume: نوارِ پخش را باز می‌کند؛ اگر چیزی در صف نباشد همان خانه می‌ماند
        window.dispatchEvent(new Event('musicbazi:expand-player'))
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

  /*
   * بارگذاریِ داده‌ی یک صفحه.
   *
   * تنها راهِ رسیدن به داده است — هم افکتِ خودکار و هم pull-to-refresh از این
   * رد می‌شوند. یک بدنه‌ی مشترک، چون تفاوتِ آن دو فقط *چه‌وقت* است نه *چه*.
   *
   * سه رفتار، بر اساسِ این‌که صفحه‌ی تازه است یا از قبل دیده شده:
   *   • صفحه‌ی تازه      → اسکلتون، واکشی، نمایش.
   *   • صفحه‌ی کش‌شده    → همان محتوا فوراً، و درخواستِ تازه در پس‌زمینه.
   *   • نتایجِ جستجو     → فقط با کنشِ صریح؛ ورودِ دوباره درخواستی نمی‌فرستد.
   */
  const revalidate = useCallback(
    async (target: ActiveKey, explicit: boolean): Promise<void> => {
      const hasData = isCached(target)

      /*
       * نتایجِ جستجو فقط با کنشِ صریح دوباره خوانده می‌شود — خواسته‌ی صریحِ
       * کارفرما: هر بار وارد شدن به صفحه‌ی نتایج نباید دوباره لود کند.
       * (آرتیست و آلبوم سرِ هر ورود تازه می‌شوند، در پس‌زمینه.)
       */
      if (target.kind === 'results' && !explicit && hasData) {
        setLoading(false)
        setSearching(false)
        return
      }

      // درخواستِ قبلی اگر هنوز تمام نشده، دیگر به‌کار نمی‌آید — نتیجه‌اش به صفحه‌ی
      // دیگری تعلق داشت. خودِ درخواستِ شبکه کش نمی‌شود (سیگنالش مالِ خطِ کش
      // است)؛ فقط این مصرف‌کننده از اعمالِ نتیجه منصرف می‌شود.
      pageAbort.current?.abort()
      const ctrl = new AbortController()
      pageAbort.current = ctrl
      // اسکلتون فقط وقتی چیزی برای نشان‌دادن نیست — نه برای تازه‌سازیِ پس‌زمینه.
      // وگرنه روی هر ورودِ دوباره، صفحه‌ای که کامل بود خالی می‌شد و برمی‌گشت.
      if (!hasData) setLoading(true)
      // اسپینرِ نوار جستجو سرِ هر جستجوی تازه — حتی وقتی نتایجِ کش‌شده روی
      // صفحه‌اند. `explicit` شاملِ pull-to-refresh هم می‌شود و آنجا نشانگرِ
      // خودش بالای صفحه است، پس فقط برای نتایج معنا دارد.
      if (target.kind === 'results') setSearching(true)
      setDetailError(null)

      /*
       * صفحه‌ای که واقعاً باز شده و داده‌اش آمده، ارزشِ «ادامه بده» دارد — نه
       * ref‌ای که کاربر تایپ کرده و ۴۰۴ گرفته.
       *
       * سیگنال از خودِ خط می‌آید نه از `ctrl`: درخواستِ کش‌شده می‌تواند بین دو
       * مصرف‌کننده مشترک باشد، و اگر `ctrl` را می‌دادیم، پاک‌سازیِ افکت (که با
       * هر ناوبری و در StrictMode دوبار اجرا می‌شود) درخواستِ مشترک را می‌کشت.
       * `ctrl` فقط برای این است که نتیجه‌ی ویوی رفته را *اعمال نکنیم*.
       */
      const task: Promise<Loaded> =
        target.kind === 'results'
          ? pageCache.results
              .load(target.key, (signal) => api.search(target.ref, signal))
              .then((data) => ({ key: target.key, kind: 'results' as const, data }))
          : target.kind === 'artist'
            ? pageCache.artist
                .load(target.key, (signal) => api.getArtist(target.ref, signal))
                .then((data) => ({ key: target.key, kind: 'artist' as const, data }))
            : pageCache.album
                .load(target.key, (signal) => api.getAlbum(target.ref, signal))
                .then((data) => ({ key: target.key, kind: 'album' as const, data }))

      try {
        const loaded = await task
        if (ctrl.signal.aborted) return
        setDetail(loaded)
        // فقط سرِ بارِ اول؛ تازه‌سازیِ پس‌زمینه نباید «اخیرها» را هر بار جلو بیندازد
        if (hasData) return
        if (loaded.kind === 'artist') {
          remember('artist', target.ref, loaded.data.name, '', loaded.data.artworkUrl, loaded.data.id)
        } else if (loaded.kind === 'album') {
          remember('album', target.ref, loaded.data.title, loaded.data.artist, loaded.data.artworkUrl, loaded.data.id)
        }
      } catch (err: unknown) {
        if (ctrl.signal.aborted) return
        if (err instanceof DOMException && err.name === 'AbortError') return
        if (err instanceof IntranetError) useNet.getState().noteIntranet()

        /*
         * محتوایی که روی صفحه است نباید با شکستِ تازه‌سازیِ پس‌زمینه پاک شود —
         * کاربر دارد می‌خواندش. فقط کنشِ صریح توست می‌گیرد؛ شکستِ خودکارِ
         * آفلاین هر بار توست می‌داد و نوارِ وضعیت (OfflineBar) از قبل هست.
         */
        // ترجمه‌ها از استور خوانده می‌شوند نه از کلوژرِ رندر: این callback با
        // دپ‌آرِیِ خالی ساخته می‌شود تا هویتش پایدار بماند (افکت به آن وابسته
        // است و عوض‌شدنش افکت را بی‌دلیل دوباره اجرا می‌کرد)، پس `t`ِ بسته‌شده
        // می‌توانست زبانِ قدیمی را نگه دارد.
        const tr = useI18n.getState().t
        if (hasData) {
          if (explicit) pushToast(err instanceof Error ? err.message : tr.fetchError, 'error')
          return
        }

        // داده‌ی ویوی قبلی باید برود؛ وگرنه بعد از یک درخواست ناموفق، نتیجه‌ی
        // جستجوی قبلی زیر عبارت جدید می‌ماند و انگار همان‌ها جوابِ این‌اند
        setDetail(null)

        // «اینترنتِ بین‌الملل نیست و این صفحه هم کش نشده بود» خرابی نیست و
        // نباید قرمز نشان داده شود — کاری هم برای «تلاش دوباره» نمانده تا
        // شبکه برنگردد. نوارِ وضعیت همان لحظه بالا می‌آید و بقیه‌ی داستان را
        // می‌گوید.
        if (err instanceof IntranetError) {
          pushToast(tr.intranetPageMissing, 'info')
          setDetailError(tr.intranetPageMissing)
          return
        }
        const message = err instanceof Error ? err.message : tr.fetchError
        pushToast(message, 'error')
        setDetailError(message)
      } finally {
        if (!ctrl.signal.aborted) {
          setLoading(false)
          setSearching(false)
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  /*
   * افکتِ بارگذاری — به‌ازای هر ویو (و هر کنشِ صریح) یک بار.
   *
   * `view` عمداً در دپ‌آرِی هست هرچند شیءِ تازه است: باید سرِ هر ناوبری اجرا شود،
   * چون آرتیست و آلبوم همان لحظه تازه‌سازیِ پس‌زمینه می‌خواهند.
   */
  useEffect(() => {
    preview.stop()

    // خانه، کتابخانه، آمار و تنظیمات هیچ‌کدام از این لایه داده نمی‌گیرند
    // (کتابخانه و آمار خودشان fetch می‌کنند چون فیلتر/بازه‌ی درون‌صفحه‌ای دارند؛
    // تنظیمات فقط از استور و چند اندپوینت وضعیت می‌خواند)
    const target = detailKeyOf(view)
    if (!target) {
      setLoading(false)
      setSearching(false)
      return
    }

    // `reloadKey` به‌معنیِ «کاربر خودش خواست» است، نه «ویو عوض شد».
    //
    // فقط *تغییرش* نشانه است نه مقدارش، و چون افکت با هر ناوبری هم اجرا
    // می‌شود، مقایسه با مقدارِ دیده‌شده‌ی قبلی همان تفاوت را می‌سازد.
    const explicit = seenReload.current !== reloadKey
    seenReload.current = reloadKey

    // جستجوی تازه هم «صریح» است: کاربر همین حالا در نوار جستجو چیزی نوشت و
    // Enter زد (یا عبارتی از تاریخچه را انتخاب کرد)، پس نباید جوابِ کش‌شده را
    // ببیند. `view.fresh` فقط روی ویوهای آمده از نوار جستجو می‌نشیند — برگشت
    // از آلبوم و `popstate` آن را ندارند و همان مسیرِ کش را می‌روند.
    const freshSearch = view.kind === 'results' && view.fresh === true
    void revalidate(target, explicit || freshSearch)
    return () => pageAbort.current?.abort()
  }, [view, reloadKey, revalidate])

  /*
   * کشیدنِ صفحه به پایین.
   *
   * روی `revalidate` صبر می‌کند تا اسپینرِ pull-to-refresh واقعاً تا پایانِ
   * درخواست بچرخد — با `setReloadKey` صدا زدن و برگشتن، اسپینر یک فریم
   * می‌درخشید و خاموش می‌شد و کاربر فکر می‌کرد چیزی تازه نشد.
   */
  const handleRefresh = useCallback(async () => {
    if (view.kind === 'home') {
      window.dispatchEvent(new Event('musicbazi:refresh-home'))
      return
    }
    if (view.kind === 'library') {
      window.dispatchEvent(new Event('musicbazi:refresh-library'))
      return
    }
    const target = detailKeyOf(view)
    if (target) await revalidate(target, true)
  }, [view, revalidate])

  const { pullDistance, refreshing } = usePullToRefresh(handleRefresh)

  /**
   * live=true یعنی حین تایپ (debounce شده از SearchBar): نباید تاریخچه ثبت
   * کند و نباید هر ضربه‌کلید یک ورودی جدید در تاریخچه‌ی مرورگر بگذارد —
   * فقط جابه‌جایی اول از یک ویوی غیرِنتایج به نتایج push می‌شود، بقیه replace.
   *
   * هر دو مسیر `fresh: true` می‌گذارند: این تابع یعنی «کاربر در نوار جستجو
   * دنبال چیزی گشت»، و نتیجه‌اش باید تازه از سرور بیاید — نه از کشِ همان
   * عبارت که از دفعه‌ی قبل مانده. بارگذاریِ کش فقط برای *برگشتن* به صفحه‌ی
   * نتایج است (دکمه‌ی برگشت، `popstate`، دکمه‌ی مرورگر) که از این تابع رد نمی‌شود.
   */
  const submit = (value: string, opts: { live?: boolean } = {}) => {
    if (isArtistUrl(value)) return navigate({ kind: 'artist', ref: value })
    if (isUrl(value)) return navigate({ kind: 'album', ref: value })

    if (!opts.live) {
      // فقط عبارت‌های واقعی جستجوِ صریح تاریخچه می‌شوند؛ نه هر مکثِ حین تایپ
      useSearchHistory.getState().add(value)
      /*
       * ارسالِ دوباره‌ی همان عبارت.
       *
       * ناوبریِ دوباره همان آدرس را push می‌کرد و یک ورودیِ تکراری در تاریخچه‌ی
       * مرورگر می‌ساخت (و «برگشت» دو بار لازم می‌شد). `reloadKey` همان اثر را
       * دارد — افکت را دوباره اجرا می‌کند — بدونِ دست‌زدن به تاریخچه.
       */
      if (view.kind === 'results' && view.query === value) {
        setReloadKey((k) => k + 1)
        return
      }
      return navigate({ kind: 'results', query: value, fresh: true })
    }

    const alreadyOnResults = view.kind === 'results'
    navigate(
      { kind: 'results', query: value, fresh: true },
      alreadyOnResults ? { replace: true } : { push: true },
    )
  }

  /** عبارت جستجویی که باید موقع «برگشت» به آن برگردیم */
  const searchOrigin = () =>
    view.kind === 'results' ? view.query : 'from' in view ? view.from : undefined

  const openAlbum = (a: Album, artistDiscography?: ArtistDiscographyContext) => {
    if (artistDiscography) void fetchCompleteArtistDiscography(artistDiscography).catch(() => {})
    navigate({ kind: 'album', ref: a.sourceUrl || a.id, from: searchOrigin(), artistDiscography })
  }

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

    window.addEventListener('musicbazi:open-artist', onOpenArtist)
    window.addEventListener('musicbazi:open-album', onOpenAlbum)
    return () => {
      window.removeEventListener('musicbazi:open-artist', onOpenArtist)
      window.removeEventListener('musicbazi:open-album', onOpenAlbum)
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
   * «اشتراک‌گذاری» از تلگرام یا مرورگر به موزیک بازی.
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
  const tab: Tab | undefined =
    view.kind === 'library'
      ? 'library'
      : view.kind === 'stats'
        ? 'stats'
        : view.kind === 'settings' || view.kind === 'profile'
          ? // تنظیمات و پروفایل هیچ‌کدام از چهار مقصدِ ناوبری نیستند؛
            // «هیچ‌کدام» را با `undefined` می‌گوییم تا نه تب‌بار تبی را روشن
            // نشان بدهد و نه هدر قرصی را — وگرنه کاربر فکر می‌کند در «خانه» است
            undefined
          : view.kind === 'results' || ('from' in view && view.from)
            ? 'search'
            : 'home'

  // بستن فقط وقتی معنا دارد که آدرسی از قبل هست؛ در اولین اجرا راهِ فرار
  // نباید باشد، چون پشتِ این صفحه چیزی جز خطا نیست
  if (setup) return <ServerSetup onDone={needsSetup() ? undefined : () => setSetup(false)} />

  // ویزاردِ راه‌اندازی. بستنش فقط `wizard` را خاموش می‌کند؛ مقدارها همان لحظه
  // در دیتابیس نشسته‌اند و درخواستِ بعدی زنده خوانده می‌شوند — ری‌استارتی نیست.
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
        onServer={() => {
          setWizard(false)
          setSetup(true)
        }}
      />
    )

  /*
   * صفحه‌ی ورود، بیرونِ پوسته. مثل ویزارد زودهنگام return می‌کند چون تاپ‌بار
   * و تب‌بار روی صفحه‌ای که هنوز کاربری نیست فقط حواس‌پرتی‌اند.
   */
  if (loginOpen)
    return (
      <Suspense fallback={<div className="min-h-dvh" />}>
        <LoginView
          onDone={() => {
            setLoginOpen(false)
            // پارامتر از آدرس پاک می‌شود تا رفرش دوباره صفحه‌ی ورود را باز نکند
            const p = new URLSearchParams(location.search)
            p.delete('login')
            const qs = p.toString()
            history.replaceState(null, '', qs ? `/?${qs}` : '/')
          }}
        />
      </Suspense>
    )

  return (
    <div
      ref={shellRef}
      className="app-shell tint-scope flex flex-col"
      data-page-tint={themed ? '' : undefined}
      /*
       * استایل عمداً روی صفحه‌های بی‌تم گذاشته *نمی‌شود*: `@property`ها
       * `initial-value` خاکستری دارند و اگر روی خانه هم بنشینند، گذارِ
       * خانه→هنرمند از یک خاکستریِ کور شروع می‌شود. نبودشان یعنی
       * `--page-*` به مقدارِ `--bg` می‌افتد و `data-page-tint` هم `opacity`
       * را صفر نگه می‌دارد — یعنی همان رفتارِ امروز.
       */
      style={themed ? shellTint : undefined}
    >
      {/*
       * پس‌زمینه‌ی تمام‌صفحه. اولین فرزند است و `z-index: -1` دارد؛
       * `isolation: isolate` روی `.app-shell` نمی‌گذارد از شل بیرون بزند و
       * زیرِ `background`ِ `body` گم شود. جزئیات در index.css → .page-tint.
       */}
      <div aria-hidden className="page-tint" />
      <Header
        onServer={() => setSetup(true)}
        onSetup={() => {
          setWizard(true)
          const p = new URLSearchParams(location.search)
          p.set('setup', '1')
          history.pushState(null, '', `/?${p}`)
        }}
        onHome={goHome}
        onLibrary={goLibrary}
        onStats={goStats}
        onIdentify={openIdentify}
        onSettings={goSettings}
        onProfile={goProfile}
        onLogin={() => setLoginOpen(true)}
        active={tab}
        searchValue={query}
        searchLoading={searching || (loading && view.kind === 'results')}
        onSearch={(value, opts) => submit(value, opts)}
      />

      <OfflineBar />

      {/* بنرِ «نسخه‌ی تازه هست» — فقط روی اندروید و فقط وقتی سرور نسخه‌ی
          تازه‌تری از نصبِ فعلی اعلام کرده باشد */}
      <UpdateBanner />

      {/* نشانگر Pull-to-Refresh در بالای صفحه */}
      {(pullDistance > 0 || refreshing) && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed top-[calc(var(--header-h)+0.5rem)] inset-x-0 z-40 flex justify-center transition-transform"
          style={{ transform: `translateY(${Math.min(pullDistance, 48)}px)` }}
        >
          <div className="grid size-8 place-items-center rounded-full border border-line bg-panel/95 text-accent shadow-lg backdrop-blur-md">
            {refreshing ? (
              <Spinner className="size-4" />
            ) : (
              <span
                className="text-xs transition-transform duration-100"
                style={{
                  transform: `rotate(${Math.min(180, (pullDistance / 64) * 180)}deg)`,
                  opacity: Math.max(0.4, pullDistance / 64),
                }}
              >
                ↓
              </span>
            )}
          </div>
        </div>
      )}

      {/* 5xl نه 6xl: در ۱۴۴۰ پیکسل، ستونِ ۱۱۵۲ پیکسلی دو سویِ ردیف‌های آلبوم/
          هنرمند خلاِ مرده می‌ساخت؛ ۱۰۲۴ تراکمِ سالمی به ردیف‌ها می‌دهد */}
      {/*
        `key` روی `<main>` است تا هر ویویی که باز است با تغییرِ هویت از نو سوار
        شود — یک نقطه‌ی کنترل، نه یک کلیدِ جدا برای هر ویو که یکی‌شان جا بیفتد.
        اسکرول و منوهای بازِ صفحه هم با آن ریست می‌شوند، که بعدِ عوض شدنِ حساب
        درست است.
      */}
      <main key={identityEpoch} className="px-safe mx-auto w-full max-w-5xl flex-1 pb-12">
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

            {view.kind === 'settings' && (
              <SettingsView
                onSetup={() => {
                  setWizard(true)
                  const p = new URLSearchParams(location.search)
                  p.set('setup', '1')
                  history.pushState(null, '', `/?${p}`)
                }}
                onServer={() => setSetup(true)}
              />
            )}

            {view.kind === 'profile' && <ProfileView onLogin={() => setLoginOpen(true)} />}

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
