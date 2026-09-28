import { IdentifyUnavailable } from '../types'
import type {
  AlbumDetail,
  DownloadProgress,
  DownloadRequest,
  MusicApi,
  SearchResults,
  VibeInput,
  VibeSuggestion,
} from '../types'
import {
  ALBUMS,
  albumDetail,
  ARTISTS,
  artistDetail,
  PLAYLISTS,
  TOP_TRACKS,
} from './catalog'

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(t)
      reject(new DOMException('aborted', 'AbortError'))
    })
  })

/** عدد شبه‌تصادفی ولی پایدار برای یک کلید مشخص */
function seeded(key: string): number {
  let h = 2166136261
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 1000) / 1000
}

/** برچسب/پاسخِ هر چیپ در مود دمو — چیزی سبک، بدون نیاز به سرور یا LLM */
const VIBE_LABELS: Record<string, string> = {
  sad: '😢 غمگین',
  happy: '😊 شاد',
  energetic: '🔥 پرانرژی',
  calm: '😌 آرام',
  romantic: '❤️ عاشقانه',
  angry: '😤 عصبانی',
  discover: '🎵 پیشنهادی',
}

const VIBE_REPLIES: Record<string, string> = {
  sad: 'می‌دونم حس بدی داری. این چندتا رو گذاشتم برات.',
  happy: 'عالیه! بزن بریم با یه پلی‌لیست شاد.',
  energetic: 'بریم رو دور تند!',
  calm: 'باشه، بریم رو یه ریتم آروم.',
  romantic: 'چه حس قشنگی.',
  angry: 'بریزش بیرون.',
  discover: 'در مود دمو یه لیست نمونه برات آوردم — بک‌اند واقعی که وصل باشه، بر اساس حالت پیدا می‌کنه.',
}

