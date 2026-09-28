import { useSettings } from '../../store/settings'
import { absolute, apiUrl } from '../server'
import { IdentifyUnavailable, IntranetError } from '../types'
import type {
  AlbumDetail,
  ArtistDetail,
  CandidateOption,
  ChaptersInfo,
  DailyMix,
  DownloadProgress,
  Follow,
  FollowRequest,
  FollowState,
  IdentifyResult,
  LibraryItem,
  LibraryPage,
  MusicApi,
  NetStatus,
  Quality,
  SplitStatus,
  Stats,
  TelegramPairing,
  TelegramSend,
  TelegramStatus,
  Track,
  SearchResults,
  UserPlaylist,
  UserPlaylistDetail,
  VibeInput,
  VibeSuggestion,
} from '../types'

/** متادیتای ترک، به شکلی که بک‌اند می‌خواهد — تا از lookup دوباره جلوگیری شود */
const trackRef = (track: Track) => ({
  trackId: track.id,
  sourceUrl: track.sourceUrl,
  title: track.title,
  artist: track.artist,
  album: track.album,
  // شناسه‌ی آلبوم دقیق‌ترین کلیدِ گروه‌بندی در کتابخانه است — نامِ آلبوم می‌تواند
  // بین دو نسخه‌ی یک اثر (Deluxe، ریمستر) تکراری باشد
  albumId: track.albumId,
  albumArtist: track.albumArtist,
  durationMs: track.durationMs,
  artworkUrl: track.artworkUrl,
  trackNumber: track.trackNumber,
  discNumber: track.discNumber,
  year: track.year,
  genre: track.genre,
  source: track.source,
})

/**
 * ریشه‌ی API.
 *
 * تابع است نه ثابت: آدرس سرور در اپ نیتیو از تنظیمات می‌آید و کاربر می‌تواند
 * وسط کار عوضش کند. با یک ثابت، مقدار در لحظه‌ی import قفل می‌شد.
 */
const base = () => apiUrl('/api')

/**
 * پاسخ‌های سرور از این‌جا رد می‌شوند تا آدرس‌های نسبیِ داخلشان (فایل، استریم،
 * متن آهنگ) مطلق شوند. در مرورگر بی‌اثر است.
 */
async function readJson<T>(res: Response): Promise<T> {
  return absolute((await res.json()) as T)
}

/**
 * پیام خطای خودِ بک‌اند، وگرنه کدِ HTTP.
 *
 * FastAPI دلیل را در `detail` می‌گذارد و همان چیزی است که باید به کاربر نشان
 * داده شود («پلی‌لیست هوشمند عضوِ دستی نمی‌گیرد»)، نه یک ۴۰۰ خشک.
 */
async function errorText(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // بدنه JSON نبود — همان کد کافی است
  }
  return `${res.status} ${res.statusText}`
}

async function json<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(base() + path, { signal, cache: 'no-store' })
  // مسیرهای POST از اول `errorText` را می‌خواندند ولی GETها نه، و همه‌ی
  // پیام‌های دقیقِ سرور («این لینک شناخته نشد یا محتوایی نداشت») سرِ راه به
  // یک «۴۰۴ Not Found»ِ بی‌فایده تبدیل می‌شد
  //
  // ۵۰۳ معنیِ مشخصی دارد و سرور فقط برای همین یک چیز می‌فرستدش: اینترنتِ
  // بین‌الملل قطع است و این درخواست در کش هم نبود. تبدیلش به `Error`ِ ساده،
  // آن را در همان قیفِ «یک چیزی خراب شد» گم می‌کرد.
  if (res.status === 503) throw new IntranetError(await errorText(res))
  if (!res.ok) throw new Error(await errorText(res))
  return readJson<T>(res)
}

function abortJob(jobId: string): Promise<unknown> {
  return fetch(`${base()}/downloads/${jobId}`, { method: 'DELETE' }).catch(() => null)
}

