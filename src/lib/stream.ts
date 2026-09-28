import { apiUrl } from './server'
import type { Quality, Track } from './types'
import type { PlayItem } from '../store/player'
import { useSettings } from '../store/settings'

/**
 * رتبه‌بندی کیفی برای مقایسه و انتخاب بالاترین کیفیت صوتی.
 */
export const QUALITY_RANK: Record<string, number> = {
  flac: 7,
  original: 6,
  '320': 5,
  opus: 4,
  m4a: 3,
  '192': 2,
  '128': 1,
}

/**
 * پیدا کردن باکیفیت‌ترین جاب آماده در کتابخانه برای یک ترک.
 * در صورت مشخص بودن کیفیت مورد نظر، ابتدا تلاش برای تطابق دقیق انجام می‌شود.
 * در غیر این صورت، بالاترین کیفیت موجود (FLAC > Original > 320 > Opus ...) انتخاب می‌شود.
 */
export function findBestJob<
  T extends { track: { id: string }; quality?: string; format?: string; createdAt?: number },
>(jobs: T[], trackId: string, preferredQuality?: string | null): T | undefined {
  const matching = jobs.filter((j) => j.track.id === trackId)
  if (matching.length === 0) return undefined
  if (matching.length === 1) return matching[0]

  if (preferredQuality) {
    const exact = matching.find((j) => j.quality === preferredQuality || j.format === preferredQuality)
    if (exact) return exact
  }

  return [...matching].sort((a, b) => {
    const keyA = a.quality || a.format || ''
    const keyB = b.quality || b.format || ''
    const rankA = QUALITY_RANK[keyA] ?? 0
    const rankB = QUALITY_RANK[keyB] ?? 0
    if (rankB !== rankA) return rankB - rankA
    return (b.createdAt ?? 0) - (a.createdAt ?? 0)
  })[0]
}

/**
 * آدرس استریم آنلاین برای یک ترک (بدون نیاز به دانلود در کتابخانه).
 * همواره با بالاترین کیفیت صوتی ممکن از سرور دریافت می‌شود.
 */
export function streamUrlFor(track: Track, quality?: Quality | null): string {
  const p = new URLSearchParams({
    track_id: track.id,
    title: track.title,
    artist: track.artist,
  })
  if (track.album) p.set('album', track.album)
  if (track.durationMs) p.set('duration_ms', String(track.durationMs))
  if (track.source) p.set('source', track.source)
  if (track.sourceUrl) p.set('source_url', track.sourceUrl)
  const q = quality ?? useSettings.getState().quality
  if (q) p.set('quality', q)
  return apiUrl(`/api/stream?${p.toString()}`)
}

/**
 * آدرس لیریکس استریم برای یک ترک.
 */
export function streamLyricsUrlFor(track: Track): string {
  const p = new URLSearchParams({
    track_id: track.id,
    title: track.title,
    artist: track.artist,
  })
  if (track.album) p.set('album', track.album)
  if (track.durationMs) p.set('duration_ms', String(track.durationMs))
  return apiUrl(`/api/stream/lyrics?${p.toString()}`)
}

/**
 * تبدیل یک Track به PlayItem قابل پخش در صف پلیر.
 * اگر ترک از قبل در کتابخانه دانلود شده باشد، از باکیفیت‌ترین فایل محلی استفاده می‌کند؛
 * در غیر این صورت، از استریم آنلاین با بالاترین کیفیت استفاده می‌کند.
 */
export function toPlayItem(
  track: Track,
  downloadedJob?: { streamUrl?: string; lyricsUrl?: string; gainDb?: number } | null,
  preferredQuality?: Quality | null,
): PlayItem {
  if (downloadedJob?.streamUrl) {
    return {
      id: track.id,
      track,
      streamUrl: downloadedJob.streamUrl,
      lyricsUrl: downloadedJob.lyricsUrl,
      gainDb: downloadedJob.gainDb,
    }
  }

  const q = preferredQuality ?? useSettings.getState().quality

  return {
    id: `stream:${track.id}`,
    track,
    streamUrl: streamUrlFor(track, q),
    lyricsUrl: streamLyricsUrlFor(track),
  }
}
