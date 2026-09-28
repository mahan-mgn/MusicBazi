import { api } from './api'
import type { Quality, Track } from './types'

/**
 * عنوان را برای یکتاسازی نرمال می‌کند — پسوندهای انتشاری مثل Single و Remastered
 * حذف می‌شوند ولی گونه‌های هنری مثل Remix و Acoustic دست‌نخورده می‌مانند.
 */
export function normalizeTrackTitle(title: string): string {
  return title
    .trim()
    .toLowerCase()
    .replace(/\s*-\s*(single|ep|album version|remastered|mono|stereo).*/i, '')
    .replace(/\s*\((single version|remastered[^)]*|mono|stereo|album version)\)/i, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** کلید یکتای (عنوان نرمال‌شده، هنرمند) برای یکتاسازی ترک‌های سینگل و آلبوم */
export function trackDedupeKey(
  track: Pick<Track, 'title' | 'artist'>,
  mainArtistName?: string,
): string {
  const normTitle = normalizeTrackTitle(track.title)
  const normArtist = (mainArtistName ?? track.artist).trim().toLowerCase()
  return `${normTitle}::${normArtist}`
}

/** کلید یکتای (عنوان، هنرمند) — برای جلوگیری از پیشنهاد دوباره‌ی همان ترک */
export const radioKey = (t: Pick<Track, 'title' | 'artist'>) =>
  `${t.title.trim().toLowerCase()}::${t.artist.trim().toLowerCase()}`

/** یک ترکِ تصادفی از pool که در exclude نیست؛ null یعنی چیزی نمانده */
export function pickRadioTrack(pool: Track[], exclude: Set<string>): Track | null {
  const candidates = pool.filter((t) => !exclude.has(radioKey(t)))
  if (!candidates.length) return null
  return candidates[Math.floor(Math.random() * candidates.length)]
}

/**
 * صفحه‌ی هنرمندِ ترکِ فعلی را باز می‌کند تا `topTracks`اش pool رادیو شود.
 * هیچ endpoint اختصاصی «مرتبط» یا «رادیو» در بک‌اند نیست — از همان جستجو و
 * صفحه‌ی هنرمندی استفاده می‌شود که کارت هنرمند در نتایج جستجو هم باز می‌کند.
 */
async function artistPool(seed: Track): Promise<Track[]> {
  const results = await api.search(seed.artist)
  const name = seed.artist.trim().toLowerCase()
  const artist =
    results.artists.find((a) => a.source === seed.source && a.name.trim().toLowerCase() === name) ??
    results.artists.find((a) => a.name.trim().toLowerCase() === name) ??
    results.artists[0]
  if (!artist) return []
  const detail = await api.getArtist(artist.id)
  return detail.topTracks
}

/**
 * ترکِ بعدیِ رادیو برای این seed؛ null یعنی چیزی پیدا نشد (هنرمند در دسترس
 * نیست، خطای شبکه، یا همه‌ی محبوب‌هایش قبلاً پخش شده‌اند).
 */
export async function findRadioTrack(seed: Track, exclude: Set<string>): Promise<Track | null> {
  try {
    const pool = await artistPool(seed)
    return pickRadioTrack(pool, exclude)
  } catch {
    return null
  }
}

/**
 * دانلود یک ترکِ رادیو و صبر تا آماده شدن؛ null یعنی شکست (خطا یا لغو).
 *
 * تابع لغوِ برگشتیِ `api.download` عمداً نادیده گرفته می‌شود: صدا زدنش حتی
 * بعد از رسیدن به 'ready' یک DELETE به سرور می‌زند و جابِ تازه‌تمام‌شده را پاک
 * می‌کند — آن رفتار برای لغوِ دستیِ کاربر ساخته شده، نه پاک‌سازی بعد از موفقیت.
 */
export function downloadRadioTrack(
  track: Track,
  quality: Quality,
): Promise<{ streamUrl: string; lyricsUrl?: string; gainDb?: number } | null> {
  return new Promise((resolve) => {
    api.download({ track, quality }, (p) => {
      if (p.status === 'ready') {
        resolve(
          p.streamUrl
            ? { streamUrl: p.streamUrl, lyricsUrl: p.lyricsUrl, gainDb: p.gainDb }
            : null,
        )
      } else if (p.status === 'error' || p.status === 'canceled') {
        resolve(null)
      }
    })
  })
}