function patchPlaylist(id: string, body: Record<string, unknown>): Promise<Response> {
  return fetch(`${base()}/playlists/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async (res) => {
    if (!res.ok) throw new Error(await errorText(res))
    return res
  })
}

/**
 * ZIP روی jobId های سرور کار می‌کند، ولی صفِ دانلود فقط trackId می‌شناسد —
 * شناسه‌ی جابِ داخلِ آن استور محلی است، نه چیزی که سرور بشناسد. این نگاشت
 * همان پل است و همین‌جا می‌ماند تا از store بیرون بماند.
 *
 * کلید جفتِ (ترک، کیفیت) است نه فقط ترک: هر کیفیت جابِ خودش و فایل خودش را
 * دارد، و با کلیدِ تک‌بخشی، دانلود دوباره‌ی یک آلبوم با کیفیت دیگر نگاشت را
 * بازنویسی می‌کرد و ZIPِ بچِ قدیمی فایل‌های کیفیت جدید را می‌داد.
 *
 * فقط با دانلود در همین بازدید پر می‌شود، پس صدازننده‌ای که jobId واقعی دارد
 * (ردیف‌های کتابخانه) باید خودش بدهدش — به `ZipItem.jobId` نگاه کن.
 */
const jobIdByTrack = new Map<string, string>()

const jobKey = (trackId: string, quality: Quality) => `${trackId}::${quality}`

/**
 * پیاده‌سازی واقعی روی بک‌اند FastAPI.
 * پروگرس از طریق SSE می‌آید: POST /downloads → {jobId} سپس GET /downloads/{jobId}/events
 */
export const httpApi: MusicApi = {
  search(query, signal) {
    return json<SearchResults>(`/search?q=${encodeURIComponent(query)}`, signal)
  },

  async netStatus(recheck = false, signal) {
    // `/net` فقط یک بولِ در حافظه را می‌خواند و مرتب پرسیده می‌شود؛ `/net/check`
    // واقعاً پروب می‌زند و فقط با کلیکِ صریحِ کاربر صدا زده می‌شود
    const res = recheck
      ? await fetch(`${base()}/net/check`, { method: 'POST', signal })
      : await fetch(`${base()}/net`, { signal })
    // نرسیدن به خودِ سرور یک چیزِ دیگر است (وای‌فای قطع، سرور خاموش) و
    // `OfflineBar` جدا نشانش می‌دهد — اینجا فقط «نمی‌دانم» برمی‌گردانیم
    if (!res.ok) return null
    return (await res.json()) as NetStatus
  },

  getAlbum(idOrUrl, signal) {
    return json<AlbumDetail>(`/album?ref=${encodeURIComponent(idOrUrl)}`, signal)
  },

  getArtist(idOrUrl, signal) {
    return json<ArtistDetail>(`/artist?ref=${encodeURIComponent(idOrUrl)}`, signal)
  },

  library(query, signal) {
    return json<LibraryPage>(`/library?q=${encodeURIComponent(query)}&limit=200`, signal)
  },

  async removeFromLibrary(jobId) {
    const res = await fetch(`${base()}/library/${jobId}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await errorText(res))
  },

  async toggleFavorite(jobId, favorite) {
    const res = await fetch(
      `${base()}/library/${jobId}/favorite?favorite=${favorite}`,
      { method: 'PUT' },
    )
    if (!res.ok) throw new Error(await errorText(res))
  },

  async recordPlay(jobId, seconds) {
    // شکستش بی‌صدا رد می‌شود: ثبتِ پخش یک راحتی است، نه چیزی که پخش را خراب کند
    await fetch(`${base()}/plays`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ jobId, seconds }),
    }).catch(() => null)
  },

  async stats(days = 7, signal) {
    const res = await fetch(`${base()}/stats?days=${days}`, { signal })
    if (!res.ok) return null
    return readJson<Stats>(res)
  },

  async favorites(signal) {
    const res = await fetch(`${base()}/favorites`, { signal })
    if (!res.ok) return null
    return readJson<LibraryItem[]>(res)
  },

  async dailyMix(signal) {
    const res = await fetch(`${base()}/mix`, { signal })
    if (!res.ok) return null
    return readJson<DailyMix>(res)
  },

  async candidates(track, source) {
    const res = await fetch(`${base()}/candidates`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ...trackRef(track), source }),
    })
    if (!res.ok) throw new Error(await errorText(res))
    return readJson<CandidateOption[]>(res)
  },

  download({ track, quality, candidateUrl }, onProgress) {
    const ctrl = new AbortController()
    let events: EventSource | null = null
    let id: string | null = null
    let staleTimer: ReturnType<typeof setTimeout> | undefined

    onProgress({ status: 'queued', percent: 0 })

    fetch(`${base()}/downloads`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      // متادیتا را همراه می‌فرستیم تا سرور برای تگ‌گذاری دوباره lookup نزند
      body: JSON.stringify({ ...trackRef(track), quality, candidateUrl }),
      signal: ctrl.signal,
    })
      .then(async (r) => {
        if (r.status === 503) throw new IntranetError(await errorText(r))
        if (!r.ok) throw new Error(await errorText(r))
        return r.json() as Promise<{ jobId: string; reused: boolean }>
      })
      .then(({ jobId }) => {
        id = jobId
        jobIdByTrack.set(jobKey(track.id, quality), jobId)
        // لغو قبل از رسیدن jobId: حالا که id داریم، به سرور هم خبر بده
        if (ctrl.signal.aborted) {
          void abortJob(jobId)
          return
        }
        events = new EventSource(`${base()}/downloads/${jobId}/events`)
        events.onmessage = (e) => {
          if (staleTimer) {
            clearTimeout(staleTimer)
            staleTimer = undefined
          }
          // این‌یکی از fetch نمی‌آید، پس خودش باید مطلق شود
          const p = absolute(JSON.parse(e.data) as DownloadProgress)
          onProgress(p)
          if (p.status === 'ready' || p.status === 'error' || p.status === 'canceled') {
            events?.close()
          }
        }
        events.onerror = () => {
          // EventSource خودش وصل دوباره می‌زند و در آن حالت readyState روی
          // CONNECTING است. قبلاً هر خطایی — از جمله یک قطعیِ گذرا — کار را
          // شکست‌خورده اعلام می‌کرد، درحالی‌که دانلود روی سرور ادامه داشت.
          // سرور موقع وصل دوباره وضعیت فعلی را می‌فرستد، پس چیزی گم نمی‌شود.
          if (events?.readyState === EventSource.CLOSED) {
            onProgress({ status: 'error', percent: 0, error: 'ارتباط با سرور قطع شد' })
            return
          }
          // ولی اگر تلاش برای وصل دوباره خیلی طول بکشد (قطعیِ دائمی، نه گذرا)،
          // برای همیشه در حالت «در حال تلاش» گیر نکنیم
          if (!staleTimer) {
            staleTimer = setTimeout(() => {
              staleTimer = undefined
              events?.close()
              onProgress({ status: 'error', percent: 0, error: 'ارتباط با سرور قطع شد' })
            }, 20000)
          }
        }
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return
        onProgress({
          status: 'error',
          percent: 0,
          error: err instanceof Error ? err.message : 'خطای ناشناخته',
        })
      })

    return () => {
      ctrl.abort()
      if (staleTimer) clearTimeout(staleTimer)
      events?.close()
      // بستن EventSource کار را روی سرور متوقف نمی‌کند — باید صریح لغو شود
      if (id) void abortJob(id)
    }
  },

  async vibeSuggest(input: VibeInput, signal) {
    const res = await fetch(`${base()}/vibe`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
      signal,
    })
    if (!res.ok) throw new Error(await errorText(res))
    return readJson<VibeSuggestion>(res)
  },

  async zip(items, name) {
    // شناسه‌ای که صدازننده داده مقدم است: ردیف‌های کتابخانه از سرور می‌آیند و
    // jobId واقعی همراهشان است، درحالی‌که `jobIdByTrack` فقط چیزهایی را دارد
    // که در همین بازدید دانلود شده‌اند — بعد از یک رفرش خالی است
    const jobIds = items
      .map((item) => item.jobId ?? jobIdByTrack.get(jobKey(item.trackId, item.quality)))
      .filter((id): id is string => Boolean(id))
    if (!jobIds.length) return null

    const res = await fetch(`${base()}/downloads/zip`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ jobIds, name }),
    })
    if (!res.ok) throw new Error(await errorText(res))
    const { url } = await readJson<{ url: string }>(res)
    return url
  },

  async identify(file, filename, signal) {
    const body = new FormData()
    body.append('file', file, filename)
    const res = await fetch(`${base()}/identify`, { method: 'POST', body, signal })
    // ۵۰۳ یعنی سرور اصلاً شناسایی ندارد — با «چیزی پیدا نشد» فرق دارد، و
    // متنش دقیقاً می‌گوید کدام تکه کم است
    if (res.status === 503) throw new IdentifyUnavailable(await errorText(res))
    if (!res.ok) throw new Error(await errorText(res))
    return readJson<IdentifyResult>(res)
  },

  async chapters(url, signal) {
    const res = await fetch(`${base()}/chapters?ref=${encodeURIComponent(url)}`, { signal })
    // لینکی که باز نشد یعنی «چپتری در کار نیست»، نه خطایی که باید toast شود
    if (!res.ok) return null
    return readJson<ChaptersInfo>(res)
  },

  async split(url, quality, indexes) {
    const res = await fetch(`${base()}/downloads/split`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ url, quality, indexes }),
    })
    if (!res.ok) throw new Error(await errorText(res))
    return readJson<SplitStatus>(res)
  },

  async splitStatus(taskId) {
    const res = await fetch(`${base()}/downloads/split/${taskId}`)
    if (!res.ok) return null
    return readJson<SplitStatus>(res)
  },

  playlists(signal) {
    return json<UserPlaylist[]>('/playlists', signal)
  },

  async playlist(id, signal) {
    const res = await fetch(`${base()}/playlists/${id}`, { signal })
    if (!res.ok) return null
    return readJson<UserPlaylistDetail>(res)
  },

  async createPlaylist(input) {
    const res = await fetch(`${base()}/playlists`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    })
    if (!res.ok) throw new Error(await errorText(res))
    return readJson<UserPlaylist>(res)
  },

  async renamePlaylist(id, name) {
    await patchPlaylist(id, { name })
  },

  async updatePlaylistRule(id, rule) {
    await patchPlaylist(id, { rule })
  },

  async deletePlaylist(id) {
    const res = await fetch(`${base()}/playlists/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await errorText(res))
  },

  async addToPlaylist(id, jobIds) {
    const res = await fetch(`${base()}/playlists/${id}/items`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ jobIds }),
    })
    if (!res.ok) throw new Error(await errorText(res))
    const { added } = (await res.json()) as { added: number }
    return added
  },

  async removeFromPlaylist(id, jobId) {
    const res = await fetch(`${base()}/playlists/${id}/items/${jobId}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await errorText(res))
  },

  async telegramStatus(signal) {
    // سروری که این نسخه را ندارد نباید دکمه‌ی شکسته نشان بدهد
    const res = await fetch(`${base()}/telegram/status`, { signal })
    if (!res.ok) return null
    return (await res.json()) as TelegramStatus
  },

  async telegramPair() {
    const res = await fetch(`${base()}/telegram/pair`, { method: 'POST' })
    if (!res.ok) throw new Error(await errorText(res))
    return (await res.json()) as TelegramPairing
  },

  async telegramUnlink() {
    const res = await fetch(`${base()}/telegram/link`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await errorText(res))
  },

  async telegramSend(req) {
    // همان trackRef مسیر دانلود: متادیتای همراه یعنی سرور lookup دوباره نمی‌کند
    // و تگ‌های آلبومیِ فایلی که به تلگرام می‌رود هم درست درمی‌آیند
    const body =
      req.kind === 'track'
        ? { kind: 'track', track: trackRef(req.track), title: req.track.title, quality: req.quality, keep: req.keep }
        : { kind: 'album', ref: req.ref, title: req.title, quality: req.quality, keep: req.keep }

    const res = await fetch(`${base()}/telegram/send`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(await errorText(res))
    return (await res.json()) as TelegramSend
  },

  async telegramSendStatus(id) {
    const res = await fetch(`${base()}/telegram/sends/${id}`)
    if (!res.ok) throw new Error(await errorText(res))
    return (await res.json()) as TelegramSend
  },

  async follows(chatId, signal) {
    const qs = chatId !== undefined ? `?chatId=${chatId}` : ''
    const res = await fetch(`${base()}/follows${qs}`, { signal })
    if (!res.ok) throw new Error(await errorText(res))
    return (await res.json()) as Follow[]
  },

  async followState(chatId, artistId, signal) {
    const res = await fetch(
      `${base()}/follows/state?chatId=${chatId}&artistId=${encodeURIComponent(artistId)}`,
      { signal },
    )
    if (!res.ok) throw new Error(await errorText(res))
    return (await res.json()) as FollowState
  },

  async follow(chatId, req: FollowRequest) {
    const res = await fetch(`${base()}/follows?chatId=${chatId}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(req),
    })
    if (!res.ok) throw new Error(await errorText(res))
    return (await res.json()) as FollowState
  },

  async unfollow(chatId, artistId) {
    const res = await fetch(
      `${base()}/follows?chatId=${chatId}&artistId=${encodeURIComponent(artistId)}`,
      { method: 'DELETE' },
    )
    if (!res.ok) throw new Error(await errorText(res))
  },

  async prefetchStream(track: Track, quality?: Quality | null) {
    try {
      const q = quality ?? useSettings.getState().quality
      await fetch(`${base()}/stream/prefetch`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ...trackRef(track), quality: q }),
      })
    } catch {
      // پری‌فچ بهترین تلاش است و خطایش نباید رابط کاربری را تحت تاثیر بگذارد
    }
  },
}
