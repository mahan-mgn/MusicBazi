import { api } from './api'
import type { Quality, Track, VibeReady } from './types'
import type { PlayItem } from '../store/player'

export interface QueueDownloadResult {
  item: PlayItem | null
  /** شناسه‌ی جابِ آماده — برای «ذخیره در پلی‌لیست»، که روی jobId می‌نشیند */
  jobId?: string
  /** پیامِ خطای سرور (مثلاً «نسخه‌ی قابل دانلودی پیدا نشد») — برای نمایش دلیلِ شکست */
  error?: string
}

/**
 * شناسه‌ی جاب از آدرسِ فایل.
 *
 * `api.download` آن را در پاسخِ SSE نمی‌دهد (فقط fileUrl/streamUrl)، و ساختنش
 * از همان URL بهتر از رمزگشاییِ `item.id` در هر مصرف‌کننده است — یک‌جا، با
 * یک قالبِ معلوم: `/api/downloads/<id>/file`.
 */
function jobIdFromUrl(url?: string): string | undefined {
  return url?.match(/\/api\/downloads\/([^/]+)\//)?.[1]
}

/**
 * یک ترکِ پیشنهادی را به PlayItemِ قابل‌پخش تبدیل می‌کند.
 *
 * `id` عمداً از jobId ساخته می‌شود نه timestamp: همان فایلِ کتابخانه هر بار یک
 * کلید دارد، پس پلیر (و هر کشِ مبتنی بر id) بینِ دو درخواستِ چت نمی‌پرد.
 */
export function itemFromJob(track: Track, ready: VibeReady): PlayItem {
  return {
    id: `lib-${ready.jobId}`,
    track,
    streamUrl: ready.streamUrl,
    lyricsUrl: ready.lyricsUrl ?? undefined,
    gainDb: ready.gainDb ?? 0,
  }
}

/**
 * دانلود یک ترکِ پیشنهادیِ چت‌بات وایب و صبر تا آماده شدن. هم‌شکلِ
 * `downloadRadioTrack` در radio.ts، فقط خروجی‌اش هم PlayItemِ کامل می‌دهد
 * (چون مستقیم به صفِ پخش اضافه می‌شود) هم پیامِ خطا را نگه می‌دارد — بدون آن
 * UI فقط می‌دانست ترک شکست خورده، نه چرا.
 */
export function downloadForQueue(track: Track, quality: Quality): Promise<QueueDownloadResult> {
  return new Promise((resolve) => {
    api.download({ track, quality }, (p) => {
      if (p.status === 'ready') {
        resolve(
          p.streamUrl
            ? {
                jobId: jobIdFromUrl(p.streamUrl),
                item: {
                  id: `vibe-${track.id}-${Date.now()}`,
                  track,
                  streamUrl: p.streamUrl,
                  lyricsUrl: p.lyricsUrl,
                  gainDb: p.gainDb,
                },
              }
            : { item: null },
        )
      } else if (p.status === 'error' || p.status === 'canceled') {
        resolve({ item: null, error: p.error })
      }
    })
  })
}

/**
 * چند دانلودِ کم‌تعدادِ هم‌زمان، به همان ترتیبِ لیست.
 *
 * چرا سقف دارد: `Promise.allSettled` روی هشت ترک یعنی هشت jobِ موازی روی
 * سرورِ خانگیِ همان کاربر — هر کدام با ytdlp و ffmpegِ خودش. اولین‌ها که
 * زودتر آماده شوند، دکمه‌ی پخش هم زودتر فعال می‌شود.
 */
export async function prefetchTracks(
  tracks: Track[],
  quality: Quality,
  resolveOwned: (track: Track) => VibeReady | null,
  onItem: (track: Track, result: QueueDownloadResult) => void,
  concurrency = 3,
): Promise<void> {
  let next = 0
  const worker = async () => {
    for (;;) {
      const index = next++
      if (index >= tracks.length) return
      const track = tracks[index]
      const owned = resolveOwned(track)
      // از قبل در کتابخانه است — دانلودِ دوباره همان فایل، فقط ترافیک و وقت است
      if (owned) onItem(track, { item: itemFromJob(track, owned), jobId: owned.jobId })
      else onItem(track, await downloadForQueue(track, quality))
    }
  }
  await Promise.allSettled(Array.from({ length: Math.min(concurrency, tracks.length) }, worker))
}
