import { cachedMediaToken, withMediaToken } from './auth'
import { trackDedupeKey } from './radio'
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
  T extends { track: { id: string; title?: string; artist?: string; durationMs?: number }; quality?: string; format?: string; createdAt?: number },
>(jobs: T[], trackId: string, preferredQuality?: string | null, track?: Pick<Track, 'title' | 'artist' | 'durationMs'>): T | undefined {
  let matching = jobs.filter((j) => j.track.id === trackId)
  if (matching.length === 0 && track?.title && track?.artist) {
    const key = trackDedupeKey(track)
    matching = jobs.filter(
      (j) => j.track.title && j.track.artist && trackDedupeKey(j.track as Pick<Track, 'title' | 'artist'>) === key,
    )
  }

  // اعتبارسنجی انطباق مدت‌زمان: اگر ترکی در کتابخانه با طول انحرافی (مانند نسخه slowed ۳:۴۹ در برابر ۳:۱۹)
  // وجود داشته باشد، آن جاب نامنطبق تلقی شده و رد می‌شود تا پلیر به استریم نسخه اصلی سوئیچ کند
  if (track?.durationMs && track.durationMs >= 30_000) {
    matching = matching.filter((j) => {
      const jDur = j.track.durationMs ?? 0
      if (!jDur) return true
      const delta = Math.abs(track.durationMs! - jDur) / 1000
      const relDelta = delta / (track.durationMs! / 1000)
      return !(delta > 5.0 && relDelta > 0.035)
    })
  }

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
  // `<audio>` و hls.js هدر نمی‌فرستند: برای کاربرِ واردشده، مسیرِ `/api/stream`
  // بدونِ `mt` به مهمان تفسیر می‌شود و یوتیوب با کوکیِ او پیش نمی‌رود.
  return withMediaToken(apiUrl(`/api/stream?${p.toString()}`), cachedMediaToken())
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
  // راهنماهای اختیاری — فقط وقتی مقدار دارند فرستاده می‌شوند تا URLِ
  // درخواست‌های معمولی مثل قبل بماند
  if (track.videoId) p.set('videoId', track.videoId)
  if (track.isrc) p.set('isrc', track.isrc)
  return withMediaToken(apiUrl(`/api/stream/lyrics?${p.toString()}`), cachedMediaToken())
}

/**
 * تبدیل یک Track به PlayItem قابل پخش در صف پلیر.
 * اگر ترک از قبل در کتابخانه دانلود شده باشد، از باکیفیت‌ترین فایل محلی استفاده می‌کند؛
 * در غیر این صورت، از استریم آنلاین با بالاترین کیفیت استفاده می‌کند.
 */
export function toPlayItem(
  track: Track,
  downloadedJob?: { track?: { durationMs?: number }; streamUrl?: string; lyricsUrl?: string; gainDb?: number } | null,
  preferredQuality?: Quality | null,
): PlayItem {
  let isMismatched = false
  if (downloadedJob && downloadedJob.track?.durationMs && track.durationMs && track.durationMs >= 30_000) {
    const delta = Math.abs(track.durationMs - downloadedJob.track.durationMs) / 1000
    const relDelta = delta / (track.durationMs / 1000)
    if (delta > 5.0 && relDelta > 0.035) {
      isMismatched = true
    }
  }

  if (downloadedJob?.streamUrl && !isMismatched) {
    const media = cachedMediaToken()
    return {
      id: track.id,
      track,
      streamUrl: withMediaToken(apiUrl(downloadedJob.streamUrl), media),
      lyricsUrl: downloadedJob.lyricsUrl
        ? withMediaToken(apiUrl(downloadedJob.lyricsUrl), media)
        : undefined,
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
