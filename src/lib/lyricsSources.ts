import { apiUrl } from './server'
import type { Track } from './types'

/**
 * کلاینتِ انتخابِ منبعِ متن.
 *
 * همه‌چیز اینجا **کم‌خطر** است: هر خطای شبکه یا پاسخِ بد → مقدارِ خنثی،
 * نه استثنا. پخش نباید به‌خاطرِ یک درخواستِ ناموفقِ متن متوقف شود.
 *
 * نکتهٔ مهم: `trackId` تنها چیزی است که برای ترجیح لازم است — همان هویتی
 * که مسیرِ `/api/stream/lyrics` و کش استفاده می‌کنند. بقیهٔ پارامترها فقط
 * برای ساختنِ `Track` سمت سرورِ `sources` لازم‌اند.
 */

/** آنچه سرور برای هر منبع گزارش می‌کند. */
export interface LyricsSource {
  id: string
  label: string
  capabilities: string[]
  in_auto_chain: boolean
  selectable: boolean
  status: string
  terms_note?: string | null
  setup_hint?: string | null
  experimental: boolean
  unavailable_reason?: string | null
}

export interface LyricsSourcesResponse {
  trackId: string
  /** منبعِ ذخیره‌شده، یا `null` یعنی «خودکار». */
  preferred: string | null
  sources: LyricsSource[]
}

function trackParams(track: Track): URLSearchParams {
  const params = new URLSearchParams({
    track_id: track.id,
    title: track.title,
    artist: track.artist,
  })
  if (track.album) params.set('album', track.album)
  if (track.durationMs) params.set('duration_ms', String(track.durationMs))
  if (track.videoId) params.set('videoId', track.videoId)
  if (track.isrc) params.set('isrc', track.isrc)
  return params
}

/**
 * فهرستِ منابع + ترجیحِ ذخیره‌شده.
 *
 * این درخواست **هیچ Providerی را صدا نمی‌زند** (سمتِ سرور تضمین شده)، پس
 * باز کردنِ منو ارزان است.
 */
export async function fetchLyricsSources(track: Track): Promise<LyricsSourcesResponse | null> {
  try {
    const response = await fetch(apiUrl(`/api/lyrics/sources?${trackParams(track).toString()}`))
    if (!response.ok) return null
    const body = (await response.json()) as LyricsSourcesResponse
    if (!body || !Array.isArray(body.sources)) return null
    return body
  } catch {
    return null
  }
}

/** ترجیحِ ذخیره‌شده برای یک آهنگ؛ `null` یعنی «خودکار» یا خطا. */
export async function fetchLyricsPreference(trackId: string): Promise<string | null> {
  try {
    const response = await fetch(
      apiUrl(`/api/lyrics/preference?track_id=${encodeURIComponent(trackId)}`),
    )
    if (!response.ok) return null
    const body = (await response.json()) as { provider?: string | null }
    return body.provider ?? null
  } catch {
    return null
  }
}

/**
 * ذخیرهٔ انتخاب.
 *
 * `provider = ''` انتخاب را پاک می‌کند (بازگشت به «خودکار») — همان قراردادِ
 * سرور. برمی‌گرداند که ذخیره موفق بود یا نه، تا UI بتواند پیام بدهد.
 */
export async function saveLyricsPreference(trackId: string, provider: string): Promise<boolean> {
  try {
    const response = await fetch(
      apiUrl(
        `/api/lyrics/preference?track_id=${encodeURIComponent(trackId)}` +
          `&provider=${encodeURIComponent(provider)}`,
      ),
      { method: 'PUT' },
    )
    return response.ok
  } catch {
    return false
  }
}

/** بازگشتِ یک آهنگ به «خودکار». */
export async function clearLyricsPreference(trackId: string): Promise<boolean> {
  try {
    const response = await fetch(
      apiUrl(`/api/lyrics/preference?track_id=${encodeURIComponent(trackId)}`),
      { method: 'DELETE' },
    )
    return response.ok
  } catch {
    return false
  }
}

/** آدرسِ متنِ یک منبعِ مشخص — برای دریافتِ تنبلِ همان منبع. */
export function streamLyricsUrlForProvider(track: Track, provider: string): string {
  const params = trackParams(track)
  params.set('provider', provider)
  return apiUrl(`/api/stream/lyrics?${params.toString()}`)
}

/** برچسبِ خوانای قابلیت‌ها برای نمایش در منو. */
export function capabilityLabel(capabilities: string[]): string {
  if (capabilities.includes('word')) return 'word'
  if (capabilities.includes('ttml')) return 'ttml'
  if (capabilities.includes('line')) return 'line'
  return 'plain'
}