export const mockApi: MusicApi = {
  async netStatus() {
    // مود دمو سروری ندارد که وضعیتِ شبکه‌اش را بپرسد؛ `null` یعنی «نمی‌دانم»
    // و UI هیچ نوارِ اینترانتی نشان نمی‌دهد — نه اینکه ادعای آنلاین بودن کند
    return null
  },

  async search(query, signal) {
    await wait(700 + seeded(query) * 600, signal)
    const results: SearchResults = {
      query,
      tracks: TOP_TRACKS,
      artists: ARTISTS,
      albums: ALBUMS,
      playlists: PLAYLISTS,
    }
    return results
  },

  async getAlbum(idOrUrl, signal) {
    await wait(600, signal)
    const album =
      ALBUMS.find((a) => a.id === idOrUrl) ??
      ALBUMS.find((a) => idOrUrl.includes(a.sourceUrl)) ??
      // لینک ناشناس: با اسلاگِ داخل لینک حدس بزن، وگرنه آلبوم اول
      ALBUMS.find((a) => idOrUrl.toLowerCase().includes(a.title.toLowerCase().slice(0, 6))) ??
      ALBUMS[0]
    return albumDetail(album) satisfies AlbumDetail
  },

  async getArtist(idOrUrl, signal) {
    await wait(500, signal)
    const artist =
      ARTISTS.find((a) => a.id === idOrUrl) ??
      ARTISTS.find((a) => idOrUrl.includes(a.sourceUrl)) ??
      ARTISTS[ARTISTS.length - 1]
    return artistDetail(artist)
  },

  async library() {
    // کتابخانه فایل واقعی روی دیسک سرور است؛ در مود دمو سروری در کار نیست
    return null
  },

  async removeFromLibrary() {},

  async toggleFavorite() {},

  async recordPlay() {},

  async stats() {
    // آمار روی جدولِ پخشِ سرور ساخته می‌شود؛ مود دمو سروری ندارد
    return null
  },

  async favorites() {
    return null
  },

  async dailyMix() {
    return null
  },

  async candidates() {
    // انتخاب دستی به جستجوی واقعی در یوتیوب/ساندکلاد نیاز دارد
    return null
  },

  download({ track, quality }: DownloadRequest, onProgress) {
    let canceled = false
    let timer: ReturnType<typeof setTimeout>

    const emit = (p: DownloadProgress) => {
      if (!canceled) onProgress(p)
    }

    const step = (fn: () => void, ms: number) => {
      timer = setTimeout(() => {
        if (!canceled) fn()
      }, ms)
    }

    // یکی از هر ۸ ترک را عمداً خطا می‌دهیم تا مسیر «تلاش دوباره» هم دیده شود
    const roll = seeded(track.id + quality)
    const shouldFail = roll > 0.88

    emit({ status: 'queued', percent: 0 })

    step(() => {
      emit({ status: 'searching', percent: 0 })

      step(() => {
        if (shouldFail) {
          emit({
            status: 'error',
            percent: 0,
            error: 'نسخه‌ی قابل دانلودی برای این آهنگ پیدا نشد',
          })
          return
        }

        let percent = 0
        const tick = () => {
          if (canceled) return
          percent = Math.min(100, percent + 1.2 + roll * 2.2)
          if (percent < 100) {
            emit({ status: 'downloading', percent })
            step(tick, 200 + roll * 180)
          } else {
            emit({ status: 'downloading', percent: 100 })
            step(() => {
              emit({ status: 'tagging', percent: 100 })
              step(() => {
                // سرور واقعی فرمتِ به‌دست‌آمده را می‌دهد، نه کیفیت درخواستی
                const format =
                  quality === 'original'
                    ? 'm4a 256'
                    : /^\d+$/.test(quality)
                      ? `mp3 ${quality}`
                      : quality === 'flac'
                        ? 'flac 16/44'
                        : `${quality} 160`
                emit({
                  status: 'ready',
                  percent: 100,
                  format,
                  // در مود ماک فایل واقعی وجود ندارد
                  fileUrl: undefined,
                })
              }, 500)
            }, 300)
          }
        }
        tick()
      }, 900 + roll * 1400)
    }, 250)

    return () => {
      canceled = true
      clearTimeout(timer!)
    }
  },

  async vibeSuggest(input: VibeInput, signal) {
    await wait(500, signal)
    const key = input.vibe && VIBE_LABELS[input.vibe] ? input.vibe : 'discover'
    const exclude = new Set(input.excludeIds ?? [])
    // تصادفِ واقعی، نه seed ثابت — کلیک‌های پیاپی روی یک چیپ باید پلی‌لیستِ
    // متفاوت بدهند، و ترک‌هایی که همین گفتگو قبلاً دیده دوباره نمی‌آیند
    const tracks = [...TOP_TRACKS]
      .filter((t) => !exclude.has(t.id))
      .sort(() => Math.random() - 0.5)
      .slice(0, 8)
    return {
      vibe: key,
      label: VIBE_LABELS[key],
      reply: VIBE_REPLIES[key],
      tracks,
    } satisfies VibeSuggestion
  },

  async zip() {
    // مود دمو فایل واقعی تولید نمی‌کند، پس ZIPی هم در کار نیست
    return null
  },

  // هرچه از این پایین می‌آید به فایلِ واقعی روی دیسکِ سرور گره خورده —
  // شناسایی با فینگرپرینت، تکه‌کردنِ میکس و پلی‌لیستی که روی کتابخانه ساخته
  // می‌شود. مود دمو هیچ‌کدام را ندارد و null یعنی «این لایه پشتیبانی نمی‌کند»،
  // که UI بلد است پیام درست را برایش نشان بدهد.
  async identify(): Promise<never> {
    throw new IdentifyUnavailable('در مود دمو شناسایی صوتی وجود ندارد.')
  },

  async chapters() {
    return null
  },

  async split() {
    return null
  },

  async splitStatus() {
    return null
  },

  async playlists() {
    return null
  },

  async playlist() {
    return null
  },

  async createPlaylist() {
    return null
  },

  async renamePlaylist() {},

  async updatePlaylistRule() {},

  async deletePlaylist() {},

  async addToPlaylist() {
    return 0
  },

  async removeFromPlaylist() {},

  // مود دمو بات ندارد؛ null یعنی دکمه‌ی تلگرام اصلاً نشان داده نشود
  async telegramStatus() {
    return null
  },

  async telegramPair(): Promise<never> {
    throw new Error('در مود دمو بات تلگرام وجود ندارد.')
  },

  async telegramUnlink() {},

  async telegramSend(): Promise<never> {
    throw new Error('در مود دمو بات تلگرام وجود ندارد.')
  },

  async telegramSendStatus(): Promise<never> {
    throw new Error('در مود دمو بات تلگرام وجود ندارد.')
  },

  // مود دمو بات ندارد، پس دنبال‌کردن هم بی‌معناست؛ دکمه با `usable` پنهان می‌ماند
  async follows() {
    return []
  },

  async followState(): Promise<never> {
    throw new Error('در مود دمو بات تلگرام وجود ندارد.')
  },

  async follow(): Promise<never> {
    throw new Error('در مود دمو بات تلگرام وجود ندارد.')
  },

  async unfollow(): Promise<never> {
    throw new Error('در مود دمو بات تلگرام وجود ندارد.')
  },

  async prefetchStream() {},
}
