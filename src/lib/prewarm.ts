import { api } from './api'
import { findBestJob } from './stream'
import type { Quality, Track } from './types'
import { useDownloads } from '../store/downloads'

// کشِ شناسه‌های اخیراً گرم‌شده با مهلتِ اعتبار (۵ دقیقه) برای جلوگیری از ارسال مکرر درخواست به سرور
const WARMED_TTL_MS = 5 * 60 * 1000
const MAX_WARMED_ENTRIES = 100
const warmedCache = new Map<string, number>()

function pruneWarmed(now: number): void {
  for (const [id, ts] of warmedCache.entries()) {
    if (now - ts > WARMED_TTL_MS) {
      warmedCache.delete(id)
    }
  }
  if (warmedCache.size > MAX_WARMED_ENTRIES) {
    const oldestKey = warmedCache.keys().next().value
    if (oldestKey) warmedCache.delete(oldestKey)
  }
}

/**
 * گرم‌کردن پیش‌دستانه‌ی استریم یک ترک (Spotify-like Predictive Pre-warming).
 *
 * پیش از کلیک کاربر (مثلاً با Hover ماوس یا باز شدن آلبوم)، آدرس استریم در حافظه رم سرور
 * آماده می‌شود تا زمان پخش به صفر میلی‌ثانیه برسد.
 */
export function prewarmTrack(track: Track, quality?: Quality | null): void {
  if (!track || !track.id) return

  // اگر آهنگ از قبل در کتابخانه دانلود شده باشد، نیازی به استریم آنلاین نیست
  const jobs = useDownloads.getState().jobs
  const downloaded = findBestJob(jobs, track.id, quality)
  if (downloaded && downloaded.streamUrl) return

  const now = Date.now()
  pruneWarmed(now)

  const cachedTs = warmedCache.get(track.id)
  if (cachedTs && now - cachedTs < WARMED_TTL_MS) {
    return
  }

  warmedCache.set(track.id, now)

  // درخواست سبک به سرور بدون بلاک کردن UI یا انتظار برای نتیجه
  void api.prefetchStream?.(track, quality).catch(() => {
    // خطا در پیش‌گرم‌سازی اختیاری است و تاثیری در جریان نرمال کاربر ندارد
  })
}

/** فقط برای تست‌های واحد */
export function _resetPrewarmCache(): void {
  warmedCache.clear()
}
