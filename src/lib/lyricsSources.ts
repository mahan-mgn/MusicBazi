import { cachedMediaToken, token, withMediaToken } from './auth'
import { apiUrl } from './server'
import type { Track } from './types'

/**
 * هدرِ نشست برای مسیرهایی که کلیدِ شخصی می‌خوانند.
 *
 * `/api/lyrics/sources` و `/api/lyrics/preference` با `optional_user` کار
 * می‌کنند: بی‌توکن یعنی مهمان. نتیجه‌اش دو باگِ بی‌صدا بود — منوی منبع با
 * کلیدهای مهمان ساخته می‌شد (پس توکنِ Geniusِ خودِ کاربر «تنظیم نشده» دیده
 * می‌شد) و ترجیح در ردیفِ `local` می‌نشست، یعنی برای همه.
 */
function authHeaders(): Record<string, string> {
  const value = token()
  return value ? { authorization: `Bearer ${value}` } : {}
}

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
  /** آخرین نتیجهٔ همین آهنگ: cached / not_found / error / never_tried */
  last_outcome?: string
  /** نوعِ خطا: network / http / body / rate_limited */
  last_error_kind?: string | null
  /** کدِ HTTPِ آخرین خطا (فقط عدد) */
  http_status?: number | null
}

export interface LyricsSourcesResponse {
  trackId: string
  /** منبعِ ذخیره‌شده، یا `null` یعنی «خودکار». */
  preferred: string | null
  sources: LyricsSource[]
}

/**
 * خطای ساخت‌یافتهٔ مسیرِ منبع‌محور.
 *
 * `code` همان چیزی است که تصمیمِ UI را می‌سازد؛ `detail` برای سازگاریِ
 * عقب‌رو نگه داشته می‌شود و هرگز نمایش داده نمی‌شود (ممکن است فارسی و
 * غیرِقابلِ‌ترجمه باشد).
 */
export interface LyricsSourceError {
  code: string
  provider: string
  httpStatus: number | null
}

/** نامِ نمایشیِ یک منبع از پاسخِ فهرست؛ اگر نبود، خودِ شناسه. */
export function sourceLabel(sources: LyricsSource[] | null, id: string | null): string {
  if (!id) return ''
  return sources?.find((s) => s.id === id)?.label ?? id
}

/**
 * پیامِ خطای منبع — دقیق، بر پایهٔ کدِ ماشین‌خوان.
 *
 * این تابع قلبِ رفعِ مشکلِ «پیامِ مبهم» است: قبلاً هر خطا یک متنِ ثابت
 * می‌گرفت. حالا «این آهنگ متن ندارد» با «سرویس خراب است» و «راه‌اندازی
 * نشده» پیامِ متفاوت می‌گیرند.
 */
export function sourceErrorLabel(
  t: Record<string, unknown>,
  provider: string,
  code: string,
  label?: string,
): string {
  const name = label || provider
  const call = (key: string, fallback: string): string => {
    const fn = t[key]
    return typeof fn === 'function' ? (fn as (s: string) => string)(name) : fallback
  }
  switch (code) {
    case 'not_found':
      return call('srcNotFound', `No lyrics found in ${name}`)
    case 'rate_limited':
      return call('srcRateLimited', `${name} is rate limiting`)
    case 'needs_setup':
      return call('srcNeedsSetupMsg', `${name} needs setup`)
    case 'blocked':
      return call('srcBlockedMsg', `${name} is unavailable`)
    case 'disabled':
      return call('srcDisabledMsg', `${name} is off`)
    case 'unknown_provider':
      return typeof t.srcUnknownMsg === 'string' ? t.srcUnknownMsg : 'Unknown source'
    default:
      return call('srcUnavailable', `${name} is not responding`)
  }
}

/** بدنهٔ خطای بک‌اند را از پاسخ بیرون بکش، با پیش‌فرضِ امن. */
export function readSourceError(body: unknown, provider: string): LyricsSourceError {
  const b = (body ?? {}) as Record<string, unknown>
  return {
    code: typeof b.code === 'string' ? b.code : 'provider_error',
    provider: typeof b.provider === 'string' ? b.provider : provider,
    httpStatus: typeof b.http_status === 'number' ? b.http_status : null,
  }
}

/**
 * دریافتِ متن از یک منبعِ مشخص.
 *
 * برخلافِ `fetch`ِ خام، اینجا کدِ خطای بک‌اند خوانده می‌شود تا «این آهنگ
 * متن ندارد» از «سرویس خراب است» جدا شود — تمایزی که قبلاً وجود نداشت و
 * باعثِ پیامِ مبهم می‌شد.
 */
export async function fetchLyricsFromSource(
  track: Track,
  provider: string,
  { force = false }: { force?: boolean } = {},
): Promise<{ text: string } | { error: LyricsSourceError }> {
  const params = trackParams(track)
  params.set('provider', provider)
  if (force) params.set('force', 'true')
  try {
    // مسیرِ مدیا هدر نمی‌گیرد، پس توکن در query می‌رود — وگرنه انتخابِ منبع
    // برای کاربرِ واردشده به مهمان تفسیر می‌شود و کوکیِ او استفاده نمی‌شود.
    const url = withMediaToken(
      apiUrl(`/api/stream/lyrics?${params.toString()}`),
      cachedMediaToken(),
    )
    const response = await fetch(url)
    if (response.ok) {
      return { text: await response.text() }
    }
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    return { error: readSourceError(body, provider) }
  } catch {
    // خطای شبکه: هیچ بدنه‌ای نیست، پس کد را خودمان می‌سازیم
    return { error: { code: 'provider_error', provider, httpStatus: null } }
  }
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
    const response = await fetch(apiUrl(`/api/lyrics/sources?${trackParams(track).toString()}`), {
      headers: authHeaders(),
    })
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
      { headers: authHeaders() },
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
      { method: 'PUT', headers: authHeaders() },
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
      { method: 'DELETE', headers: authHeaders() },
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
  return withMediaToken(
    apiUrl(`/api/stream/lyrics?${params.toString()}`),
    cachedMediaToken(),
  )
}
